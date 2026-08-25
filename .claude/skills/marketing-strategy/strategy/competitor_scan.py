#!/usr/bin/env python3
"""Разбор сайтов конкурентов фактами: цены, доказательства, штампы, спрос на бренд.

    set -a && . ./.env && set +a
    python3 competitor_scan.py --file competitors.txt --geo 213 --out competitors.json

`competitors.txt` — по строке на конкурента: `Название|https://site.ru`.

Что делает:
  · обходит сайт тем же способом, что site_scan.py (последовательно, с паузой, браузерный UA);
  · вытаскивает цены, телефоны, формы, числовые доказательства («16 лет», «640 объектов»);
  · помечает обещания-штампы по словарю — кандидатов в «довески» при разборе УТП;
  · проверяет через API Директа, ищут ли бренд конкурента в регионе.

Наблюдения о рекламе конкурентов скрипт не делает: данных о чужих кампаниях в API нет,
это заполняется глазами и помечается как наблюдение с датой.
"""
import argparse, html, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import date

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
PRICE = re.compile(r"(\d[\d\s  ]{2,12})\s*(?:₽|руб\.?|р\.)", re.I)
PER_UNIT = re.compile(r"(?:от\s*)?(\d[\d\s  ]{2,9})\s*(?:₽|руб\.?|р\.)\s*"
                      r"(?:/|за|в)?\s*(м2|м²|кв\.?\s?м|квадратный метр|мес|месяц|шт)", re.I)
# страница-заглушка антибота: считать её «сайт не проверен», а не «цен нет»
ANTIBOT = re.compile(r"(проверяем,?\s*человек\s*ли\s*вы|подтвердите,?\s*что\s*вы\s*не\s*робот|"
                     r"just a moment|checking your browser|доступ ограничен|captcha)", re.I)
PHONE = re.compile(r"\+?7[\s(\-]*\d{3}[\s)\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
# «16 лет», «640 объектов» — доказательства. Числа рядом с ₽ и четырёхзначные «проекты»
# почти всегда цены или артикулы, поэтому диапазон узкий и деньги отсекаются отдельно.
PROOF = re.compile(r"(?<![\d₽])(\d{1,4})\s+(лет|года|год|объектов|объекта|домов|дома|"
                   r"клиентов|проектов|отзывов|кейсов|филиалов|сотрудников)\b", re.I)
CLICHE = [
    "индивидуальный подход", "высокое качество", "гибкая система скидок", "широкий ассортимент",
    "команда профессионалов", "лучшие цены", "выгодные условия", "работаем на результат",
    "качественно и в срок", "надёжный партнёр", "надежный партнер", "european quality",
    "европейское качество", "любой сложности", "под ваши задачи", "воплотим ваши мечты",
]
SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".mp4", ".webp", ".ico")


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "ru"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(2_000_000)
        return r.geturl(), raw.decode(r.headers.get_content_charset() or "utf-8", "replace")


def text_of(doc):
    t = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", doc, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def links(doc, base, host, limit=6):
    out = []
    for href in re.findall(r'href="([^"]+)"', doc):
        u = urllib.parse.urljoin(base, href.split("#")[0])
        p = urllib.parse.urlsplit(u)
        if p.netloc == host and not p.path.lower().endswith(SKIP_EXT):
            clean = urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, "", ""))
            if clean not in out:
                out.append(clean)
    return out[:limit]


def money(v):
    v = int(re.sub(r"\D", "", v))
    return v if 1000 <= v <= 100_000_000 else None


