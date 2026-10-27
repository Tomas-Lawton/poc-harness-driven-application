import datetime


class Blocked(Exception):
    """A connection refused access: a missing key, a 403, a redirect to a login page."""


class NotAllowed(Blocked):
    """A request outside the user scope: an unapproved host, a non-https address."""


def earliest_date(since: str) -> str:
    return (datetime.date.fromisoformat(since) - datetime.timedelta(days=1)).isoformat()


def to_number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def feedback_item(
    source: dict, native_id: object, date: str, text: str, title: str, rating: object, url: object
) -> dict:
    """One item in the shape every step after collection uses. `date` may be a full timestamp."""
    rating = to_number(rating)
    return {
        "id": f"{source['id']}:{native_id}",
        "url": url or None,
        "date": date,
        "title": title or "",
        "text": text,
        "rating": rating,
        "ratingScale": source.get("ratingScale") if rating is not None else None,
    }
