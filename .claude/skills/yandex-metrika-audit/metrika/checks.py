#!/usr/bin/env python3
"""Автопроверки счётчика Метрики по слепку и отчётам.

    python3 checks.py snapshot.json --reports data [--json out.json]

Реестр CHECKS: у каждой проверки идентификатор, категория, серьёзность и признак быстрой
починки. Статусы pass / warn / fail / na, балл считается с весами — формула общая с аудитом
Директа (../../yandex-direct-audit/audit/scoring.md).

Проверяется корректность учёта: то, из-за чего цифры врут или автостратегия учится
на пустоте. Качество трафика — работа аналитика, а не этого скрипта.
"""
import argparse, json, os, re, sys
from collections import Counter, defaultdict

CRIT, WARN, INFO = "КРИТИЧНО", "ВАЖНО", "УЛУЧШЕНИЕ"
PASS, WARNST, FAIL, NA = "pass", "warn", "fail", "na"

CATEGORIES = {
    "tracking": ("Сбор данных", 30),
    "goals": ("Цели и конверсии", 30),
    "quality": ("Чистота данных", 20),
    "access": ("Доступы и связки", 20),
}
SEVERITY = {"critical": 5.0, "high": 3.0, "medium": 1.5, "low": 0.5}
SEV_LEVEL = {"critical": CRIT, "high": WARN, "medium": WARN, "low": INFO}
GRADES = [(90, "A", "отличный"), (75, "B", "хороший"), (60, "C", "требует внимания"),
          (40, "D", "плохой"), (0, "F", "критический")]

# цели-«всё подряд»: их достижение почти совпадает с визитом и портит любую оптимизацию
JUNK_GOAL = re.compile(r"(посетил сайт|просмотр|визит больше|время на сайте|глубина)", re.I)
PHONE_GOAL = re.compile(r"(звонок|тел\b|тел\.|call|phone)", re.I)


def names(items, limit=6):
    items = list(items)
    return ", ".join(str(x) for x in items[:limit]) + ("…" if len(items) > limit else "")


def opt(counter, path, default=None):
    cur = counter
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
    return default if cur is None else cur


# ─────────────────────────── проверки ───────────────────────────

def c_counter_alive(ctx):
    """Статус кода и факт поступления данных — разные вещи, и путать их нельзя.

    `code_status` показывает результат проверки кода роботом Метрики. Если сайт закрыт
    от проверки или отвечает нестандартно, статус будет ошибочным, хотя визиты идут.
    Поэтому вердикт выносится с оглядкой на реальные визиты за период.
    """
    c = ctx["counter"]
    st, code = c.get("status"), c.get("code_status")
    visits = ctx["visits"]
    if st != "Active":
        return FAIL, f"счётчик не активен: статус {st}", "данные не собираются"
    if code and code != "CS_OK":
        if visits:
            return WARNST, f"проверка кода не прошла: {code}", \
                f"при этом визиты идут ({visits:.0f} за период) — данные собираются, " \
                f"но робот Метрики код не увидел: проверить установку и доступность сайта"
        return FAIL, f"код счётчика не найден: {code}", "визитов за период нет — данные не собираются"
    return PASS, "счётчик активен, код найден на сайте", ""


def c_robots(ctx):
    v = ctx["counter"].get("filter_robots")
    if str(v) == "2":
        return PASS, "роботы фильтруются по правилам и поведению", ""
    return WARNST, f"фильтрация роботов ослаблена (filter_robots={v})", \
        "часть визитов в отчётах может быть ботами — конверсия занижена"


def c_webvisor(ctx):
    wv = ctx["counter"].get("webvisor") or {}
    if not wv.get("arch_enabled"):
        return WARNST, "вебвизор выключен", "нечем разбирать поведение при просадке конверсии"
    return PASS, "вебвизор включён" + (", формы записываются" if wv.get("wv_forms") else ""), ""


def c_visit_threshold(ctx):
    t = ctx["counter"].get("visit_threshold")
    if t and int(t) != 1800:
        return WARNST, f"нестандартный таймаут визита: {t} сек", \
            "визиты считаются иначе, чем в других счётчиках — сравнения некорректны"
    return PASS, "таймаут визита стандартный, 1800 секунд", ""


def c_timezone(ctx):
    tz = ctx["counter"].get("time_zone_name")
    return PASS, f"часовой пояс счётчика: {tz}", \
        "сверить с часовым поясом кампаний Директа — иначе дневные отчёты разъедутся"


def c_goals_exist(ctx):
    if not ctx["goals"]:
        return FAIL, "целей нет вообще", "без целей нет ни оптимизации, ни оценки"
    return PASS, f"целей заведено: {len(ctx['goals'])}", ""


def c_dead_goals(ctx):
    stats = ctx["goal_stats"]
    if not stats:
        return NA, "статистика по целям не собрана", ""
    dead = [v["name"] for v in stats.values() if v.get("reaches", 0) == 0]
    if not dead:
        return PASS, "все цели срабатывали за период", ""
    lvl = FAIL if len(dead) > len(stats) / 3 else WARNST
    return lvl, f"целей без единого срабатывания: {len(dead)} из {len(stats)}", \
        names(dead) + " — сломаны, не нужны или сезонные"


