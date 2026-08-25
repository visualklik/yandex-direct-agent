#!/usr/bin/env python3
"""Автопроверки настроек по слепку collect.py.

    python3 checks.py snapshot.json [--json out.json]

Каждая проверка — запись реестра CHECKS: идентификатор, категория, серьёзность,
чинится ли за 15 минут. Возвращает не только находки, но и статус каждой проверки
(pass / warn / fail / na), из которых считается балл — audit/scoring.md.

Проверки механические: только то, что видно из настроек, без статистики.
Каталог с описанием каждой — audit/settings-checklist.md.
"""
import argparse, json, re, sys
from collections import Counter, defaultdict

CRIT, WARN, INFO = "КРИТИЧНО", "ВАЖНО", "УЛУЧШЕНИЕ"
PASS, WARNST, FAIL, NA = "pass", "warn", "fail", "na"

# Веса категорий: во что упирается результат, если сломано. Сумма — 100.
CATEGORIES = {
    "analytics": ("Аналитика и цели", 25),
    "waste": ("Слив бюджета", 20),
    "structure": ("Структура аккаунта", 15),
    "keywords": ("Ключевые фразы", 15),
    "ads": ("Объявления", 15),
    "settings": ("Настройки и таргетинг", 10),
}
SEVERITY = {"critical": 5.0, "high": 3.0, "medium": 1.5, "low": 0.5}
SEV_LEVEL = {"critical": CRIT, "high": WARN, "medium": WARN, "low": INFO}
GRADES = [(90, "A", "отличный"), (75, "B", "хороший"), (60, "C", "требует внимания"),
          (40, "D", "плохой"), (0, "F", "критический")]
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


NETWORK_ONLY_TYPES = {"SMART_CAMPAIGN", "CPM_BANNER_CAMPAIGN", "CPM_DEALS_CAMPAIGN",
                      "CPM_PRICE_CAMPAIGN", "MOBILE_APP_CAMPAIGN"}


def search_serves(c, st):
    """Идут ли показы по поисковому запросу.

    Минус-слова отсекают запрос. Если запроса нет — отсекать нечего:
    кампания только на сети (Search = SERVING_OFF), смарт-баннеры, медийка,
    реклама приложений. Для них пустой список минус-слов — норма, а не находка.
    """
    if c.get("Type") in NETWORK_ONLY_TYPES:
        return False
    return st["Search"] not in (None, "SERVING_OFF")


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




# ─────────────────────────── контекст ───────────────────────────

def build_ctx(snap):
    """Всё, что считается один раз и нужно нескольким проверкам."""
    camps = [c for c in snap["campaigns"] if c.get("State") not in ("ARCHIVED",)]
    live = {c["Id"]: c for c in camps if c.get("State") == "ON"}
    groups = [g for g in snap.get("adgroups", []) if g["CampaignId"] in live]
    ads = snap.get("ads", [])
    keys = snap.get("keywords", [])
    live_ads = [a for a in ads if a.get("State") == "ON" and a["CampaignId"] in live]
    live_keys = [k for k in keys if k.get("State") == "ON" and k["CampaignId"] in live]

    by_group_ads = defaultdict(list)
    for a in live_ads:
        by_group_ads[a["AdGroupId"]].append(a)
    keys_per_group = Counter(k["AdGroupId"] for k in live_keys)

    negatives_in_groups = defaultdict(int)
    for g in groups:
        negatives_in_groups[g["CampaignId"]] += len(
            (g.get("NegativeKeywords") or {}).get("Items") or [])
        negatives_in_groups[g["CampaignId"]] += len(
            (g.get("NegativeKeywordSharedSetIds") or {}).get("Items") or [])

    camps_without_utm = set()
    for a in live_ads:
        h = (a.get("ResponsiveAd") or a.get("TextAd") or {}).get("Href") or ""
        if h and "utm_" not in h and "openstat" not in h:
            camps_without_utm.add(a["CampaignId"])

    return dict(snap=snap, camps=camps, live=live, groups=groups, ads=ads, keys=keys,
                live_ads=live_ads, live_keys=live_keys, by_group_ads=by_group_ads,
                keys_per_group=keys_per_group, negatives_in_groups=negatives_in_groups,
                camps_without_utm=camps_without_utm,
                gname={g["Id"]: g["Name"] for g in snap.get("adgroups", [])},
                sitelinks={s["Id"]: s for s in snap.get("sitelinks", [])},
                neg_sets={s["Id"]: s for s in snap.get("negativekeywordsharedsets", [])})


