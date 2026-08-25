#!/usr/bin/env python3
"""Стратегия в один HTML-файл: markdown-артефакты + графика по данным.

    python3 report.py --project projects/domsegodnya --out projects/domsegodnya/strategy/strategy.html

Читает `strategy/*.md` и структурированные данные, если они есть: `usp.json`, `personas.json`,
`channels.json`, `budget.json`, `_state.json`, `data/demand.json`.

Правило вёрстки: **где есть структура — рисуем её, текст уходит под спойлер «подробности»**.
Отчёт читают сверху вниз и обычно не целиком, поэтому первый экран — вывод и четыре цифры,
дальше визуальные блоки, а сплошной текст остаётся доказательной базой для того, кто копает. Markdown рендерится
своим минимальным конвертером — внешних зависимостей нет, файл самодостаточный: ни шрифтов,
ни скриптов снаружи. Оформление то же, что у дашборда аудита (audit/dashboard.md).
"""
import argparse, html, json, os, re, sys
from datetime import date

E = html.escape
ORDER = ["strategy", "brief", "demand", "competitors", "personas", "channels", "budget",
         "kpi", "handoff"]
TITLES = {
    "strategy": "Сводка", "brief": "Бриф", "demand": "Спрос", "competitors": "Конкуренты",
    "personas": "Персоны",
    "channels": "Каналы", "budget": "Бюджет", "kpi": "KPI", "handoff": "Передача",
}


# ─────────────────────────── markdown ───────────────────────────