def c_phone_goals(ctx):
    """Молчащая цель-звонок — типичный симптом мёртвого коллтрекинга."""
    stats = ctx["goal_stats"]
    if not stats:
        return NA, "статистика по целям не собрана", ""
    phone = {k: v for k, v in stats.items() if PHONE_GOAL.search(v.get("name", ""))}
    if not phone:
        return WARNST, "нет ни одной цели на звонок", \
            "если в нише звонят, эти обращения не считаются и не видны автостратегии"
    dead = [v["name"] for v in phone.values() if v.get("reaches", 0) == 0]
    if dead and len(dead) == len(phone):
        return FAIL, f"все цели на звонки молчат: {len(dead)}", \
            names(dead) + " — проверить коллтрекинг"
    if dead:
        return WARNST, f"часть целей на звонки не срабатывает: {len(dead)} из {len(phone)}", \
            names(dead)
    return PASS, f"цели на звонки работают: {len(phone)}", ""


def c_junk_goals(ctx):
    stats, total = ctx["goal_stats"], ctx["visits"]
    if not stats or not total:
        return NA, "нет статистики визитов", ""
    junk = [(v["name"], v["reaches"]) for v in stats.values()
            if JUNK_GOAL.search(v.get("name", "")) and v.get("reaches", 0) > total * 0.3]
    if junk:
        return WARNST, f"цели-«всё подряд»: {len(junk)}", \
            names(f"{n} — {r:.0f} достижений при {total:.0f} визитах" for n, r in junk) + \
            "; на такой цели стратегия учится на всём трафике подряд"
    return PASS, "целей-заглушек не найдено", ""


def c_goal_duplicates(ctx):
    """Два счётчика одного действия задваивают конверсии в отчётах и в стратегии."""
    stats = ctx["goal_stats"]
    if len(stats) < 2:
        return NA, "целей слишком мало", ""
    phone = [v["name"] for v in stats.values() if PHONE_GOAL.search(v.get("name", ""))]
    if len(phone) > 2:
        return WARNST, f"целей на одно действие (звонок): {len(phone)}", \
            names(phone) + " — проверить, не считают ли они одно и то же"
    return PASS, "явных дублей целей не видно", ""


def c_autogoals(ctx):
    if ctx["counter"].get("autogoals_enabled"):
        return PASS, "автоцели включены", "проверить, не дублируют ли они ручные цели"
    return WARNST, "автоцели выключены", "теряется дополнительный источник сигналов"


def c_filters(ctx):
    """Свой офис и разработчики в статистике портят конверсию и поведенческие."""
    if ctx["filters"]:
        return PASS, f"фильтры настроены: {len(ctx['filters'])}", \
            "проверить вручную, не устарел ли список IP"
    return WARNST, "фильтров нет", "внутренний трафик офиса и подрядчиков попадает в отчёты"


def c_ecommerce(ctx):
    """Тип бизнеса скрипт не знает: для магазина это провал, для услуг — норма."""
    if opt(ctx["counter"], "code_options.ecommerce"):
        return PASS, "электронная коммерция включена", ""
    return WARNST, "электронная коммерция выключена", \
        "для интернет-магазина это значит, что доход не передаётся и ДРР считать нечем"


def c_sampling(ctx):
    sampled = [n for n, r in ctx["reports"].items()
               if isinstance(r, dict) and r.get("sampled")]
    if sampled:
        return WARNST, f"отчёты посчитаны по выборке: {len(sampled)}", \
            names(sampled) + " — цифры приблизительные, сузить период или accuracy=full"
    return PASS, "отчёты посчитаны без выборки", ""


def c_direct_link(ctx):
    """Без связки с Директом кампании не видны, а расход не подтягивается."""
    d = ctx["reports"].get("direct")
    if not d:
        return NA, "отчёт по кампаниям Директа не собран", ""
    rows = d.get("data") or []
    if not rows:
        return FAIL, "визитов из Директа в отчёте нет", \
            "не настроена связка счётчика с аккаунтом либо отключена разметка ссылок"
    return PASS, f"связка с Директом работает: кампаний в отчёте {len(rows)}", ""


def c_grants(ctx):
    if not ctx["grants"]:
        return NA, "доступы не отданы API", ""
    logins = [g.get("user_login") for g in ctx["grants"] if g.get("user_login")]
    return PASS, f"доступов выдано: {len(ctx['grants'])}", \
        (names(logins) + " — проверить вручную, нет ли бывших подрядчиков") if logins else ""


