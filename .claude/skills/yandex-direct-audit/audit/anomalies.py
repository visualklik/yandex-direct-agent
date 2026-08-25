#!/usr/bin/env python3
"""Поиск аномальных дней по дневным отчётам.

    python3 anomalies.py --reports data --out anomalies.json

Читает days.tsv (аккаунт целиком) и campdays.tsv (по кампаниям), считает норму робастно
(медиана + MAD) и отмечает отклонения. Каталог правил и пороги — anomalies.md.
Ничего не диагностирует: аномалия это адрес для проверки, а не вывод.
"""
import argparse, csv, json, os, statistics, sys
from collections import defaultdict

TAIL_DAYS = 3          # хвост окна атрибуции: конверсии ещё дозаписываются
Z = 3.5                # порог робастного z
MIN_DAYS = 10          # короче ряд — нормы нет, проверять нечего


def num(v):
    if v in (None, "", "--"):
        return 0.0
    try:
        return float(str(v).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return 0.0


def _norm_conv(rows):
    """Отчёт с фильтром по цели даёт колонку Conversions_<goal>_<attr>.
    Приводим её к Conversions, чтобы считалки не зависели от имени."""
    out = []
    for r in rows:
        k = next((k for k in r if k and k.startswith("Conversions") and k != "Conversions"), None)
        if k:
            r = dict(r)
            r["Conversions"] = r.pop(k)
        out.append(r)
    return out


def tsv(path):
    lines = open(path, encoding="utf-8-sig").read().splitlines()
    return _norm_conv([r for r in csv.DictReader(lines, delimiter="\t") if any(r.values())])


def med(xs):
    return statistics.median(xs) if xs else 0.0


def mad(xs, m=None):
    if not xs:
        return 0.0
    m = med(xs) if m is None else m
    return med([abs(x - m) for x in xs])


def rz(x, m, d):
    """Робастный z. При нулевом MAD ряд почти константа — отклонением считаем только явный скачок."""
    if d == 0:
        return 0.0 if x <= m else (99.0 if x > m * 1.5 else 0.0)
    return 0.6745 * (x - m) / d


def series(rows, scope):
    """[{date, cost, clicks, imps, conv}] по возрастанию даты."""
    acc = defaultdict(lambda: dict(cost=0.0, clicks=0.0, imps=0.0, conv=0.0))
    for r in rows:
        d = acc[r["Date"]]
        d["cost"] += num(r.get("Cost"))
        d["clicks"] += num(r.get("Clicks"))
        d["imps"] += num(r.get("Impressions"))
        d["conv"] += num(r.get("Conversions"))
    return [dict(date=k, scope=scope, **v) for k, v in sorted(acc.items())]


def check(days, scope):
    """Правила A–J каталога. Возвращает список находок."""
    out = []
    if len(days) < MIN_DAYS:
        return out
    body = days[:-TAIL_DAYS] if len(days) > TAIL_DAYS else days
    costs = [d["cost"] for d in body]
    m_cost, d_cost = med(costs), mad(costs)
    if m_cost <= 0:
        return out
    conv_total = sum(d["conv"] for d in body)
    cost_total = sum(d["cost"] for d in body)
    m_cpa = cost_total / conv_total if conv_total else 0

    cpcs = [d["cost"] / d["clicks"] for d in body if d["clicks"] >= 20]
    m_cpc, d_cpc = med(cpcs), mad(cpcs)
    ctrs = [d["clicks"] / d["imps"] for d in body if d["imps"] > 0]
    m_ctr = med(ctrs)
    m_imps = med([d["imps"] for d in body])
    m_clicks = med([d["clicks"] for d in body])
    conv_per_day = conv_total / len(body) if body else 0

    def add(day, code, title, detail, weight, cost=None, days=1):
        """cost — расход, к которому относится находка. Для однодневных правил это расход дня,
        для полос и сдвигов уровня — сумма за days дней. Потребитель обязан различать: подпись
        «расход дня» на семидневной сумме — ложь в отчёте."""
        out.append(dict(date=day["date"], scope=scope, code=code, title=title, detail=detail,
                        cost=round(day["cost"] if cost is None else cost, 2), days=days,
                        conv=day["conv"], weight=round(weight, 1)))

    def flush_streak(streak):
        """Полоса нулей — находка, только если за неё ожидались хотя бы три конверсии.

        Кампания с 0,3 конверсии в день сутками стоит без конверсий по своей природе:
        семь пустых дней там — обычное течение, а не поломка учёта. Порог в три
        ожидаемые конверсии отсекает именно такие ряды: при пуассоновском потоке
        вероятность увидеть ноль при ожидании трёх — около 5%.
        """
        if len(streak) < 2:
            return
        expected = len(streak) * conv_per_day
        if expected < 3:
            return
        add(streak[-1], "F", "обрыв конверсий",
            f"{len(streak)} дня(ей) подряд без конверсий "
            f"({streak[0]['date']} — {streak[-1]['date']}) при обычном трафике; "
            f"ожидалось около {expected:.0f} — проверить счётчик и цели",
            sum(d["cost"] for d in streak))

    zero_streak = []
    for day in body:
        z = rz(day["cost"], m_cost, d_cost)
        if z >= Z and day["cost"] >= m_cost * 1.5 and day["cost"] >= 1000:
            add(day, "A", "всплеск расхода",
                f"{day['cost']:,.0f} ₽ против обычных {m_cost:,.0f} ₽ "
                f"(×{day['cost']/m_cost:.1f})".replace(",", " "), day["cost"] - m_cost)
        if day["cost"] == 0 and m_cost >= 300:
            add(day, "C", "нулевой день", f"обычно {m_cost:,.0f} ₽ в день".replace(",", " "),
                m_cost)
        elif day["cost"] <= m_cost * 0.25 and m_cost >= 500:
            add(day, "B", "обвал расхода",
                f"{day['cost']:,.0f} ₽ против обычных {m_cost:,.0f} ₽".replace(",", " "),
                m_cost - day["cost"])
        if m_cpa and day["conv"] >= 3:
            cpa = day["cost"] / day["conv"]
            if cpa >= m_cpa * 2:
                add(day, "D", "дорогой день по CPA",
                    f"CPA {cpa:,.0f} ₽ против обычных {m_cpa:,.0f} ₽ "
                    f"при {day['conv']:.0f} конверсиях".replace(",", " "),
                    day["cost"] - day["conv"] * m_cpa)
        if m_cpa and day["conv"] == 0 and day["cost"] >= m_cpa * 3:
            add(day, "E", "пустой день",
                f"{day['cost']:,.0f} ₽ без единой конверсии при обычном CPA "
                f"{m_cpa:,.0f} ₽".replace(",", " "), day["cost"])
        if day["clicks"] >= 20 and m_cpc:
            cpc = day["cost"] / day["clicks"]
            if rz(cpc, m_cpc, d_cpc) >= Z:
                add(day, "G", "скачок цены клика",
                    f"{cpc:,.0f} ₽ против обычных {m_cpc:,.0f} ₽".replace(",", " "),
                    (cpc - m_cpc) * day["clicks"])
        if m_ctr and day["imps"] >= m_imps * 0.7 and day["imps"] > 0:
            ctr = day["clicks"] / day["imps"]
            if ctr <= m_ctr * 0.5:
                add(day, "H", "провал CTR",
                    f"{ctr*100:.2f}% против обычных {m_ctr*100:.2f}% "
                    f"при {day['imps']:,.0f} показах".replace(",", " "), day["cost"])
        if day["imps"] >= m_imps * 2 and day["clicks"] <= m_clicks * 0.3:
            add(day, "I", "показы без кликов",
                f"{day['imps']:,.0f} показов и всего {day['clicks']:.0f} кликов".replace(",", " "),
                day["cost"])
        # F — обрыв конверсий: копим полосу нулевых дней при живых кликах
        if day["conv"] == 0 and day["clicks"] >= m_clicks * 0.7 and m_cpa:
            zero_streak.append(day)
        else:
            flush_streak(zero_streak)
            zero_streak = []
    flush_streak(zero_streak)


    # J — сдвиг уровня: последняя неделя против предыдущих трёх
    if len(body) >= 28:
        last, prev = body[-7:], body[-28:-7]
        lm, pm = med([d["cost"] for d in last]), med([d["cost"] for d in prev])
        if pm > 0 and abs(lm - pm) / pm >= 0.4:
            out.append(dict(date=last[0]["date"], scope=scope, code="J", title="сдвиг уровня",
                            detail=f"расход последней недели {lm:,.0f} ₽/день против "
                                   f"{pm:,.0f} ₽ ранее — искать правку в журнале изменений"
                                   .replace(",", " "),
                            cost=round(sum(d['cost'] for d in last), 2), days=len(last), conv=0,
                            weight=abs(lm - pm) * 7))
    return out


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--reports", required=True, help="каталог от fetch.py")
    a.add_argument("--out", default="anomalies.json")
    a.add_argument("--per-campaign", action="store_true", default=True)
    args = a.parse_args()

    found, checked = [], []
    days_path = os.path.join(args.reports, "days.tsv")
    if os.path.exists(days_path):
        s = series(tsv(days_path), "аккаунт")
        checked.append(("аккаунт", len(s)))
        found += check(s, "аккаунт")

    camp_path = os.path.join(args.reports, "campdays.tsv")
    if os.path.exists(camp_path):
        rows = tsv(camp_path)
        by_camp = defaultdict(list)
        for r in rows:
            by_camp[r.get("CampaignName", "—")].append(r)
        for name, rs in by_camp.items():
            s = series(rs, name)
            checked.append((name, len(s)))
            found += check(s, name)

    found.sort(key=lambda f: -f["weight"])
    json.dump(dict(anomalies=found, checked=[{"scope": s, "days": d} for s, d in checked],
                   tail_days=TAIL_DAYS),
              open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"проверено рядов: {len(checked)}, аномалий: {len(found)}", file=sys.stderr)
    for f in found[:15]:
        print(f"  {f['date']} · {f['scope'][:22]:24} {f['code']} {f['title']}: {f['detail']}",
              file=sys.stderr)
    print(args.out)


if __name__ == "__main__":
    main()
