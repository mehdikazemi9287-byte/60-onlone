#!/usr/bin/env python3
"""Enrich 60online catalog rows with exact official product images.

Uses only each row's source_url. Exact product pages may use og:image;
category pages require a matching image alt/title. Ambiguous matches stay blank.
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
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (compatible; 60OnlineCatalogBot/1.0; +https://60online.ir)"
GENERIC = {"محصول", "خرید", "فروش", "بسته", "بندی", "طبیعت", "تواضع", "مهیا", "پروتئین"}


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(value or "")).lower()
    value = value.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    return " ".join(re.findall(r"[\w\u0600-\u06ff]+", value))


def tokens(value: str) -> set[str]:
    return {t for t in norm(value).split() if len(t) > 1 and t not in GENERIC}


def fetch(url: str, timeout: int) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "fa,en;q=0.7"})
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=timeout, context=ctx) as response:
        raw = response.read(4_000_000)
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def attrs(tag: str) -> dict[str, str]:
    return {
        k.lower(): html.unescape(v)
        for k, _, v in re.findall(r"([\w:-]+)\s*=\s*(['\"])(.*?)\2", tag, re.I | re.S)
    }


def candidates(page: str, base_url: str) -> tuple[list[dict], str | None]:
    found: list[dict] = []
    og_image = None
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
        a = attrs(tag)
        key = (a.get("property") or a.get("name") or "").lower()
        if key in {"og:image", "og:image:url", "twitter:image"} and a.get("content"):
            image = urljoin(base_url, a["content"])
            if not og_image:
                og_image = image
    for tag in re.findall(r"<img\b[^>]*>", page, re.I):
        a = attrs(tag)
        src = a.get("data-src") or a.get("data-lazy-src") or a.get("src")
        if not src or src.startswith("data:"):
            continue
        label = " ".join(filter(None, [a.get("alt"), a.get("title")]))
        found.append({"url": urljoin(base_url, src), "label": label})
    return found, og_image


def is_product_page(url: str) -> bool:
    path = urlparse(url).path.rstrip("/").lower()
    return "/product/" in path and path != "/product"


def pick_image(name: str, source_url: str, page: str) -> tuple[str, str, float]:
    imgs, og = candidates(page, source_url)
    wanted = tokens(name)
    best = ("", "", 0.0)
    for item in imgs:
        got = tokens(item["label"])
        if not wanted or not got:
            continue
        score = len(wanted & got) / len(wanted)
        if score > best[2]:
            best = (item["url"], "matched_img_alt", score)
    if best[2] >= 0.67 and len(wanted & tokens(best[1] if False else next((i["label"] for i in imgs if i["url"] == best[0]), ""))) >= 1:
        return best
    if is_product_page(source_url) and og:
        return og, "exact_product_og", 1.0
    return "", "unresolved", best[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input_csv", type=Path)
    ap.add_argument("output_csv", type=Path)
    ap.add_argument("--report", type=Path, default=Path("image_enrichment_report.json"))
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args()

    with args.input_csv.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if "image_url" not in fields:
        raise SystemExit("CSV does not contain image_url")

    cache: dict[str, str | Exception] = {}
    report = []
    for index, row in enumerate(rows, 2):
        name, source = row.get("canonical_name_fa", ""), row.get("source_url", "")
        if row.get("image_url"):
            report.append({"row": index, "name": name, "status": "existing", "image_url": row["image_url"]})
            continue
        if not source.startswith(("http://", "https://")):
            report.append({"row": index, "name": name, "status": "missing_source"})
            continue
        if source not in cache:
            try:
                cache[source] = fetch(source, args.timeout)
            except Exception as exc:  # network/site errors remain auditable
                cache[source] = exc
            time.sleep(args.delay)
        page = cache[source]
        if isinstance(page, Exception):
            report.append({"row": index, "name": name, "status": "fetch_error", "detail": str(page)})
            continue
        image, method, score = pick_image(name, source, page)
        if image:
            row["image_url"] = image
        report.append({"row": index, "name": name, "status": method, "score": round(score, 3), "image_url": image, "source_url": source})

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "total": len(rows),
        "images_filled": sum(bool(r.get("image_url")) for r in rows),
        "images_pending": sum(not bool(r.get("image_url")) for r in rows),
        "details": report,
    }
    args.report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("total", "images_filled", "images_pending")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