def names(items, limit=6):
    items = list(items)
    return ", ".join(str(x) for x in items[:limit]) + ("…" if len(items) > limit else "")


def verdict(bad, total, title_bad, title_ok, level_if_bad=None):
    """Стандартный ответ проверки: список нарушителей → статус и текст."""
    if total == 0:
        return NA, "нечего проверять", ""
    if not bad:
        return PASS, title_ok, ""
    return (level_if_bad or FAIL), title_bad, ""


# ─────────────────────────── проверки ───────────────────────────

def c_counter(ctx):
    bad = [c["Name"] for c in ctx["live"].values()
           if conv_strategy(c) and not body(c).get("CounterIds")]
    if not [c for c in ctx["live"].values() if conv_strategy(c)]:
        return NA, "конверсионных стратегий нет", ""
    if bad:
        return FAIL, f"нет счётчика Метрики при конверсионной стратегии: {len(bad)}", names(bad)
    return PASS, "счётчик привязан во всех конверсионных кампаниях", ""


def c_goals(ctx):
    conv = [c for c in ctx["live"].values() if conv_strategy(c)]
    if not conv:
        return NA, "конверсионных стратегий нет", ""
    bad = [c["Name"] for c in conv if not campaign_goals(c)]
    if bad:
        return FAIL, f"не заданы цели при конверсионной стратегии: {len(bad)}", names(bad)
    return PASS, "цели заданы во всех конверсионных кампаниях", ""


def c_attribution(ctx):
    models = {body(c).get("AttributionModel") for c in ctx["live"].values()
              if body(c).get("AttributionModel")}
    if not models:
        return NA, "модель атрибуции не отдана API", ""
    if len(models) > 1:
        return WARNST, f"в кампаниях разные модели атрибуции: {names(models)}", \
            "сравнивать их метрики между собой нельзя"
    return PASS, f"единая модель атрибуции: {names(models)}", ""


def c_utm(ctx):
    bad = [c["Name"] for c in ctx["live"].values()
           if setting(c, "ADD_METRICA_TAG") == "NO" and c["Id"] in ctx["camps_without_utm"]]
    if bad:
        return FAIL, f"нет ни разметки, ни UTM: {len(bad)} кампаний", names(bad)
    return PASS, "источник отслеживается везде: разметка или UTM", ""


def c_lonely_counters(ctx):
    use = defaultdict(set)
    for c in ctx["live"].values():
        for cid in (body(c).get("CounterIds") or {}).get("Items") or []:
            use[cid].add(c["Id"])
    lonely = sorted(cid for cid, used in use.items() if len(used) == 1)
    if not use:
        return NA, "счётчиков нет", ""
    if lonely and len(use) > len(lonely):
        return WARNST, f"счётчиков, стоящих лишь в одной кампании: {len(lonely)}", \
            f"{names(lonely)} — проверить в интерфейсе пометку «Счётчик не найден»: " \
            f"валидность API не отдаёт"
    return PASS, "счётчики общие для аккаунта", ""


def c_negatives(ctx):
    checkable = [c for c in ctx["live"].values() if search_serves(c, strategy_types(c))]
    if not checkable:
        return NA, "поисковых показов нет — минус-слова не нужны", ""
    bad = []
    for c in checkable:
        n = len((c.get("NegativeKeywords") or {}).get("Items") or [])
        n += ctx["negatives_in_groups"].get(c["Id"], 0)
        n += len((body(c).get("NegativeKeywordSharedSetIds") or {}).get("Items") or [])
        if n == 0:
            bad.append(c["Name"])
    if bad:
        return FAIL, f"минус-слов нет нигде: {len(bad)} кампаний", names(bad)
    return PASS, "минус-слова есть во всех поисковых кампаниях", ""


