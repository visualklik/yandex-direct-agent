#!/usr/bin/env python3
"""Слепок настроек аккаунта Яндекс Директа в один JSON.

Запуск:
    set -a && . ./.env && set +a
    python3 collect.py --out snapshot.json [--states ON SUSPENDED]

Читает DIRECT_TOKEN и DIRECT_LOGIN из окружения. Ничего не меняет — только get.
Дальше аудит идёт по файлу, а не по API: воспроизводимо и не жжёт лимиты.
"""
import argparse, json, os, sys, time, urllib.request, urllib.error

API = "https://api.direct.yandex.com/json/{ver}/{svc}"
TOKEN = os.environ.get("DIRECT_TOKEN")
LOGIN = os.environ.get("DIRECT_LOGIN")

CAMPAIGN_FIELDS = ["Id", "Name", "Type", "Status", "State", "StatusPayment", "StartDate", "EndDate",
                   "Currency", "Funds", "DailyBudget", "TimeTargeting", "TimeZone",
                   "NegativeKeywords", "ExcludedSites", "BlockedIps", "Notification", "Statistics"]
TEXT_CAMPAIGN_FIELDS = ["BiddingStrategy", "Settings", "CounterIds", "PriorityGoals",
                        "AttributionModel", "RelevantKeywords", "TrackingParams",
                        "NegativeKeywordSharedSetIds", "WeeklyBudgetRollover"]
ADGROUP_FIELDS = ["Id", "CampaignId", "Name", "Status", "Type", "Subtype", "ServingStatus",
                  "RegionIds", "RestrictedRegionIds", "NegativeKeywords",
                  "NegativeKeywordSharedSetIds", "TrackingParams"]
KEYWORD_FIELDS = ["Id", "Keyword", "State", "Status", "ServingStatus", "AdGroupId", "CampaignId",
                  "Bid", "ContextBid", "StrategyPriority", "Productivity",
                  "AutotargetingCategories"]
AD_FIELDS = ["Id", "CampaignId", "AdGroupId", "Type", "Subtype", "State", "Status",
             "StatusClarification"]
RESPONSIVE_FIELDS = ["Href", "Titles", "Texts", "AdImages", "SitelinkSetId", "AdExtensions",
                     "DisplayUrlPath", "VideoExtensions", "BusinessId",
                     "TrackingPhoneId", "PriceExtension", "ButtonExtension"]
TEXTAD_FIELDS = ["Href", "Title", "Title2", "Text", "SitelinkSetId", "AdExtensions",
                 "DisplayUrlPath", "AdImageHash", "VCardId", "TurboPageId",
                 "VideoExtension", "BusinessId", "TrackingPhoneId", "ButtonExtension"]


def call(svc, params, ver="v5", method="get"):
    """Один вызов API с постраничной догрузкой (Page.Limit / LimitedBy)."""
    if not TOKEN or not LOGIN:
        sys.exit("нет DIRECT_TOKEN или DIRECT_LOGIN в окружении")
    out, offset = [], 0
    key = None
    while True:
        p = json.loads(json.dumps(params))
        p["Page"] = {"Limit": 1000, "Offset": offset}
        body = json.dumps({"method": method, "params": p}, ensure_ascii=False).encode()
        req = urllib.request.Request(API.format(ver=ver, svc=svc), data=body, headers={
            "Authorization": f"Bearer {TOKEN}", "Client-Login": LOGIN,
            "Accept-Language": "ru", "Content-Type": "application/json; charset=utf-8",
            "returnMoneyInMicros": "false"})
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read().decode("utf-8"))
        if "error" in data:
            sys.exit(f"{svc}: {data['error'].get('error_detail') or data['error']}")
        res = data["result"]
        key = key or next(k for k in res if isinstance(res[k], list))
        out += res.get(key, [])
        limited = res.get("LimitedBy")
        if not limited:
            break
        offset = limited
        time.sleep(0.2)
    return out


def by_campaigns(svc, ids, params, ver="v5", chunk=10):
    """CampaignIds ограничен 10 значениями за запрос — режем на пачки."""
    out = []
    for i in range(0, len(ids), chunk):
        p = json.loads(json.dumps(params))
        p["SelectionCriteria"]["CampaignIds"] = ids[i:i + chunk]
        out += call(svc, p, ver=ver)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="snapshot.json")
    ap.add_argument("--states", nargs="*", default=["ON", "SUSPENDED", "OFF"],
                    help="состояния объявлений/ключей; ARCHIVED обычно не нужен")
    ap.add_argument("--campaigns", nargs="*", type=int, help="ограничить конкретными Id")
    a = ap.parse_args()

    sel = {"Ids": a.campaigns} if a.campaigns else {}
    print("кампании…", file=sys.stderr)
    camps = call("campaigns", {"SelectionCriteria": sel, "FieldNames": CAMPAIGN_FIELDS,
                               "TextCampaignFieldNames": TEXT_CAMPAIGN_FIELDS})
    ids = [c["Id"] for c in camps if c.get("State") != "ARCHIVED"]
    snap = {"campaigns": camps}

    if ids:
        print("группы…", file=sys.stderr)
        snap["adgroups"] = by_campaigns("adgroups", ids, {
            "SelectionCriteria": {}, "FieldNames": ADGROUP_FIELDS})
        print("ключи…", file=sys.stderr)
        snap["keywords"] = by_campaigns("keywords", ids, {
            "SelectionCriteria": {"States": a.states}, "FieldNames": KEYWORD_FIELDS})
        print("корректировки…", file=sys.stderr)
        snap["bidmodifiers"] = by_campaigns("bidmodifiers", ids, {
            "SelectionCriteria": {"Levels": ["CAMPAIGN", "AD_GROUP"]},
            "FieldNames": ["Id", "CampaignId", "AdGroupId", "Level", "Type"]})
        print("объявления (v501)…", file=sys.stderr)
        snap["ads"] = by_campaigns("ads", ids, {
            "SelectionCriteria": {"States": a.states}, "FieldNames": AD_FIELDS,
            "ResponsiveAdFieldNames": RESPONSIVE_FIELDS,
            "TextAdFieldNames": TEXTAD_FIELDS}, ver="v501")

        sl_ids = sorted({(ad.get("ResponsiveAd") or ad.get("TextAd") or {}).get("SitelinkSetId")
                         for ad in snap["ads"]} - {None})
        if sl_ids:
            print("быстрые ссылки…", file=sys.stderr)
            sets = []
            for i in range(0, len(sl_ids), 10):
                sets += call("sitelinks", {"SelectionCriteria": {"Ids": sl_ids[i:i + 10]},
                                           "FieldNames": ["Id", "Sitelinks"]})
            snap["sitelinks"] = sets

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    print({k: len(v) for k, v in snap.items()}, file=sys.stderr)
    print(a.out)


if __name__ == "__main__":
    main()
