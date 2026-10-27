import datetime
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).absolute().parents[1]))  # engine/

from checks.collect import check_collect
from core.config import PROFILES_DIR
from core.config import Settings
from core.config import write_json
from core.runs import profile_key_from_command_line
from core.runs import start_run
from core.runs import step_command
from core.text import scrub
from read import Blocked
from read import bigquery
from read import csv_file
from read import service

try:
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize
except ImportError:
    sys.exit("scikit-learn is missing; install it with: python3 -m pip install -r requirements.txt")


def main() -> None:
    settings, run_info = start_run(profile_key_from_command_line())
    items, log, duplicates = collect(settings, run_info)

    cap = settings.scope["collect"]["maxItems"]
    items.sort(key=lambda item: item["date"], reverse=True)
    capped = len(items) > cap
    items = items[:cap]
    kept = {}
    for number, item in enumerate(items, 1):
        item["nativeId"], item["id"] = item["id"], f"{item['source']}-{number:03d}"
        kept[item["source"]] = kept.get(item["source"], 0) + 1
    for entry in log:
        if entry["status"] == "ok":
            entry["kept"] = kept.get(entry["id"], 0)
    write_json("items.json", {"items": items, "capped": capped}, indent=1)
    write_json("collect_log.json", {"duplicatesDropped": duplicates, "capped": capped, "sources": log}, indent=2)

    errors = check_collect(settings, run_info)
    print(
        f"run folder: {run_info['folder']}  |  {run_info['dateLabel']}  |  "
        f"window {run_info['since']} to {run_info['until']}"
    )
    read = sum(entry["status"] == "ok" for entry in log)
    print(
        f"{len(items)} items from {read} of {len(log)} connections -> items.json"
        + (f" (the newest {cap} in the window)" if capped else "")
    )
    if errors or not read:
        sys.exit(
            "STOP:\n  "
            + "\n  ".join(errors or ["no connection could be read; report the reasons above, never look elsewhere"])
        )

    write_reading(items, settings.scope["cluster"])
    if items:
        todo = "read every part in reading/, write themes.json, tag every item in tags/"
    else:
        todo = 'no feedback in the window, so nothing to read or tag: write themes.json as {"themes": []}'
    print(f"next: {todo}, then run: {step_command('summarise', settings.key)}")


def collect(settings: Settings, run_info: dict) -> tuple[list[dict], list[dict], int]:
    """Every new item in the window from every connection, a log entry per connection, and the duplicates dropped."""
    items, log, seen, duplicates = [], [], set(), 0
    for source in settings.sources:
        entry = {
            "id": source["id"],
            "type": source["type"],
            "label": source.get("label", source["id"]),
            "private": is_private(source, settings),
        }
        try:
            fetched, limit = fetch(source, settings, run_info["since"])
            kept = []
            for fetched_item in fetched:
                date = local_date(fetched_item.get("date"), settings.timezone)
                if not date or not run_info["since"] <= date <= run_info["until"]:
                    continue
                item = dict(
                    fetched_item,
                    date=date,
                    source=source["id"],
                    connection=source["type"],
                    sourceLabel=entry["label"],
                    private=entry["private"],
                    text=scrub(fetched_item.get("text")),
                    title=scrub(fetched_item.get("title")),
                )
                key = re.sub(r"\W+", " ", item["text"].lower()).strip()  # near-identical text is a duplicate
                if key and key not in seen:
                    seen.add(key)
                    kept.append(item)
                elif key:
                    duplicates += 1
            items += kept
            entry.update(status="ok", kept=len(kept))
            if source["type"] == "service":
                entry["link"] = source.get("page")
            if len(fetched) >= limit:
                entry["note"] = f"item limit of {limit} reached; may not cover the whole window"
        except Blocked as refusal:
            entry.update(status="blocked", reason=str(refusal))
        except Exception as error:
            entry.update(status="error", reason=f"{type(error).__name__}: {error}")
        log.append(entry)
        print(
            f"{source['id']:<16} {entry['status']:<8} {entry.get('kept', 0):>4} items  "
            f"{entry.get('reason') or entry.get('note') or ''}"
        )
    return items, log, duplicates


def fetch(source: dict, settings: Settings, since: str) -> tuple[list[dict], int]:
    rules = settings.scope["collect"]
    limit = min(int(source.get("maxItems", rules["maxItemsPerSource"])), rules["maxItemsPerSource"])
    if source["type"] == "service":
        max_pages = settings.scope["connectionTypes"]["service"]["maxPages"]
        return service.fetch(source, since, limit, rules["timeoutSeconds"], max_pages), limit
    if source["type"] == "file":
        return csv_file.fetch(source, since, limit, str(PROFILES_DIR / settings.key)), limit
    return bigquery.fetch(source, since, limit, rules["timeoutSeconds"], rules["warehouseMaxBytesBilled"]), limit


