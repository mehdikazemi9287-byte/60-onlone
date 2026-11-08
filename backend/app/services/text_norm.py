"""Persian/Latin text normalization for catalog matching and search.

Covers the practical cases: Arabic ي/ك/ة/ۀ vs Persian ی/ک/ه, alef variants, diacritics,
ZWNJ/ZWJ and spacing, Persian/Arabic-Indic digits, Latin case, and unit spellings.
"""
from __future__ import annotations

import re

_MAP = str.maketrans({
    "ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ؤ": "و",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "٫": ".", "٬": "", "،": " ", "‌": " ", "‍": "", "‏": "", "‎": "", "ـ": "",
})
_DIACRITICS = re.compile(r"[ً-ٰٟ]")
_NON_WORD = re.compile(r"[^\w.\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    if not text:
        return ""
    t = _DIACRITICS.sub("", str(text).translate(_MAP)).lower()
    t = _NON_WORD.sub(" ", t)
    return _SPACES.sub(" ", t).strip()


def compact(text: str | None) -> str:
    """Normalized with all spaces removed: «نیمه جامد» == «نیمه‌جامد» == «نیمهجامد»."""
    return normalize(text).replace(" ", "")


def tokens(text: str | None) -> list[str]:
    return [t for t in normalize(text).split(" ") if t]


def edit_distance_le1(a: str, b: str) -> bool:
    """True when a and b differ by at most one insertion, deletion or substitution."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = j = diff = 0
    while i < la and j < lb:
        if a[i] != b[j]:
            diff += 1
            if diff > 1:
                return False
            if la == lb:
                i += 1
            j += 1
        else:
            i += 1
            j += 1
    return diff + (lb - j) + (la - i) <= 1


# ── Size / measure extraction ──
_UNITS = [
    (r"کیلو ?گرم(?:ی)?|کیلویی|کیلو|kg", "weight_g", 1000),
    (r"گرم(?:ی)?|gr", "weight_g", 1),
    (r"میلی ?لیتر(?:ی)?|ml", "volume_ml", 1),
    (r"لیتر(?:ی)?|l", "volume_ml", 1000),
    (r"اینچ(?:ی)?|inch", "screen_inch", 1),
    (r"میلی ?امپر(?:ی)?|mah", "capacity_mah", 1),
    (r"گیگابایت|gb", "storage_gb", 1),
]
_MEASURE = re.compile(r"(\d+(?:\.\d+)?)\s*(" + "|".join(u for u, _, _ in _UNITS) + r")(?![a-z؀-ۿ])")
SIZE_WORDS = {"کوچک": "small", "متوسط": "medium", "بزرگ": "large"}


def measures(text: str | None) -> dict:
    out: dict = {}
    for m in _MEASURE.finditer(normalize(text)):
        value, unit = float(m.group(1)), m.group(2).replace(" ", "")
        for pattern, key, factor in _UNITS:
            if re.fullmatch(pattern.replace(" ?", ""), unit):
                v = value * factor
                out.setdefault(key, int(v) if v == int(v) else v)
                break
    return out


def strip_measures(text: str | None) -> str:
    t = _MEASURE.sub(" ", normalize(text))
    t = " ".join(w for w in t.split() if w not in SIZE_WORDS)
    return _SPACES.sub(" ", t).strip()


# Latin/Persian spellings of the same brand; display uses the Persian name, search matches both.
BRAND_ALIASES = {"samsung": "سامسونگ", "xiaomi": "شیائومی", "lenovo": "لنوو", "asus": "ایسوس", "hp": "اچ‌پی", "mikrotik": "میکروتیک"}


def canonical_brand(brand: str | None) -> str:
    return BRAND_ALIASES.get(normalize(brand), brand or "")
