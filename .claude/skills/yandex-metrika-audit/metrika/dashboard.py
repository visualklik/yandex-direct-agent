#!/usr/bin/env python3
"""Визуальный отчёт аудита Метрики: один самодостаточный HTML.

    python3 dashboard.py --snapshot snapshot.json --reports data --out audit.html

Оформление и правила те же, что у дашборда аудита Директа
(../../yandex-direct-audit/audit/dashboard.md): вердикт и план правок вверху, данные ниже,
сырые таблицы под спойлером. Ни шрифтов, ни скриптов снаружи.
"""
import argparse, html, importlib.util, json, os, sys
from collections import Counter
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("mchecks", os.path.join(HERE, "checks.py"))
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)

E = html.escape
P0, P1, P2 = "P0", "P1", "P2"
LEVEL_TO_P = {checks.CRIT: P0, checks.WARN: P1, checks.INFO: P2}


def n(v, d=0):
    return f"{v:,.{d}f}".replace(",", " ")


def pct(v, d=1):
    return f"{v:.{d}f}%"


# ─────────────────────────── графика ───────────────────────────

def score_ring(score, grade, size=120):
    r = size / 2 - 6
    circ = 2 * 3.14159265 * r
    cls = "arc" + (" crit" if score < 55 else " warn" if score < 80 else "")
    return (f'<div class="score"><svg viewBox="0 0 {size} {size}" aria-hidden="true">'
            f'<circle class="track" cx="{size/2}" cy="{size/2}" r="{r:.1f}"/>'
            f'<circle class="{cls}" cx="{size/2}" cy="{size/2}" r="{r:.1f}" '
            f'stroke-dasharray="{circ*score/100:.1f} {circ:.1f}"/></svg>'
            f'<div class="score-txt"><b>{score}</b><small>грейд {E(grade)}</small></div></div>')


def bars(rows, label_key, value_key, note_key=None, fmt=n):
    if not rows:
        return ""
    top = max(r[value_key] for r in rows) or 1
    out = ['<div class="bars">']
    for r in rows:
        share = r[value_key] / top * 100
        cls = r.get("cls", "")
        # разделитель нужен и глазам, и при копировании строки в текст
        note = f'<span class="bar-sec">· {E(str(r[note_key]))}</span>' if note_key else ""
        out.append(f'<div class="bar-row"><div class="bar-label" title="{E(str(r[label_key]))}">'
                   f'{E(str(r[label_key]))}</div>'
                   f'<div class="bar-track"><div class="bar-fill {cls}" '
                   f'style="width:{share:.1f}%"></div></div>'
                   f'<div class="bar-val">{fmt(r[value_key])}{note}</div></div>')
    out.append("</div>")
    return "".join(out)


# ─────────────────────────── разбор отчётов ───────────────────────────

def report_rows(rep, limit=None):
    """Строки отчёта Метрики в плоский вид: имя измерения + метрики."""
    if not rep or not rep.get("data"):
        return []
    out = []
    for row in rep["data"]:
        name = " / ".join((d.get("name") or "—") for d in row["dimensions"])
        out.append({"name": name, "m": row["metrics"]})
    return out[:limit] if limit else out


