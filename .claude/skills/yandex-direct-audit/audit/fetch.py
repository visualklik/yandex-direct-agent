#!/usr/bin/env python3
"""Скачать все отчёты, нужные для аудита, одной командой.

    set -a && . ./.env && set +a
    python3 fetch.py --days 30 --out-dir data

Кладёт TSV с фиксированными именами: campaigns, days, placements, device, gender,
age, geo, queries. Их же ждёт dashboard.py --reports data.

Отчёты асинхронные: HTTP 201 — в очереди, повторяем до 200. Заголовок
returnMoneyInMicros: false в reports работает (в campaigns.get — нет, см. api-collect.md).
"""
import argparse, json, os, sys, time, urllib.request, urllib.error
from datetime import date, timedelta

URL = "https://api.direct.yandex.com/json/v5/reports"

SPECS = {
    "campaigns": dict(type="CAMPAIGN_PERFORMANCE_REPORT",
                      fields=["CampaignId", "CampaignName", "AdNetworkType", "Impressions",
                              "Clicks", "Cost", "Conversions", "BounceRate"]),
    "days": dict(type="CUSTOM_REPORT", fields=["Date", "Cost", "Clicks", "Conversions"]),
    "placements": dict(type="CUSTOM_REPORT",
                       fields=["Placement", "AdNetworkType", "Impressions", "Clicks", "Cost",
                               "Conversions", "BounceRate", "AvgPageviews"],
                       filter=[{"Field": "AdNetworkType", "Operator": "EQUALS",
                                "Values": ["AD_NETWORK"]}]),
    "segment": dict(type="CUSTOM_REPORT",
                    fields=["AdNetworkType", "Impressions", "Clicks", "Cost", "Conversions"]),
    "device": dict(type="CUSTOM_REPORT",
                   fields=["Device", "Impressions", "Clicks", "Cost", "Conversions"]),
    "gender": dict(type="CUSTOM_REPORT",
                   fields=["Gender", "Impressions", "Clicks", "Cost", "Conversions"]),
    "age": dict(type="CUSTOM_REPORT",
                fields=["Age", "Impressions", "Clicks", "Cost", "Conversions"]),
    "geo": dict(type="CUSTOM_REPORT",
                fields=["LocationOfPresenceName", "Impressions", "Clicks", "Cost", "Conversions"]),
    "queries": dict(type="SEARCH_QUERY_PERFORMANCE_REPORT",
                    fields=["Query", "Impressions", "Clicks", "Cost", "Conversions",
                            "CampaignName"]),
}


def run(name, spec, d_from, d_to, out_dir, tag, tries=12):
    token, login = os.environ.get("DIRECT_TOKEN"), os.environ.get("DIRECT_LOGIN")
    if not token or not login:
        sys.exit("нет DIRECT_TOKEN или DIRECT_LOGIN в окружении")
    sel = {"DateFrom": d_from, "DateTo": d_to}
    if spec.get("filter"):
        sel["Filter"] = spec["filter"]
    body = json.dumps({"params": {
        "SelectionCriteria": sel, "FieldNames": spec["fields"],
        "OrderBy": [{"Field": "Cost", "SortOrder": "DESCENDING"}] if "Cost" in spec["fields"] else [],
        "ReportName": f"audit_{name}_{tag}", "ReportType": spec["type"],
        "DateRangeType": "CUSTOM_DATE", "Format": "TSV", "IncludeVAT": "YES"}},
        ensure_ascii=False).encode()
    req = lambda: urllib.request.Request(URL, data=body, headers={
        "Authorization": f"Bearer {token}", "Client-Login": login, "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8", "processingMode": "auto",
        "returnMoneyInMicros": "false", "skipReportHeader": "true", "skipReportSummary": "true"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req(), timeout=120) as r:
                if r.status == 200:
                    data = r.read().decode("utf-8")
                    path = os.path.join(out_dir, f"{name}.tsv")
                    open(path, "w", encoding="utf-8").write(data)
                    print(f"{name:11} {len(data.splitlines()) - 1:>7} строк", file=sys.stderr)
                    return path
        except urllib.error.HTTPError as e:
            if e.code not in (201, 202):
                sys.exit(f"{name}: {e.read().decode('utf-8')[:300]}")
        time.sleep(3 + attempt)
    print(f"{name}: не дождались отчёта", file=sys.stderr)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--days", type=int, default=30)
    a.add_argument("--date-from")
    a.add_argument("--date-to")
    a.add_argument("--out-dir", default="data")
    a.add_argument("--tag", default="1", help="суффикс имени отчёта: оно уникально в аккаунте")
    a.add_argument("--only", nargs="*", help="скачать только указанные срезы")
    args = a.parse_args()

    d_to = args.date_to or (date.today() - timedelta(days=1)).isoformat()
    d_from = args.date_from or (date.fromisoformat(d_to) - timedelta(days=args.days - 1)).isoformat()
    os.makedirs(args.out_dir, exist_ok=True)
    print(f"период {d_from} — {d_to}", file=sys.stderr)
    for name, spec in SPECS.items():
        if args.only and name not in args.only:
            continue
        run(name, spec, d_from, d_to, args.out_dir, args.tag)
    print(args.out_dir)


if __name__ == "__main__":
    main()
