#!/usr/bin/env python3
"""Разбор сайта под сборку кампании: страницы, офферы, цены, аргументы.

    python3 site_scan.py https://site.ru --out site.json [--max-pages 40]

Обходит сайт по внутренним ссылкам (или по sitemap.xml, если есть), с каждой страницы
снимает то, из чего потом пишутся объявления: заголовок, описание, заголовки блоков,
цены, телефоны, формы, видимый текст.

Вежливость к чужому сайту обязательна: запросы последовательные, с паузой и браузерным
User-Agent. Параллельные пачки ловят 403 и портят разбор.
"""
import argparse, html, json, re, sys, time, urllib.error, urllib.parse, urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
PRICE = re.compile(r"(\d[\d\s  ]{2,12})\s*(?:₽|руб\.?|р\.)", re.I)
PHONE = re.compile(r"\+?7[\s(\-]*\d{3}[\s)\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".mp4", ".webp", ".ico")


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "ru"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(3_000_000)
        enc = r.headers.get_content_charset() or "utf-8"
        return r.geturl(), raw.decode(enc, "replace")


def visible_text(doc):
    t = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", doc, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def tag_texts(doc, tags):
    out = []
    for tag in tags:
        for m in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", doc, re.S | re.I):
            s = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m))).strip()
            if 2 < len(s) < 200:
                out.append(s)
    return out


def links(doc, base, host):
    out = set()
    for href in re.findall(r'href="([^"]+)"', doc):
        u = urllib.parse.urljoin(base, href.split("#")[0])
        p = urllib.parse.urlsplit(u)
        if p.netloc != host or p.path.lower().endswith(SKIP_EXT):
            continue
        out.add(urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, "", "")))
    return out


def sitemap_urls(root, host):
    """sitemap.xml даёт карту сайта дешевле обхода — если он есть."""
    try:
        _, xml = get(urllib.parse.urljoin(root, "/sitemap.xml"))
    except Exception:
        return set()
    return {u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
            if urllib.parse.urlsplit(u).netloc == host
            and not u.lower().endswith(SKIP_EXT)}


def parse(url, doc):
    text = visible_text(doc)
    title = (re.search(r"<title[^>]*>(.*?)</title>", doc, re.S | re.I) or [None, ""])[1]
    desc = (re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', doc, re.I)
            or [None, ""])[1]
    prices = []
    for p in PRICE.findall(text):
        v = re.sub(r"\D", "", p)
        if v and 1000 <= int(v) <= 100_000_000:
            prices.append(int(v))
    return dict(
        url=url,
        title=re.sub(r"\s+", " ", html.unescape(title)).strip(),
        description=re.sub(r"\s+", " ", html.unescape(desc)).strip(),
        headings=tag_texts(doc, ("h1", "h2", "h3"))[:30],
        # у конструкторов вроде Тильды заголовки часто не в h1–h3, а в div с классом
        block_titles=[s for s in tag_texts(doc, ("strong", "b"))[:40] if len(s) > 8][:20],
        prices=sorted(set(prices))[:20],
        phones=sorted(set(PHONE.findall(text)))[:5],
        has_form=bool(re.search(r"<form|tilda-form|Отправить", doc, re.I)),
        text_len=len(text),
        text=text[:6000],
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default="site.json")
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--delay", type=float, default=0.5)
    a = ap.parse_args()

    root = a.url if a.url.startswith("http") else "https://" + a.url
    host = urllib.parse.urlsplit(root).netloc
    queue, seen, pages = [root], set(), []

    for u in sorted(sitemap_urls(root, host)):
        if u not in queue:
            queue.append(u)

    while queue and len(pages) < a.max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            final, doc = get(url)
        except Exception as e:
            print(f"× {url} — {type(e).__name__}", file=sys.stderr)
            continue
        page = parse(final, doc)
        pages.append(page)
        print(f"· {len(pages):3} {final} — {page['text_len']} симв., "
              f"цен {len(page['prices'])}", file=sys.stderr)
        for link in sorted(links(doc, final, host)):
            if link not in seen and link not in queue:
                queue.append(link)
        time.sleep(a.delay)

    site = dict(root=root, host=host, pages=pages,
                prices=sorted({p for pg in pages for p in pg["prices"]}),
                phones=sorted({t for pg in pages for t in pg["phones"]}))
    json.dump(site, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nстраниц: {len(pages)}, цен найдено: {len(site['prices'])}", file=sys.stderr)
    print(a.out)


if __name__ == "__main__":
    main()