def is_private(source: dict, settings: Settings) -> bool:
    """Private if its kind of connection always is (a warehouse), else as the user scope says, else if keyed."""
    if settings.scope["connectionTypes"][source["type"]].get("private"):
        return True
    return bool(source.get("private", bool(source.get("auth"))))


def local_date(value: object, timezone: str) -> str:
    """The day an item was written, in the profile's timezone.

    A ticket sent at 9am in Sydney is 11pm the day before in UTC, so convert before taking the date.
    """
    text = str(value or "").strip().replace("Z", "+00:00").replace(" UTC", "+00:00")
    text = re.sub(r"([+-]\d\d)$", r"\1:00", text)  # BigQuery writes +00
    try:
        moment = datetime.datetime.fromisoformat(text)
    except ValueError:
        return text[:10]
    if moment.tzinfo:
        moment = moment.astimezone(ZoneInfo(timezone))
    return moment.date().isoformat()


def write_reading(items: list[dict], rules: dict) -> None:
    """Group similar items and write them, group by group, into reading/part_NN.txt.
    Each item's place on the feedback map goes in positions.json."""
    labels, top_words, positions = group_similar(items, rules["k"])
    if positions:
        write_json("positions.json", {item["id"]: place for item, place in zip(items, positions, strict=True)})
    groups = sorted(set(labels), key=lambda label: -labels.count(label))
    lines = []
    for number, label in enumerate(groups, 1):
        members = [item for item, item_label in zip(items, labels, strict=True) if item_label == label]
        lines.append(f"## Cluster {number} ({len(members)} items): {', '.join(top_words[label])}")
        lines += [reading_line(item, rules["textChars"]) for item in members]
        print(f"cluster {number}: {len(members):>4} items  {', '.join(top_words[label][:6])}")

    reading = Path("reading")
    reading.mkdir(exist_ok=True)
    for old_part in reading.iterdir():
        old_part.unlink()
    parts, part, in_part = 0, [], 0
    for index, line in enumerate(lines):
        part.append(line)
        in_part += not line.startswith("## ")
        if in_part >= rules["readingChunk"] or index == len(lines) - 1:
            parts += 1
            (reading / f"part_{parts:02d}.txt").write_text("\n".join(part) + "\n", encoding="utf-8")
            part, in_part = [], 0
    Path("tags").mkdir(exist_ok=True)  # where the agent writes its tags
    print(f"{len(items)} items in {len(groups)} clusters -> reading/ ({parts} parts)")


def group_similar(items: list[dict], most_groups: int) -> tuple[list[int], list[list[str]], list[list[float]]]:
    """Each item's group number, each group's top words, and each item's place on a 2D map.
    Under 12 items, one group in order and no map."""
    if len(items) < 12:
        return [0] * len(items), [[]], []
    try:
        return cluster(items, most_groups)
    except ValueError:  # too few distinct words to compare
        return [0] * len(items), [[]], []


def cluster(items: list[dict], most_groups: int) -> tuple[list[int], list[list[str]], list[list[float]]]:
    tfidf = TfidfVectorizer(stop_words="english", max_df=0.6, min_df=2, sublinear_tf=True)
    weights = tfidf.fit_transform([f"{item.get('title') or ''} {item['text']}" for item in items])
    lsa = TruncatedSVD(n_components=max(2, min(60, weights.shape[1] - 1, len(items) - 1)), random_state=0)
    vectors = normalize(lsa.fit_transform(weights))
    kmeans = KMeans(n_clusters=max(2, min(most_groups, len(items) // 10)), n_init=10, random_state=0).fit(vectors)
    words = tfidf.get_feature_names_out()
    top_words = [
        [words[index] for index in centre.argsort()[::-1][:8]]
        for centre in lsa.inverse_transform(kmeans.cluster_centers_)
    ]
    positions = [[round(float(x), 4), round(float(y), 4)] for x, y in PCA(n_components=2).fit_transform(vectors)]
    return kmeans.labels_.tolist(), top_words, positions


def reading_line(item: dict, length: int) -> str:
    rating = f"{item['rating']:g}/{item['ratingScale']}" if item.get("rating") is not None else "-"
    private = " | private" if item.get("private") else ""
    text = (f"{item['title']}: " if item.get("title") else "") + item["text"]
    return f"{item['id']} | {item['date']} | {rating}{private} | {text[:length]}"


if __name__ == "__main__":
    main()
