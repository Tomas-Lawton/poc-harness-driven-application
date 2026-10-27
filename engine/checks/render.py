from typing import Any

from core.config import Settings
from core.config import read_json_if_exists
from core.runs import read_items
from core.text import CITATION
from core.text import cited_item_ids
from core.text import normalise
from core.text import numbers_to_check
from core.text import sentences
from core.text import text_errors


def check_render(settings: Settings, run_info: dict) -> list[str]:
    rules = settings.scope["themes"]
    kept, watched = counted_themes("keep"), counted_themes("watch")
    plan = read_json_if_exists("plan.json")
    content = read_json_if_exists("live_content.json")
    plan_errors = check_plan(plan, kept, watched, rules) if plan else ["plan.json not found"]
    if content:
        content_errors = check_content(content, plan or {}, kept, watched, rules, run_info)
    else:
        content_errors = ["live_content.json not found"]
    return [f"plan: {error}" for error in plan_errors] + [f"content: {error}" for error in content_errors]


def check_plan(plan: dict, kept: dict, watched: dict, rules: dict) -> list[str]:
    errors = text_errors("headline", plan.get("headline"))
    actions, shown = plan.get("actions") or [], plan.get("themes") or []
    if not (0 if plan.get("quietWeek") else 1) <= len(actions) <= rules["maxActions"]:
        errors.append(f"`actions` needs 1 to {rules['maxActions']} items (or quietWeek: true)")
    for index, action in enumerate(actions):
        theme = kept.get(action.get("theme"))
        if not theme:
            errors.append(f"`actions[{index}].theme` is not a kept theme")
            continue
        if theme["computed"]["score"] < rules["actionScore"]:
            errors.append(
                f"`actions[{index}]` theme scores {theme['computed']['score']}; actions need {rules['actionScore']}"
            )
        if action["theme"] not in shown:
            errors.append(f"action theme `{action['theme']}` must also be in `themes`")
    fewest = 1 if kept else 0
    if not fewest <= len(shown) <= rules["maxThemes"] or any(theme_id not in kept for theme_id in shown):
        errors.append(f"`themes` must list {fewest} to {rules['maxThemes']} kept theme ids")
    if sorted(plan.get("watch") or []) != sorted(watched):
        errors.append(f"`watch` must list every watched theme: {', '.join(sorted(watched)) or 'none'}")
    return errors


def check_content(content: dict, plan: dict, kept: dict, watched: dict, rules: dict, run_info: dict) -> list[str]:
    items = read_items()
    errors = []
    meta = content.get("meta") or {}
    if meta.get("dateLabel") != run_info["dateLabel"] or meta.get("windowLabel") != run_info["windowLabel"]:
        errors.append(
            f'`meta` must copy dateLabel "{run_info["dateLabel"]}" and windowLabel "{run_info["windowLabel"]}" '
            "from run.json"
        )
    for field in ("subject", "preheader", "headline", "footer"):
        errors += text_errors(field, content.get(field))

    questions = content.get("questions") or []
    fewest, most = rules["questions"]
    if not fewest <= len(questions) <= most:
        errors.append(f"`questions` needs {fewest} to {most} follow-up questions the reader could ask about this pulse")
    for index, question in enumerate(questions):
        errors += text_errors(f"questions[{index}]", question)
        if isinstance(question, str) and not question.strip().endswith("?"):
            errors.append(f"`questions[{index}]` should be a question")

    if [action.get("theme") for action in content.get("actions") or []] != [
        action.get("theme") for action in plan.get("actions") or []
    ]:
        errors.append("`actions` must follow the plan")
    if [theme.get("id") for theme in content.get("themes") or []] != plan.get("themes"):
        errors.append("`themes` must be the plan's themes, in order")
    if [entry.get("id") for entry in content.get("watch") or []] != (plan.get("watch") or []):
        errors.append("`watch` must be the plan's watched themes, in order")

    errors += watchlist_errors(content, watched, rules, items)
    errors += theme_errors(content, kept, rules, items)
    errors += action_errors(content, kept, items)
    errors += [
        f"`headline` cites `{item_id}`, which is not a collected item"
        for item_id in cited_item_ids(content.get("headline"))
        if item_id not in items
    ]
    errors += number_errors(content, items)
    return errors


def watchlist_errors(content: dict, watched: dict, rules: dict, items: dict) -> list[str]:
    errors = []
    for index, entry in enumerate(content.get("watch") or []):
        theme = watched.get(entry.get("id")) or {}
        allowed_quotes, quotes = checked_quotes(theme), entry.get("quotes") or []
        errors += text_errors(f"watch[{index}].title", entry.get("title"))
        errors += text_errors(f"watch[{index}].why", entry.get("why"))
        errors += citation_errors(f"watch[{index}].why", entry.get("why"), tagged_ids(theme), items)
        if not min(1, len(allowed_quotes)) <= len(quotes) <= rules["maxWatchQuotes"]:
            errors.append(
                f"`watch[{index}]` shows 1 to {rules['maxWatchQuotes']} quotes (none only if it has no quotable items)"
            )
        errors += quote_errors(f"watch[{index}]", quotes, allowed_quotes)
    return errors


