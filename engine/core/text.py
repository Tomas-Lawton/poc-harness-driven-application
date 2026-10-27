import re
from typing import Any

ITEM_ID = r"[A-Za-z0-9_-]+-\d+"
CITATION = re.compile(rf"\[\s*({ITEM_ID}(?:\s*,\s*{ITEM_ID})*)\s*\]")


def normalise(text: Any) -> str:
    """Plain punctuation and single spaces, so a quote matches however it was typed."""
    plain = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00a0": " "}
    return re.sub(r"\s+", " ", str(text or "").translate(str.maketrans(plain))).strip()


def is_word_for_word(quote: Any, item: dict) -> bool:
    quote = normalise(quote).strip(" .\"'")
    return bool(quote) and (quote in normalise(item.get("text")) or quote in normalise(item.get("title")))


def cited_item_ids(text: Any) -> list[str]:
    return [item_id.strip() for citation in CITATION.findall(str(text or "")) for item_id in citation.split(",")]


def sentences(text: Any) -> list[str]:
    return [sentence for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", str(text or "").strip()) if sentence.strip()]


def numbers_to_check(text: Any) -> list[str]:
    """Numbers a reader would check: 11 or more, or with a decimal point, ignoring dates.

    Each is written as `f"{value:g}"`, so "12.0" and "12" compare equal; "1.2.3" stays as written.
    """
    # Dates such as "23 Oct", "Oct 23", "2026" or "2026-10-23" are not numbers a reader would check.
    dates = r"\b\d{1,2}\s+[A-Z][a-z]{2,8}\b|\b[A-Z][a-z]{2,8}\s+\d{1,2}\b|\b(?:19|20)\d{2}\b|\b\d{4}-\d{2}-\d{2}\b"
    found = []
    for number in re.findall(r"\d+(?:\.\d+)*", re.sub(dates, " ", str(text or ""))):
        if number.count(".") > 1:
            found.append(number)
        elif "." in number or int(number) > 10:
            found.append(f"{float(number):g}")
    return found


def text_errors(path: str, value: Any) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return [f"`{path}` is empty"]
    if re.search(r"https?://", value):
        return [f"`{path}` contains a link; links are added at render time"]
    return []


def scrub(text: str | None) -> str:
    """Email addresses, phone numbers and long numbers replaced by placeholders."""

    def phone(match: re.Match) -> str:
        found = match.group(0)
        is_date = re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", found)
        return found if is_date or sum(character.isdigit() for character in found) < 8 else "[phone]"

    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", text or "")
    text = re.sub(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)", phone, text)
    return re.sub(r"(?<![\w.])\d{6,}(?!\w|\.\d)", "[number]", text)  # account, card and reference numbers
