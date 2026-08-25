#!/usr/bin/env python3
"""Проверка объявлений на лимиты и правила модерации до загрузки.

    python3 adtext_check.py campaign.json

Лимиты — docs/moderation/technical-restrictions.md, требования к тексту —
docs/moderation/ad-rules.md. Скрипт не оценивает смысл: он ловит то, из-за чего
файл не загрузится или объявление отклонят.
"""
import argparse, json, re, sys
from collections import Counter

LIMITS = dict(title=56, title_word=22, text=81, text_word=23,
              sitelink_title=30, callout=25, display_path=20)
CONTACT = re.compile(r"(\+?7[\s(\-]?\d{3}|@[a-z0-9.\-]+\.[a-z]{2,}|www\.|https?://)", re.I)
SUPERLATIVE = re.compile(r"\b(лучш|самый|самая|самые|№\s?1|номер один|первый на рынке|"
                         r"дешевле всех|единственн)", re.I)


def long_word(s, limit):
    return [w for w in re.split(r"[\s\-—/]+", s) if len(w) > limit]


def check_ad(ad, where):
    out = []

    def bad(msg, sev="ошибка"):
        out.append(dict(where=where, severity=sev, message=msg))

    for i, t in enumerate(ad.get("titles", []), 1):
        if len(t) > LIMITS["title"]:
            bad(f"заголовок {i}: {len(t)} символов при лимите {LIMITS['title']} — «{t}»")
        for w in long_word(t, LIMITS["title_word"]):
            bad(f"заголовок {i}: слово «{w}» длиннее {LIMITS['title_word']} символов")
        if t.isupper():
            bad(f"заголовок {i}: набран капсом — модерация отклонит")
        if "!" in t:
            bad(f"заголовок {i}: восклицательный знак в заголовке", "предупреждение")
        if SUPERLATIVE.search(t):
            bad(f"заголовок {i}: превосходная степень без подтверждения — «{t}»",
                "предупреждение")
    for i, t in enumerate(ad.get("texts", []), 1):
        if len(t) > LIMITS["text"]:
            bad(f"текст {i}: {len(t)} символов при лимите {LIMITS['text']} — «{t}»")
        for w in long_word(t, LIMITS["text_word"]):
            bad(f"текст {i}: слово «{w}» длиннее {LIMITS['text_word']} символов")
        if CONTACT.search(t):
            bad(f"текст {i}: контакты в тексте объявления запрещены — «{t}»")
        if SUPERLATIVE.search(t):
            bad(f"текст {i}: превосходная степень без подтверждения", "предупреждение")
    if not ad.get("titles"):
        bad("нет ни одного заголовка")
    if not ad.get("texts"):
        bad("нет ни одного текста")
    if not (ad.get("href") or "").startswith("http"):
        bad(f"ссылка без протокола или пустая: {ad.get('href')!r}")
    dup = [t for t, n in Counter(ad.get("titles", [])).items() if n > 1]
    if dup:
        bad(f"повторяющиеся заголовки: {', '.join(dup)}", "предупреждение")
    for s in ad.get("sitelinks", []):
        if len(s.get("title", "")) > LIMITS["sitelink_title"]:
            bad(f"быстрая ссылка «{s['title']}»: длиннее {LIMITS['sitelink_title']}")
    for c in ad.get("callouts", []):
        if len(c) > LIMITS["callout"]:
            bad(f"уточнение «{c}»: длиннее {LIMITS['callout']}")
    return out


def main():
    a = argparse.ArgumentParser()
    a.add_argument("plan")
    args = a.parse_args()
    plan = json.load(open(args.plan, encoding="utf-8"))

    problems, ads, groups = [], 0, 0
    for camp in plan["campaigns"]:
        for g in camp["groups"]:
            groups += 1
            if len(g.get("keywords", [])) > 200:
                problems.append(dict(where=f"{camp['name']} / {g['name']}", severity="ошибка",
                                     message=f"фраз в группе {len(g['keywords'])} при лимите 200"))
            for kw in g.get("keywords", []):
                if len(re.findall(r"\w+", kw)) > 7:
                    problems.append(dict(where=f"{camp['name']} / {g['name']}",
                                         severity="ошибка",
                                         message=f"фраза длиннее 7 слов: «{kw}»"))
            for ad in g.get("ads", []):
                ads += 1
                problems += check_ad(ad, f"{camp['name']} / {g['name']}")

    errors = [p for p in problems if p["severity"] == "ошибка"]
    warns = [p for p in problems if p["severity"] != "ошибка"]
    print(f"кампаний {len(plan['campaigns'])} · групп {groups} · объявлений {ads}")
    print(f"ошибок {len(errors)} · предупреждений {len(warns)}\n")
    for p in errors + warns:
        mark = "✗" if p["severity"] == "ошибка" else "!"
        print(f"{mark} [{p['where']}] {p['message']}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
