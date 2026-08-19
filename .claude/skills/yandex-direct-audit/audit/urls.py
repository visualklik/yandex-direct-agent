#!/usr/bin/env python3
"""Проверка посадочных страниц: доступность ссылок объявлений и быстрых ссылок.

    python3 urls.py --snapshot snapshot.json --out urls.json

Что делает: собирает уникальные адреса из объявлений и наборов быстрых ссылок,
дёргает каждый по одному разу и записывает код ответа, цепочку редиректов и признаки
подмены страницы. Ничего не меняет ни в аккаунте, ни на сайте.

Вежливость к чужому сайту обязательна: запросы строго последовательные, с паузой и
браузерным User-Agent. Параллельные пачки ловят 403 от защиты и портят замер.
"""
import argparse, json, re, ssl, sys, time, urllib.error, urllib.parse, urllib.request
from collections import defaultdict

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
MACRO = re.compile(r"\{[^}]*\}")            # {campaign_id}, {ad_id} и прочие подстановки Директа
SOFT404 = re.compile(r"(страница не найдена|page not found|404 not found|ничего не найдено)", re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def clean(url, keep_query=False):
    """Убрать макросы Директа; по умолчанию — и служебный query, мешающий сравнению."""
    url = MACRO.sub("", url).strip()
    p = urllib.parse.urlsplit(url)
    if not keep_query:
        p = p._replace(query="")
    return urllib.parse.urlunsplit(p)


def collect(snap, keep_query=False):
    """{нормализованный url: [(источник, объект)]} — чтобы в отчёте было видно, где чинить."""
    live_sets = {(ad.get("ResponsiveAd") or ad.get("TextAd") or {}).get("SitelinkSetId")
                 for ad in snap.get("ads", []) if ad.get("State") == "ON"}
    where = defaultdict(list)
    for ad in snap.get("ads", []):
        body = ad.get("ResponsiveAd") or ad.get("TextAd") or {}
        href = body.get("Href")
        if href:
            where[clean(href, keep_query)].append(
                ("объявление", ad["Id"], ad.get("State") == "ON"))
    for s in snap.get("sitelinks", []):
        for sl in s.get("Sitelinks", []):
            if sl.get("Href"):
                where[clean(sl["Href"], keep_query)].append(
                    (f"быстрая ссылка «{sl.get('Title', '')}»", s["Id"], s["Id"] in live_sets))
    return where


def fetch(url, timeout=12, max_hops=6):
    """Ручной обход редиректов: нужна вся цепочка, а не только конечный ответ."""
    ctx = ssl.create_default_context()
    chain, cur = [], url
    for _ in range(max_hops):
        req = urllib.request.Request(cur, method="GET", headers={
            "User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "ru"})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                body = r.read(60000).decode(r.headers.get_content_charset() or "utf-8", "replace")
                return dict(status=r.status, final=cur, chain=chain, body=body, error=None)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                nxt = urllib.parse.urljoin(cur, e.headers["Location"])
                chain.append((cur, e.code))
                cur = nxt
                continue
            return dict(status=e.code, final=cur, chain=chain, body="", error=None)
        except Exception as e:                      # таймаут, DNS, TLS
            return dict(status=None, final=cur, chain=chain, body="",
                        error=type(e).__name__ + ": " + str(e)[:120])
    return dict(status=None, final=cur, chain=chain, body="", error="слишком много редиректов")


def verdict(url, res):
    """Строка проблемы или None. Порядок важен: сначала жёсткие ошибки."""
    if res["error"]:
        return "недоступна", res["error"]
    st = res["status"]
    if st in (404, 410):
        return "битая", f"HTTP {st}"
    if st and st >= 500:
        return "ошибка сервера", f"HTTP {st}"
    if st and st >= 400:
        return "отказ", f"HTTP {st}"
    src_path = urllib.parse.urlsplit(url).path.rstrip("/")
    dst = urllib.parse.urlsplit(res["final"])
    if res["chain"]:
        if src_path and dst.path.rstrip("/") in ("", "/") :
            return "редирект на главную", f"{len(res['chain'])} переход(ов) → {res['final']}"
        if urllib.parse.urlsplit(url).netloc != dst.netloc:
            return "редирект на другой домен", res["final"]
    title = (TITLE.search(res["body"]) or [None, ""])[1].strip()[:120]
    if SOFT404.search(title) or SOFT404.search(res["body"][:4000]):
        return "мягкая 404", f"страница отдаёт 200, но выглядит как «не найдено»: {title}"
    return None, f"HTTP {st}" + (f" после {len(res['chain'])} редиректов" if res["chain"] else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out", default="urls.json")
    ap.add_argument("--delay", type=float, default=0.4, help="пауза между запросами, секунды")
    ap.add_argument("--keep-query", action="store_true",
                    help="проверять адреса вместе с UTM (по умолчанию query отбрасывается)")
    a = ap.parse_args()

    snap = json.load(open(a.snapshot, encoding="utf-8"))
    where = collect(snap, a.keep_query)
    print(f"уникальных адресов: {len(where)}", file=sys.stderr)

    out = []
    for i, (url, refs) in enumerate(sorted(where.items()), 1):
        res = fetch(url)
        kind, detail = verdict(url, res)
        out.append(dict(url=url, status=res["status"], final=res["final"],
                        redirects=len(res["chain"]), problem=kind, detail=detail,
                        used_by=[f"{s} {i}" for s, i, _ in refs[:5]], used_count=len(refs),
                        active_count=sum(1 for *_, live in refs if live)))
        mark = "!" if kind else "·"
        print(f"{mark} [{i}/{len(where)}] {res['status'] or '—'} {url[:70]} {kind or ''}",
              file=sys.stderr)
        time.sleep(a.delay)

    bad = [r for r in out if r["problem"]]
    json.dump(dict(checked=len(out), problems=len(bad), items=out),
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nпроверено {len(out)}, с проблемами {len(bad)}", file=sys.stderr)
    for r in bad:
        state = (f"в показах: {r['active_count']}" if r["active_count"]
                 else "только в остановленных объектах")
        print(f"  {r['problem']}: {r['url']} — {r['detail']} "
              f"(объектов: {r['used_count']}, {state})", file=sys.stderr)
    print(a.out)


if __name__ == "__main__":
    main()