def theme_errors(content: dict, kept: dict, rules: dict, items: dict) -> list[str]:
    """Each theme cites its items and shows as many checked quotes as it has, up to the limit."""
    errors = []
    most_quotes = rules["maxQuotesPerTheme"]
    for index, shown in enumerate(content.get("themes") or []):
        theme = kept.get(shown.get("id"))
        errors += text_errors(f"themes[{index}].title", shown.get("title"))
        errors += text_errors(f"themes[{index}].summary", shown.get("summary"))
        errors += citation_errors(f"themes[{index}].summary", shown.get("summary"), tagged_ids(theme), items)
        allowed_quotes, quotes = checked_quotes(theme), shown.get("quotes") or []
        wanted = min(most_quotes, len(allowed_quotes))
        if not wanted <= len(quotes) <= most_quotes:
            errors.append(
                f"`themes[{index}]` shows {wanted} quotes "
                f"(it has {len(allowed_quotes)} checked quotes; the most shown is {most_quotes})"
            )
        cited = set(cited_item_ids(shown.get("summary")))
        for quote in quotes:
            if quote.get("item") not in cited:
                errors.append(
                    f"`themes[{index}].summary` should cite `{quote.get('item')}`, the item its quote comes from"
                )
        errors += quote_errors(f"themes[{index}]", quotes, allowed_quotes)
    return errors


def action_errors(content: dict, kept: dict, items: dict) -> list[str]:
    """Each action is a draft ticket: a title, the issue, and the tagged items it rests on."""
    errors = []
    for index, action in enumerate(content.get("actions") or []):
        allowed = tagged_ids(kept.get(action.get("theme")))
        ticket = action.get("ticket") or {}
        for field in ("title", "issue"):
            errors += text_errors(f"actions[{index}].ticket.{field}", ticket.get(field))
        listed = ticket.get("items") or []
        if not listed:
            errors.append(f"`actions[{index}].ticket.items` must list the feedback the ticket rests on")
        for item_id in listed:
            if item_id not in items:
                errors.append(f"`actions[{index}].ticket.items` lists `{item_id}`, which is not a collected item")
            elif item_id not in allowed:
                errors.append(f"`actions[{index}].ticket.items` lists `{item_id}`, which is not tagged with this theme")
    return errors


def number_errors(content: dict, items: dict) -> list[str]:
    """Every number a reader would check comes from summary.json or the feedback itself."""
    known = set()
    add_numbers(read_json_if_exists("summary.json"), known)
    for item in items.values():
        known |= set(numbers_to_check(f"{item.get('title', '')} {item.get('text', '')}"))

    fields = [(field, content.get(field)) for field in ("headline", "preheader", "subject")]
    for index, action in enumerate(content.get("actions") or []):
        ticket = action.get("ticket") or {}
        fields += [
            (f"actions[{index}].ticket.title", ticket.get("title")),
            (f"actions[{index}].ticket.issue", ticket.get("issue")),
        ]
    for index, theme in enumerate(content.get("themes") or []):
        fields += [(f"themes[{index}].title", theme.get("title")), (f"themes[{index}].summary", theme.get("summary"))]
    for index, entry in enumerate(content.get("watch") or []):
        fields += [(f"watch[{index}].title", entry.get("title")), (f"watch[{index}].why", entry.get("why"))]
    fields += [(f"questions[{index}]", question) for index, question in enumerate(content.get("questions") or [])]

    return [
        f"`{path}` uses the number {number}, which is not in summary.json or the feedback"
        for path, text in fields
        for number in numbers_to_check(CITATION.sub(" ", str(text or "")))  # item ids aren't numbers
        if number not in known
    ]


def add_numbers(value: Any, known: set[str]) -> None:
    """Every number in summary.json, as written, rounded, and without its sign."""
    if isinstance(value, dict):
        for child in value.values():
            add_numbers(child, known)
    elif isinstance(value, list):
        for child in value:
            add_numbers(child, known)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        for number in (value, abs(value)):
            for places in (0, 1):
                known.add(f"{round(number, places):g}")


def counted_themes(decision: str) -> dict[str, dict]:
    """Themes with this decision that summarise.py has counted, by id."""
    themes = read_json_if_exists("themes.json", {}).get("themes", [])
    return {theme["id"]: theme for theme in themes if theme.get("decision") == decision and theme.get("computed")}


def tagged_ids(theme: dict | None) -> set[str]:
    return set((theme or {}).get("computed", {}).get("items") or [])


def checked_quotes(theme: dict | None) -> set[tuple[str, str]]:
    """The theme's evidence as (item id, quote) pairs, already checked word for word."""
    return {(quote.get("item"), normalise(quote.get("quote"))) for quote in (theme or {}).get("evidence") or []}


def citation_errors(path: str, text: Any, allowed: set[str] | None, items: dict[str, dict]) -> list[str]:
    """Every sentence cites at least one collected item, from `allowed` when given."""
    errors = []
    for number, sentence in enumerate(sentences(text), 1):
        item_ids = cited_item_ids(sentence)
        if not item_ids:
            errors.append(
                f"`{path}` sentence {number} cites no items; "
                "end it with the ids it rests on, like [tickets-012, survey-087]"
            )
        for item_id in item_ids:
            if item_id not in items:
                errors.append(f"`{path}` cites `{item_id}`, which is not a collected item")
            elif allowed is not None and item_id not in allowed:
                errors.append(f"`{path}` cites `{item_id}`, which is not tagged with this theme")
    return errors


def quote_errors(path: str, quotes: list[dict], allowed: set[tuple[str, str]]) -> list[str]:
    return [
        f"`{path}.quotes[{index}]` is not one of the theme's checked quotes"
        for index, quote in enumerate(quotes)
        if (quote.get("item"), normalise(quote.get("quote"))) not in allowed
    ]
