#!/usr/bin/env python3
"""Проверка спроса по темам через API Директа.

    set -a && . ./.env && set +a
    python3 demand_probe.py --themes themes.txt --geo 213 --out demand.json

Файл тем: одна тема в строке, варианты фраз внутри темы через «|».
Скрипт спрашивает у keywordsresearch.hasSearchVolume, есть ли показы по каждой фразе
в регионе, и считает долю живых фраз по теме.

Ответ API — «есть спрос / нет», без частотности: в v5 частот Wordstat нет. Этого хватает,
чтобы отличить живую тему от выдуманной, но не хватает, чтобы обещать объём заявок.
"""
import argparse, json, os, sys, urllib.request

URL = "https://api.direct.yandex.com/json/v5/keywordsresearch"
CHUNK = 100


def ask(keywords, geo):
    token, login = os.environ.get("DIRECT_TOKEN"), os.environ.get("DIRECT_LOGIN")
    if not token or not login:
        sys.exit("нет DIRECT_TOKEN или DIRECT_LOGIN в окружении")
    body = json.dumps({"method": "hasSearchVolume", "params": {
        "SelectionCriteria": {"Keywords": keywords, "RegionIds": geo},
        "FieldNames": ["Keyword", "AllDevices"]}}, ensure_ascii=False).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": f"Bearer {token}", "Client-Login": login, "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    if "error" in data:
        sys.exit(data["error"].get("error_detail") or str(data["error"]))
    return {x["Keyword"]: x.get("AllDevices") == "YES"
            for x in data["result"]["HasSearchVolumeResults"]}


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--themes", required=True)
    a.add_argument("--geo", required=True, help="коды регионов через запятую")
    a.add_argument("--out", default="demand.json")
    args = a.parse_args()

    geo = [int(x) for x in args.geo.split(",")]
    themes = []
    for line in open(args.themes, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            themes.append([p.strip() for p in line.split("|") if p.strip()])

    flat = list(dict.fromkeys(p for t in themes for p in t))
    print(f"тем: {len(themes)}, фраз: {len(flat)}", file=sys.stderr)
    verdict = {}
    for i in range(0, len(flat), CHUNK):
        verdict.update(ask(flat[i:i + CHUNK], geo))

    out = []
    for t in themes:
        live = [p for p in t if verdict.get(p)]
        out.append(dict(theme=t[0], phrases=t, live=live, dead=[p for p in t if p not in live],
                        share=round(len(live) / len(t) * 100)))

    out.sort(key=lambda x: -x["share"])
    json.dump(dict(geo=geo, themes=out,
                   live_phrases=[p for x in out for p in x["live"]]),
              open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\n{'тема':45} живых")
    for x in out:
        print(f"{x['theme'][:44]:45} {len(x['live'])}/{len(x['phrases'])} ({x['share']}%)")
    dead_themes = [x["theme"] for x in out if not x["live"]]
    if dead_themes:
        print(f"\nтемы без спроса целиком: {', '.join(dead_themes[:8])}", file=sys.stderr)
    print(args.out)


if __name__ == "__main__":
    main()
