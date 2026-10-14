"""Extract the supplied PDFs without guessing commercial fields.

Requires pypdf in an isolated tooling environment; never opens a database.
The PDF text visitor preserves logical Persian order and original cells.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader


def clean(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).replace("ـ", "")).strip()


def normalized(value):
    return clean(value).replace("ي", "ی").replace("ك", "ک")


def cells(page):
    result = []
    page.extract_text(visitor_text=lambda text, cm, tm, font, size: result.append(
        {"x": round(tm[4], 2), "y": round(tm[5], 2), "text": text, "size": size}
    ) if text.strip() else None)
    return result


def join(parts):
    # Cells are emitted in logical reading order, including Latin/numeric runs.
    return clean(" ".join(p["text"] for p in parts))


def base(file, page, supplier, name, sku, raw, identifier):
    return {
        "supplier": supplier, "supplier_product_code": sku,
        "original_name": name, "normalized_name": normalized(name),
        "brand": "آریا" if supplier == "آریا" else None,
        "category": None, "subcategory": None, "variant": None,
        "barcode": None, "unit": None, "weight": None, "weight_unit": None,
        "size": None, "packaging": None, "pack_qty": None,
        "carton_quantity": None, "price": None, "currency": None,
        "price_type": None, "price_basis": None, "price_status": "absent",
        "stock": None, "images": [], "description": None,
        "source_file": file, "source_page": page, "source_identifier": identifier,
        "source_date": "1405-06" if "1405" in file else None,
        "raw_cells": raw, "attributes": {}, "issues": [],
    }


def price_rows(file, page_number, pieces):
    rows = []
    codes = [p for p in pieces if p["x"] > 490 and re.fullmatch(r"\d{4}(?:-\d+)?", clean(p["text"]))]
    for code in codes:
        same = [p for p in pieces if abs(p["y"] - code["y"]) < 2]
        name = join([p for p in same if 250 < p["x"] < 490])
        row = base(file, page_number, "آریا", name, clean(code["text"]), same, f"sku:{clean(code['text'])}")
        row["category"] = "books-stationery"
        weight = re.search(r"(\d+(?:[./]\d+)?)\s*(کیلویی|گرمی)", name)
        if weight:
            row["weight"] = weight.group(1)
            row["weight_unit"] = "kg" if weight.group(2) == "کیلویی" else "g"
        elif "کیلویی" in name:
            row["weight"], row["weight_unit"] = "1", "kg"
        colors = re.search(r"(\d+)\s*رنگ", name)
        if colors:
            row["attributes"]["color_count"] = int(colors.group(1))
        unit = join([p for p in same if 220 < p["x"] <= 250])
        qty = join([p for p in same if 180 < p["x"] <= 220])
        price = join([p for p in same if p["x"] <= 180])
        row["unit"] = unit or None
        row["carton_quantity"] = int(qty) if qty.isdigit() else None
        # This is carton quantity, not stock or items inside a retail pack.
        row["price_raw"] = price or None
        row["price_type"] = "consumer"
        if price:
            if re.fullmatch(r"\d{1,3}(?:,\d{3})+|\d+", price):
                row["price"] = int(price.replace(",", ""))
                row["price_type"] = "consumer"
                row["price_status"] = "currency_and_basis_unconfirmed"
            else:
                row["issues"].append("malformed_price_cell")
        if not name or not unit or not qty.isdigit():
            row["issues"].append("incomplete_table_cells")
        rows.append(row)
    return rows


def protein_rows(file, page_number, pieces, species):
    # Each PDF has independently headed fresh and frozen columns.
    code_cells = [p for p in pieces if re.fullmatch(r"\d{8}", clean(p["text"]))]
    right_code = max(p["x"] for p in code_cells)
    left_code = min(p["x"] for p in code_cells)
    # Code columns are to the right of their descriptions. The physical
    # separator follows the frozen code cell, not the midpoint of both codes.
    boundary = left_code + 40
    result = []
    ys = sorted({round(p["y"], 0) for p in pieces if p["y"] > 50}, reverse=True)
    # Group near-identical baselines (numeric codes can sit 0.5pt higher).
    groups = []
    for p in pieces:
        if not groups or all(abs(p["y"] - g[0]["y"]) > 2 for g in groups):
            groups.append([p])
        else:
            next(g for g in groups if abs(p["y"] - g[0]["y"]) <= 2).append(p)
    for group in sorted(groups, key=lambda g: -g[0]["y"]):
        for side, state in [("right", "fresh"), ("left", "frozen")]:
            part = [p for p in group if (p["x"] > boundary) == (side == "right")]
            codes = [p for p in part if re.fullmatch(r"\d{8}", clean(p["text"]))]
            name_parts = [p for p in part if p not in codes]
            name = join(name_parts)
            if not name or name in {"کد", "شرح کالا", "باتشکر", "با تشکر"}:
                continue
            if any(w in name for w in ["محصولات", "گوشت تازه", "گوشت منجمد", "مرغ تازه مرغ منجمد"]):
                continue
            if name in ["گوشت", "منجمد", "تازه", "مرغ تازه", "مرغ منجمد"]:
                continue
            # All product rows are between the column header and footer.
            if group[0]["y"] >= min(p["y"] for p in pieces if clean(p["text"]) == "کد"):
                continue
            sku = clean(codes[0]["text"]) if codes else None
            row = base(file, page_number, "پویا پروتئین", name, sku, part,
                       f"{side}:y={group[0]['y']}:sku={sku or 'absent'}")
            row["category"] = {"veal": "protein-fresh--red-meat--veal", "lamb": "protein-fresh--red-meat--lamb", "chicken": "protein-fresh--poultry"}[species]
            row["subcategory"] = species
            row["variant"] = state
            row["attributes"] = {"species": species, "temperature_state": state}
            weight = re.search(r"(\d+(?:[./]\d+)?)\s*گرمی", name)
            if weight:
                row["weight"], row["weight_unit"] = weight.group(1), "g"
            for word in ["وکیوم", "بشقابی", "فله", "ظرفی"]:
                if word in name: row["packaging"] = word
            result.append(row)
    return result


def extract(root, output):
    records, files = [], []
    for path in sorted((root / "data/data/imports").rglob("*.pdf")):
        if path.parent.name not in {"aria", "pouya-protein"}:
            continue
        reader = PdfReader(path)
        file = str(path.relative_to(root))
        info = {"file": file, "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "pages": len(reader.pages), "extracted_rows": 0}
        for number, page in enumerate(reader.pages, 1):
            pieces = cells(page)
            if path.name.startswith("__"):
                extracted = price_rows(file, number, pieces)
            elif path.parent.name == "pouya-protein":
                extracted = protein_rows(file, number, pieces,
                     {"gosaleh.pdf": "veal", "gosfand.pdf": "lamb", "morgh.pdf": "chicken"}[path.name])
            else:
                continue  # Catalogue extraction is handled by the reviewed OCR/text census.
            records.extend(extracted)
            info["extracted_rows"] += len(extracted)
        files.append(info)
    output.mkdir(parents=True, exist_ok=True)
    (output / "table-rows.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
    (output / "table-census.json").write_text(json.dumps(files, ensure_ascii=False, indent=2))
    print(json.dumps([{ "file": f["file"], "pages": f["pages"], "rows": f["extracted_rows"]} for f in files], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    extract(args.root.resolve(), args.output.resolve())
