"""
Per-country license-plate validation + character disambiguation.

Purpose: NEVER report a wrong plate. An OCR read is accepted only if it matches
a known plate format for the configured country (PANEL_PLATE_COUNTRY, default
'generic'). Format knowledge also drives disambiguation of the classic OCR
confusions (O<->0, I<->1, B<->8, S<->5, Z<->2, G<->6) using each character
position's expected class (letter vs digit).

Formats are deliberately simple/robust; extend per deployment. This is a
correctness gate, not a legal-grade validator.
"""
from __future__ import annotations

import os
import re

# Ordered patterns per country. Each is a full-match regex on the cleaned
# (A-Z0-9) plate string. 'L' means letter, 'D' digit in the comments.
_PATTERNS: dict[str, list[str]] = {
    # Fallback: 4-10 alphanumerics (rejects garble, accepts most real plates).
    "generic": [r"[A-Z0-9]{4,10}"],
    # Bosnia & Herzegovina (2009 unified): A00-A-000 -> L DD L DDD. The unified
    # plate uses only the 7 letters common to Latin+Cyrillic (A,E,J,K,M,O,T);
    # the strict pattern is first (best for disambiguation), then a looser BiH
    # form, then an EU-wide fallback so mixed/EU footage still validates.
    "ba": [
        r"[AEJKMOT][0-9]{2}[AEJKMOT][0-9]{3}",
        r"[A-Z][0-9]{2}[A-Z][0-9]{3}",
        r"[A-Z0-9]{5,9}",
    ],
    # UK current: LL DD LLL ; older: L D{1,3} LLL and LLL D{1,3} L
    "uk": [r"[A-Z]{2}[0-9]{2}[A-Z]{3}", r"[A-Z][0-9]{1,3}[A-Z]{3}", r"[A-Z]{3}[0-9]{1,3}[A-Z]"],
    # US: state-dependent; general 5-8 alphanumerics.
    "us": [r"[A-Z0-9]{5,8}"],
    # Germany: 1-3 letters (city) + 1-2 letters + 1-4 digits.
    "de": [r"[A-Z]{1,3}[A-Z]{1,2}[0-9]{1,4}"],
    # Turkey: DD L{1,3} D{2,5}  (province code + letters + digits)
    "tr": [r"[0-9]{2}[A-Z]{1,3}[0-9]{2,5}"],
    # France (SIV): LL-DDD-LL
    "fr": [r"[A-Z]{2}[0-9]{3}[A-Z]{2}"],
    # Generic EU-ish: 5-9 alphanumerics.
    "eu": [r"[A-Z0-9]{5,9}"],
}

_ALNUM = re.compile(r"[^A-Z0-9]")
# Position-aware disambiguation maps.
_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
             "S": "5", "B": "8", "G": "6", "T": "7", "A": "4"}
_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G"}


def country() -> str:
    # Default: Bosnia & Herzegovina (with an EU-wide fallback in its patterns).
    return os.getenv("PANEL_PLATE_COUNTRY", "ba").lower()


def _patterns(c: str | None = None) -> list[str]:
    return _PATTERNS.get(c or country(), _PATTERNS["generic"])


def clean(text: str) -> str:
    return _ALNUM.sub("", text.upper())


def is_valid(plate: str, c: str | None = None) -> bool:
    """True if `plate` fully matches a plate format for the country."""
    if not plate:
        return False
    return any(re.fullmatch(p, plate) for p in _patterns(c))


def disambiguate(plate: str, c: str | None = None) -> str:
    """Fix classic OCR confusions using the position classes of the matched
    format. If no format matches even after fixing, the original is returned
    (and is_valid will reject it)."""
    plate = clean(plate)
    if is_valid(plate, c):
        return plate
    for pat in _patterns(c):
        m = _class_string(pat, len(plate))
        if m is None:
            continue
        fixed = []
        for ch, cls in zip(plate, m):
            if cls == "D" and not ch.isdigit():
                fixed.append(_TO_DIGIT.get(ch, ch))
            elif cls == "L" and not ch.isalpha():
                fixed.append(_TO_LETTER.get(ch, ch))
            else:
                fixed.append(ch)
        cand = "".join(fixed)
        if is_valid(cand, c):
            return cand
    return plate


def _class_string(pattern: str, length: int) -> str | None:
    """Expand a simple regex into a per-position class string ('L'/'D'/'*') for
    a given length, or None if the pattern can't produce that length. Handles
    the [A-Z]{n,m} / [0-9]{n,m} / [A-Z0-9]{n,m} token forms used above."""
    tokens = re.findall(r"\[([^\]]+)\]\{(\d+)(?:,(\d+))?\}", pattern)
    if not tokens:
        return None
    # Try to fit `length` by expanding each token to a count within its range.
    ranges = []
    for chars, lo, hi in tokens:
        lo = int(lo)
        hi = int(hi) if hi else lo
        cls = "D" if chars == "0-9" else ("L" if chars == "A-Z" else "*")
        ranges.append((cls, lo, hi))
    min_len = sum(lo for _, lo, _ in ranges)
    max_len = sum(hi for _, _, hi in ranges)
    if not (min_len <= length <= max_len):
        return None
    # Greedily give each token its minimum, then distribute the remainder.
    counts = [lo for _, lo, _ in ranges]
    remainder = length - min_len
    for i, (_, lo, hi) in enumerate(ranges):
        add = min(remainder, hi - lo)
        counts[i] += add
        remainder -= add
    out = []
    for (cls, _, _), n in zip(ranges, counts):
        out.append(cls * n)
    s = "".join(out)
    return s if len(s) == length else None
