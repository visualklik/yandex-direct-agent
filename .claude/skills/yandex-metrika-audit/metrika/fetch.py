#!/usr/bin/env python3
"""Отчёты Метрики для аудита: пресеты срезов + достижения по каждой цели.

    set -a && . ./.env && set +a
    python3 fetch.py --days 30 --out-dir data [--counter 12345678]

Каждый отчёт сохраняется в JSON с сырым ответом API. Признак выборки (`sampled`,
`sample_share`) сохраняется как есть и выводится в консоль: цифра, посчитанная
по 10% выборке, — это оценка, и отчёт обязан об этом говорить.
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

BASE = "https://api-metrika.yandex.net/stat/v1/data"
COMPARE = BASE + "/comparison"
# цели вроде «Посетил сайт» срабатывают почти на каждом визите: главной такую брать нельзя
JUNK_GOAL = re.compile(r"(посетил сайт|просмотр|визит больше|время на сайте|глубина)", re.I)
CORE = "ym:s:visits,ym:s:users,ym:s:bounceRate,ym:s:avgVisitDurationSeconds,ym:s:pageDepth"

# имя → (измерения, метрики). Пресеты закрывают вопросы аудита, а не «всю Метрику».
PRESETS = {
    "sources":    ("ym:s:lastsignTrafficSource", CORE),
    "direct":     ("ym:s:lastDirectClickOrder", CORE),
    "direct_days":("ym:s:date,ym:s:lastsignTrafficSource", CORE),
    "landing":    ("ym:s:startURL", CORE),
    "devices":    ("ym:s:deviceCategory", CORE),
    "geo":        ("ym:s:regionCity", CORE),
    "search":     ("ym:s:searchPhrase", CORE),
    "browsers":   ("ym:s:browser", CORE),
    "days":       ("ym:s:date", CORE),
}


def api(token, base=None, **params):
    url = (base or BASE) + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {token}",
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"errors": True, "message": e.read().decode("utf-8", "replace")[:300]}


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--days", type=int, default=30)
    a.add_argument("--date-from")
    a.add_argument("--date-to")
    a.add_argument("--counter")
    a.add_argument("--out-dir", default="data")
    a.add_argument("--limit", type=int, default=200)
    a.add_argument("--only", nargs="*")
    a.add_argument("--goal", help="идентификатор главной цели; по умолчанию выбирается сама")
    args = a.parse_args()

    token = os.environ.get("METRIKA_TOKEN")
    counter = args.counter or os.environ.get("METRIKA_COUNTER")
    if not token or not counter:
        sys.exit("нет METRIKA_TOKEN или METRIKA_COUNTER в окружении")
    d1 = args.date_from or f"{args.days}daysAgo"
    d2 = args.date_to or "yesterday"
    os.makedirs(args.out_dir, exist_ok=True)
    print(f"счётчик {counter}, период {d1} — {d2}", file=sys.stderr)

    def save(name, data):
        json.dump(data, open(os.path.join(args.out_dir, name + ".json"), "w",
                             encoding="utf-8"), ensure_ascii=False, indent=1)
        rows = len(data.get("data", []))
        mark = "" if not data.get("sampled") else f" · ВЫБОРКА {data.get('sample_share')}"
        print(f"{name:14} строк {rows:>5}{mark}", file=sys.stderr)

    for name, (dims, metrics) in PRESETS.items():
        if args.only and name not in args.only:
            continue
        res = api(token, ids=counter, dimensions=dims, metrics=metrics,
                  date1=d1, date2=d2, limit=args.limit, sort="-ym:s:visits",
                  accuracy="full")
        if res.get("errors"):
            print(f"{name:14} ошибка: {res['message'][:120]}", file=sys.stderr)
            continue
        save(name, res)
        time.sleep(0.2)

    # достижения по каждой цели: за один запрос можно до 20 метрик
    if not args.only or "goals" in args.only:
        goals_url = (f"https://api-metrika.yandex.net/management/v1/counter/{counter}/goals")
        req = urllib.request.Request(goals_url, headers={"Authorization": f"OAuth {token}"})
        goals = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())["goals"]
        # лимит API — 20 метрик на запрос, а на каждую цель их две: достижения и конверсия
        chunks, out = [goals[i:i + 10] for i in range(0, len(goals), 10)], {}
        for ch in chunks:
            metrics = ",".join(f"ym:s:goal{g['id']}reaches" for g in ch)
            rates = ",".join(f"ym:s:goal{g['id']}conversionRate" for g in ch)
            res = api(token, ids=counter, metrics=metrics + "," + rates,
                      date1=d1, date2=d2, accuracy="full")
            if res.get("errors"):
                print("цели: " + res["message"][:120], file=sys.stderr)
                continue
            half = len(ch)
            for i, g in enumerate(ch):
                out[str(g["id"])] = {"name": g.get("name"), "type": g.get("type"),
                                     "reaches": res["totals"][i],
                                     "conversion_rate": res["totals"][half + i]}
        save("goals", {"period": [d1, d2], "goals": out})

    # ── главная цель: самая результативная из неслужебных
    goals_data = None
    path = os.path.join(args.out_dir, "goals.json")
    if os.path.exists(path):
        goals_data = json.load(open(path, encoding="utf-8"))["goals"]
    main_goal = args.goal
    if not main_goal and goals_data:
        real = {k: v for k, v in goals_data.items()
                if not JUNK_GOAL.search(v.get("name", "")) and v.get("reaches", 0) > 0}
        if real:
            main_goal = max(real, key=lambda k: real[k]["reaches"])
    if main_goal and goals_data:
        print(f"главная цель: {main_goal} — {goals_data.get(main_goal, {}).get('name')}",
              file=sys.stderr)

    # ── динамика по дням с достижениями главной цели: ловит обрывы учёта
    if main_goal and (not args.only or "days_goal" in args.only):
        res = api(token, ids=counter, dimensions="ym:s:date",
                  metrics=f"ym:s:visits,ym:s:goal{main_goal}reaches,"
                          f"ym:s:goal{main_goal}conversionRate",
                  date1=d1, date2=d2, sort="ym:s:date", limit=400, accuracy="full")
        if not res.get("errors"):
            res["main_goal"] = main_goal
            res["main_goal_name"] = (goals_data or {}).get(main_goal, {}).get("name")
            save("days_goal", res)

    # ── посадочные с конверсией по главной цели, а не только с отказами
    if main_goal and (not args.only or "landing_goal" in args.only):
        res = api(token, ids=counter, dimensions="ym:s:startURL",
                  metrics=f"ym:s:visits,ym:s:bounceRate,ym:s:goal{main_goal}reaches,"
                          f"ym:s:goal{main_goal}conversionRate",
                  date1=d1, date2=d2, sort="-ym:s:visits", limit=args.limit, accuracy="full")
        if not res.get("errors"):
            res["main_goal"] = main_goal
            res["main_goal_name"] = (goals_data or {}).get(main_goal, {}).get("name")
            save("landing_goal", res)

    # ── здоровье трафика: роботы, новизна аудитории, доля мобильных
    if not args.only or "health" in args.only:
        res = api(token, ids=counter, date1=d1, date2=d2, accuracy="full",
                  metrics="ym:s:visits,ym:s:users,ym:s:robotPercentage,"
                          "ym:s:percentNewVisitors,ym:s:mobilePercentage")
        if not res.get("errors"):
            save("health", res)

    # ── сравнение с предыдущим периодом такой же длины
    if not args.only or "compare" in args.only:
        span = args.days
        res = api(token, base=COMPARE, ids=counter, accuracy="full",
                  metrics="ym:s:visits,ym:s:users,ym:s:bounceRate,"
                          "ym:s:avgVisitDurationSeconds"
                          + (f",ym:s:goal{main_goal}reaches" if main_goal else ""),
                  date1_a=d1, date2_a=d2,
                  date1_b=f"{span * 2}daysAgo", date2_b=f"{span + 1}daysAgo")
        if not res.get("errors"):
            res["main_goal"] = main_goal
            save("compare", res)
        else:
            print("сравнение: " + res["message"][:120], file=sys.stderr)

    print(args.out_dir)


if __name__ == "__main__":
    main()