def section_goals(snap, reports):
    stats = (reports.get("goals") or {}).get("goals", {})
    if not stats:
        return ""
    visits = (reports.get("days") or {}).get("totals", [0])[0]
    rows = []
    for gid, v in stats.items():
        reaches = v.get("reaches", 0)
        junk = checks.JUNK_GOAL.search(v.get("name", "")) and visits and reaches > visits * 0.3
        state = ("мёртвая" if reaches == 0 else "заглушка" if junk else "работает")
        rows.append(dict(id=gid, name=v.get("name", ""), type=v.get("type", ""),
                         reaches=reaches, cr=v.get("conversion_rate", 0), state=state,
                         cls="bad" if reaches == 0 else ("warn" if junk else "")))
    rows.sort(key=lambda r: -r["reaches"])
    dead = [r for r in rows if r["state"] == "мёртвая"]
    junk = [r for r in rows if r["state"] == "заглушка"]
    live = [r for r in rows if r["state"] == "работает"]

    tiles = [("Целей всего", str(len(rows)), ""),
             ("Работают", str(len(live)), "срабатывали за период"),
             ("Молчат", str(len(dead)), "ни одного достижения"),
             ("Заглушки", str(len(junk)), "срабатывают почти на каждом визите")]
    kh = "".join(f'<div class="kpi"><div class="l">{E(l)}</div><div class="v">{E(v)}</div>'
                 f'<div class="m">{E(m)}</div></div>' for l, v, m in tiles)

    note = ""
    if dead:
        note = (f'<p class="note warn"><b>Молчащие цели: {len(dead)}.</b> '
                f'{E(", ".join(r["name"] for r in dead[:6]))}. Прежде чем чинить — проверить '
                f'период и сезонность; цель на звонок в этом списке почти всегда означает '
                f'неработающий коллтрекинг.</p>')
    bar_rows = [dict(name=f'{r["name"]}', reaches=r["reaches"],
                     cls=r["cls"], note=f'{pct(r["cr"], 2)}') for r in rows[:12]]
    body = "".join(
        f'<tr><td>{E(r["name"])}</td><td class="mono">{E(r["type"])}</td>'
        f'<td class="r">{n(r["reaches"])}</td><td class="r">{pct(r["cr"], 2)}</td>'
        f'<td><span class="tag {"p0" if r["state"] == "мёртвая" else "p1" if r["state"] == "заглушка" else "ok"}">'
        f'{E(r["state"])}</span></td><td class="mono">{E(str(r["id"]))}</td></tr>' for r in rows)
    return (f'<section id="goals"><h2><span class="num">##</span>Цели</h2>'
            f'<p class="lede">Достижения за период по каждой цели. «Заглушка» — цель, '
            f'которая срабатывает почти на каждом визите: оптимизировать по ней значит '
            f'учить стратегию на всём трафике подряд.</p>'
            f'<div class="kpis">{kh}</div>{note}'
            + bars(bar_rows, "name", "reaches", "note")
            + f'<details><summary>Все цели ({len(rows)})</summary><div class="tbl"><table>'
              f'<thead><tr><th>Цель</th><th>Тип</th><th class="r">Достижения</th>'
              f'<th class="r">Конверсия</th><th>Статус</th><th>id</th></tr></thead>'
              f'<tbody>{body}</tbody></table></div></details></section>')


def section_traffic(reports):
    src = report_rows(reports.get("sources"), 10)
    dev = report_rows(reports.get("devices"), 6)
    geo = report_rows(reports.get("geo"), 8)
    if not src:
        return ""
    total = sum(r["m"][0] for r in src) or 1
    bar_rows = [dict(name=r["name"], visits=r["m"][0],
                     note=f'отказы {pct(r["m"][2])}') for r in src]

    def mini(rows, title):
        if not rows:
            return ""
        body = "".join(f'<tr><td>{E(r["name"])}</td><td class="r">{n(r["m"][0])}</td>'
                       f'<td class="r">{pct(r["m"][2])}</td></tr>' for r in rows)
        return (f'<div class="seg"><h4>{E(title)}</h4><div class="tbl"><table>'
                f'<thead><tr><th>Срез</th><th class="r">Визиты</th><th class="r">Отказы</th>'
                f'</tr></thead><tbody>{body}</tbody></table></div></div>')

    return (f'<section id="traffic"><h2><span class="num">##</span>Трафик</h2>'
            f'<p class="lede">Источники за период: объём и качество. Отказы сильно выше '
            f'по одному каналу — повод смотреть посадочные и релевантность именно там.</p>'
            + bars(bar_rows, "name", "visits", "note")
            + f'<div class="segs">{mini(dev, "Устройства")}{mini(geo, "Города")}</div>'
              f'</section>')


def section_direct(reports):
    rows = report_rows(reports.get("direct"))
    if not rows:
        return ('<section id="direct"><h2><span class="num">##</span>Кампании Директа</h2>'
                '<p class="note crit">Визитов из Директа в отчёте нет. Либо связка счётчика '
                'с рекламным аккаунтом не настроена, либо отключена разметка ссылок — '
                'в обоих случаях кампании не видны в Метрике.</p></section>')
    body = "".join(
        f'<tr><td>{E(r["name"])}</td><td class="r">{n(r["m"][0])}</td>'
        f'<td class="r">{n(r["m"][1])}</td><td class="r">{pct(r["m"][2])}</td>'
        f'<td class="r">{r["m"][3]/60:.1f} мин</td></tr>' for r in rows)
    return (f'<section id="direct"><h2><span class="num">##</span>Кампании Директа</h2>'
            f'<p class="lede">Так кампании видит Метрика. Эти цифры сравниваются с отчётом '
            f'Директа: клик не равен визиту, расхождение 5–15% — норма, больше — искать '
            f'причину (разметка, редиректы, часовой пояс).</p>'
            f'<div class="tbl"><table><thead><tr><th>Кампания</th><th class="r">Визиты</th>'
            f'<th class="r">Пользователи</th><th class="r">Отказы</th><th class="r">Время</th>'
            f'</tr></thead><tbody>{body}</tbody></table></div></section>')