def c_neg_library(ctx):
    used = any((body(c).get("NegativeKeywordSharedSetIds") or {}).get("Items")
               for c in ctx["live"].values())
    if used:
        return PASS, "используются библиотечные наборы минус-слов", ""
    return WARNST, "библиотечные наборы минус-слов не используются", \
        "общий стоп-лист в библиотеке правится один раз, а не в каждой кампании"


def c_dupes_intra(ctx):
    intra = defaultdict(set)
    for k in ctx["live_keys"]:
        intra[(k["CampaignId"], norm_key(k["Keyword"]))].add(k["AdGroupId"])
    d = {k: v for k, v in intra.items() if len(v) > 1}
    if not ctx["live_keys"]:
        return NA, "ключей нет", ""
    if d:
        return FAIL, f"дублей фраз внутри кампаний (между группами): {len(d)}", \
            names([k[1] for k in d], 3) + " — группы конкурируют друг с другом"
    return PASS, "дублей фраз внутри кампаний нет", ""


def c_dupes_cross(ctx):
    cross = defaultdict(set)
    for k in ctx["live_keys"]:
        cross[norm_key(k["Keyword"])].add(k["CampaignId"])
    d = {k: v for k, v in cross.items() if len(v) > 1}
    if not ctx["live_keys"]:
        return NA, "ключей нет", ""
    if d:
        return WARNST, f"фраз, встречающихся в нескольких кампаниях: {len(d)}", \
            "проверить, что это разные площадки или регионы, а не конкуренция"
    return PASS, "пересечений фраз между кампаниями нет", ""


def c_excluded_sites(ctx):
    big = [(c["Name"], len((c.get("ExcludedSites") or {}).get("Items") or []))
           for c in ctx["live"].values()
           if len((c.get("ExcludedSites") or {}).get("Items") or []) > 300]
    if big:
        return WARNST, f"длинные списки запрещённых площадок: {len(big)}", \
            names([f"{n} — {k}" for n, k in big], 4) + " — проверить, не режут ли охват"
    return PASS, "списки запрещённых площадок в разумных пределах", ""


def c_relevant_keywords(ctx):
    on = [c["Name"] for c in ctx["live"].values() if body(c).get("RelevantKeywords")]
    if on:
        return WARNST, f"включены дополнительные релевантные фразы: {len(on)}", \
            names(on) + " — источник нецелевых запросов, сверить с отчётом"
    return PASS, "дополнительные релевантные фразы выключены", ""


def c_one_ad(ctx):
    if not ctx["by_group_ads"]:
        return NA, "активных объявлений нет", ""
    single = [g for g, v in ctx["by_group_ads"].items() if len(v) == 1]
    if single:
        return WARNST, f"групп с единственным активным объявлением: {len(single)}", \
            names([ctx["gname"].get(g, g) for g in single], 5) + " — нечего ротировать"
    return PASS, "во всех группах есть варианты объявлений", ""


def c_group_size(ctx):
    big = [(g, n) for g, n in ctx["keys_per_group"].items() if n > 15]
    if not ctx["keys_per_group"]:
        return NA, "ключей нет", ""
    if big:
        return WARNST, f"групп с более чем 15 активными фразами: {len(big)}", \
            names([f"{ctx['gname'].get(g, g)} — {n}" for g, n in sorted(big, key=lambda x: -x[1])],
                  4) + " — объявление не может быть релевантно всем фразам сразу"
    return PASS, "размер групп в норме (до 15 фраз)", ""


def c_zombie(ctx):
    zombie = [c["Name"] for c in ctx["camps"] if c.get("State") == "SUSPENDED"]
    if len(zombie) > len(ctx["live"]):
        return WARNST, f"остановленных кампаний больше, чем работающих: {len(zombie)}", \
            "архивировать то, к чему не вернутся: иначе аккаунт нечитаем"
    if zombie:
        return PASS, f"остановленных кампаний {len(zombie)} — в пределах нормы", ""
    return PASS, "кампаний-зомби нет", ""