def inline(s):
    s = E(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"<i>\1</i>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def md(text):
    """Достаточный для наших артефактов набор: заголовки, таблицы, списки, цитаты, код."""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(E(lines[i]))
                i += 1
            out.append(f'<pre><code>{chr(10).join(buf)}</code></pre>')
        elif re.match(r"^\|.*\|\s*$", line) and i + 1 < len(lines) and re.match(
                r"^\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and re.match(r"^\|.*\|\s*$", lines[i]):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            i -= 1
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            tb = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                         for r in rows)
            out.append(f'<div class="tbl"><table><thead><tr>{th}</tr></thead>'
                       f"<tbody>{tb}</tbody></table></div>")
        elif re.match(r"^#{1,4} ", line):
            lvl = len(line) - len(line.lstrip("#"))
            out.append(f"<h{min(lvl + 1, 5)}>{inline(line.lstrip('# ').strip())}</h{min(lvl + 1, 5)}>")
        elif re.match(r"^\s*[-*] ", line) or re.match(r"^\s*\d+\. ", line):
            tag = "ul" if re.match(r"^\s*[-*] ", line) else "ol"
            items = []
            while i < len(lines) and (re.match(r"^\s*[-*] ", lines[i])
                                      or re.match(r"^\s*\d+\. ", lines[i])):
                items.append(re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", lines[i]))
                i += 1
            i -= 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
        elif line.startswith(">"):
            out.append(f'<blockquote>{inline(line.lstrip("> "))}</blockquote>')
        elif line.strip() == "":
            pass
        else:
            buf = [line]
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(
                    r"^(#{1,4} |\||>|```|\s*[-*] |\s*\d+\. )", lines[i + 1]):
                i += 1
                buf.append(lines[i])
            out.append(f"<p>{inline(' '.join(buf))}</p>")
        i += 1
    return "\n".join(out)


# ─────────────────────────── блоки по данным ───────────────────────────

def demand_block(data, embed=False):
    if not data:
        return ""
    themes = data.get("themes", [])
    live = sum(len(t["live"]) for t in themes)
    total = sum(len(t["phrases"]) for t in themes)
    rows = ""
    for t in themes:
        share = t["share"]
        cls = "bad" if share == 0 else ("warn" if share < 60 else "")
        rows += (f'<div class="bar-row"><div class="bar-label">{E(t["theme"])}</div>'
                 f'<div class="bar-track"><div class="bar-fill {cls}" '
                 f'style="width:{share}%"></div></div>'
                 f'<div class="bar-val">{len(t["live"])}/{len(t["phrases"])}</div></div>')
    inner = (f'<p class="lede">Каждая тема — набор формулировок, проверенных через API Директа '
            f'на наличие показов в регионе. Полоса — доля фраз со спросом.</p>'
            f'<div class="kpis"><div class="kpi"><div class="l">Тем проверено</div>'
            f'<div class="v">{len(themes)}</div></div>'
            f'<div class="kpi"><div class="l">Фраз</div><div class="v">{total}</div></div>'
            f'<div class="kpi"><div class="l">Со спросом</div><div class="v">{live}</div>'
            f'<div class="m">{live / total * 100:.0f}% от проверенных</div></div>'
            f'<div class="kpi"><div class="l">Регионы</div>'
            f'<div class="v">{", ".join(str(x) for x in data.get("geo", []))}</div></div></div>'
            f'<div class="bars">{rows}</div>')
    if embed:
        return inner
    return (f'<section id="demand-data"><h2><span class="num">##</span>Проверка спроса</h2>'
            f'{inner}</section>')


def usp_block(u):
    if not u:
        return ""
    main, backup = u.get("main", {}), u.get("backup", {})
    k = main.get("kotler", {})
    marks = "".join(
        f'<span class="tag {"ok" if v else "p0"}">{E(name)}</span>'
        for name, v in [("конкретное", k.get("specific")), ("отличающее", k.get("unique")),
                        ("цепляющее", k.get("compelling")), ("правдоподобное", k.get("believable")),
                        ("запоминающееся", k.get("memorable"))])
    rejected = "".join(f'<tr><td>{E(r["text"])}</td><td>{E(r["why"])}</td></tr>'
                       for r in u.get("rejected", []))
    chips = lambda items: "".join(f'<span class="chip">{E(x)}</span>' for x in items)
    return (f'<section id="usp-data"><h2><span class="num">##</span>УТП</h2>'
            f'<div class="usp-main"><div class="usp-text">{E(main.get("text", ""))}</div>'
            f'<div class="usp-proof">Подтверждается: {E(main.get("proof", ""))}</div>'
            f'<div class="usp-marks">{marks}</div>'
            + (f'<p class="why">{E(main.get("why", ""))}</p>' if main.get("why") else "")
            + "</div>"
            f'<div class="card"><h4>Резервное</h4><p>{E(backup.get("text", ""))}</p></div>'
            + (f'<p class="note warn">{E(u["gap"])}</p>' if u.get("gap") else "")
            + f'<h3>Уточнения</h3><div class="chips">{chips(u.get("callouts", []))}</div>'
            f'<h3>Идеи быстрых ссылок</h3><div class="chips">{chips(u.get("sitelink_ideas", []))}</div>'
            + (f'<details><summary>Отбраковано ({len(u.get("rejected", []))})</summary>'
               f'<div class="tbl"><table><thead><tr><th>Формулировка</th><th>Почему нет</th>'
               f'</tr></thead><tbody>{rejected}</tbody></table></div></details>' if rejected else "")
            + "</section>")


def hero_block(state, demand, channels):
    """Первый экран: вывод одной фразой и цифры, ради которых читают отчёт."""
    live = total = 0
    if demand:
        live = sum(len(t["live"]) for t in demand.get("themes", []))
        total = sum(len(t["phrases"]) for t in demand.get("themes", []))
    top = ""
    if channels:
        best = sorted((c for c in channels["channels"] if c.get("rank")),
                      key=lambda c: c["rank"])
        top = " → ".join(c["name"] for c in best[:3])
    tiles = [("Спрос подтверждён", f"{live}/{total}", "фраз со спросом" if total else ""),
             ("Топ-канал", (top.split(" → ")[0] if top else "—"), "по сумме баллов"),
             ("Шаг", f'{state.get("step", "—")}/8', state.get("mode", "")),
             ("Открытых вопросов", str(len(state.get("blocked_on") or [])), "ждём от клиента")]
    kh = "".join(f'<div class="kpi"><div class="l">{E(l)}</div><div class="v">{E(v)}</div>'
                 f'<div class="m">{E(m)}</div></div>' for l, v, m in tiles)
    verdict = state.get("verdict") or ""
    chain = (f'<div class="chain">{"".join(f"<span class=chain-item>{E(x)}</span>" for x in top.split(" → "))}</div>'
             if top else "")
    return (f'<section class="hero"><div class="hero-grid"><div>'
            f'<div class="eyebrow">Вывод</div>'
            f'<p class="verdict">{E(verdict)}</p>{chain}</div></div>'
            f'<div class="kpis">{kh}</div></section>')


def gaps_block(demand):
    """Темы со спросом, под которые нет посадочной, — главная находка проверки."""
    gaps = (demand or {}).get("gaps") or []
    if not gaps:
        return ""
    tiles = "".join(
        f'<div class="gap"><div class="gap-theme">{E(g["theme"])}</div>'
        f'<div class="gap-status">{E(g["status"])}</div>'
        f'<div class="gap-site">{E(g["site"])}</div></div>' for g in gaps)
    return (f'<div class="note warn"><b>Спрос есть, посадочной нет.</b> Вести туда рекламу '
            f'нельзя: объявление обещает то, чего страница не подтверждает.</div>'
            f'<div class="gaps">{tiles}</div>')


def channels_block(ch):
    if not ch:
        return ""
    crit = ch["criteria"]
    rows = []
    for c in sorted(ch["channels"], key=lambda c: -sum(c["scores"])):
        total = sum(c["scores"])
        medal = {1: "1", 2: "2", 3: "3"}.get(c.get("rank"), "")
        cells = "".join(
            f'<span class="dots" title="{E(name)}: {v}">' +
            "".join(f'<i class="{"on" if k < v else ""}"></i>' for k in range(3)) + "</span>"
            for name, v in zip(crit, c["scores"]))
        rows.append(
            f'<div class="chan{" top" if medal else ""}">'
            f'<div class="chan-name">{"<b class=rank>" + medal + "</b>" if medal else ""}'
            f'{E(c["name"])}</div>'
            f'<div class="chan-dots">{cells}</div>'
            f'<div class="chan-bar"><div class="bar-track"><div class="bar-fill" '
            f'style="width:{total / (len(crit) * 3) * 100:.0f}%"></div></div>'
            f'<span class="chan-total">{total}</span></div>'
            f'<div class="chan-why">{E(c.get("why", ""))}</div></div>')
    legend = " · ".join(E(x) for x in crit)
    return (f'<p class="lede">Шесть критериев по три балла: {legend}. '
            f'Точки — оценка по каждому, полоса — сумма.</p>'
            f'<div class="chans">{"".join(rows)}</div>')


def budget_block(b):
    if not b:
        return ""
    colors = ["a", "b", "c"]
    phases = ""
    for i, p in enumerate(b["phases"]):
        split = "".join(
            f'<div class="split-row"><span>{E(x["ch"])}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{x["pct"]}%"></div></div>'
            f'<span class="pct">{x["pct"]}%</span></div>' for x in p["split"])
        phases += (f'<div class="phase"><div class="phase-head">'
                   f'<span class="phase-n {colors[i % 3]}">{i + 1}</span>'
                   f'<div><div class="phase-name">{E(p["name"])}</div>'
                   f'<div class="phase-weeks">{E(p["weeks"])}</div></div>'
                   f'<div class="phase-share">{p["share"]}%</div></div>'
                   f'<p class="phase-goal">{E(p["goal"])}</p>{split}</div>')
    ruler = "".join(f'<div class="ruler-part {colors[i % 3]}" style="flex:{p["share"]}">'
                    f'{E(p["name"])} · {p["share"]}%</div>'
                    for i, p in enumerate(b["phases"]))
    return (f'<div class="ruler">{ruler}</div>'
            f'<div class="formula"><span class="formula-label">Порог обучения</span>'
            f'<code>{E(b["formula"])}</code></div>'
            + (f'<p class="note warn">{E(b["note"])}</p>' if b.get("note") else "")
            + f'<div class="phases">{phases}</div>')


STATUS_CLS = {"есть": "ok", "нет": "no", "закрыт защитой": "unk", "не открылся": "unk",
              "не проверяли": "unk", "проверен": "ok"}


def competitors_block(c):
    """Факты со сканирования + матрица каналов, где у каждой ячейки виден способ проверки."""
    if not c:
        return ""
    comps = c.get("competitors", [])
    checked = [x for x in comps if x.get("status") == "проверен"]
    with_prices = [x for x in checked if x.get("has_prices")]
    branded = [x for x in comps if x.get("brand_searched")]
    units = [u for x in comps for u in x.get("unit_prices", [])]
    pos = c.get("our_position") or {}

    tiles = [("Проверено сайтов", f"{len(checked)}/{len(comps)}", "остальные закрыты"),
             ("С ценами на сайте", str(len(with_prices)), "из проверенных"),
             ("Цена за м²", pos.get("unit_market", "—") if units else "не найдена", "по рынку"),
             ("Бренд ищут", str(len(branded)), "из всех проверенных")]
    kh = "".join(f'<div class="kpi"><div class="l">{E(l)}</div><div class="v">{E(v)}</div>'
                 f'<div class="m">{E(m)}</div></div>' for l, v, m in tiles)

    rows = ""
    for x in comps:
        st = x.get("status", "")
        chips = "".join(f'<span class="chip obj">{E(cl)}</span>' for cl in x.get("cliches", []))
        proofs = "".join(f'<span class="chip">{E(pf)}</span>' for pf in x.get("proofs", [])[:4])
        prices = ", ".join(x.get("unit_prices", [])[:2]) or (
            f'{min(x["prices"]):,} – {max(x["prices"]):,} ₽'.replace(",", " ")
            if x.get("prices") else "—")
        rows += (f'<tr><td><b>{E(x["name"])}</b><div class="muted-s">{E(x.get("title", "")[:60])}</div></td>'
                 f'<td><span class="tag {STATUS_CLS.get(st, "unk")}">{E(st)}</span></td>'
                 f'<td>{E(prices)}</td>'
                 f'<td>{proofs or "—"}</td>'
                 f'<td>{chips or "—"}</td>'
                 f'<td>{"ищут" if x.get("brand_searched") else "нет"}</td></tr>')

    matrix = c.get("channels_matrix") or {}
    mrows = ""
    for r in matrix.get("rows", []):
        cells = "".join(f'<td><span class="mark {STATUS_CLS.get(v, "unk")}">{E(v)}</span></td>'
                        for v in r["cells"])
        gap = E(r.get("gap", ""))
        gap_html = f'<b>{gap}</b>' if gap.startswith("GAP") else gap
        mrows += (f'<tr><td>{E(r["channel"])}</td>{cells}'
                  f'<td>{E(r.get("density", ""))}</td><td>{gap_html}</td></tr>')
    heads = "".join(f"<th>{E(x['name'].split()[0])}</th>" for x in comps)
    matrix_html = ("" if not mrows else
                   f'<h3>Матрица присутствия</h3>'
                   f'<p class="lede">{E(matrix.get("method", ""))}</p>'
                   f'<div class="tbl"><table><thead><tr><th>Канал</th>{heads}'
                   f'<th>Плотность</th><th>Вывод</th></tr></thead><tbody>{mrows}</tbody></table></div>')

    verdict = (f'<p class="note warn"><b>Позиционирование по цене.</b> {E(pos.get("verdict", ""))} '
               f'Наши цены: {E(pos.get("prices", "—"))}.</p>' if pos else "")

    return (f'<div class="kpis">{kh}</div>{verdict}'
            f'<div class="tbl"><table><thead><tr><th>Конкурент</th><th>Статус</th>'
            f'<th>Цены</th><th>Доказательства</th><th>Штампы</th><th>Бренд</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>{matrix_html}')


def personas_block(p):
    if not p:
        return ""
    cards = ""
    for x in p["personas"]:
        chips = lambda items, cls: "".join(
            f'<span class="chip {cls}">{E(i)}</span>' for i in items)
        cards += (f'<div class="persona"><div class="persona-top">'
                  f'<span class="persona-icon">{E(x.get("icon", ""))}</span>'
                  f'<div><div class="persona-name">{E(x["name"])}</div>'
                  f'<div class="persona-channel">{E(x.get("channel", ""))}</div></div></div>'
                  f'<p class="jtbd">«{E(x["jtbd"])}»</p>'
                  f'<h4>Ищет так</h4><div class="chips">{chips(x.get("search", []), "")}</div>'
                  f'<h4>Боли</h4><div class="chips">{chips(x.get("pains", []), "pain")}</div>'
                  f'<h4>Возражения</h4><div class="chips">{chips(x.get("objections", []), "obj")}</div>'
                  f'<div class="persona-foot"><div><b>Сообщение:</b> {E(x.get("message", ""))}</div>'
                  f'<div><b>Чем закрываем:</b> {E(x.get("answer", ""))}</div></div></div>')
    common = (f'<p class="note">{E(p["common"])}</p>' if p.get("common") else "")
    return f'<div class="personas">{cards}</div>{common}'


CSS = """
:root{--bg:#f6f7f5;--surface:#fff;--surface-2:#fafbfa;--ink:#16211f;--muted:#66757a;
 --line:#e2e8e5;--accent:#0f766e;--accent-soft:#e2f4f1;--p0:#b42318;--p0-bg:#fdeceb;
 --p1:#a35a09;--p1-bg:#fdf3e5;--ok:#0f766e;--ok-bg:#e2f4f1;--radius:14px;
 --shadow:0 1px 2px rgba(16,32,28,.05),0 8px 24px rgba(16,32,28,.06)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#0f1513;--surface:#161d1b;--surface-2:#1a2220;--ink:#e8efec;--muted:#95a5a3;
 --line:#28322f;--accent:#4fd1c5;--accent-soft:#12302d;--p0:#ff8a80;--p0-bg:#2a1614;
 --p1:#f0b45e;--p1-bg:#2a2113;--ok:#4fd1c5;--ok-bg:#12302d;
 --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3)}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.55;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Arial,sans-serif;
 font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.wrap{width:min(1000px,94vw);margin:0 auto;padding:28px 0 64px}
header.top{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;
 flex-wrap:wrap;padding-bottom:18px;border-bottom:1px solid var(--line);margin-bottom:20px}
h1{margin:0;font-size:clamp(21px,2.4vw,30px);letter-spacing:-.02em}
.sub{color:var(--muted);font-size:13px;margin-top:6px}
nav.toc{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 20px}
nav.toc a{font-size:12px;color:var(--muted);text-decoration:none;border:1px solid var(--line);
 padding:5px 10px;border-radius:999px;background:var(--surface)}
nav.toc a:hover{color:var(--ink);border-color:var(--accent)}
section{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
 padding:20px 22px;margin-bottom:16px;box-shadow:var(--shadow)}
h2{margin:0 0 12px;font-size:18px;letter-spacing:-.01em}
h2 .num{color:var(--muted);font-weight:400;margin-right:8px}
h3{font-size:14px;margin:18px 0 6px;letter-spacing:-.01em}
h4{font-size:13px;margin:14px 0 4px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
h5{font-size:13px;margin:12px 0 4px}
p{margin:8px 0}
.lede{color:var(--muted);font-size:13px;max-width:72ch}
ul,ol{margin:8px 0;padding-left:20px}li{margin:3px 0}
blockquote{border-left:3px solid var(--accent);background:var(--accent-soft);margin:12px 0;
 padding:10px 14px;border-radius:0 8px 8px 0}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;
 background:var(--surface-2);border:1px solid var(--line);border-radius:4px;padding:1px 5px}
pre{background:var(--surface-2);border:1px solid var(--line);border-radius:10px;padding:12px;
 overflow-x:auto}pre code{border:0;background:none;padding:0}
.tbl{overflow-x:auto;margin:12px 0;border:1px solid var(--line);border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:var(--surface-2);text-align:left;font-weight:600;font-size:11px;color:var(--muted);
 text-transform:uppercase;letter-spacing:.05em;padding:9px 12px;border-bottom:1px solid var(--line)}
td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;
 background:var(--line);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:14px 0}
.kpi{background:var(--surface);padding:12px 14px}
.kpi .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.kpi .v{font-size:22px;font-weight:650;letter-spacing:-.02em;margin-top:2px}
.kpi .m{font-size:12px;color:var(--muted)}
.bars{display:grid;gap:7px;margin:12px 0}
.bar-row{display:grid;grid-template-columns:minmax(120px,1.4fr) 2.2fr auto;gap:12px;
 align-items:center;font-size:13px}
.bar-label{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-track{height:9px;border-radius:5px;background:var(--line);overflow:hidden}
.bar-fill{height:100%;border-radius:5px;background:var(--accent)}
.bar-fill.warn{background:var(--p1)}.bar-fill.bad{background:var(--p0)}
.bar-val{font-size:12px;white-space:nowrap;color:var(--muted)}
.usp-main{border:1px solid var(--accent);background:var(--accent-soft);border-radius:12px;
 padding:16px 18px;margin:8px 0 14px}
.usp-text{font-size:17px;font-weight:600;letter-spacing:-.01em}
.usp-proof{color:var(--muted);font-size:12px;margin-top:6px}
.usp-marks{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.why{font-size:13px;margin-top:10px}
.tag{font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px}
.tag.ok{background:var(--ok-bg);color:var(--ok)}.tag.p0{background:var(--p0-bg);color:var(--p0)}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-size:12px;border:1px solid var(--line);background:var(--surface-2);
 border-radius:999px;padding:4px 10px}
.card{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:var(--surface-2)}
.note{border-left:3px solid var(--accent);background:var(--accent-soft);padding:11px 14px;
 border-radius:0 8px 8px 0;font-size:13px;margin:14px 0}
.note.warn{border-color:var(--p1);background:var(--p1-bg)}
details{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
summary{cursor:pointer;font-size:13px;color:var(--muted);list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸ ";color:var(--accent)}
details[open] summary::before{content:"▾ "}
footer{color:var(--muted);font-size:12px;margin-top:20px;text-align:center}
/* ── первый экран ── */
.hero{background:linear-gradient(180deg,var(--accent-soft),var(--surface) 70%)}
.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--accent);
 font-weight:700}
.verdict{font-size:clamp(16px,2vw,21px);line-height:1.4;letter-spacing:-.01em;margin:8px 0 0;
 max-width:60ch}
.chain{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;align-items:center}
.chain-item{font-size:12px;font-weight:600;background:var(--surface);border:1px solid var(--line);
 border-radius:999px;padding:5px 12px;position:relative}
.chain-item:not(:last-child)::after{content:"→";position:absolute;right:-14px;top:5px;
 color:var(--muted);font-weight:400}
/* ── текст под спойлером ── */
.prose{max-width:74ch}
.prose>summary{margin-bottom:6px}
details.prose[open]{padding-top:12px}
/* ── дыры спроса ── */
.gaps{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:12px 0}
.gap{border:1px solid var(--p1);background:var(--p1-bg);border-radius:10px;padding:12px 14px}
.gap-theme{font-weight:650;font-size:14px}
.gap-status{font-size:12px;color:var(--ok);margin-top:4px}
.gap-site{font-size:12px;color:var(--muted);margin-top:4px}
/* ── персоны ── */
.personas{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin:12px 0}
.persona{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:var(--surface-2)}
.persona-top{display:flex;gap:12px;align-items:center}
.persona-icon{font-size:26px;line-height:1}
.persona-name{font-weight:650;font-size:15px}
.persona-channel{font-size:12px;color:var(--accent);font-weight:600}
.jtbd{font-size:14px;font-style:italic;color:var(--ink);margin:10px 0;line-height:1.4}
.persona h4{margin:12px 0 5px}
.persona .chip{font-size:11px;padding:3px 9px}
.chip.pain{border-color:var(--p1);background:var(--p1-bg);color:var(--p1)}
.chip.obj{border-color:var(--p0);background:var(--p0-bg);color:var(--p0)}
.tag.ok{background:var(--ok-bg);color:var(--ok)}
.tag.no{background:var(--p0-bg);color:var(--p0)}
.tag.unk{background:var(--surface-2);color:var(--muted);border:1px solid var(--line)}
.mark{font-size:11px;padding:2px 7px;border-radius:5px;white-space:nowrap}
.mark.ok{background:var(--ok-bg);color:var(--ok)}
.mark.no{background:var(--p0-bg);color:var(--p0)}
.mark.unk{background:var(--surface-2);color:var(--muted)}
.muted-s{font-size:11px;color:var(--muted);margin-top:2px}
.persona-foot{margin-top:12px;padding-top:10px;border-top:1px solid var(--line);
 font-size:12px;color:var(--muted);display:grid;gap:4px}
/* ── каналы ── */
.chans{display:grid;gap:8px;margin:12px 0}
.chan{display:grid;grid-template-columns:minmax(150px,1.1fr) auto minmax(120px,.8fr) 1.6fr;
 gap:14px;align-items:center;padding:10px 12px;border:1px solid var(--line);border-radius:10px;
 background:var(--surface-2);font-size:13px}
.chan.top{border-color:var(--accent);background:var(--accent-soft)}
.chan-name{font-weight:600;display:flex;align-items:center;gap:8px}
.rank{width:20px;height:20px;border-radius:50%;background:var(--accent);color:#fff;font-size:11px;
 display:grid;place-items:center;flex:0 0 auto}
.chan-dots{display:flex;gap:6px}
.dots{display:flex;gap:2px}
.dots i{width:5px;height:5px;border-radius:50%;background:var(--line);display:block}
.dots i.on{background:var(--accent)}
.chan-bar{display:flex;align-items:center;gap:8px}
.chan-bar .bar-track{flex:1}
.chan-total{font-weight:650;font-size:13px;min-width:18px;text-align:right}
.chan-why{color:var(--muted);font-size:12px}
/* ── бюджет ── */
.ruler{display:flex;gap:3px;margin:14px 0;font-size:11px;font-weight:600}
.ruler-part{padding:9px 12px;border-radius:8px;color:#fff;white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis}
.ruler-part.a{background:var(--accent)}
.ruler-part.b{background:color-mix(in srgb,var(--accent) 70%,var(--p2,#2f5eb0))}
.ruler-part.c{background:color-mix(in srgb,var(--accent) 40%,#6b7280)}
.formula{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0;
 border:1px dashed var(--accent);border-radius:10px;padding:10px 14px}
.formula-label{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.formula code{font-size:14px;background:none;border:0}
.phases{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;margin-top:12px}
.phase{border:1px solid var(--line);border-radius:12px;padding:14px;background:var(--surface-2)}
.phase-head{display:flex;gap:10px;align-items:center}
.phase-n{width:24px;height:24px;border-radius:8px;color:#fff;display:grid;place-items:center;
 font-size:12px;font-weight:700;flex:0 0 auto}
.phase-n.a{background:var(--accent)}
.phase-n.b{background:color-mix(in srgb,var(--accent) 70%,#2f5eb0)}
.phase-n.c{background:color-mix(in srgb,var(--accent) 40%,#6b7280)}
.phase-name{font-weight:650;font-size:14px}
.phase-weeks{font-size:12px;color:var(--muted)}
.phase-share{margin-left:auto;font-size:18px;font-weight:700;letter-spacing:-.02em}
.phase-goal{font-size:12px;color:var(--muted);margin:8px 0 10px}
.split-row{display:grid;grid-template-columns:minmax(70px,auto) 1fr auto;gap:8px;
 align-items:center;font-size:12px;margin:4px 0}
.split-row .pct{color:var(--muted)}
@media (max-width:720px){.chan{grid-template-columns:1fr;gap:8px}}
@media print{body{background:#fff}section{break-inside:avoid;box-shadow:none}
 nav.toc{display:none}details{display:block}summary{display:none}}
"""


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--project", required=True, help="папка projects/<slug>")
    a.add_argument("--out")
    a.add_argument("--title")
    args = a.parse_args()

    sdir = os.path.join(args.project, "strategy")
    out = args.out or os.path.join(sdir, "strategy.html")
    load = lambda p: json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
    state = load(os.path.join(sdir, "_state.json")) or {}
    usp = load(os.path.join(sdir, "usp.json"))
    personas = load(os.path.join(sdir, "personas.json"))
    channels = load(os.path.join(sdir, "channels.json"))
    budget = load(os.path.join(sdir, "budget.json"))
    demand = load(os.path.join(args.project, "data", "demand.json"))
    competitors = load(os.path.join(args.project, "data", "competitors.json"))

    blocks = [hero_block(state, demand, channels)]
    for name in ORDER:
        path = os.path.join(sdir, name + ".md")
        if not os.path.exists(path):
            continue
        body = md(open(path, encoding="utf-8").read())
        body = re.sub(r"^<h2>.*?</h2>", "", body, count=1)      # заголовок даёт секция
        # структурированные блоки идут первыми в секции, текст — под ними «подробностями»
        rich = ""
        if name == "demand":
            rich = gaps_block(demand) + demand_block(demand, embed=True)
        elif name == "competitors":
            rich = competitors_block(competitors)
        elif name == "personas":
            rich = personas_block(personas)
        elif name == "channels":
            rich = channels_block(channels)
        elif name == "budget":
            rich = budget_block(budget)
        wrapped = (f'<details class="prose"><summary>Подробности текстом</summary>{body}</details>'
                   if rich else f'<div class="prose">{body}</div>')
        blocks.append(f'<section id="{name}"><h2><span class="num">##</span>'
                      f'{E(TITLES.get(name, name))}</h2>{rich}{wrapped}</section>')
        if name == "personas" and usp:
            blocks.append(usp_block(usp))

    numbered, k = [], 0
    for b in blocks:
        while '<span class="num">##</span>' in b:
            k += 1
            b = b.replace('<span class="num">##</span>',
                          f'<span class="num">{k:02d}</span>', 1)
        numbered.append(b)

    toc = "".join(f'<a href="#{n}">{E(TITLES[n])}</a>' for n in ORDER
                  if os.path.exists(os.path.join(sdir, n + ".md")))
    title = args.title or state.get("product_name") or os.path.basename(args.project)
    site = state.get("site_url", "")
    blocked = state.get("blocked_on") or []
    waiting = ("".join(f"<li>{E(x)}</li>" for x in blocked))
    tail = (f'<section id="waiting"><h2><span class="num">{k + 1:02d}</span>Чего ждём</h2>'
            f'<p class="lede">Без этих данных цифры в стратегии остаются формулами.</p>'
            f'<ul>{waiting}</ul></section>' if blocked else "")

    doc = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Стратегия — {E(title)}</title><style>{CSS}</style></head><body><div class="wrap">
<header class="top"><div><h1>Стратегия — {E(title)}</h1>
<div class="sub">{E(site)} · обновлено {E(state.get("updated", date.today().isoformat()))}</div></div>
<div class="sub">шаг {E(str(state.get("step", "—")))} из 9</div></header>
<nav class="toc">{toc}</nav>{"".join(numbered)}{tail}
<footer>Собрано скиллом marketing-strategy. Спрос проверен через API Яндекс Директа,
отраслевые бенчмарки не используются.</footer></div></body></html>"""
    open(out, "w", encoding="utf-8").write(doc)
    print(f"разделов: {k}", file=sys.stderr)
    print(out)


if __name__ == "__main__":
    main()
