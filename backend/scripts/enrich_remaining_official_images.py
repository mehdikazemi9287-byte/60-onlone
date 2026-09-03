#!/usr/bin/env python3
"""Resolve missing catalogue images from exact pages on the row's official domain.

The script follows same-domain product links and sitemaps, reads og:image,
JSON-LD Product.image and labelled img tags, and leaves ambiguous rows blank.
No third-party search engine or unrelated stock image is used.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import ssl
import sys
import time
import unicodedata
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (compatible; 60OnlineOfficialImageBot/2.0; +https://60online.ir)"
GENERIC = {"محصول", "خرید", "فروش", "بسته", "بندی", "تواضع", "میهن", "پویا", "پروتئین", "هایزم"}
ALIASES = {
    "شیر": {"milk", "sterilized", "uht"}, "ماست": {"yogurt", "yoghurt"},
    "پنیر": {"cheese"}, "خامه": {"cream"}, "کره": {"butter"},
    "دوغ": {"doogh", "ayran"}, "بستنی": {"icecream", "ice", "cream"},
    "آبمیوه": {"juice", "fruit"}, "گوساله": {"beef", "veal"},
    "گوسفندی": {"lamb", "mutton"}, "مرغ": {"chicken", "poultry"},
    "ماهی": {"fish", "seafood"}, "سوسیس": {"sausage"},
    "کالباس": {"coldcuts", "cold", "cuts", "salami"},
    "همبرگر": {"burger", "hamburger"}, "تخمه": {"seed", "seeds"},
    "کدو": {"pumpkin"}, "قره": {"ghare", "qare"},
}


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(value or "")).lower()
    value = value.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    return " ".join(re.findall(r"[a-z0-9\w\u0600-\u06ff]+", value))


def tokens(value: str) -> set[str]:
    base = {t for t in norm(value).split() if len(t) > 1 and t not in GENERIC}
    expanded = set(base)
    for token in base:
        expanded.update(ALIASES.get(token, set()))
    return expanded


def fetch(url: str, timeout: int) -> tuple[str, str]:
    req = Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "fa,en;q=0.8",
    })
    with urlopen(req, timeout=timeout, context=ssl.create_default_context()) as response:
        raw = response.read(5_000_000)
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace"), response.geturl()


def attrs(tag: str) -> dict[str, str]:
    return {k.lower(): html.unescape(v) for k, _, v in
            re.findall(r"([\w:-]+)\s*=\s*(['\"])(.*?)\2", tag, re.I | re.S)}


def strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def same_domain(url: str, base: str) -> bool:
    a, b = urlparse(url).netloc.lower(), urlparse(base).netloc.lower()
    return a.removeprefix("www.") == b.removeprefix("www.")


def valid_http(url: str) -> bool:
    p = urlparse(url)
    return p.scheme in {"http", "https"} and not re.search(
        r"\.(?:pdf|zip|rar|mp4|mp3|svg|woff2?|ttf|css|js)(?:$|\?)", p.path, re.I)


def links(page: str, base_url: str) -> list[tuple[str, str]]:
    out = []
    for opening, body in re.findall(r"(<a\b[^>]*>)(.*?)</a\s*>", page, re.I | re.S):
        a = attrs(opening)
        href = a.get("href")
        if not href:
            continue
        url = urldefrag(urljoin(base_url, href))[0]
        if valid_http(url) and same_domain(url, base_url):
            out.append((url, strip_tags(body) + " " + a.get("title", "")))
    return out


def sitemap_urls(page: str, base_url: str) -> list[str]:
    return [urldefrag(urljoin(base_url, html.unescape(x)))[0] for x in
            re.findall(r"<loc>\s*(.*?)\s*</loc>", page, re.I | re.S)]


def image_candidates(page: str, base_url: str) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
        a = attrs(tag)
        key = (a.get("property") or a.get("name") or "").lower()
        if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"} and a.get("content"):
            out.append((urljoin(base_url, a["content"]), "page_meta", ""))
    for block in re.findall(r"<script\b[^>]*type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", page, re.I | re.S):
        try:
            data = json.loads(html.unescape(block).strip())
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                stack.extend(node.values())
                image = node.get("image")
                label = str(node.get("name") or "")
                if image:
                    values = image if isinstance(image, list) else [image]
                    for value in values:
                        if isinstance(value, dict):
                            value = value.get("url") or value.get("contentUrl")
                        if isinstance(value, str):
                            out.append((urljoin(base_url, value), "jsonld", label))
    for tag in re.findall(r"<img\b[^>]*>", page, re.I):
        a = attrs(tag)
        src = a.get("data-src") or a.get("data-original") or a.get("data-lazy-src") or a.get("src")
        if not src or src.startswith("data:"):
            continue
        out.append((urljoin(base_url, src), "labelled_img", " ".join(filter(None, [a.get("alt"), a.get("title")]))) )
    seen, unique = set(), []
    for value in out:
        if value[0] not in seen and valid_http(value[0]):
            seen.add(value[0]); unique.append(value)
    return unique


def overlap_score(name_tokens: set[str], text: str) -> float:
    got = tokens(text)
    if not name_tokens or not got:
        return 0.0
    core = {t for t in name_tokens if t not in {v for vals in ALIASES.values() for v in vals}}
    return max(len(name_tokens & got) / len(name_tokens), len(core & got) / max(1, len(core)))


def page_title(page: str) -> str:
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    heads = " ".join(re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", page, re.I | re.S)[:8])
    return strip_tags((title.group(1) if title else "") + " " + heads)


def resolve(name: str, source: str, timeout: int, delay: float, max_pages: int) -> dict:
    wanted = tokens(name)
    queue = deque([(source, "", 0)])
    for suffix in ("/sitemap.xml", "/sitemap_index.xml"):
        root = f"{urlparse(source).scheme}://{urlparse(source).netloc}"
        queue.append((root + suffix, "sitemap", 0))
    visited, pages = set(), []
    while queue and len(visited) < max_pages:
        url, hint, depth = queue.popleft()
        if url in visited or not same_domain(url, source):
            continue
        visited.add(url)
        try:
            body, final_url = fetch(url, timeout)
        except Exception:
            continue
        time.sleep(delay)
        if "<urlset" in body[:1000].lower() or "<sitemapindex" in body[:1000].lower():
            ranked = sorted(sitemap_urls(body, final_url), key=lambda u: overlap_score(wanted, u), reverse=True)
            for item in ranked[:max_pages]:
                queue.append((item, item, depth + 1))
            continue
        title = page_title(body)
        page_score = max(overlap_score(wanted, title), overlap_score(wanted, final_url), overlap_score(wanted, hint))
        pages.append((page_score, final_url, title, body))
        if depth < 2:
            ranked_links = sorted(links(body, final_url), key=lambda x: overlap_score(wanted, x[0] + " " + x[1]), reverse=True)
            for link, label in ranked_links[:25]:
                if overlap_score(wanted, link + " " + label) >= 0.34:
                    queue.append((link, label, depth + 1))

    best = {"image_url": "", "status": "unresolved", "score": 0.0, "page_url": ""}
    for page_score, url, title, body in sorted(pages, reverse=True):
        for image, method, label in image_candidates(body, url):
            if any(x in image.lower() for x in ("logo", "favicon", "icon", "placeholder", "default-image")):
                continue
            label_score = overlap_score(wanted, label)
            score = max(label_score, page_score if method in {"page_meta", "jsonld"} else 0)
            exact_page = page_score >= 0.67
            exact_label = label_score >= 0.67
            if (exact_page or exact_label) and score > best["score"]:
                best = {"image_url": image, "status": method, "score": round(score, 3),
                        "page_url": url, "page_title": title}
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_csv", type=Path)
    ap.add_argument("output_csv", type=Path)
    ap.add_argument("--report", type=Path, default=Path("remaining_image_report.json"))
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--delay", type=float, default=0.25)
    ap.add_argument("--max-pages", type=int, default=80)
    args = ap.parse_args()
    with args.input_csv.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh); rows = list(reader); fields = list(reader.fieldnames or [])
    if "image_url" not in fields:
        raise SystemExit("CSV does not contain image_url")
    report = []
    for row_number, row in enumerate(rows, 2):
        if (row.get("image_url") or "").strip():
            continue
        result = resolve(row.get("canonical_name_fa", ""), row.get("source_url", ""),
                         args.timeout, args.delay, args.max_pages)
        if result["image_url"]:
            row["image_url"] = result["image_url"]
        report.append({"row": row_number, "name": row.get("canonical_name_fa", ""), **result})
        print(json.dumps(report[-1], ensure_ascii=False), flush=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    summary = {"checked": len(report), "resolved": sum(bool(x["image_url"]) for x in report),
               "pending": sum(not bool(x["image_url"]) for x in report), "details": report}
    args.report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("checked", "resolved", "pending")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
