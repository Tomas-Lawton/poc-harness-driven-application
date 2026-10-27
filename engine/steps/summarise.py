import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[1]))  # engine/

from checks.summarise import check_summarise
from core.config import read_json
from core.config import write_json
from core.runs import open_latest_run
from core.runs import profile_key_from_command_line
from core.runs import step_command


def main() -> None:
    settings, run_info = open_latest_run(profile_key_from_command_line())
    items_file = read_json("items.json")
    items = {item["id"]: item for item in items_file["items"]}
    collect_log = read_json("collect_log.json")
    if not Path("themes.json").exists():
        sys.exit("FIX: themes.json not found. Write it first (pulse/SKILL.md, step 2), then run summarise.py again.")
    themes_file = read_json("themes.json")
    tags = read_tags(items)

    since = datetime.date.fromisoformat(run_info["since"])
    until = datetime.date.fromisoformat(run_info["until"])
    midpoint = since + (until - since) / 2  # trends compare the two halves of the window
    for theme in themes_file.get("themes", []):
        theme["computed"] = count_theme(theme, tags, items, midpoint, settings.scope["themes"])
    write_json("themes.json", themes_file, indent=2)

    themes = themes_file["themes"]
    kept = sorted(
        (theme for theme in themes if theme.get("decision") == "keep"), key=lambda theme: -theme["computed"]["score"]
    )
    shown_ids = {theme["id"] for theme in themes if theme.get("decision") in ("keep", "watch")}
    untagged = sum(1 for theme_ids in tags.values() if not set(theme_ids) & shown_ids)
    connections = collect_log["sources"]
    summary = {
        "date": run_info["date"],
        "window": {"since": run_info["since"], "until": run_info["until"], "label": run_info["windowLabel"]},
        "totals": {"items": len(items), **rating_stats(list(items.values()))},
        "capped": items_file.get("capped", False),
        "untaggedShare": round(100 * untagged / (len(items) or 1)),
        "daily": daily_counts(list(items.values()), since, until),
        "themes": [theme_counts(theme) for theme in kept],
        "watch": [theme_counts(theme) for theme in themes if theme.get("decision") == "watch"],
        "sources": {
            status: sum(connection["status"] == status for connection in connections)
            for status in ("ok", "blocked", "error")
        },
        "connections": connections,
    }
    write_json("summary.json", summary, indent=2)

    for theme in kept:
        counts = theme["computed"]
        print(
            f"{counts['score']:>2}  {theme['id']:<30} {counts['count']:>4} items  "
            f"{counts['share']:>5}%  {counts['trend']}"
        )
    print(
        f"{len(items)} items, {len(kept)} kept themes, {summary['untaggedShare']}% fit no kept theme "
        "-> themes.json, summary.json"
    )
    errors = check_summarise(settings)
    if errors:
        sys.exit("FIX themes.json or tags/, then run summarise.py again:\n  " + "\n  ".join(errors))
    print(f"next: write plan.json and live_content.json, then run: {step_command('render', settings.key)}")


def read_tags(items: dict[str, dict]) -> dict[str, list[str]]:
    """Every item's theme ids from tags/part_NN.json, or stop if any item is untagged."""
    tags = {}
    for path in sorted(Path("tags").glob("part_*.json")):
        for item_id, theme_ids in read_json(path).items():
            tags[item_id] = [theme_ids] if isinstance(theme_ids, str) else list(theme_ids or [])
    missing = [item_id for item_id in items if item_id not in tags]
    if missing:
        sys.exit(
            f"FIX: {len(missing)} of {len(items)} items are not tagged (for example {', '.join(missing[:5])}). "
            "Tag every item in tags/part_NN.json, using [] when no theme fits, then run summarise.py again."
        )
    return tags


def count_theme(
    theme: dict, tags: dict[str, list[str]], items: dict[str, dict], midpoint: datetime.date, rules: dict
) -> dict:
    """Everything code counts about a theme. Its score is the agent's impact and actionability,
    plus breadth (how much feedback it covers) and growth (1 if rising)."""
    item_ids = [item_id for item_id, theme_ids in tags.items() if theme.get("id") in theme_ids and item_id in items]
    share = round(100 * len(item_ids) / (len(items) or 1), 1)
    breadth = next((points for lowest, points in rules["breadth"] if share >= lowest), 0)
    first_half = sum(datetime.date.fromisoformat(items[item_id]["date"]) <= midpoint for item_id in item_ids)
    second_half = len(item_ids) - first_half
    if second_half >= 3 and second_half >= 1.5 * max(first_half, 1):
        trend, growth = "rising", 1
    elif first_half >= 3 and first_half >= 1.5 * max(second_half, 1):
        trend, growth = "easing", 0
    else:
        trend, growth = "steady", 0
    scores = theme.get("scores") or {}
    # A score that isn't a whole number counts as 0 here; the check then tells the agent to fix it.
    agent_score = sum(
        min(max(scores[field], 0), top) if isinstance(scores.get(field), int) else 0
        for field, top in (("impact", rules["maxImpact"]), ("actionability", rules["maxActionability"]))
    )

    per_source = {}
    for item_id in item_ids:
        per_source[items[item_id]["source"]] = per_source.get(items[item_id]["source"], 0) + 1
    return {
        **rating_stats([items[item_id] for item_id in item_ids]),
        "count": len(item_ids),
        "share": share,
        "sources": per_source,
        "firstHalf": first_half,
        "secondHalf": second_half,
        "trend": trend,
        "breadth": breadth,
        "growth": growth,
        "score": agent_score + breadth + growth,
        "items": item_ids,
    }


def rating_stats(items: list[dict]) -> dict:
    """The average rating out of 5, and the share rated 2 or less, whatever scale each came on."""
    ratings = [
        item["rating"] / item["ratingScale"] * 5
        for item in items
        if item.get("rating") is not None and item.get("ratingScale")
    ]
    if not ratings:
        return {"avgRating": None, "lowShare": None}
    return {
        "avgRating": round(sum(ratings) / len(ratings), 1),
        "lowShare": round(100 * sum(rating <= 2 for rating in ratings) / len(ratings)),
    }


def daily_counts(items: list[dict], since: datetime.date, until: datetime.date) -> list[dict]:
    days = []
    for offset in range((until - since).days + 1):
        date = (since + datetime.timedelta(days=offset)).isoformat()
        that_day = [item for item in items if item["date"] == date]
        days.append({"date": date, "count": len(that_day), "avgRating": rating_stats(that_day)["avgRating"]})
    return days


def theme_counts(theme: dict) -> dict:
    """A theme as summary.json lists it: its name and kind, and everything counted except its item ids."""
    counts = {key: value for key, value in theme["computed"].items() if key != "items"}
    return {"id": theme["id"], "title": theme.get("title"), "kind": theme.get("kind"), **counts}


if __name__ == "__main__":
    main()