def brand_demand(names, geo):
    """Ищут ли бренд конкурента — дешёвый признак известности."""
    token, login = os.environ.get("DIRECT_TOKEN"), os.environ.get("DIRECT_LOGIN")
    if not token or not login:
        return {}
    body = json.dumps({"method": "hasSearchVolume", "params": {
        "SelectionCriteria": {"Keywords": names, "RegionIds": geo},
        "FieldNames": ["Keyword", "AllDevices"]}}, ensure_ascii=False).encode()
    req = urllib.request.Request("https://api.direct.yandex.com/json/v5/keywordsresearch",
                                 data=body, headers={
        "Authorization": f"Bearer {token}", "Client-Login": login, "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
        return {x["Keyword"]: x.get("AllDevices") == "YES"
                for x in data["result"]["HasSearchVolumeResults"]}
    except Exception as e:
        print(f"проверка брендов не удалась: {e}", file=sys.stderr)
        return {}


def scan(name, url, pages=5, delay=0.5):
    host = urllib.parse.urlsplit(url).netloc
    errors = []
    seen, texts, prices, units, phones, proofs, forms = [], [], set(), set(), set(), set(), False
    title = desc = ""
    queue = [url]
    while queue and len(seen) < pages:
        u = queue.pop(0)
        if u in seen:
            continue
        try:
            final, doc = get(u)
        except Exception as e:
            print(f"  × {u} — {type(e).__name__}", file=sys.stderr)
            errors.append(f"{u}: {type(e).__name__}")
            seen.append(u)
            continue
        seen.append(u)
        if not title:
            title = re.sub(r"\s+", " ", html.unescape(
                (re.search(r"<title[^>]*>(.*?)</title>", doc, re.S | re.I) or [None, ""])[1])).strip()
            desc = re.sub(r"\s+", " ", html.unescape(
                (re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', doc, re.I)
                 or [None, ""])[1])).strip()
        t = text_of(doc)
        texts.append(t)
        forms = forms or bool(re.search(r"<form|Отправить|Оставить заявку", doc, re.I))
        for p in PRICE.findall(t):
            v = money(p)
            if v:
                prices.add(v)
        for v, unit in PER_UNIT.findall(t):
            m = money(v)
            if m:
                units.add(f"{m:,} ₽/{unit}".replace(",", " "))
        phones |= set(PHONE.findall(t))
        for num, word in PROOF.findall(t):
            n = int(num)
            if 1 < n <= 3000:                     # больше — обычно цена или артикул
                proofs.add(f"{n} {word.lower()}")
        for link in links(doc, final, host):
            if link not in seen and link not in queue:
                queue.append(link)
        time.sleep(delay)

    joined = " ".join(texts).lower()
    blocked = bool(texts) and bool(ANTIBOT.search(" ".join(texts)[:4000]))
    return dict(name=name, url=url, title=title, description=desc,
                pages_scanned=len(seen),
                prices=sorted(prices)[:12], unit_prices=sorted(units)[:6],
                has_prices=bool(prices or units),
                phones=sorted(phones)[:3], has_form=forms,
                proofs=sorted(proofs, key=lambda s: -int(s.split()[0]))[:8],
                cliches=[c for c in CLICHE if c in joined],
                errors=errors,
                # сайт не открылся или отдал пустоту — это «не проверено», а не «нет цен»
                status=("не открылся" if len(errors) == len(seen)
                        else "закрыт защитой" if blocked else "проверен"),
                checked=date.today().isoformat())


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--file", required=True, help="строки вида «Название|https://site.ru»")
    a.add_argument("--geo", required=True)
    a.add_argument("--out", default="competitors.json")
    a.add_argument("--pages", type=int, default=5, help="страниц на сайт")
    args = a.parse_args()

    items = []
    for line in open(args.file, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            name, url = (line.split("|", 1) + [""])[:2]
            items.append((name.strip(), url.strip()))

    out = []
    for name, url in items:
        print(f"· {name} — {url}", file=sys.stderr)
        out.append(scan(name, url, pages=args.pages))

    geo = [int(x) for x in args.geo.split(",")]
    demand = brand_demand([c["name"].lower() for c in out], geo)
    for c in out:
        c["brand_searched"] = demand.get(c["name"].lower())

    allp = sorted({p for c in out for p in c["prices"]})
    result = dict(geo=geo, checked=date.today().isoformat(), competitors=out,
                  price_range=dict(min=allp[0], max=allp[-1],
                                   median=allp[len(allp) // 2]) if allp else None,
                  note="Реклама конкурентов в API Директа не видна: строки матрицы про каналы "
                       "заполняются наблюдением и помечаются датой.")
    json.dump(result, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\n{'конкурент':28}{'цены':>6}{'штампы':>8}{'бренд ищут':>12}  доказательства",
          file=sys.stderr)
    for c in out:
        prices = "?" if c["status"] != "проверен" else ("да" if c["has_prices"] else "нет")
        print(f"{c['name'][:27]:28}{prices:>6}"
              f"{len(c['cliches']):>8}"
              f"{('да' if c['brand_searched'] else 'нет' if c['brand_searched'] is not None else '?'):>12}"
              f"  {', '.join(c['proofs'][:3])}", file=sys.stderr)
    print(args.out)


if __name__ == "__main__":
    main()