def section_landing(reports):
    rows = report_rows(reports.get("landing"), 15)
    if not rows:
        return ""
    body = "".join(
        f'<tr><td class="mono">{E(r["name"][:70])}</td><td class="r">{n(r["m"][0])}</td>'
        f'<td class="r">{pct(r["m"][2])}</td><td class="r">{r["m"][4]:.1f}</td></tr>'
        for r in rows)
    return (f'<section id="landing"><h2><span class="num">##</span>Посадочные</h2>'
            f'<p class="lede">Страницы входа по объёму. Высокие отказы при заметном трафике — '
            f'первый кандидат на разбор в вебвизоре.</p>'
            f'<div class="tbl"><table><thead><tr><th>Страница входа</th>'
            f'<th class="r">Визиты</th><th class="r">Отказы</th><th class="r">Глубина</th>'
            f'</tr></thead><tbody>{body}</tbody></table></div></section>')


def section_settings(snap):
    c = snap.get("counter", {})
    wv = c.get("webvisor") or {}
    co = c.get("code_options") or {}
    rows = [
        ("Сайт", c.get("site", "—")),
        ("Статус счётчика", c.get("status", "—")),
        ("Проверка кода", c.get("code_status", "—")),
        ("Фильтрация роботов", str(c.get("filter_robots", "—"))),
        ("Таймаут визита", f'{c.get("visit_threshold", "—")} сек'),
        ("Часовой пояс", c.get("time_zone_name", "—")),
        ("Валюта", c.get("currency_code", "—")),
        ("Вебвизор", "включён" if wv.get("arch_enabled") else "выключен"),
        ("Запись форм", "да" if wv.get("wv_forms") else "нет"),
        ("Карта кликов", "да" if co.get("clickmap") else "нет"),
        ("Электронная коммерция", "включена" if co.get("ecommerce") else "выключена"),
        ("Автоцели", "включены" if c.get("autogoals_enabled") else "выключены"),
        ("Целей заведено", f'{len(snap.get("goals", []))} из {c.get("max_goals", "—")}'),
        ("Фильтров", f'{len(snap.get("filters", []))} из {c.get("max_filters", "—")}'),
        ("Сегментов", str(len(snap.get("segments", [])))),
        ("Доступов выдано", str(len(snap.get("grants", [])))),
    ]
    body = "".join(f'<tr><td>{E(k)}</td><td>{E(str(v))}</td></tr>' for k, v in rows)
    return (f'<section id="settings"><h2><span class="num">##</span>Настройки счётчика</h2>'
            f'<p class="lede">Слепок значений, а не пересказ. Спорные места разобраны '
            f'в находках выше.</p>'
            f'<div class="tbl"><table><tbody>{body}</tbody></table></div></section>')