def c_mixed(ctx):
    mixed = [c["Name"] for c in ctx["live"].values()
             if strategy_types(c)["Search"] not in (None, "SERVING_OFF")
             and strategy_types(c)["Network"] not in (None, "SERVING_OFF", "NETWORK_DEFAULT")]
    if mixed:
        return WARNST, f"Поиск и сети в одной кампании: {len(mixed)}", names(mixed)
    return PASS, "Поиск и сети разделены", ""


def c_rarely_served(ctx):
    rare = [g["Name"] for g in ctx["groups"] if g.get("ServingStatus") == "RARELY_SERVED"]
    if rare:
        return WARNST, f"групп с пометкой «мало показов»: {len(rare)}", \
            names(rare, 4) + " — расширить семантику или поднять бюджет"
    return PASS, "групп со статусом «мало показов» нет", ""


def c_productivity(ctx):
    vals = [(k["Keyword"], k["Productivity"]) for k in ctx["live_keys"]
            if isinstance(k.get("Productivity"), (int, float)) and k["Productivity"] > 0]
    if not vals:
        return NA, "продуктивность фраз не рассчитана", ""
    low = [k for k, p in vals if p < 5]
    if len(low) > len(vals) * 0.3:
        return FAIL, f"фраз с низкой продуктивностью (<5): {len(low)} из {len(vals)}", \
            names(low, 4) + " — переписать или объединить"
    if low:
        return WARNST, f"фраз с низкой продуктивностью (<5): {len(low)} из {len(vals)}", \
            names(low, 4)
    return PASS, "продуктивность фраз в норме", ""


def c_moderation(ctx):
    rejected = [a for a in ctx["ads"]
                if a.get("Status") == "REJECTED" and a["CampaignId"] in ctx["live"]]
    if rejected:
        return FAIL, f"объявлений отклонено модерацией: {len(rejected)}", \
            names([a["Id"] for a in rejected], 5) + " — разбирать причины"
    return PASS, "отклонённых объявлений нет", ""


def c_clones(ctx):
    clones = []
    for g, v in ctx["by_group_ads"].items():
        buckets = defaultdict(list)
        for a in v:
            if a.get("Type") != "RESPONSIVE_AD":
                continue
            if len((a.get("ResponsiveAd") or {}).get("Titles") or []) > 1:
                continue
            buckets[((a.get("ResponsiveAd") or {}).get("Href") or "").split("?")[0]].append(a)
        if any(len(b) >= 2 for b in buckets.values()):
            clones.append(g)
    if not ctx["by_group_ads"]:
        return NA, "активных объявлений нет", ""
    if clones:
        return WARNST, f"групп с объявлениями-клонами: {len(clones)}", \
            "схлопнуть в комбинаторное — updates/api-responsive-ads.md"
    return PASS, "объявлений-клонов нет", ""


def c_images(ctx):
    net = {i for i, c in ctx["live"].items()
           if strategy_types(c)["Network"] not in (None, "SERVING_OFF")}
    ads = [a for a in ctx["live_ads"] if a["CampaignId"] in net]
    if not ads:
        return NA, "показов в сетях нет", ""
    thin = [a for a in ads
            if len(((a.get("ResponsiveAd") or {}).get("AdImages") or {}).get("Items") or []) == 1]
    if thin:
        return WARNST, f"объявлений в сетях с единственным изображением: {len(thin)}", \
            "в комбинаторном можно до 5 — больше вариантов для подбора"
    return PASS, "изображений в сетевых объявлениях достаточно", ""


def c_sitelinks(ctx):
    if not ctx["live_ads"]:
        return NA, "активных объявлений нет", ""
    without, thin = [], []
    for a in ctx["live_ads"]:
        sid = (a.get("ResponsiveAd") or a.get("TextAd") or {}).get("SitelinkSetId")
        if not sid:
            without.append(a["Id"])
        elif sid in ctx["sitelinks"] and len(ctx["sitelinks"][sid].get("Sitelinks") or []) < 4:
            thin.append(sid)
    if without:
        return FAIL, f"объявлений без быстрых ссылок: {len(without)}", \
            "быстрые ссылки занимают место в выдаче и поднимают CTR"
    if thin:
        return WARNST, f"наборов быстрых ссылок меньше четырёх штук: {len(set(thin))}", \
            names(sorted(set(thin)), 4) + " — добирать до 4–8"
    return PASS, "быстрые ссылки заполнены", ""


