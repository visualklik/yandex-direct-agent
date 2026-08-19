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


STRATEGY_PARAM_KEYS = ("PayForConversion", "AverageCpa", "AverageCrr", "AverageRoi",
                      "WbMaximumConversionRate", "PayForConversionCrr", "WbMaximumAppInstalls",
                      "AverageCpi", "WeeklyClickPackage", "AverageCpc", "WbMaximumClicks")


def strategy_params(camp):
    """Параметры стратегий Поиска и сетей: {Search: {...}, Network: {...}}."""
    bs = body(camp).get("BiddingStrategy") or {}
    out = {}
    for place in ("Search", "Network"):
        blk = bs.get(place) or {}
        for k in STRATEGY_PARAM_KEYS:
            if isinstance(blk.get(k), dict):
                out[place] = blk[k]
                break
    return out


def campaign_goals(camp):
    """Цели кампании: из PriorityGoals и из самой стратегии.

    Ловушка: при одной цели она лежит в стратегии (`PayForConversion.GoalId`),
    а `PriorityGoals` остаётся null. Судить по одному PriorityGoals — ложная тревога.
    """
    goals = {g["GoalId"] for g in ((body(camp).get("PriorityGoals") or {}).get("Items") or [])}
    for params in strategy_params(camp).values():
        if params.get("GoalId"):
            goals.add(params["GoalId"])
    return goals