CHECKS = [
    ("TRK01", "tracking", "critical", False, "счётчик активен и код найден", c_counter_alive),
    ("TRK02", "tracking", "high", True, "фильтрация роботов", c_robots),
    ("TRK03", "tracking", "medium", True, "вебвизор", c_webvisor),
    ("TRK04", "tracking", "medium", False, "таймаут визита", c_visit_threshold),
    ("TRK05", "tracking", "low", False, "часовой пояс", c_timezone),
    ("GOL01", "goals", "critical", False, "цели заведены", c_goals_exist),
    ("GOL02", "goals", "high", False, "цели срабатывают", c_dead_goals),
    ("GOL03", "goals", "high", False, "цели на звонки", c_phone_goals),
    ("GOL04", "goals", "medium", False, "цели-заглушки", c_junk_goals),
    ("GOL05", "goals", "low", False, "дубли целей", c_goal_duplicates),
    ("GOL06", "goals", "low", True, "автоцели", c_autogoals),
    ("QLT01", "quality", "high", True, "фильтры внутреннего трафика", c_filters),
    ("QLT02", "quality", "medium", False, "электронная коммерция", c_ecommerce),
    ("QLT03", "quality", "medium", False, "выборка в отчётах", c_sampling),
    ("ACC01", "access", "critical", False, "связка с Директом", c_direct_link),
    ("ACC02", "access", "low", False, "список доступов", c_grants),
]


def score(results):
    got = poss = 0.0
    for r in results:
        if r["status"] == NA:
            continue
        w = SEVERITY[r["severity"]] * CATEGORIES[r["category"]][1]
        poss += w
        got += w * {PASS: 1.0, WARNST: 0.5, FAIL: 0.0}[r["status"]]
    pct = round(got / poss * 100) if poss else 0
    grade, label = next((g, l) for th, g, l in GRADES if pct >= th)
    return pct, grade, label


def run(snap, reports):
    goal_stats = (reports.get("goals") or {}).get("goals", {})
    visits = 0
    days = reports.get("days") or {}
    if days.get("totals"):
        visits = days["totals"][0]
    ctx = dict(counter=snap.get("counter", {}), goals=snap.get("goals", []),
               filters=snap.get("filters", []), grants=snap.get("grants", []),
               segments=snap.get("segments", []), reports=reports,
               goal_stats=goal_stats, visits=visits)
    results = []
    for cid, cat, sev, quick, title, fn in CHECKS:
        try:
            status, what, detail = fn(ctx)
        except Exception as e:                       # проверка не должна ронять аудит
            status, what, detail = NA, f"проверка не выполнена: {type(e).__name__}", str(e)[:120]
        results.append(dict(id=cid, category=cat, severity=sev, quick=quick, title=title,
                            status=status, what=what, detail=detail))
    pct, grade, label = score(results)
    findings = [dict(level=SEV_LEVEL[r["severity"]] if r["status"] == FAIL
                     else (WARN if r["severity"] in ("critical", "high") else INFO), **r)
                for r in results if r["status"] in (FAIL, WARNST)]
    order = {CRIT: 0, WARN: 1, INFO: 2}
    findings.sort(key=lambda f: (order[f["level"]], f["id"]))
    return dict(results=results, findings=findings, score=pct, grade=grade, label=label,
                counts=Counter(r["status"] for r in results),
                site=ctx["counter"].get("site"), counter_id=snap.get("counter_id"),
                visits=visits, goals_total=len(ctx["goals"]))


def main():
    a = argparse.ArgumentParser()
    a.add_argument("snapshot")
    a.add_argument("--reports", help="каталог с отчётами от fetch.py")
    a.add_argument("--json")
    args = a.parse_args()

    snap = json.load(open(args.snapshot, encoding="utf-8"))
    reports = {}
    if args.reports:
        for f in sorted(os.listdir(args.reports)):
            if f.endswith(".json"):
                reports[f[:-5]] = json.load(open(os.path.join(args.reports, f),
                                                 encoding="utf-8"))
    res = run(snap, reports)
    c = res["counts"]
    print(f"Счётчик {res['counter_id']} · {res['site']} · целей {res['goals_total']} · "
          f"визитов за период {res['visits']:.0f}")
    print(f"Балл: {res['score']} из 100 · грейд {res['grade']} ({res['label']}) · "
          f"пройдено {c[PASS]}, с замечанием {c[WARNST]}, провалено {c[FAIL]}, "
          f"неприменимо {c[NA]}\n")
    for lvl in (CRIT, WARN, INFO):
        block = [f for f in res["findings"] if f["level"] == lvl]
        if not block:
            continue
        print(f"── {lvl} ({len(block)})")
        for f in block:
            print(f"  • [{f['id']}]{' ⚡' if f['quick'] else ''} {f['what']}")
            if f["detail"]:
                print(f"      {f['detail']}")
        print()
    quick = [f for f in res["findings"] if f["quick"]]
    if quick:
        print(f"Быстрые победы: {', '.join(f['id'] for f in quick)}")
    if args.json:
        json.dump(res, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1,
                  default=lambda o: dict(o) if isinstance(o, Counter) else str(o))
        print(args.json)


if __name__ == "__main__":
    main()
