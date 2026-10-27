import csv
import os

from read import earliest_date
from read import feedback_item

FIELDS = ("id", "url", "date", "title", "text", "rating")


def fetch(source: dict, since: str, limit: int, profile_dir: str) -> list[dict]:
    path = os.path.join(profile_dir, source["file"])
    if not os.path.exists(path):
        raise FileNotFoundError(f"{os.path.relpath(path)} not found; export it again or ask setup to refresh it")
    columns = source.get("columns") or {}
    first_date = earliest_date(since)
    items = []
    with open(path, newline="", encoding="utf-8-sig") as export:  # utf-8-sig: Excel starts files with a BOM
        for row_number, row in enumerate(csv.DictReader(export)):
            value = {field: (row.get(columns.get(field, field)) or "").strip() for field in FIELDS}
            date, text = value.get("date", ""), value.get("text", "")
            if not text or not date or date[:10] < first_date:
                continue
            items.append(
                feedback_item(
                    source,
                    value.get("id") or row_number,
                    date,
                    text,
                    value.get("title"),
                    value.get("rating"),
                    value.get("url"),
                )
            )
    return sorted(items, key=lambda item: item["date"], reverse=True)[:limit]  # the newest, whatever the file order