CSS = """
:root{--bg:#f6f7f5;--surface:#fff;--surface-2:#fafbfa;--ink:#16211f;--muted:#66757a;
 --line:#e2e8e5;--accent:#0f766e;--accent-soft:#e2f4f1;--p0:#b42318;--p0-bg:#fdeceb;
 --p1:#a35a09;--p1-bg:#fdf3e5;--p2:#2f5eb0;--p2-bg:#eaf0fc;--ok:#0f766e;--ok-bg:#e2f4f1;
 --radius:14px;--shadow:0 1px 2px rgba(16,32,28,.05),0 8px 24px rgba(16,32,28,.06)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#0f1513;--surface:#161d1b;--surface-2:#1a2220;--ink:#e8efec;--muted:#95a5a3;
 --line:#28322f;--accent:#4fd1c5;--accent-soft:#12302d;--p0:#ff8a80;--p0-bg:#2a1614;
 --p1:#f0b45e;--p1-bg:#2a2113;--p2:#8ab4f8;--p2-bg:#151f2e;--ok:#4fd1c5;--ok-bg:#12302d;
 --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3)}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.5;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Arial,sans-serif;
 font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.wrap{width:min(1080px,94vw);margin:0 auto;padding:28px 0 64px}
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
h2{margin:0 0 6px;font-size:18px;letter-spacing:-.01em}
h2 .num{color:var(--muted);font-weight:400;margin-right:8px}
h4{font-size:12px;margin:0 0 6px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.lede{color:var(--muted);font-size:13px;margin:0 0 14px;max-width:74ch}
.verdict{display:grid;grid-template-columns:auto 1fr;gap:22px;align-items:center}
.score{position:relative;width:120px;height:120px;flex:0 0 auto}
.score svg{width:100%;height:100%;transform:rotate(-90deg)}
.score .track{fill:none;stroke:var(--line);stroke-width:9}
.score .arc{fill:none;stroke:var(--accent);stroke-width:9;stroke-linecap:round}
.score .arc.warn{stroke:var(--p1)}.score .arc.crit{stroke:var(--p0)}
.score-txt{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
 justify-content:center;gap:1px;line-height:1}
.score-txt b{font-size:34px;letter-spacing:-.03em}
.score-txt small{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.verdict h3{margin:0 0 6px;font-size:19px;letter-spacing:-.015em}
.verdict ul{margin:8px 0 0;padding-left:18px;font-size:14px;display:grid;gap:5px}
.cover{color:var(--muted);font-size:12px;margin:10px 0 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;
 background:var(--line);border:1px solid var(--line);border-radius:var(--radius);
 overflow:hidden;margin:14px 0}
.kpi{background:var(--surface);padding:13px 15px}
.kpi .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.kpi .v{font-size:23px;font-weight:650;letter-spacing:-.02em;margin-top:3px}
.kpi .m{font-size:12px;color:var(--muted)}
.qw{border:1px solid var(--ok);background:var(--ok-bg);border-radius:10px;padding:12px 14px;
 margin:0 0 12px;font-size:13px}
.qw ul{margin:6px 0 0;padding-left:20px;display:grid;gap:3px}
.actions{display:grid;gap:10px}
.act{display:grid;grid-template-columns:auto 1fr;gap:14px;align-items:start;
 border:1px solid var(--line);border-left-width:3px;border-radius:10px;padding:12px 14px;
 background:var(--surface-2)}
.act.p0{border-left-color:var(--p0)}.act.p1{border-left-color:var(--p1)}
.act.p2{border-left-color:var(--p2)}
.act .what{font-weight:600;font-size:14px}
.act .why{color:var(--muted);font-size:13px;margin-top:3px}
.tag{font-size:11px;font-weight:700;padding:3px 8px;border-radius:6px;white-space:nowrap;
 display:inline-block}
.tag.p0{background:var(--p0-bg);color:var(--p0)}.tag.p1{background:var(--p1-bg);color:var(--p1)}
.tag.p2{background:var(--p2-bg);color:var(--p2)}.tag.ok{background:var(--ok-bg);color:var(--ok)}
.bars{display:grid;gap:7px;margin:12px 0}
.bar-row{display:grid;grid-template-columns:minmax(140px,1.3fr) 2.2fr auto;gap:12px;
 align-items:center;font-size:13px}
.bar-label{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-track{height:9px;border-radius:5px;background:var(--line);overflow:hidden}
.bar-fill{height:100%;border-radius:5px;background:var(--accent)}
.bar-fill.warn{background:var(--p1)}.bar-fill.bad{background:var(--p0)}
.bar-val{font-size:12px;white-space:nowrap}
.bar-sec{color:var(--muted);margin-left:8px}
.segs{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-top:14px}
.tbl{overflow-x:auto;margin-top:10px;border:1px solid var(--line);border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:var(--surface-2);text-align:left;font-weight:600;font-size:11px;color:var(--muted);
 text-transform:uppercase;letter-spacing:.05em;padding:9px 12px;border-bottom:1px solid var(--line)}
td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
td.r,th.r{text-align:right}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
.note{border-left:3px solid var(--accent);background:var(--accent-soft);padding:11px 14px;
 border-radius:0 8px 8px 0;font-size:13px;margin:14px 0}
.note.warn{border-color:var(--p1);background:var(--p1-bg)}
.note.crit{border-color:var(--p0);background:var(--p0-bg)}
details{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
summary{cursor:pointer;font-size:13px;color:var(--muted);list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸ ";color:var(--accent)}
details[open] summary::before{content:"▾ "}
footer{color:var(--muted);font-size:12px;margin-top:20px;text-align:center}
@media (max-width:720px){.verdict{grid-template-columns:1fr}}
@media print{body{background:#fff}section{break-inside:avoid;box-shadow:none}
 nav.toc{display:none}details{display:block}summary{display:none}}
"""


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--snapshot", required=True)
    a.add_argument("--reports", required=True)
    a.add_argument("--period", default="")
    a.add_argument("--out", default="metrika-audit.html")
    args = a.parse_args()

    snap = json.load(open(args.snapshot, encoding="utf-8"))
    reports = {}
    for f in sorted(os.listdir(args.reports)):
        if f.endswith(".json"):
            reports[f[:-5]] = json.load(open(os.path.join(args.reports, f), encoding="utf-8"))

    audit = checks.run(snap, reports)
    days = reports.get("days") or {}
    totals = days.get("totals") or [0, 0, 0, 0, 0]
    visits, users, bounce, dur = totals[0], totals[1], totals[2], totals[3]
    stats = (reports.get("goals") or {}).get("goals", {})
    dead = sum(1 for v in stats.values() if v.get("reaches", 0) == 0)

    lines = []
    crit = [f for f in audit["findings"] if f["level"] == checks.CRIT]
    if crit:
        plural = "проблема" if len(crit) == 1 else "проблемы"
        lines.append(f"<b>{len(crit)}</b> {plural} уровня «критично»: данные собираются "
                     f"или считаются неверно")
    if dead:
        lines.append(f"Молчащих целей: <b>{dead}</b> из {len(stats)} — часть конверсий "
                     f"не попадает ни в отчёты, ни в автостратегии")
    if reports.get("direct", {}).get("data"):
        lines.append(f"Связка с Директом работает: кампаний в отчёте "
                     f"{len(reports['direct']['data'])}")
    lines.append(f"Проверок пройдено {audit['counts'][checks.PASS]}, "
                 f"с замечанием {audit['counts'][checks.WARNST]}, "
                 f"провалено {audit['counts'][checks.FAIL]}")

    acts, quick = [], []
    for f in audit["findings"]:
        p = LEVEL_TO_P[f["level"]]
        if f["quick"]:
            quick.append(f["what"])
        acts.append(f'<div class="act {p.lower()}"><span class="tag {p.lower()}">{p}</span>'
                    f'<div><div class="what">{"⚡ " if f["quick"] else ""}'
                    f'[{E(f["id"])}] {E(f["what"])}</div>'
                    f'<div class="why">{E(f["detail"])}</div></div></div>')
    qw = ("" if not quick else
          '<div class="qw"><b>⚡ Быстрые победы</b> — чинится за 15 минут:<ul>'
          + "".join(f"<li>{E(x)}</li>" for x in quick) + "</ul></div>")

    kpis = [("Визиты", n(visits), args.period),
            ("Пользователи", n(users), ""),
            ("Отказы", pct(bounce), "по всему трафику"),
            ("Время на сайте", f"{dur/60:.1f} мин", ""),
            ("Целей", f'{len(stats)}', f"молчат {dead}" if dead else "все работают")]
    kh = "".join(f'<div class="kpi"><div class="l">{E(l)}</div><div class="v">{E(v)}</div>'
                 f'<div class="m">{E(m)}</div></div>' for l, v, m in kpis)

    blocks = [
        f'<section><div class="verdict">' + score_ring(audit["score"], audit["grade"])
        + f'<div><h3>Учёт {E(audit["label"])}</h3><ul>'
        + "".join(f"<li>{x}</li>" for x in lines)
        + f'</ul><p class="cover">Балл считается с весами категорий и серьёзности, '
          f'неприменимые проверки исключаются — '
          f'audit/scoring.md.</p></div></div><div class="kpis">{kh}</div></section>',
        f'<section id="plan"><h2><span class="num">##</span>Что делать первым</h2>'
        f'<p class="lede">P0 — цифры врут прямо сейчас, P1 — часть данных теряется, '
        f'P2 — гигиена учёта.</p>{qw}<div class="actions">{"".join(acts)}</div></section>',
        section_goals(snap, reports),
        section_traffic(reports),
        section_direct(reports),
        section_landing(reports),
        section_settings(snap),
    ]
    numbered, k = [], 0
    for b in blocks:
        while '<span class="num">##</span>' in b:
            k += 1
            b = b.replace('<span class="num">##</span>', f'<span class="num">{k:02d}</span>', 1)
        numbered.append(b)

    toc = ('<nav class="toc"><a href="#plan">План правок</a><a href="#goals">Цели</a>'
           '<a href="#traffic">Трафик</a><a href="#direct">Директ</a>'
           '<a href="#landing">Посадочные</a><a href="#settings">Настройки</a></nav>')
    site = snap.get("counter", {}).get("site", "")
    doc = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Аудит Метрики — {E(site)}</title><style>{CSS}</style></head><body><div class="wrap">
<header class="top"><div><h1>Аудит Метрики — {E(site)}</h1>
<div class="sub">счётчик {E(str(snap.get("counter_id", "")))} · {E(args.period)} ·
сформировано {date.today().isoformat()}</div></div>
<div class="sub">только чтение</div></header>
{toc}{"".join(numbered)}
<footer>Собрано скиллом yandex-metrika-audit. Настройки счётчика не изменялись.</footer>
</div></body></html>"""
    open(args.out, "w", encoding="utf-8").write(doc)
    print(f"разделов: {k}", file=sys.stderr)
    print(args.out)


if __name__ == "__main__":
    main()