def norm_key(k):
    """Ключ без операторов, минус-слов и порядка слов — для поиска дублей."""
    k = re.sub(r"-\S+", "", k.lower())          # минус-слова принадлежат фразе, не совпадению
    k = re.sub(r"[!+\"\[\]]", "", k)
    return " ".join(sorted(w for w in re.split(r"\W+", k) if w))


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

    negatives_in_groups = defaultdict(int)
    for g in groups:
        negatives_in_groups[g["CampaignId"]] += len(
            (g.get("NegativeKeywords") or {}).get("Items") or [])
        negatives_in_groups[g["CampaignId"]] += len(
            (g.get("NegativeKeywordSharedSetIds") or {}).get("Items") or [])

    for c in live.values():
        n, b = c["Name"], body(c)
        st = strategy_types(c)
        conv_strategy = any(t in CONV_STRATEGIES for t in st.values() if t)
        if conv_strategy and not b.get("CounterIds"):
            add(CRIT, "нет счётчика Метрики при конверсионной стратегии", n)
        if conv_strategy and not campaign_goals(c):
            add(CRIT, "не заданы цели при конверсионной стратегии", n)
        for place, params in strategy_params(c).items():
            week, cpa_t = params.get("WeeklySpendLimit"), params.get("Cpa")
            if week and cpa_t and week / cpa_t < 10:
                add(WARN, "недельный бюджет не даёт 10 конверсий — стратегия не обучится",
                    f"{n}: {week/1e6:,.0f} ₽/нед при цели {cpa_t/1e6:,.0f} ₽ "
                    f"= {week/cpa_t:.1f} конверсий".replace(",", " "))
        if setting(c, "ENABLE_SITE_MONITORING") == "NO":
            add(WARN, "выключен мониторинг сайта", n)
        if setting(c, "ADD_METRICA_TAG") == "NO" and c["Id"] in camps_without_utm:
            add(WARN, "разметка выключена, а в ссылках нет UTM — источник не отследить", n)
        if setting(c, "ENABLE_AREA_OF_INTEREST_TARGETING") == "YES":
            add(INFO, "включён расширенный геотаргетинг — проверить по отчёту регионов", n)
        neg_c = len((c.get("NegativeKeywords") or {}).get("Items") or [])
        neg_g = negatives_in_groups.get(c["Id"], 0)
        sets = len((b.get("NegativeKeywordSharedSetIds") or {}).get("Items") or [])
        if neg_c + neg_g + sets == 0:
            search_serves = st["Search"] not in (None, "SERVING_OFF")
            add(WARN if search_serves else INFO,
                "минус-слов нет нигде: ни в кампании, ни в группах, ни в наборах", n)
        if len((c.get("ExcludedSites") or {}).get("Items") or []) > 300:
            add(INFO, f"запрещённых площадок {len(c['ExcludedSites']['Items'])} — проверить эффект", n)
        if st["Search"] not in (None, "SERVING_OFF") and st["Network"] not in (None, "SERVING_OFF",
                                                                              "NETWORK_DEFAULT"):
            add(INFO, "Поиск и сети в одной кампании", n)

    # Валидность счётчиков API не отдаёт. Косвенный признак: счётчик стоит в одной кампании,
    # тогда как остальные разделяют общий набор. Это повод посмотреть глазами, а не находка.
    counter_use = defaultdict(set)
    for c in live.values():
        for cid in (body(c).get("CounterIds") or {}).get("Items") or []:
            counter_use[cid].add(c["Id"])
    lonely = sorted(cid for cid, used in counter_use.items() if len(used) == 1)
    if lonely and len(counter_use) > len(lonely):
        add(INFO, f"счётчиков Метрики, стоящих лишь в одной кампании: {len(lonely)}",
            f"{', '.join(str(x) for x in lonely[:8])} — проверить в интерфейсе, "
            f"нет ли пометки «Счётчик не найден»: API валидность не показывает")

    by_group_ads = defaultdict(list)
    for a in ads:
        if a.get("State") == "ON" and a["CampaignId"] in live:
            by_group_ads[a["AdGroupId"]].append(a)
    gname = {g["Id"]: g["Name"] for g in groups}
    single = [g for g, v in by_group_ads.items() if len(v) == 1]
    if single:
        add(INFO, f"групп с единственным активным объявлением: {len(single)}",
            ", ".join(gname.get(g, str(g)) for g in single[:5]) + ("…" if len(single) > 5 else ""))

    # клоны считаем только внутри одной посадочной: объявления с разными URL
    # схлопывать нельзя — половина заголовков поведёт не туда
    clones = []
    for g, v in by_group_ads.items():
        buckets = defaultdict(list)
        for a in v:
            if a.get("Type") != "RESPONSIVE_AD":
                continue
            if len((a.get("ResponsiveAd") or {}).get("Titles") or []) > 1:
                continue
            buckets[((a.get("ResponsiveAd") or {}).get("Href") or "").split("?")[0]].append(a)
        if any(len(b) >= 2 for b in buckets.values()):
            clones.append((g, max(len(b) for b in buckets.values())))
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

    intra, cross = defaultdict(set), defaultdict(set)
    for k in keys:
        if k.get("State") == "ON" and k["CampaignId"] in live:
            intra[(k["CampaignId"], norm_key(k["Keyword"]))].add(k["AdGroupId"])
            cross[norm_key(k["Keyword"])].add(k["CampaignId"])
    di = {k: v for k, v in intra.items() if len(v) > 1}
    dc = {k: v for k, v in cross.items() if len(v) > 1}
    if di:
        sample = "; ".join(k[1] for k in list(di)[:3])
        add(WARN, f"дублей фраз внутри кампаний (между группами): {len(di)}",
            sample + ("…" if len(di) > 3 else "") + " — группы конкурируют друг с другом")
    if dc:
        add(INFO, f"фраз, встречающихся в нескольких кампаниях: {len(dc)}",
            "проверить, что это разные площадки или разные регионы, а не конкуренция")

    net_camps = {i for i, c in live.items()
                 if strategy_types(c)["Network"] not in (None, "SERVING_OFF")}
    thin_ads = [a for a in ads if a.get("State") == "ON" and a["CampaignId"] in net_camps
                and len(((a.get("ResponsiveAd") or {}).get("AdImages") or {}).get("Items") or []) == 1]
    if thin_ads:
        add(INFO, f"объявлений в сетях с единственным изображением: {len(thin_ads)}",
            "в комбинаторном можно до 5 — больше вариантов для подбора")

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
