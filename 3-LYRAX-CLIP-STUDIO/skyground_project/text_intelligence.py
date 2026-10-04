"""
Unicode-based text intelligence for Persian/Latin mixed environments.

Goals:
- Detect Persian/Arabic-script vs Latin-script text using Unicode ranges.
- Infer direction: rtl, ltr, mixed, neutral.
- Split text into script runs for UI/log handling.
- Avoid external dependencies.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from typing import Dict, List


@dataclasses.dataclass(frozen=True)
class TextProfile:
    length: int
    letters: int
    persian_arabic_letters: int
    latin_letters: int
    digits: int
    persian_digits: int
    latin_digits: int
    other_letters: int
    rtl_strong: int
    ltr_strong: int
    primary_script: str  # persian_arabic | latin | mixed | neutral | other
    direction: str       # rtl | ltr | mixed | neutral
    persian_ratio: float
    latin_ratio: float
    is_mixed: bool

    def to_dict(self) -> Dict[str, object]:
        return dataclasses.asdict(self)


# Arabic block includes Persian letters. Additional Arabic supplement/extended blocks included.
def is_arabic_script_char(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x0600 <= cp <= 0x06FF
        or 0x0750 <= cp <= 0x077F
        or 0x08A0 <= cp <= 0x08FF
        or 0xFB50 <= cp <= 0xFDFF
        or 0xFE70 <= cp <= 0xFEFF
    )


def is_persian_digit(ch: str) -> bool:
    cp = ord(ch)
    return 0x06F0 <= cp <= 0x06F9 or 0x0660 <= cp <= 0x0669


def is_latin_char(ch: str) -> bool:
    cp = ord(ch)
    return (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A) or (0x00C0 <= cp <= 0x024F)


def unicode_direction(ch: str) -> str:
    bidi = unicodedata.bidirectional(ch)
    if bidi in {"R", "AL", "AN"}:
        return "rtl"
    if bidi in {"L", "EN"}:
        return "ltr"
    return "neutral"


def char_script(ch: str) -> str:
    if is_arabic_script_char(ch):
        if ch.isalpha() or is_persian_digit(ch):
            return "persian_arabic"
        return "neutral"
    if is_latin_char(ch):
        return "latin"
    if ch.isdigit():
        return "digit"
    if ch.isalpha():
        return "other"
    return "neutral"


def detect_text_profile(text: str) -> TextProfile:
    length = len(text or "")
    letters = 0
    persian_arabic_letters = 0
    latin_letters = 0
    other_letters = 0
    digits = 0
    persian_digits = 0
    latin_digits = 0
    rtl_strong = 0
    ltr_strong = 0

    for ch in text or "":
        direction = unicode_direction(ch)
        if direction == "rtl":
            rtl_strong += 1
        elif direction == "ltr":
            ltr_strong += 1

        if ch.isdigit():
            digits += 1
            if is_persian_digit(ch):
                persian_digits += 1
            elif "0" <= ch <= "9":
                latin_digits += 1

        if ch.isalpha():
            letters += 1
            if is_arabic_script_char(ch):
                persian_arabic_letters += 1
            elif is_latin_char(ch):
                latin_letters += 1
            else:
                other_letters += 1

    persian_ratio = persian_arabic_letters / letters if letters else 0.0
    latin_ratio = latin_letters / letters if letters else 0.0

    if letters == 0:
        primary_script = "neutral"
    elif persian_ratio >= 0.75:
        primary_script = "persian_arabic"
    elif latin_ratio >= 0.75:
        primary_script = "latin"
    elif persian_arabic_letters and latin_letters:
        primary_script = "mixed"
    else:
        primary_script = "other"

    if rtl_strong == 0 and ltr_strong == 0:
        direction = "neutral"
    elif rtl_strong and ltr_strong:
        # Treat as mixed if both sides are meaningful, not just one digit/word.
        smaller = min(rtl_strong, ltr_strong)
        larger = max(rtl_strong, ltr_strong)
        direction = "mixed" if smaller / larger >= 0.15 else ("rtl" if rtl_strong > ltr_strong else "ltr")
    else:
        direction = "rtl" if rtl_strong else "ltr"

    return TextProfile(
        length=length,
        letters=letters,
        persian_arabic_letters=persian_arabic_letters,
        latin_letters=latin_letters,
        digits=digits,
        persian_digits=persian_digits,
        latin_digits=latin_digits,
        other_letters=other_letters,
        rtl_strong=rtl_strong,
        ltr_strong=ltr_strong,
        primary_script=primary_script,
        direction=direction,
        persian_ratio=round(persian_ratio, 4),
        latin_ratio=round(latin_ratio, 4),
        is_mixed=primary_script == "mixed" or direction == "mixed",
    )


def split_script_runs(text: str) -> List[Dict[str, object]]:
    """Split text into consecutive script runs: Persian/Arabic, Latin, digit, neutral, other."""
    runs: List[Dict[str, object]] = []
    if not text:
        return runs
    current_script = char_script(text[0])
    buf = [text[0]]
    start = 0
    for idx, ch in enumerate(text[1:], start=1):
        script = char_script(ch)
        # Attach whitespace/punctuation to current run for readability.
        comparable = current_script if script == "neutral" else script
        if comparable == current_script or current_script == "neutral":
            if current_script == "neutral" and script != "neutral":
                current_script = script
            buf.append(ch)
            continue
        segment = "".join(buf)
        runs.append({"script": current_script, "direction": detect_text_profile(segment).direction, "start": start, "end": idx, "text": segment})
        start = idx
        current_script = script
        buf = [ch]
    segment = "".join(buf)
    runs.append({"script": current_script, "direction": detect_text_profile(segment).direction, "start": start, "end": len(text), "text": segment})
    return runs


def direction_hint(text: str) -> str:
    return detect_text_profile(text).direction