import re

from core.config import Settings
from core.config import read_json_if_exists
from core.runs import read_items
from core.text import is_word_for_word
from core.text import normalise
from core.text import text_errors

THEME_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
KINDS = ("problem", "request", "praise", "question")
DECISIONS = ("keep", "watch", "drop")


def check_summarise(settings: Settings) -> list[str]:
    themes_file = read_json_if_exists("themes.json")
    if themes_file is None:
        return ["themes: themes.json not found"]
    errors = [f"themes: {error}" for error in theme_errors(themes_file.get("themes") or [], settings)]
    untagged = read_json_if_exists("summary.json", {}).get("untaggedShare", 0)
    most_untagged = settings.scope["themes"]["maxUntaggedShare"]
    if untagged > most_untagged:
        errors.append(
            f"{untagged}% of items fit no kept theme (limit {most_untagged}%); "
            "read the untagged items again, add or widen a theme, and retag"
        )
    return errors


def theme_errors(themes: list[dict], settings: Settings) -> list[str]:
    rules = settings.scope["themes"]
    items = read_items()
    errors, seen_ids = [], set()
    for index, theme in enumerate(themes):
        path = f"themes[{index}] ({theme.get('id')})"
        if "computed" not in theme:
            errors.append(f"`{path}` has not been counted; run summarise.py again")
            continue
        if not THEME_ID.match(str(theme.get("id", ""))) or theme.get("id") in seen_ids:
            errors.append(f"`{path}.id` must be a unique lowercase slug")
        seen_ids.add(theme.get("id"))
        if theme.get("kind") not in KINDS:
            errors.append(f"`{path}.kind` must be problem, request, praise or question")
        if theme.get("decision") not in DECISIONS or not str(theme.get("reason", "")).strip():
            errors.append(f"`{path}` needs a decision (keep, watch or drop) and a reason")
        errors += text_errors(f"{path}.title", theme.get("title"))
        errors += text_errors(f"{path}.summary", theme.get("summary"))
        scores = theme.get("scores") or {}
        for field, highest in (("impact", rules["maxImpact"]), ("actionability", rules["maxActionability"])):
            if not isinstance(scores.get(field), int) or not 0 <= scores[field] <= highest:
                errors.append(f"`{path}.scores.{field}` must be a whole number from 0 to {highest}")

        if theme.get("decision") == "watch":
            errors += watch_errors(path, theme, rules)
        if theme.get("decision") == "keep" and theme["computed"]["score"] < rules["keepScore"]:
            errors.append(
                f"`{path}` is kept with score {theme['computed']['score']}; "
                f"below {rules['keepScore']} drop it, or watch it if it is serious"
            )
        if theme.get("decision") in ("keep", "watch"):
            errors += evidence_errors(path, theme, settings, items)

    kept = sum(theme.get("decision") == "keep" for theme in themes)
    watched = sum(theme.get("decision") == "watch" for theme in themes)
    if kept > rules["maxThemes"]:
        errors.append(f"{kept} kept themes; keep at most {rules['maxThemes']}")
    if watched > rules["maxWatch"]:
        errors.append(f"{watched} watched themes; watch at most {rules['maxWatch']}")
    return errors


def watch_errors(path: str, theme: dict, rules: dict) -> list[str]:
    """The watchlist is for rare, serious themes that something is tagged with."""
    errors = []
    share = theme["computed"]["share"]
    if share > rules["watchMaxShare"]:
        errors.append(
            f"`{path}` is {share}% of feedback; the watchlist is for rare items "
            f"(up to {rules['watchMaxShare']}%), so keep it"
        )
    if (theme.get("scores") or {}).get("impact", 0) < rules["watchMinImpact"]:
        errors.append(
            f"`{path}` is on the watchlist, which is only for serious items "
            f"(impact {rules['watchMinImpact']} to {rules['maxImpact']})"
        )
    if not theme["computed"]["count"]:
        errors.append(f"`{path}` is on the watchlist but no item is tagged with it")
    return errors


def evidence_errors(path: str, theme: dict, settings: Settings, items: dict[str, dict]) -> list[str]:
    """Quotes are word for word, from tagged items the pulse may quote.

    A theme built only from private feedback, when private quotes are off, is described, not quoted.
    """
    rules = settings.scope["themes"]
    private_quotes = settings.user_scope.get("privateQuotes", True)
    tagged = theme["computed"]["items"]
    quotable = [item_id for item_id in tagged if private_quotes or not items.get(item_id, {}).get("private")]
    needed = min(1 if theme["decision"] == "watch" else rules["minEvidence"], len(quotable))

    evidence = theme.get("evidence") or []
    errors = []
    if len(evidence) < needed:
        errors.append(f"`{path}` needs at least {needed} quote{'s' if needed > 1 else ''}")
    for index, quote in enumerate(evidence):
        where = f"`{path}.evidence[{index}]`"
        item = items.get(quote.get("item"))
        if not item or quote["item"] not in tagged:
            errors.append(f"{where} must name an item tagged with this theme")
            continue
        if len(normalise(quote.get("quote")).split()) < rules["minQuoteWords"]:
            errors.append(f"{where} is shorter than {rules['minQuoteWords']} words")
        if not is_word_for_word(quote.get("quote"), item):
            errors.append(f"{where} does not appear word for word in `{quote['item']}`; copy it exactly")
        if item.get("private") and not private_quotes:
            errors.append(f"{where} quotes a private item; describe it instead")
    return errors
