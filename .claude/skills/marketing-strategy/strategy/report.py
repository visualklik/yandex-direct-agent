#!/usr/bin/env python3
"""Стратегия в один HTML-файл: markdown-артефакты + графика по данным.

    python3 report.py --project projects/domsegodnya --out projects/domsegodnya/strategy/strategy.html

Читает `strategy/*.md`, `usp.json`, `_state.json` и `data/demand.json`. Markdown рендерится
своим минимальным конвертером — внешних зависимостей нет, файл самодостаточный: ни шрифтов,
ни скриптов снаружи. Оформление то же, что у дашборда аудита (audit/dashboard.md).
"""
import argparse, html, json, os, re, sys
from datetime import date

E = html.escape
ORDER = ["strategy", "brief", "demand", "personas", "channels", "budget", "kpi", "handoff"]
TITLES = {
    "strategy": "Сводка", "brief": "Бриф", "demand": "Спрос", "personas": "Персоны",
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

def demand_block(data):
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
    return (f'<section id="demand-data"><h2><span class="num">##</span>Проверка спроса</h2>'
            f'<p class="lede">Каждая тема — набор формулировок, проверенных через API Директа '
            f'на наличие показов в регионе. Полоса — доля фраз со спросом.</p>'
            f'<div class="kpis"><div class="kpi"><div class="l">Тем проверено</div>'
            f'<div class="v">{len(themes)}</div></div>'
            f'<div class="kpi"><div class="l">Фраз</div><div class="v">{total}</div></div>'
            f'<div class="kpi"><div class="l">Со спросом</div><div class="v">{live}</div>'
            f'<div class="m">{live / total * 100:.0f}% от проверенных</div></div>'
            f'<div class="kpi"><div class="l">Регионы</div>'
            f'<div class="v">{", ".join(str(x) for x in data.get("geo", []))}</div></div></div>'
            f'<div class="bars">{rows}</div></section>')


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
    demand = load(os.path.join(args.project, "data", "demand.json"))

    blocks = []
    for name in ORDER:
        path = os.path.join(sdir, name + ".md")
        if not os.path.exists(path):
            continue
        body = md(open(path, encoding="utf-8").read())
        body = re.sub(r"^<h2>.*?</h2>", "", body, count=1)      # заголовок даёт секция
        blocks.append(f'<section id="{name}"><h2><span class="num">##</span>'
                      f'{E(TITLES.get(name, name))}</h2>{body}</section>')
        if name == "demand" and demand:
            blocks.append(demand_block(demand))
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
<div class="sub">шаг {E(str(state.get("step", "—")))} из 8</div></header>
<nav class="toc">{toc}</nav>{"".join(numbered)}{tail}
<footer>Собрано скиллом marketing-strategy. Спрос проверен через API Яндекс Директа,
отраслевые бенчмарки не используются.</footer></div></body></html>"""
    open(out, "w", encoding="utf-8").write(doc)
    print(f"разделов: {k}", file=sys.stderr)
    print(out)


if __name__ == "__main__":
    main()