def c_one_landing(ctx):
    hrefs = Counter()
    for a in ctx["live_ads"]:
        h = ((a.get("ResponsiveAd") or a.get("TextAd") or {}).get("Href") or "").split("?")[0]
        if h:
            hrefs[h] += 1
    if not hrefs:
        return NA, "ссылок нет", ""
    top, cnt = hrefs.most_common(1)[0]
    if cnt / sum(hrefs.values()) > 0.5:
        return WARNST, f"{cnt} из {sum(hrefs.values())} объявлений ведут на одну страницу", top
    return PASS, "объявления ведут на разные посадочные", ""


def c_monitoring(ctx):
    off = [c["Name"] for c in ctx["live"].values()
           if setting(c, "ENABLE_SITE_MONITORING") == "NO"]
    if off:
        return FAIL, f"выключен мониторинг сайта: {len(off)} кампаний", \
            names(off) + " — при падении сайта показы не остановятся"
    return PASS, "мониторинг сайта включён", ""


def c_geo_wide(ctx):
    on = [c["Name"] for c in ctx["live"].values()
          if setting(c, "ENABLE_AREA_OF_INTEREST_TARGETING") == "YES"]
    if on:
        return WARNST, f"включён расширенный геотаргетинг: {len(on)}", \
            names(on) + " — сверить с отчётом по регионам"
    return PASS, "расширенный геотаргетинг выключен", ""


def c_budget_learning(ctx):
    bad = []
    for c in ctx["live"].values():
        for place, params in strategy_params(c).items():
            week, cpa_t = params.get("WeeklySpendLimit"), params.get("Cpa")
            if week and cpa_t and week / cpa_t < 10:
                bad.append(f"{c['Name']}: {week/1e6:,.0f} ₽/нед при цели {cpa_t/1e6:,.0f} ₽ "
                           f"= {week/cpa_t:.1f} конверсий".replace(",", " "))
    if not any(strategy_params(c) for c in ctx["live"].values()):
        return NA, "параметры стратегий не отданы", ""
    if bad:
        return FAIL, f"недельный бюджет не даёт 10 конверсий: {len(bad)}", names(bad, 3)
    return PASS, "бюджета хватает на обучение стратегий", ""


def c_bidmodifiers(ctx):
    mods = ctx["snap"].get("bidmodifiers", [])
    if mods:
        return PASS, f"корректировки ставок заданы: {len(mods)}", ""
    return WARNST, "корректировок ставок нет ни на одном уровне", \
        "проверить разницу по устройствам, полу, возрасту и гео в срезах"


def conv_strategy(c):
    return any(t in CONV_STRATEGIES for t in strategy_types(c).values() if t)


