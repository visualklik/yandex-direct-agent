#!/usr/bin/env python3
"""Визуальный HTML-отчёт аудита: один самодостаточный файл, без внешних ресурсов.

    python3 dashboard.py --snapshot snapshot.json \
        --campaigns camp.tsv --placements placements.tsv --days days.tsv \
        --target-cpa 500 --account "Клиент N" --out audit.html

Все входы кроме --snapshot необязательны: чего нет, тот блок не рисуется.
Логика находок — та же, что в checks.py; принципы вёрстки — dashboard.md.
"""
import argparse, csv, html, json, os, sys, importlib.util
from collections import defaultdict
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("checks", os.path.join(HERE, "checks.py"))
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)

P0, P1, P2 = "P0", "P1", "P2"
LEVEL_TO_P = {checks.CRIT: P0, checks.WARN: P1, checks.INFO: P2}
E = html.escape


def num(v):
    if v in (None, "", "--"):
        return 0.0
    try:
        return float(str(v).replace("\xa0", "").replace(" ", "").replace("%", "").replace(",", "."))
    except ValueError:
        return 0.0


def tsv(path, key_hint=None):
    if not path:
        return []
    lines = open(path, encoding="utf-8-sig").read().splitlines()
    hdr = 0
    if key_hint:
        hdr = next((i for i, l in enumerate(lines) if key_hint in l), 0)
    return [r for r in csv.DictReader(lines[hdr:], delimiter="\t") if any(r.values())]


def plural(k, one, few, many):
    k = abs(int(k))
    if k % 10 == 1 and k % 100 != 11:
        return one
    if 2 <= k % 10 <= 4 and not 12 <= k % 100 <= 14:
        return few
    return many


def money(v):
    return f"{v:,.0f}".replace(",", " ") + " ₽"


def n(v, d=0):
    return f"{v:,.{d}f}".replace(",", " ")


# ─────────────────────────── графика ───────────────────────────

def bars(rows, label_key, value_key, second=None, second_label="", width=560):
    """Горизонтальные бары: доля расхода. rows — список dict."""
    if not rows:
        return ""
    top = max(r[value_key] for r in rows) or 1
    out = ['<div class="bars">']
    for r in rows:
        share = r[value_key] / top * 100
        sec = f'<span class="bar-sec">{r[second]}</span>' if second else ""
        out.append(
            f'<div class="bar-row"><div class="bar-label" title="{E(str(r[label_key]))}">'
            f'{E(str(r[label_key]))}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{share:.1f}%"></div></div>'
            f'<div class="bar-val">{money(r[value_key])}{sec}</div></div>')
    out.append("</div>")
    return "".join(out)


def sparkline(points, w=640, h=90):
    """Линия расхода по дням + столбики конверсий."""
    if len(points) < 2:
        return ""
    costs = [p["cost"] for p in points]
    convs = [p["conv"] for p in points]
    cmax, vmax = max(costs) or 1, max(convs) or 1
    dx = w / (len(points) - 1)
    line = " ".join(f"{i*dx:.1f},{h - c/cmax*(h-18):.1f}" for i, c in enumerate(costs))
    barsvg = "".join(
        f'<rect x="{i*dx-2:.1f}" y="{h - v/vmax*(h-30):.1f}" width="4" '
        f'rx="1.5" height="{v/vmax*(h-30):.1f}" class="spark-bar"/>'
        for i, v in enumerate(convs))
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
            f'aria-label="Расход и конверсии по дням">{barsvg}'
            f'<polyline points="{line}" class="spark-line"/></svg>')


