#!/usr/bin/env python3
"""Автопроверки настроек по слепку collect.py.

    python3 checks.py snapshot.json

Печатает находки с приоритетом. Проверки механические — то, что видно из настроек
без статистики. Всё, что требует денег и конверсий, взвешивается отдельно
(audit/settings-checklist.md, раздел «Приоритет»).
"""
import json, re, sys
from collections import Counter, defaultdict

CRIT, WARN, INFO = "КРИТИЧНО", "ВАЖНО", "УЛУЧШЕНИЕ"
CONV_STRATEGIES = {"AVERAGE_CPA", "AVERAGE_ROI", "AVERAGE_CRR", "PAY_FOR_CONVERSION",
                   "WB_MAXIMUM_CONVERSION_RATE", "PAY_FOR_CONVERSION_CRR"}


def setting(camp, option):
    body = next((camp[k] for k in camp if k.endswith("Campaign") and isinstance(camp[k], dict)), {})
    for s in body.get("Settings") or []:
        if s["Option"] == option:
            return s["Value"]
    return None


def body(camp):
    return next((camp[k] for k in camp if k.endswith("Campaign") and isinstance(camp[k], dict)), {})


def strategy_types(camp):
    bs = body(camp).get("BiddingStrategy") or {}
    return {p: (bs.get(p) or {}).get("BiddingStrategyType") for p in ("Search", "Network")}


def norm_key(k):
    k = re.sub(r"[!+\"\[\]]", "", k.lower())
    return " ".join(sorted(w for w in re.split(r"\W+", k) if w and not w.startswith("-")))


def main():
    snap = json.load(open(sys.argv[1], encoding="utf-8"))
    camps = [c for c in snap["campaigns"] if c.get("State") not in ("ARCHIVED",)]
    live = {c["Id"]: c for c in camps if c.get("State") == "ON"}
    groups = snap.get("adgroups", [])
    ads = snap.get("ads", [])
    keys = snap.get("keywords", [])
    found = []

    def add(level, what, detail):
        found.append((level, what, detail))

    camps_without_utm = set()
    for a in ads:
        if a.get("State") != "ON":
            continue
        h = (a.get("ResponsiveAd") or a.get("TextAd") or {}).get("Href") or ""
        if h and "utm_" not in h and "openstat" not in h:
            camps_without_utm.add(a["CampaignId"])

    for c in live.values():
        n, b = c["Name"], body(c)
        st = strategy_types(c)
        conv_strategy = any(t in CONV_STRATEGIES for t in st.values() if t)
        if conv_strategy and not b.get("CounterIds"):
            add(CRIT, "нет счётчика Метрики при конверсионной стратегии", n)
        if conv_strategy and not b.get("PriorityGoals"):
            add(CRIT, "не заданы ключевые цели при конверсионной стратегии", n)
        if setting(c, "ENABLE_SITE_MONITORING") == "NO":
            add(WARN, "выключен мониторинг сайта", n)
        if setting(c, "ADD_METRICA_TAG") == "NO" and c["Id"] in camps_without_utm:
            add(WARN, "разметка выключена, а в ссылках нет UTM — источник не отследить", n)
        if setting(c, "ENABLE_AREA_OF_INTEREST_TARGETING") == "YES":
            add(INFO, "включён расширенный геотаргетинг — проверить по отчёту регионов", n)
        if not (c.get("NegativeKeywords") or {}).get("Items"):
            add(WARN, "нет минус-слов на уровне кампании", n)
        if len((c.get("ExcludedSites") or {}).get("Items") or []) > 300:
            add(INFO, f"запрещённых площадок {len(c['ExcludedSites']['Items'])} — проверить эффект", n)
        if st["Search"] not in (None, "SERVING_OFF") and st["Network"] not in (None, "SERVING_OFF",
                                                                              "NETWORK_DEFAULT"):
            add(INFO, "Поиск и сети в одной кампании", n)

    by_group_ads = defaultdict(list)
    for a in ads:
        if a.get("State") == "ON" and a["CampaignId"] in live:
            by_group_ads[a["AdGroupId"]].append(a)
    gname = {g["Id"]: g["Name"] for g in groups}
    single = [g for g, v in by_group_ads.items() if len(v) == 1]
    if single:
        add(INFO, f"групп с единственным активным объявлением: {len(single)}",
            ", ".join(gname.get(g, str(g)) for g in single[:5]) + ("…" if len(single) > 5 else ""))

    clones = []
    for g, v in by_group_ads.items():
        r = [a for a in v if a.get("Type") == "RESPONSIVE_AD"]
        thin = [a for a in r if len((a.get("ResponsiveAd") or {}).get("Titles") or []) <= 1]
        if len(thin) >= 2:
            clones.append((g, len(thin)))
    if clones:
        add(WARN, f"групп с объявлениями-клонами (один заголовок): {len(clones)}",
            "кандидаты на схлопывание в комбинаторное, см. updates/api-responsive-ads.md")

    hrefs = Counter()
    for a in ads:
        if a.get("State") == "ON" and a["CampaignId"] in live:
            h = ((a.get("ResponsiveAd") or a.get("TextAd") or {}).get("Href") or "").split("?")[0]
            if h:
                hrefs[h] += 1
    if hrefs:
        top, cnt = hrefs.most_common(1)[0]
        if cnt / sum(hrefs.values()) > 0.5:
            add(WARN, f"{cnt} из {sum(hrefs.values())} объявлений ведут на одну страницу", top)

    dupes = defaultdict(set)
    for k in keys:
        if k.get("State") == "ON" and k["CampaignId"] in live:
            dupes[norm_key(k["Keyword"])].add(k["AdGroupId"])
    d = {k: v for k, v in dupes.items() if len(v) > 1}
    if d:
        add(WARN, f"дублей ключевых фраз между группами: {len(d)}",
            "; ".join(list(d)[:3]) + ("…" if len(d) > 3 else ""))

    thin_ads = [a for a in ads if a.get("State") == "ON" and a["CampaignId"] in live
                and len(((a.get("ResponsiveAd") or {}).get("AdImages") or {}).get("Items") or []) == 1]
    if thin_ads:
        add(INFO, f"объявлений с единственным изображением: {len(thin_ads)}",
            "в сетях можно до 5")

    rejected = [a for a in ads if a.get("Status") == "REJECTED" and a["CampaignId"] in live]
    if rejected:
        add(CRIT, f"объявлений отклонено модерацией: {len(rejected)}", "разбирать причины")

    rare = [g for g in groups if g.get("ServingStatus") == "RARELY_SERVED"
            and g["CampaignId"] in live]
    if rare:
        add(INFO, f"групп с пометкой «мало показов»: {len(rare)}", "расширить семантику или бюджет")

    print(f"Кампаний активных: {len(live)} · групп: {len(groups)} · объявлений: {len(ads)} "
          f"· ключей: {len(keys)}\n")
    for lvl in (CRIT, WARN, INFO):
        block = [f for f in found if f[0] == lvl]
        if not block:
            continue
        merged = defaultdict(list)
        for _, what, detail in block:
            merged[what].append(detail)
        print(f"── {lvl} ({len(merged)})")
        for what, details in merged.items():
            print(f"  • {what}")
            print(f"      {'; '.join(details[:8])}" + ("…" if len(details) > 8 else ""))
        print()
    if not found:
        print("Автопроверки чисты. Дальше — ручные пункты чеклиста.")


if __name__ == "__main__":
    main()
