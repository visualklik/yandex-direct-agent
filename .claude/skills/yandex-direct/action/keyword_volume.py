#!/usr/bin/env python3
"""Отсев фраз без спроса через API Директа (keywordsresearch.hasSearchVolume).

    set -a && . ./.env && set +a
    python3 keyword_volume.py --file keywords.txt --geo 213 --out keywords.json

API отвечает только «есть спрос / нет» для региона — частотности Wordstat в v5 нет.
Этого хватает, чтобы выбросить придуманные фразы до загрузки кампании: пустышки
не дадут показов, но раздуют структуру и испортят статистику групп.
"""
import argparse, json, os, sys, urllib.request

URL = "https://api.direct.yandex.com/json/v5/keywordsresearch"
CHUNK = 100          # практический размер пачки; лимит API выше, но так виден прогресс


def call(keywords, geo, devices):
    token, login = os.environ.get("DIRECT_TOKEN"), os.environ.get("DIRECT_LOGIN")
    if not token or not login:
        sys.exit("нет DIRECT_TOKEN или DIRECT_LOGIN в окружении")
    body = json.dumps({"method": "hasSearchVolume", "params": {
        "SelectionCriteria": {"Keywords": keywords, "RegionIds": geo},
        "FieldNames": ["Keyword"] + devices}}, ensure_ascii=False).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": f"Bearer {token}", "Client-Login": login, "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    if "error" in data:
        sys.exit(f"{data['error'].get('error_detail') or data['error']}")
    return data["result"]["HasSearchVolumeResults"]


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--file", required=True, help="файл со фразами, по одной в строке")
    a.add_argument("--geo", required=True, help="коды регионов через запятую (213 — Москва)")
    a.add_argument("--out", default="keywords.json")
    a.add_argument("--devices", default="AllDevices",
                   help="AllDevices, MobilePhones, Tablets, DesktopsAndLaptops")
    args = a.parse_args()

    geo = [int(x) for x in args.geo.split(",")]
    devices = [d.strip() for d in args.devices.split(",")]
    words = [w.strip() for w in open(args.file, encoding="utf-8") if w.strip()]
    words = list(dict.fromkeys(words))                 # порядок важен для чтения отчёта
    print(f"фраз на проверку: {len(words)}", file=sys.stderr)

    res = []
    for i in range(0, len(words), CHUNK):
        res += call(words[i:i + CHUNK], geo, devices)
        print(f"  проверено {min(i + CHUNK, len(words))}/{len(words)}", file=sys.stderr)

    live = [r["Keyword"] for r in res if any(r.get(d) == "YES" for d in devices)]
    dead = [r["Keyword"] for r in res if r["Keyword"] not in live]
    json.dump(dict(geo=geo, live=live, dead=dead),
              open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nсо спросом: {len(live)} · без спроса: {len(dead)}", file=sys.stderr)
    if dead:
        print("без спроса: " + ", ".join(dead[:10]) + ("…" if len(dead) > 10 else ""),
              file=sys.stderr)
    print(args.out)


if __name__ == "__main__":
    main()
