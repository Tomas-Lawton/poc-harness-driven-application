import base64
import datetime
import hashlib
import shutil
import sys
from email.message import EmailMessage
from email.utils import format_datetime
from email.utils import make_msgid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parents[1]))  # engine/

from checks.render import check_render
from core.config import PROFILES_DIR
from core.config import read_json
from core.config import write_json
from core.page import Page
from core.runs import fingerprint
from core.runs import open_latest_run
from core.runs import profile_key_from_command_line
from core.text import CITATION
from core.text import cited_item_ids
from core.text import sentences

try:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot
    from matplotlib.lines import Line2D
except ImportError:
    sys.exit("matplotlib is missing; install it with: python3 -m pip install -r requirements.txt")

MARKERS = "o^sDv"


def main() -> None:
    settings, run_info = open_latest_run(profile_key_from_command_line())
    errors = check_render(settings, run_info)
    if errors:
        sys.exit("FIX plan.json or live_content.json, then run render.py again:\n  " + "\n  ".join(errors))

    content = read_json("live_content.json")
    items = {item["id"]: item for item in read_json("items.json")["items"]}
    claims = build_claims(content, items)
    page = Page(settings, content, read_json("summary.json"), items)

    out = Path("out")
    images = copy_profile_images(settings.key, out)
    if draw_map(content, read_json("summary.json"), out):
        images["map"] = "map.png"
    content_ids = {name: make_msgid(domain="pulse.local")[1:-1] for name in images}
    email_html = page.html({name: f"cid:{content_id}" for name, content_id in content_ids.items()})
    # The same page with the images inside it, so it shows wherever it is opened (a browser or a harness's panel).
    preview_html = page.html({name: data_address(out / file_name) for name, file_name in images.items()})

    (out / "preview.html").write_text(preview_html, encoding="utf-8")
    write_json(out / "claims.json", claims, indent=1)
    (out / "built_from.sha256").write_text(fingerprint(), encoding="utf-8")
    message = EmailMessage()
    message["Subject"] = content["subject"]
    if settings.recipient:
        message["To"] = settings.recipient
    message["Date"] = format_datetime(datetime.datetime.now().astimezone())
    message.set_content(email_html, subtype="html")
    for name, content_id in content_ids.items():  # embedded, so Gmail shows them without fetching
        subtype = "png" if images[name].endswith(".png") else "jpeg"
        message.add_related(
            (out / images[name]).read_bytes(),
            "image",
            subtype,
            cid=f"<{content_id}>",
            disposition="inline",
            filename=images[name],
        )
    (out / "email.eml").write_bytes(bytes(message))

    print(f"wrote {run_info['folder']}/out/preview.html, claims.json and email.eml")
    print(f"preview: {(out / 'preview.html').absolute()}")


def data_address(path: Path) -> str:
    subtype = "png" if path.suffix == ".png" else "jpeg"
    return f"data:image/{subtype};base64,{base64.b64encode(path.read_bytes()).decode()}"


def copy_profile_images(profile_key: str, out: Path) -> dict[str, str]:
    """Copy assets/header and assets/logo (PNG or JPG) next to the preview; returns their file names."""
    found = {}
    for name in ("header", "logo"):
        candidates = [
            PROFILES_DIR / profile_key / "assets" / f"{name}.{extension}" for extension in ("png", "jpg", "jpeg")
        ]
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path:
            found[name] = Path(shutil.copy(path, out)).name
    return found


