#!/usr/bin/env python3
"""Слепок счётчика Яндекс Метрики: настройки, цели, фильтры, сегменты, доступы.

    set -a && . ./.env && set +a
    python3 collect.py --out snapshot.json [--counter 12345678]

Только чтение. Дальше аудит идёт по файлу, а не по API: воспроизводимо, дёшево
и не упирается в квоты. Токен берётся из METRIKA_TOKEN, счётчик — из METRIKA_COUNTER.
"""
import argparse, json, os, sys, urllib.error, urllib.parse, urllib.request

BASE = "https://api-metrika.yandex.net"
# management-разделы счётчика: имя раздела → ключ в ответе
SECTIONS = {"goals": "goals", "filters": "filters", "segments": "segments",
            "operations": "operations", "grants": "grants"}


def api(path, token, **params):
    url = f"{BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {token}",
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"{path}: HTTP {e.code} — {body}")


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--out", default="snapshot.json")
    a.add_argument("--counter", help="по умолчанию METRIKA_COUNTER")
    a.add_argument("--all-counters", action="store_true",
                   help="добавить список всех счётчиков, доступных токену")
    args = a.parse_args()

    token = os.environ.get("METRIKA_TOKEN")
    counter = args.counter or os.environ.get("METRIKA_COUNTER")
    if not token or not counter:
        sys.exit("нет METRIKA_TOKEN или METRIKA_COUNTER в окружении")

    print("настройки счётчика…", file=sys.stderr)
    snap = {"counter_id": int(counter), "counter": api(
        f"management/v1/counter/{counter}", token).get("counter", {})}

    for name, key in SECTIONS.items():
        print(f"{name}…", file=sys.stderr)
        snap[name] = api(f"management/v1/counter/{counter}/{name}", token).get(key, [])

    if args.all_counters:
        print("список счётчиков…", file=sys.stderr)
        snap["counters"] = api("management/v1/counters", token, per_page=200).get("counters", [])

    json.dump(snap, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    c = snap["counter"]
    print(f"\n{c.get('name')} · {c.get('site')} · счётчик {counter}", file=sys.stderr)
    print({k: len(v) for k, v in snap.items() if isinstance(v, list)}, file=sys.stderr)
    print(args.out)


if __name__ == "__main__":
    main()
