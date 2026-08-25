#!/usr/bin/env python3
"""Кандидаты на запрет среди площадок РСЯ.

Вход — TSV-отчёт по площадкам (Мастер отчётов или Reports API) с колонками
Placement, Clicks, Cost, Conversions и по возможности Impressions, BounceRate, AvgPageviews.

    python3 placements.py placements.tsv --target-cpa 500

Логика порогов — audit/yan-placements.md. Скрипт ничего не применяет: он печатает
список на одобрение и считает, сколько денег освобождает.
"""
import argparse, csv, sys


def num(v):
    if v in (None, "", "--"):
        return 0.0
    return float(str(v).replace("\xa0", "").replace(" ", "").replace("%", "").replace(",", "."))


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


def load(path):
    lines = open(path, encoding="utf-8-sig").read().splitlines()
    hdr = next((i for i, l in enumerate(lines)
                if "Placement" in l or "лощадк" in l), None)
    if hdr is None:
        sys.exit("не нашёл строку заголовков с колонкой площадки")
    return _norm_conv(list(csv.DictReader(lines[hdr:], delimiter="\t")))


def col(row, *names):
    for n in names:
        for k in row:
            if k.strip().lower() == n.lower():
                return row[k]
    return ""


def main():
    a = argparse.ArgumentParser()
    a.add_argument("report")
    a.add_argument("--target-cpa", type=float, default=None,
                   help="целевой CPA; без него второй критерий не применяется")
    a.add_argument("--cr", type=float, default=None,
                   help="ожидаемый CR в долях (0.02); по умолчанию считается по отчёту")
    a.add_argument("--limit", type=int, default=1000, help="лимит запрещённых площадок")
    args = a.parse_args()

    rows = load(args.report)
    for r in rows:
        r["_name"] = col(r, "Placement", "Название площадки").strip()
        r["_clicks"] = num(col(r, "Clicks", "Клики"))
        r["_cost"] = num(col(r, "Cost", "Расход", "Расход (руб.)"))
        r["_conv"] = num(col(r, "Conversions", "Конверсии"))
        r["_bounce"] = num(col(r, "BounceRate", "Отказы (%)"))
        r["_depth"] = num(col(r, "AvgPageviews", "Глубина просмотра"))
    rows = [r for r in rows if r["_name"]]

    clicks = sum(r["_clicks"] for r in rows)
    cost = sum(r["_cost"] for r in rows)
    conv = sum(r["_conv"] for r in rows)
    cr = args.cr if args.cr else (conv / clicks if clicks else 0)
    cpa = args.target_cpa or (cost / conv if conv else 0)
    min_clicks = (3 / cr) if cr else float("inf")

    print(f"Площадок {len(rows)} · клики {clicks:,.0f} · расход {cost:,.0f} · конверсии {conv:,.0f}")
    print(f"CR в сетях {cr*100:.2f}% · CPA {cpa:,.0f} · порог значимости {min_clicks:,.0f} кликов\n")

    cand = []
    for r in rows:
        if r["_conv"] > 0:
            if cpa and r["_cost"] / r["_conv"] >= 3 * cpa and r["_clicks"] >= min_clicks:
                cand.append((r, "CPA втрое выше целевого при значимом объёме"))
            continue
        if r["_clicks"] >= min_clicks:
            cand.append((r, "порог значимости пройден, конверсий нет"))
        elif cpa and r["_cost"] >= 2 * cpa:
            cand.append((r, "расход ≥ 2 целевых CPA без конверсий"))

    cand.sort(key=lambda x: -x[0]["_cost"])
    freed = sum(r["_cost"] for r, _ in cand)
    print(f"Кандидатов {len(cand)} · освобождается {freed:,.0f} ({freed/cost*100:.1f}% расхода)")
    if len(cand) > args.limit:
        print(f"ВНИМАНИЕ: кандидатов больше лимита {args.limit} — берём верх списка по расходу")
    print()
    print(f"{'Площадка':<40}{'Клики':>8}{'Расход':>12}{'Конв':>7}{'Отказы':>9}  Причина")
    for r, why in cand[:args.limit]:
        print(f"{r['_name'][:39]:<40}{r['_clicks']:>8.0f}{r['_cost']:>12,.0f}"
              f"{r['_conv']:>7.0f}{r['_bounce']:>8.0f}%  {why}")

    weak = [r for r in rows if r["_conv"] == 0 and r["_clicks"] < min_clicks]
    print(f"\nНиже порога (не трогаем): {len(weak)} площадок, "
          f"{sum(r['_cost'] for r in weak):,.0f} ({sum(r['_cost'] for r in weak)/cost*100:.1f}% расхода)")
    print("Это хвост. Банить его нельзя: данных на площадку не хватает даже на один вывод.")


if __name__ == "__main__":
    main()