def draw_map(content: dict, summary: dict, out: Path) -> bool:
    """Every item at its place from collect.py: colour shows its theme, shape shows its connection."""
    if not Path("positions.json").exists():
        return False
    positions = read_json("positions.json")
    items = {item["id"]: item for item in read_json("items.json")["items"]}
    themes = {theme["id"]: theme for theme in read_json("themes.json")["themes"]}
    shown = [entry["id"] for entry in (content.get("themes") or []) + (content.get("watch") or [])]
    colours = {theme_id: pyplot.cm.tab10(number % 10) for number, theme_id in enumerate(shown)}
    theme_of = {}
    for theme_id in reversed(shown):  # an item in several themes takes the first one shown
        theme_of.update(dict.fromkeys(themes[theme_id]["computed"]["items"], theme_id))
    connections = [connection for connection in summary["connections"] if connection["status"] == "ok"]
    shapes = {connection["id"]: MARKERS[index % len(MARKERS)] for index, connection in enumerate(connections)}

    figure, axes = pyplot.subplots(figsize=(8, 5), dpi=160)
    for item_id, (x, y) in positions.items():
        theme_id = theme_of.get(item_id)
        axes.scatter(
            x,
            y,
            s=26 if theme_id else 12,
            marker=shapes.get(items[item_id]["source"], "o"),
            color=colours.get(theme_id, "#c3cad3"),
            edgecolors="white",
            linewidths=0.4,
            zorder=3 if theme_id else 2,
        )
    for number, theme_id in enumerate(shown, 1):  # each theme's number sits at the centre of its items
        points = [
            positions[item_id] for item_id, theme in theme_of.items() if theme == theme_id and item_id in positions
        ]
        if points:
            centre = [sum(axis) / len(points) for axis in zip(*points, strict=True)]
            box = {"boxstyle": "circle,pad=0.3", "fc": colours[theme_id], "ec": "white"}
            axes.annotate(
                str(number),
                centre,
                color="white",
                fontsize=8,
                fontweight="bold",
                ha="center",
                va="center",
                zorder=4,
                bbox=box,
            )

    source_key = [
        Line2D([], [], marker=shapes[connection["id"]], color="#55606e", linestyle="", label=connection["label"])
        for connection in connections
    ]
    axes.add_artist(
        axes.legend(handles=source_key, loc="upper right", fontsize=7.5, title="Shape = source", title_fontsize=7.5)
    )
    theme_key = [
        Line2D(
            [], [], marker="o", color=colours[theme_id], linestyle="", label=f"{number}. {themes[theme_id]['title']}"
        )
        for number, theme_id in enumerate(shown, 1)
    ]
    if theme_key:
        axes.legend(handles=theme_key, loc="upper left", bbox_to_anchor=(0, -0.02), frameon=False, fontsize=7.5)
    axes.set_facecolor("#f4f5f7")
    axes.set_xticks([])
    axes.set_yticks([])
    for side in axes.spines.values():
        side.set_visible(False)
    figure.savefig(out / "map.png", facecolor="white", bbox_inches="tight")
    pyplot.close(figure)
    return True


def build_claims(content: dict, items: dict[str, dict]) -> list[dict]:
    claims = []
    for where, text in cited_writing(content):
        for sentence in sentences(text):
            item_ids = cited_item_ids(sentence)
            if not item_ids:
                continue
            claim = CITATION.sub("", sentence).strip()
            claims.append(
                {
                    "id": hashlib.sha1(f"{where}|{claim}".encode()).hexdigest()[:10],
                    "where": where,
                    "claim": claim,
                    "cited": [{"id": item_id, "text": item_text(items.get(item_id, {}))} for item_id in item_ids],
                }
            )
    return claims


def cited_writing(content: dict) -> list[tuple[str, str]]:
    """Each piece of writing that carries citations, by where it sits.

    A quote counts as a claim too: that it is a clear example of its theme.
    """
    themes, watched = content.get("themes") or [], content.get("watch") or []
    writing = [("headline", content.get("headline"))]
    writing += [(f"theme {theme['id']}", theme.get("summary")) for theme in themes]
    writing += [(f"watch {entry['id']}", entry.get("why")) for entry in watched]
    for entry in themes + watched:
        example = f'This feedback is a clear example of "{entry.get("title", "")}"'
        writing += [(f"quote {entry['id']}", f"{example} [{quote['item']}].") for quote in entry.get("quotes") or []]
    for action in content.get("actions") or []:
        ticket = action.get("ticket") or {}
        if ticket.get("issue") and ticket.get("items"):
            writing.append((f"ticket {action['theme']}", f"{ticket['issue']} [{', '.join(ticket['items'])}]"))
    return writing


def item_text(item: dict) -> str:
    return ((item.get("title") or "") + " " + item.get("text", "")).strip()


if __name__ == "__main__":
    main()