# id, категория, серьёзность, быстро ли чинится, функция
CHECKS = [
    ("MET01", "analytics", "critical", False, "счётчик Метрики в конверсионных кампаниях", c_counter),
    ("MET02", "analytics", "critical", False, "цели в конверсионных кампаниях", c_goals),
    ("MET03", "analytics", "medium", False, "единая модель атрибуции", c_attribution),
    ("MET04", "analytics", "high", True, "разметка ссылок или UTM", c_utm),
    ("MET05", "analytics", "low", True, "счётчики-одиночки", c_lonely_counters),
    ("NEG01", "waste", "high", True, "минус-слова на любом уровне", c_negatives),
    ("NEG02", "waste", "low", True, "библиотечные наборы минус-слов", c_neg_library),
    ("NEG03", "waste", "medium", False, "дубли фраз внутри кампании", c_dupes_intra),
    ("NEG04", "waste", "low", False, "пересечение фраз между кампаниями", c_dupes_cross),
    ("NEG05", "waste", "medium", False, "длина списка запрещённых площадок", c_excluded_sites),
    ("NEG06", "waste", "medium", True, "дополнительные релевантные фразы", c_relevant_keywords),
    ("STR01", "structure", "medium", False, "варианты объявлений в группе", c_one_ad),
    ("STR02", "structure", "medium", False, "размер групп по числу фраз", c_group_size),
    ("STR03", "structure", "low", True, "кампании-зомби", c_zombie),
    ("STR04", "structure", "high", False, "разделение Поиска и сетей", c_mixed),
    ("STR05", "structure", "medium", False, "группы со статусом «мало показов»", c_rarely_served),
    ("KEY01", "keywords", "medium", False, "продуктивность фраз", c_productivity),
    ("AD01", "ads", "critical", False, "модерация объявлений", c_moderation),
    ("AD02", "ads", "medium", False, "объявления-клоны", c_clones),
    ("AD03", "ads", "low", False, "изображения в сетевых объявлениях", c_images),
    ("AD04", "ads", "high", True, "быстрые ссылки", c_sitelinks),
    ("AD05", "ads", "medium", False, "разнообразие посадочных", c_one_landing),
    ("SET01", "settings", "high", True, "мониторинг сайта", c_monitoring),
    ("SET02", "settings", "low", False, "расширенный геотаргетинг", c_geo_wide),
    ("SET03", "settings", "high", False, "бюджет против обучения стратегии", c_budget_learning),
    ("SET04", "settings", "low", False, "корректировки ставок", c_bidmodifiers),
]


# ─────────────────────────── прогон и балл ───────────────────────────

def score(results):
    """Формула из audit/scoring.md: набранное/возможное с весами, N/A исключается."""
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


def run(snap):
    """Возвращает результаты всех проверок, находки и балл."""
    ctx = build_ctx(snap)
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
                     else (WARN if r["severity"] in ("critical", "high") else INFO),
                     what=r["what"], detail=r["detail"], id=r["id"], quick=r["quick"],
                     category=r["category"], severity=r["severity"], status=r["status"])
                for r in results if r["status"] in (FAIL, WARNST)]
    order = {CRIT: 0, WARN: 1, INFO: 2}
    findings.sort(key=lambda f: (order[f["level"]], f["id"]))
    return dict(results=results, findings=findings, score=pct, grade=grade, label=label,
                counts=Counter(r["status"] for r in results),
                stats=dict(campaigns=len(ctx["live"]), groups=len(ctx["groups"]),
                           ads=len(ctx["live_ads"]), keywords=len(ctx["live_keys"])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--json", help="сохранить результат в файл")
    a = ap.parse_args()
    snap = json.load(open(a.snapshot, encoding="utf-8"))
    res = run(snap)
    s = res["stats"]
    c = res["counts"]
    print(f"Кампаний активных: {s['campaigns']} · групп: {s['groups']} · "
          f"объявлений: {s['ads']} · ключей: {s['keywords']}")
    print(f"Балл: {res['score']} из 100 · грейд {res['grade']} ({res['label']}) · "
          f"проверок пройдено {c[PASS]}, с замечанием {c[WARNST]}, провалено {c[FAIL]}, "
          f"неприменимо {c[NA]}\n")
    for lvl in (CRIT, WARN, INFO):
        block = [f for f in res["findings"] if f["level"] == lvl]
        if not block:
            continue
        print(f"── {lvl} ({len(block)})")
        for f in block:
            mark = " ⚡" if f["quick"] else ""
            print(f"  • [{f['id']}]{mark} {f['what']}")
            if f["detail"]:
                print(f"      {f['detail']}")
        print()
    quick = [f for f in res["findings"] if f["quick"]]
    if quick:
        print(f"Быстрые победы (чинится за 15 минут): {len(quick)} — "
              f"{', '.join(f['id'] for f in quick)}")
    if a.json:
        json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1,
                  default=lambda o: dict(o) if isinstance(o, Counter) else str(o))
        print(a.json)


if __name__ == "__main__":
    main()