def concentration_curve(costs, w=560, h=150):
    """Кумулятивная кривая: сколько площадок дают сколько расхода."""
    if not costs:
        return ""
    costs = sorted(costs, reverse=True)
    total = sum(costs) or 1
    acc, pts = 0.0, []
    for i, c in enumerate(costs, 1):
        acc += c
        pts.append((i / len(costs), acc / total))
    step = max(1, len(pts) // 200)
    path = " ".join(f"{x*w:.1f},{h - y*h:.1f}" for x, y in pts[::step])
    p80 = next((i for i, (_, y) in enumerate(pts, 1) if y >= 0.8), len(pts))
    x80 = p80 / len(pts) * w
    return (f'<svg class="curve" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="Концентрация расхода по площадкам">'
            f'<line x1="0" y1="{h*0.2:.0f}" x2="{w}" y2="{h*0.2:.0f}" class="curve-grid"/>'
            f'<polyline points="0,{h} {path}" class="curve-line"/>'
            f'<line x1="{x80:.1f}" y1="0" x2="{x80:.1f}" y2="{h}" class="curve-mark"/>'
            f'<text x="{min(x80+6, w-140):.0f}" y="16" class="curve-text">'
            f'{p80} площадок = 80% расхода</text></svg>')


def donut(parts, size=132):
    """Кольцо долей. parts — [(label, value, css_class)]."""
    total = sum(p[1] for p in parts) or 1
    r, c = size / 2 - 12, size / 2
    circ = 2 * 3.14159 * r
    off, seg = 0.0, []
    for label, val, cls in parts:
        frac = val / total
        seg.append(f'<circle cx="{c}" cy="{c}" r="{r}" class="ring {cls}" '
                   f'stroke-dasharray="{frac*circ:.2f} {circ:.2f}" '
                   f'stroke-dashoffset="{-off*circ:.2f}"/>')
        off += frac
    legend = "".join(f'<div class="lg"><i class="{cls}"></i>{E(label)} '
                     f'<b>{val/total*100:.0f}%</b></div>' for label, val, cls in parts)
    return (f'<div class="donut-wrap"><svg viewBox="0 0 {size} {size}" class="donut">'
            f'{"".join(seg)}</svg><div class="legend">{legend}</div></div>')


# ─────────────────────────── сборка ───────────────────────────

def build(a):
    snap = json.load(open(a.snapshot, encoding="utf-8"))
    camps = {c["Id"]: c for c in snap["campaigns"]}
    live = {i: c for i, c in camps.items() if c.get("State") == "ON"}

    findings = collect_findings(snap)
    perf = tsv(a.campaigns, "CampaignId")
    days = tsv(a.days, "Date")
    places = tsv(a.placements, "Placement")
    urls = json.load(open(a.urls, encoding="utf-8")) if a.urls else None

    # Мастер кампаний в campaigns.get не отдаётся: в статистике кампания есть, в слепке её нет.
    # Молча потерять её нельзя — это может быть заметная доля расхода без единой проверенной настройки.
    known = {str(i) for i in camps}
    invisible = {}
    agg = defaultdict(lambda: dict(cost=0.0, clicks=0.0, imps=0.0, conv=0.0))
    for r in perf:
        k = r.get("CampaignName") or r.get("CampaignId")
        if r.get("CampaignId") and str(r["CampaignId"]) not in known:
            invisible[k] = r["CampaignId"]
        d = agg[k]
        d["cost"] += num(r.get("Cost"))
        d["clicks"] += num(r.get("Clicks"))
        d["imps"] += num(r.get("Impressions"))
        d["conv"] += num(r.get("Conversions"))
        d.setdefault("net", set()).add(r.get("AdNetworkType", ""))
    total = dict(cost=sum(d["cost"] for d in agg.values()),
                 clicks=sum(d["clicks"] for d in agg.values()),
                 imps=sum(d["imps"] for d in agg.values()),
                 conv=sum(d["conv"] for d in agg.values()))
    cpa = total["cost"] / total["conv"] if total["conv"] else 0
    target = a.target_cpa or cpa

    net = defaultdict(float)
    for r in perf:
        net[r.get("AdNetworkType", "—")] += num(r.get("Cost"))

    # вес кампании в расходе — для приоритизации находок
    weight = {k: (v["cost"] / total["cost"] if total["cost"] else 0) for k, v in agg.items()}

    score, grade = compute_score(findings, weight)

    camp_rows = sorted(
        ({"name": k, "cost": v["cost"], "clicks": v["clicks"], "conv": v["conv"],
          "cpa": v["cost"] / v["conv"] if v["conv"] else 0,
          "ctr": v["clicks"] / v["imps"] * 100 if v["imps"] else 0} for k, v in agg.items()),
        key=lambda r: -r["cost"])
    if a.anonymize:
        for i, r in enumerate(camp_rows, 1):
            r["name"] = f"Кампания {i}"

    day_pts = [{"cost": num(r.get("Cost")), "conv": num(r.get("Conversions")),
                "date": r.get("Date")} for r in sorted(days, key=lambda r: r.get("Date", ""))]

    pl = place_block(places, total)
    inv_cost = sum(agg[k]["cost"] for k in invisible)
    inv = dict(names=list(invisible), cost=inv_cost,
               share=inv_cost / total["cost"] * 100 if total["cost"] else 0) if invisible else None

    return render(a, live, camps, findings, score, grade, total, cpa, target,
                  camp_rows, day_pts, net, pl, inv, urls)


def collect_findings(snap):
    """Прогон checks.py с перехватом вывода в структуру."""
    out = []
    orig = checks.main
    import io, contextlib
    buf = io.StringIO()
    tmp = os.path.join(os.path.dirname(os.path.abspath(snap_path_holder[0])), ".tmp_snap.json")
    sys.argv = ["checks", snap_path_holder[0]]
    with contextlib.redirect_stdout(buf):
        orig()
    lvl = None
    for line in buf.getvalue().splitlines():
        s = line.strip()
        if s.startswith("──"):
            lvl = s.split()[1]
        elif s.startswith("•") and lvl:
            out.append({"level": lvl, "what": s[1:].strip(), "detail": ""})
        elif out and s and lvl and not s.startswith("Кампаний"):
            out[-1]["detail"] = s
    return out


def place_block(places, total):
    if not places:
        return None
    rows = []
    for r in places:
        rows.append({"name": (r.get("Placement") or "").strip(),
                     "clicks": num(r.get("Clicks")), "cost": num(r.get("Cost")),
                     "conv": num(r.get("Conversions")), "bounce": num(r.get("BounceRate"))})
    rows = [r for r in rows if r["name"]]
    clicks = sum(r["clicks"] for r in rows) or 1
    conv = sum(r["conv"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    cr = conv / clicks
    thr = 3 / cr if cr else float("inf")
    cand = [r for r in rows if r["conv"] == 0 and r["clicks"] >= thr]
    tail = [r for r in rows if r["conv"] == 0 and r["clicks"] < thr]
    return dict(rows=rows, total_cost=cost, cr=cr, thr=thr, cand=sorted(cand, key=lambda r: -r["cost"]),
                tail_cost=sum(r["cost"] for r in tail), tail_n=len(tail),
                top=sorted(rows, key=lambda r: -r["cost"])[:12])


def compute_score(findings, weight):
    penalty = {checks.CRIT: 14, checks.WARN: 6, checks.INFO: 2}
    s = 100 - sum(penalty.get(f["level"], 2) for f in findings)
    s = max(5, min(100, s))
    grade = "здоровый" if s >= 80 else "рабочий, но с потерями" if s >= 55 else "требует вмешательства"
    return s, grade


# ─────────────────────────── HTML ───────────────────────────

CSS = """
:root{
 --bg:#f6f7f5; --surface:#fff; --surface-2:#fafbfa; --ink:#16211f; --muted:#66757a;
 --line:#e2e8e5; --accent:#0f766e; --accent-soft:#e2f4f1;
 --p0:#b42318; --p0-bg:#fdeceb; --p1:#a35a09; --p1-bg:#fdf3e5; --p2:#2f5eb0; --p2-bg:#eaf0fc;
 --ok:#0f766e; --ok-bg:#e2f4f1; --radius:14px;
 --shadow:0 1px 2px rgba(16,32,28,.05), 0 8px 24px rgba(16,32,28,.06);
}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#0f1513; --surface:#161d1b; --surface-2:#1a2220; --ink:#e8efec; --muted:#95a5a3;
 --line:#28322f; --accent:#4fd1c5; --accent-soft:#12302d;
 --p0:#ff8a80; --p0-bg:#2a1614; --p1:#f0b45e; --p1-bg:#2a2113; --p2:#8ab4f8; --p2-bg:#151f2e;
 --ok:#4fd1c5; --ok-bg:#12302d; --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.3);
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.5;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,"Helvetica Neue",Arial,sans-serif;
 font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.wrap{width:min(1180px,94vw);margin:0 auto;padding:28px 0 64px}
header.top{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;
 padding-bottom:18px;border-bottom:1px solid var(--line);margin-bottom:22px}
h1{margin:0;font-size:clamp(21px,2.4vw,30px);letter-spacing:-.02em;line-height:1.15}
.sub{color:var(--muted);font-size:13px;margin-top:6px}
nav.toc{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 22px}
nav.toc a{font-size:12px;color:var(--muted);text-decoration:none;border:1px solid var(--line);
 padding:5px 10px;border-radius:999px;background:var(--surface)}
nav.toc a:hover{color:var(--ink);border-color:var(--accent)}
section{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
 padding:20px;margin-bottom:16px;box-shadow:var(--shadow)}
h2{margin:0 0 4px;font-size:17px;letter-spacing:-.01em}
h2 .num{color:var(--muted);font-weight:400;margin-right:8px}
.lede{color:var(--muted);font-size:13px;margin:0 0 16px;max-width:70ch}
.verdict{display:grid;grid-template-columns:auto 1fr;gap:22px;align-items:center}
.score{width:104px;height:104px;border-radius:50%;display:grid;place-items:center;
 background:conic-gradient(var(--accent) calc(var(--v)*1%), var(--line) 0);position:relative}
.score::after{content:"";position:absolute;inset:9px;border-radius:50%;background:var(--surface)}
.score b{position:relative;z-index:1;font-size:30px;letter-spacing:-.03em}
.score small{position:relative;z-index:1;font-size:11px;color:var(--muted);display:block;text-align:center}
.verdict h3{margin:0 0 6px;font-size:19px;letter-spacing:-.015em}
.verdict ul{margin:8px 0 0;padding-left:18px;font-size:14px;display:grid;gap:5px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;
 background:var(--line);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;margin-top:18px}
.kpi{background:var(--surface);padding:13px 15px}
.kpi .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.kpi .v{font-size:23px;font-weight:650;letter-spacing:-.02em;margin-top:3px}
.kpi .m{font-size:12px;color:var(--muted)}
.actions{display:grid;gap:10px}
.act{display:grid;grid-template-columns:auto 1fr auto;gap:14px;align-items:start;
 border:1px solid var(--line);border-left-width:3px;border-radius:10px;padding:12px 14px;background:var(--surface-2)}
.act.p0{border-left-color:var(--p0)} .act.p1{border-left-color:var(--p1)} .act.p2{border-left-color:var(--p2)}
.tag{font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;white-space:nowrap}
.tag.p0{background:var(--p0-bg);color:var(--p0)} .tag.p1{background:var(--p1-bg);color:var(--p1)}
.tag.p2{background:var(--p2-bg);color:var(--p2)} .tag.ok{background:var(--ok-bg);color:var(--ok)}
.act .what{font-weight:600;font-size:14px} .act .why{color:var(--muted);font-size:13px;margin-top:3px}
.act .eff{font-size:12px;color:var(--muted);text-align:right;max-width:20ch}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.card{border:1px solid var(--line);border-radius:10px;padding:13px 14px;background:var(--surface-2)}
.card h4{margin:0 0 4px;font-size:13px;display:flex;justify-content:space-between;gap:8px;align-items:center}
.card p{margin:0;font-size:12px;color:var(--muted)}
.bars{display:grid;gap:7px;margin:6px 0 4px}
.bar-row{display:grid;grid-template-columns:minmax(90px,1.1fr) 2.4fr auto;gap:10px;align-items:center;font-size:13px}
.bar-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--muted)}
.bar-track{height:9px;border-radius:5px;background:var(--line);overflow:hidden}
.bar-fill{height:100%;border-radius:5px;background:var(--accent)}
.bar-val{font-size:12px;white-space:nowrap}
.bar-sec{color:var(--muted);margin-left:8px}
.spark{width:100%;height:90px}
.spark-line{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round}
.spark-bar{fill:var(--accent);opacity:.22}
.curve{width:100%;height:150px}
.curve-line{fill:none;stroke:var(--accent);stroke-width:2}
.curve-grid{stroke:var(--line);stroke-width:1;stroke-dasharray:3 3}
.curve-mark{stroke:var(--p1);stroke-width:1.5;stroke-dasharray:4 3}
.curve-text{fill:var(--muted);font-size:11px}
.donut-wrap{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.donut{width:132px;height:132px;transform:rotate(-90deg)}
.ring{fill:none;stroke-width:16}
.ring.a{stroke:var(--accent)} .ring.b{stroke:var(--p2)} .ring.c{stroke:var(--line)}
.legend{display:grid;gap:6px;font-size:13px}
.lg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:7px}
.lg i.a{background:var(--accent)} .lg i.b{background:var(--p2)} .lg i.c{background:var(--line)}
.cols{display:grid;grid-template-columns:1.1fr .9fr;gap:20px}
details{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
summary{cursor:pointer;font-size:13px;color:var(--muted);list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸ ";color:var(--accent)}
details[open] summary::before{content:"▾ "}
.tbl{overflow-x:auto;margin-top:10px;border:1px solid var(--line);border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:13px;min-width:520px}
th{background:var(--surface-2);text-align:left;font-weight:600;font-size:11px;color:var(--muted);
 text-transform:uppercase;letter-spacing:.05em;padding:9px 12px;border-bottom:1px solid var(--line)}
td{padding:9px 12px;border-bottom:1px solid var(--line)}
tbody tr:last-child td{border-bottom:0}
td.r,th.r{text-align:right}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
.strat{font-size:13px;line-height:1.35}
.strat.off{color:var(--muted)}
.strat-meta{display:block;font-size:11px;color:var(--muted);margin-top:2px}
.note{border-left:3px solid var(--accent);background:var(--accent-soft);padding:11px 14px;
 border-radius:0 8px 8px 0;font-size:13px;margin:14px 0 0}
.note.warn{border-color:var(--p1);background:var(--p1-bg)}
.note.crit{border-color:var(--p0);background:var(--p0-bg)}
footer{color:var(--muted);font-size:12px;margin-top:22px;text-align:center}
@media (max-width:820px){.cols{grid-template-columns:1fr}.verdict{grid-template-columns:1fr}
 .act{grid-template-columns:auto 1fr}.act .eff{grid-column:2;text-align:left;max-width:none}}
@media print{body{background:#fff}section{break-inside:avoid;box-shadow:none}
 nav.toc{display:none}details{display:block}details summary{display:none}}
"""


def render(a, live, camps, findings, score, grade, total, cpa, target, camp_rows,
           day_pts, net, pl, inv=None, urls=None):
    crit = [f for f in findings if f["level"] == checks.CRIT]
    warn = [f for f in findings if f["level"] == checks.WARN]
    info = [f for f in findings if f["level"] == checks.INFO]

    top_line = []
    if crit:
        top_line.append(f"<b>{len(crit)}</b> "
                        + plural(len(crit), "находка", "находки", "находок")
                        + " уровня «критично» — деньги или данные теряются сейчас")
    if pl and not pl["cand"]:
        top_line.append(f"Площадки РСЯ чистить нечего: порог значимости "
                        f"({n(pl['thr'])} кликов) не проходит ни одна нулевая площадка")
    if total["conv"]:
        top_line.append(f"CPA за период — <b>{money(cpa)}</b>"
                        + (f" при целевом {money(target)}" if a.target_cpa else ""))
    top_line.append(f"Активных кампаний {len(live)}, находок всего {len(findings)}: "
                    f"{len(crit)} " + plural(len(crit), "критичная", "критичных", "критичных")
                    + f", {len(warn)} " + plural(len(warn), "важная", "важных", "важных")
                    + f", {len(info)} на улучшение")

    url_acts = []
    if urls:
        bad = [r for r in urls["items"] if r["problem"]]
        live_bad = [r for r in bad if r["active_count"]]
        if live_bad:
            url_acts.append((P0, f"битые посадочные в работающих объектах: {len(live_bad)}",
                             "; ".join(r["url"] for r in live_bad[:3]),
                             "клик оплачен, пользователь на ошибке"))
        elif bad:
            url_acts.append((P2, f"битые ссылки в остановленных объектах: {len(bad)}",
                             "; ".join(r["url"] for r in bad[:3]),
                             "починить до перезапуска"))

    items = list(url_acts)
    for f in crit + warn + info:
        hint = effect_hint(f)
        if hint and hint.lower() in f["detail"].lower():
            hint = ""
        items.append((LEVEL_TO_P[f["level"]], f["what"], f["detail"], hint))
    items.sort(key=lambda x: (P0, P1, P2).index(x[0]))

    acts = []
    for p, what, detail, hint in items:
        acts.append(f'<div class="act {p.lower()}"><span class="tag {p.lower()}">{p}</span>'
                    f'<div><div class="what">{E(what)}</div>'
                    f'<div class="why">{E(detail)}</div></div>'
                    f'<div class="eff">{E(hint)}</div></div>')

    net_parts = []
    order = [("Поиск", "SEARCH", "a"), ("Сети", "AD_NETWORK", "b")]
    for label, key, cls in order:
        if net.get(key):
            net_parts.append((label, net[key], cls))

    blocks = []
    blocks.append(section_verdict(a, score, grade, top_line, total, cpa, target, len(live)))
    blocks.append(f'<section id="plan"><h2><span class="num">01</span>Что делать первым</h2>'
                  f'<p class="lede">Порядок по влиянию на деньги. P0 — теряется бюджет или '
                  f'данные прямо сейчас, P1 — ограничивает результат, P2 — даст прирост, но не горит.</p>'
                  f'<div class="actions">{"".join(acts)}</div></section>')
    blocks.append(section_campaigns(camp_rows, day_pts, net_parts, target, inv))
    if pl:
        blocks.append(section_places(pl))
    if urls:
        blocks.append(section_urls(urls))
    blocks.append(section_settings(live, camps))

    toc = ('<nav class="toc"><a href="#plan">План правок</a><a href="#camps">Кампании</a>'
           + ('<a href="#places">Площадки РСЯ</a>' if pl else "")
           + ('<a href="#urls">Посадочные</a>' if urls else "")
           + '<a href="#settings">Настройки</a></nav>')

    title = f"Аудит аккаунта — {a.account}" if a.account else "Аудит рекламного аккаунта"
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)}</title><style>{CSS}</style></head><body><div class="wrap">
<header class="top"><div><h1>{E(title)}</h1>
<div class="sub">{E(a.period or '')} · сформировано {date.today().isoformat()} · Яндекс Директ</div></div>
<div class="sub mono">кампаний {len(camps)} · активных {len(live)}</div></header>
{toc}{"".join(blocks)}
<footer>Источники: API Директа (campaigns / adgroups / keywords / ads v501, reports).
Отчёт статический, данные встроены в файл.</footer>
</div></body></html>"""


def effect_hint(f):
    w = f["what"].lower()
    if "цел" in w and "стратег" in w:
        return "стратегия начнёт видеть конверсии"
    if "счётчик" in w:
        return "без этого автостратегия слепа"
    if "минус-слов" in w:
        return "срежет нецелевые клики"
    if "клон" in w:
        return "комбинаторика поднимет CTR"
    if "дубл" in w:
        return "уберёт конкуренцию с собой"
    if "геотаргетинг" in w:
        return "проверить долю чужих регионов"
    if "изображени" in w:
        return "в сетях можно до 5"
    if "одним" in w or "единственн" in w:
        return "нечего ротировать"
    if "площад" in w:
        return "проверить, не режет ли охват"
    return ""


def section_verdict(a, score, grade, lines, total, cpa, target, live_n):
    kpis = [("Расход", money(total["cost"]), a.period or ""),
            ("Клики", n(total["clicks"]),
             f'CTR {total["clicks"]/total["imps"]*100:.2f}%' if total["imps"] else ""),
            ("Конверсии", n(total["conv"]),
             f'CR {total["conv"]/total["clicks"]*100:.1f}%' if total["clicks"] else ""),
            ("CPA", money(cpa) if cpa else "—",
             f"цель {money(target)}" if a.target_cpa else "цель не задана")]
    kh = "".join(f'<div class="kpi"><div class="l">{E(l)}</div><div class="v">{v}</div>'
                 f'<div class="m">{E(m)}</div></div>' for l, v, m in kpis)
    return (f'<section><div class="verdict">'
            f'<div class="score" style="--v:{score}"><b>{score}</b><small>из 100</small></div>'
            f'<div><h3>Аккаунт {E(grade)}</h3><ul>'
            + "".join(f"<li>{l}</li>" for l in lines)
            + f'</ul></div></div><div class="kpis">{kh}</div></section>')


STRATEGY_NAMES = {
    "SERVING_OFF": "показы отключены",
    "NETWORK_DEFAULT": "как на Поиске",
    "HIGHEST_POSITION": "Ручное управление ставками",
    "WB_MAXIMUM_CLICKS": "Максимум кликов",
    "AVERAGE_CPC": "Максимум кликов · средняя цена клика",
    "WB_MAXIMUM_CONVERSION_RATE": "Максимум конверсий",
    "AVERAGE_CPA": "Максимум конверсий · средняя цена конверсии",
    "PAY_FOR_CONVERSION": "Максимум конверсий · оплата за конверсии",
    "AVERAGE_ROI": "Максимум конверсий · ДРР",
    "AVERAGE_CRR": "Максимум конверсий · ДРР",
    "PAY_FOR_CONVERSION_CRR": "Оплата за конверсии · ДРР",
    "WB_MAXIMUM_APP_INSTALLS": "Максимум установок приложения",
    "AVERAGE_CPI": "Максимум установок · средняя цена установки",
    "MAXIMUM_IMPRESSIONS": "Максимум показов по минимальной цене",
    "MAXIMUM_COVERAGE": "Максимальный охват",
    "MAXIMUM_IMPRESSION_SHARE": "Максимум показов по минимальной цене",
    "WB_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS": "Снижение цены повторных показов",
    "CP_AVERAGE_CPV": "Оплата за просмотры",
    "PORTFOLIO": "Пакетная стратегия",
}


def strategy_cell(camp, place):
    """Человеческое название стратегии и её ограничения. API-код в отчёт не выносим."""
    bs = checks.body(camp).get("BiddingStrategy") or {}
    blk = bs.get(place) or {}
    code = blk.get("BiddingStrategyType") or "—"
    name = STRATEGY_NAMES.get(code, code)
    params = next((v for v in blk.values() if isinstance(v, dict)), {})
    bits = []
    if params.get("Cpa"):
        bits.append(f"цена конверсии {money(params['Cpa'] / 1e6)}")
    if params.get("AverageCpc"):
        bits.append(f"клик до {money(params['AverageCpc'] / 1e6)}")
    if params.get("Crr"):
        bits.append(f"ДРР {params['Crr']}%")
    if params.get("WeeklySpendLimit"):
        bits.append(f"{money(params['WeeklySpendLimit'] / 1e6)}/нед")
    gid = params.get("GoalId")
    if gid:
        # У целей Метрики идентификаторы восьми-девятизначные. Короткий id — не клиентская цель;
        # что именно за ним стоит, из API не видно, поэтому помечаем к проверке, а не называем.
        bits.append(f"цель №{gid} — проверить в интерфейсе" if gid < 1_000_000
                    else f"цель №{gid}")
    extra = (checks.body(camp).get("PriorityGoals") or {}).get("Items") or []
    if params and len(extra) > 1:
        bits.append(f"ключевых целей {len(extra)}")
    cls = " off" if code == "SERVING_OFF" else ""
    return (f'<div class="strat{cls}">{E(name)}'
            + (f'<span class="strat-meta">{E(" · ".join(bits))}</span>' if bits else "")
            + "</div>")


target_given = [False]


def section_campaigns(rows, day_pts, net_parts, target, inv=None):
    if not rows:
        return ""
    bar_rows = [{"name": r["name"], "cost": r["cost"],
                 "cpa": (money(r["cpa"]) if r["cpa"] else "нет конверсий")} for r in rows[:10]]
    tbl = "".join(
        f'<tr><td>{E(r["name"])}</td><td class="r">{n(r["clicks"])}</td>'
        f'<td class="r">{r["ctr"]:.2f}%</td><td class="r">{money(r["cost"])}</td>'
        f'<td class="r">{n(r["conv"])}</td>'
        f'<td class="r">{money(r["cpa"]) if r["cpa"] else "—"}</td></tr>' for r in rows)
    over = [r for r in rows if target and r["cpa"] > target * 1.5 and r["conv"] >= 5]
    if not target_given[0]:
        over = []
    inv_note = (f'<p class="note crit">Кампании вне слепка настроек: '
                f'{", ".join(E(x) for x in inv["names"])} — {money(inv["cost"])}, '
                f'{inv["share"]:.0f}% расхода. Мастер кампаний не отдаётся в `campaigns.get`, '
                f'поэтому её настройки в аудит не попали: проверять в интерфейсе руками.</p>'
                if inv else "")
    note = (f'<p class="note warn">Выше целевого CPA в полтора раза и больше: '
            f'{", ".join(E(r["name"]) for r in over)}.</p>' if over else "")
    return (f'<section id="camps"><h2><span class="num">02</span>Где деньги</h2>'
            f'<p class="lede">Расход по кампаниям и динамика периода. Линия — расход по дням, '
            f'столбики — конверсии: расхождение формы линий и есть повод копать.</p>'
            f'<div class="cols"><div>{bars(bar_rows, "name", "cost", "cpa")}</div>'
            f'<div>{donut(net_parts) if net_parts else ""}</div></div>'
            f'{sparkline(day_pts)}{inv_note}{note}'
            f'<details><summary>Таблица по всем кампаниям ({len(rows)})</summary><div class="tbl">'
            f'<table><thead><tr><th>Кампания</th><th class="r">Клики</th><th class="r">CTR</th>'
            f'<th class="r">Расход</th><th class="r">Конв.</th><th class="r">CPA</th></tr></thead>'
            f'<tbody>{tbl}</tbody></table></div></details></section>')


def section_places(pl):
    cand = pl["cand"]
    verdict = (f'<p class="note">Кандидатов на запрет нет. Порог значимости — '
               f'{n(pl["thr"])} кликов при CR в сетях {pl["cr"]*100:.1f}%; '
               f'ни одна площадка без конверсий его не проходит. '
               f'Хвост из {n(pl["tail_n"])} нулевых площадок — это '
               f'{pl["tail_cost"]/pl["total_cost"]*100:.0f}% расхода и статистический шум: '
               f'блокировать его нельзя, данных на площадку не хватает даже на один вывод.</p>'
               if not cand else
               f'<p class="note warn">Кандидатов на запрет: {len(cand)}, освобождается '
               f'{money(sum(r["cost"] for r in cand))} '
               f'({sum(r["cost"] for r in cand)/pl["total_cost"]*100:.1f}% расхода сетей). '
               f'Порог — {n(pl["thr"])} кликов.</p>')
    tbl_rows = cand[:20] if cand else pl["top"]
    tbl = "".join(
        f'<tr><td class="mono">{E(r["name"])}</td><td class="r">{n(r["clicks"])}</td>'
        f'<td class="r">{money(r["cost"])}</td><td class="r">{n(r["conv"])}</td>'
        f'<td class="r">{r["bounce"]:.0f}%</td></tr>' for r in tbl_rows)
    cap = "Кандидаты на запрет" if cand else "Топ площадок по расходу"
    return (f'<section id="places"><h2><span class="num">03</span>Площадки РСЯ</h2>'
            f'<p class="lede">Кривая показывает концентрацию расхода: по оси X — площадки '
            f'от самых дорогих к дешёвым, по Y — накопленная доля денег. Чем круче начало, '
            f'тем меньше площадок реально стоит разбирать.</p>'
            f'<div class="cols"><div>{concentration_curve([r["cost"] for r in pl["rows"]])}</div>'
            f'<div class="grid"><div class="card"><h4>Площадок с показами</h4>'
            f'<p style="font-size:22px;color:var(--ink)">{n(len(pl["rows"]))}</p></div>'
            f'<div class="card"><h4>Порог значимости</h4>'
            f'<p style="font-size:22px;color:var(--ink)">{n(pl["thr"])} кликов</p>'
            f'<p>3 / CR в сетях</p></div></div></div>{verdict}'
            f'<details open><summary>{cap} ({len(tbl_rows)})</summary><div class="tbl"><table>'
            f'<thead><tr><th>Площадка</th><th class="r">Клики</th><th class="r">Расход</th>'
            f'<th class="r">Конв.</th><th class="r">Отказы</th></tr></thead>'
            f'<tbody>{tbl}</tbody></table></div></details></section>')


def section_urls(urls):
    items = urls["items"]
    bad = [r for r in items if r["problem"]]
    live_bad = [r for r in bad if r["active_count"]]
    ok = len(items) - len(bad)
    if not bad:
        note = ('<p class="note">Все проверенные адреса отвечают 200 без подмены страницы. '
                'Проверка разовая: сайт мог измениться после неё — повторять при каждом аудите '
                'и после правок на сайте.</p>')
    elif live_bad:
        note = (f'<p class="note crit">Битых адресов в работающих объектах: {len(live_bad)}. '
                f'Клики по ним оплачиваются, а пользователь попадает на ошибку — '
                f'чинить в первую очередь.</p>')
    else:
        note = (f'<p class="note warn">Проблемных адресов: {len(bad)}, но все они только '
                f'в остановленных объектах. На расход сейчас не влияют, починить до перезапуска.</p>')
    rows = "".join(
        f'<tr><td class="mono">{E(r["url"])}</td>'
        f'<td class="r">{r["status"] or "—"}</td>'
        f'<td>{E(r["problem"] or "норма")}</td>'
        f'<td class="mono">{E(r["detail"])}</td>'
        f'<td class="r">{r["used_count"]}</td>'
        f'<td class="r">{r["active_count"]}</td></tr>'
        for r in sorted(items, key=lambda r: (r["problem"] is None, -r["active_count"])))
    cards = (f'<div class="grid"><div class="card"><h4>Проверено адресов</h4>'
             f'<p style="font-size:22px;color:var(--ink)">{len(items)}</p></div>'
             f'<div class="card"><h4>Отвечают нормально</h4>'
             f'<p style="font-size:22px;color:var(--ink)">{ok}</p></div>'
             f'<div class="card"><h4>С проблемой</h4>'
             f'<p style="font-size:22px;color:var(--ink)">{len(bad)}</p>'
             f'<p>из них в показах: {len(live_bad)}</p></div></div>')
    return (f'<section id="urls"><h2><span class="num">04</span>Посадочные страницы</h2>'
            f'<p class="lede">Каждый уникальный адрес из объявлений и быстрых ссылок '
            f'запрошен один раз: код ответа, цепочка редиректов, подмена страницы. '
            f'Макросы вида {{campaign_id}} вырезаны, UTM отброшены — проверяется сама страница.</p>'
            f'{cards}{note}'
            f'<details{" open" if bad else ""}><summary>Все проверенные адреса ({len(items)})</summary>'
            f'<div class="tbl"><table><thead><tr><th>Адрес</th><th class="r">Код</th>'
            f'<th>Диагноз</th><th>Детали</th><th class="r">Объектов</th>'
            f'<th class="r">В показах</th></tr></thead><tbody>{rows}</tbody></table></div>'
            f'</details></section>')


def section_settings(live, camps):
    cards = []
    rows = []
    for c in live.values():
        b = checks.body(c)
        st = checks.strategy_types(c)
        flags = []
        for opt, good, label in (("ENABLE_SITE_MONITORING", "YES", "мониторинг"),
                                 ("ADD_METRICA_TAG", "YES", "разметка"),
                                 ("ENABLE_AREA_OF_INTEREST_TARGETING", "NO", "расшир. гео")):
            v = checks.setting(c, opt)
            flags.append((label, v == good, v))
        rows.append((c["Name"], strategy_cell(c, "Search"), strategy_cell(c, "Network"),
                     "да" if b.get("CounterIds") else "нет",
                     "да" if b.get("PriorityGoals") else "нет", flags,
                     len((c.get("NegativeKeywords") or {}).get("Items") or []),
                     len((c.get("ExcludedSites") or {}).get("Items") or [])))
    tbl = "".join(
        f'<tr><td>{E(name)}</td><td>{s}</td><td>{nw}</td>'
        f'<td>{cnt}</td><td>{goals}</td>'
        + "".join(f'<td><span class="tag {"ok" if ok else "p1"}">{E(str(v))}</span></td>'
                  for _, ok, v in fl)
        + f'<td class="r">{neg}</td><td class="r">{exc}</td></tr>'
        for name, s, nw, cnt, goals, fl, neg, exc in rows)
    return (f'<section id="settings"><h2><span class="num">05</span>Настройки активных кампаний</h2>'
            f'<p class="lede">Слепок значений, а не пересказ. Жёлтым помечено то, что отличается '
            f'от рекомендованного для этого типа кампании.</p>'
            f'<div class="tbl"><table><thead><tr><th>Кампания</th><th>Стратегия на Поиске</th>'
            f'<th>Стратегия в сетях</th><th>Счётчик</th><th>Цели</th><th>Мониторинг</th><th>Разметка</th>'
            f'<th>Расш. гео</th><th class="r">Минус-слов</th><th class="r">Запрещ. площадок</th>'
            f'</tr></thead><tbody>{tbl}</tbody></table></div></section>')


snap_path_holder = [None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--campaigns", help="TSV: CAMPAIGN_PERFORMANCE_REPORT")
    ap.add_argument("--placements", help="TSV: отчёт по площадкам (только сети)")
    ap.add_argument("--urls", help="JSON: результат urls.py")
    ap.add_argument("--days", help="TSV: расход и конверсии по дням")
    ap.add_argument("--target-cpa", type=float)
    ap.add_argument("--account", default="")
    ap.add_argument("--period", default="")
    ap.add_argument("--anonymize", action="store_true", help="заменить названия кампаний на номера")
    ap.add_argument("--out", default="audit.html")
    a = ap.parse_args()
    snap_path_holder[0] = a.snapshot
    target_given[0] = a.target_cpa is not None
    open(a.out, "w", encoding="utf-8").write(build(a))
    print(a.out)


if __name__ == "__main__":
    main()
