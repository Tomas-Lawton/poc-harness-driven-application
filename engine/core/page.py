import html
import string

from core.config import ENGINE_DIR
from core.config import Settings
from core.text import CITATION

TABLE = "<table role='presentation' width='100%' cellpadding='0' cellspacing='0'>"
COLOURS = {  # the defaults for pulse.html; PROFILE.md `colours` can change any of them
    "brand": "#1f3a5f",
    "accent": "#e07a2f",
    "ink": "#111827",
    "muted": "#6b7280",
    "line": "#e5e7eb",
    "bg": "#f5f6f8",
    "problem": "#c2410c",
    "request": "#2563eb",
    "praise": "#15803d",
    "question": "#7c3aed",
}


def escape(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def row(inner: str, css_class: str = "pad") -> str:
    return f"<tr><td class='{css_class}'>{inner}</td></tr>"


def card(inner: str, css_class: str = "") -> str:
    return row(f"<div class='box {css_class}'>{inner}</div>")


def grid(boxes: list[tuple[str, str]]) -> str:
    """(inner, class) boxes two to a row, the same height; they stack on a phone."""

    def cell(inner: str, css_class: str) -> str:
        return f"<td class='col box {css_class}' width='49%' valign='top'>{inner}</td>"

    rows = [
        row(f"{TABLE}<tr>{cell(*left)}<td class='gap' width='2%'></td>{cell(*right)}</tr></table>")
        for left, right in zip(boxes[0:-1:2], boxes[1::2], strict=False)
    ]
    return "".join(rows) + (card(*boxes[-1]) if len(boxes) % 2 else "")


def section(title: str, subtitle: str = "") -> str:
    subtitle = f"<div class='secsub'>{subtitle}</div>" if subtitle else ""
    return row(f"<div class='sectitle'>{escape(title)}</div><div class='rule'></div>{subtitle}", "sec")


def stat(label: str, value: object, note: str = "") -> str:
    return (
        f"<td class='stat' width='25%'><div class='num'>{escape(value)}</div>"
        f"<div class='lbl'>{escape(label)}</div><div class='tiny'>{note}</div></td>"
    )


def stars(rating: float | None, scale: int | None) -> str:
    if rating is None or not scale:
        return ""
    filled = round(rating / scale * 5)
    star = "&#9733;"
    return f"<span class='accent'>{star * filled}</span><span class='off'>{star * (5 - filled)}</span>"


def is_web_link(url: object) -> bool:
    return str(url or "").startswith(("https://", "http://"))


def or_na(value: object, unit: str = "") -> str:
    return "n/a" if value is None else f"{value}{unit}"


class Page:
    """Builds the page from the run's files. `cited` fills up as the sections cite items."""

    def __init__(self, settings: Settings, content: dict, summary: dict, items: dict):
        self.settings = settings
        self.content = content
        self.summary = summary
        self.items = items
        self.colours = {**COLOURS, **settings.profile.colours}
        self.colours.setdefault("brand2", self.colours["accent"])
        self.connections = {connection["id"]: connection for connection in summary.get("connections", [])}
        self.source_classes = {
            source_id: f"s{index % 5}"
            for index, source_id in enumerate(self.connections)  # pulse.html has s0 to s4
        }
        self.theme_counts = {theme["id"]: theme for theme in summary["themes"]}
        self.cited: list[str] = []

    def html(self, images: dict[str, str]) -> str:
        """The whole page, with each image ("header", "logo") at the address given."""
        body = "".join(
            [
                self.header(images),
                row(self.cite(self.content["headline"]), "headline"),
                self.stats(),
                *self.feedback_map(images),
                section("At a glance"),
                card(self.volume_chart()),
                card(self.themes_chart()) if self.summary["themes"] else "",
                *self.themes(),
                *self.watchlist(),
                *self.actions(),
                *self.questions(),
                self.footer(),
                self.evidence(),
            ]
        )
        template = string.Template((ENGINE_DIR / "pulse.html").read_text(encoding="utf-8"))
        return template.substitute(
            self.colours,
            title=escape(self.content["subject"]),
            preheader=escape(self.content["preheader"]),
            body=body,
        )

    # Pieces

    def cite(self, text: str) -> str:
        """The agent's text, escaped, with its citations as numbered links to the evidence list."""

        def numbered_links(citation) -> str:
            links = []
            for item_id in (item_id.strip() for item_id in citation.group(1).split(",")):
                if item_id not in self.cited:
                    self.cited.append(item_id)
                links.append(f"<a href='#ev-{escape(item_id)}'>{self.cited.index(item_id) + 1}</a>")
            return f"<sup class='cite'>[{','.join(links)}]</sup>"

        return CITATION.sub(numbered_links, escape(text))

    def source_label(self, source_id: str) -> str:
        connection = self.connections.get(source_id, {})
        label = escape(connection.get("label") or source_id)
        return f"<a href='{escape(connection['link'])}'>{label}</a>" if connection.get("link") else label

    def source_tag(self, source_id: str) -> str:
        return f"<span class='tag {self.source_classes.get(source_id, 's0')}'>{self.source_label(source_id)}</span>"

    def source_counts(self, counts: dict) -> str:
        return "".join(
            f"{self.source_tag(source_id)}<span class='count'>{count}</span>"
            for source_id, count in (counts.get("sources") or {}).items()
        )

    def quote(self, quote: dict) -> str:
        item = self.items.get(quote["item"], {})
        details = " &middot; ".join(
            filter(None, [escape(item.get("date")), stars(item.get("rating"), item.get("ratingScale"))])
        )
        link = f" &middot; <a href='{escape(item['url'])}'>open</a>" if is_web_link(item.get("url")) else ""
        return (
            f"<div class='quote'><div class='text'>&ldquo;{escape(quote['quote'])}&rdquo;</div>"
            f"<div class='small'>{self.source_tag(item.get('source'))}{details}{link}</div></div>"
        )

    # Sections, top to bottom

    def header(self, images: dict[str, str]) -> str:
        background = ""
        if images.get("header"):  # darkened so the title stays readable; clients without it show the brand colour
            shade = "rgba(0,0,0,0.55)"
            background = (
                f" style=\"background-image:linear-gradient({shade},{shade}),url('{images['header']}');"
                'background-size:cover;background-position:center"'
            )
        logo = ""
        if images.get("logo"):
            image = f"<img class='logo' src='{images['logo']}' width='76' height='76' alt=''/>"
            logo = f"<td width='92' valign='middle'>{image}</td>"
        meta = self.content["meta"]
        title = (
            f"<div class='prod'>{escape(self.settings.profile.product_name)}</div>"
            f"<div class='name'>{escape(self.settings.profile.title)}</div>"
            f"<div class='when'>{escape(meta['dateLabel'])} &middot; feedback from {escape(meta['windowLabel'])}</div>"
        )
        strip = f"{TABLE}<tr>{logo}<td valign='middle'>{title}</td></tr></table>"
        return f"<tr><td class='hd' bgcolor='{self.colours['brand']}'{background}>{strip}</td></tr>"

    def stats(self) -> str:
        totals, statuses = self.summary["totals"], self.summary["sources"]
        cells = [
            stat("Items", totals["items"], "newest in the window" if self.summary.get("capped") else ""),
            stat("Avg rating", or_na(totals["avgRating"])),
            stat("1 or 2 stars", or_na(totals["lowShare"], "%")),
            stat(
                "Connections",
                f"{statuses['ok']} of {sum(statuses.values())}",
                f"{statuses['blocked']} blocked" if statuses["blocked"] else "all read",
            ),
        ]
        table = TABLE.replace("<table", "<table class='stats'")
        return row(f"{table}<tr>{''.join(cells)}</tr></table>", "top")

    def feedback_map(self, images: dict[str, str]) -> list[str]:
        if not images.get("map"):
            return []
        image = (
            f"<img src='{images['map']}' width='712' alt='Every item placed by similarity, coloured by theme' "
            "style='display:block;width:100%;height:auto'/>"
        )
        how = (
            "<div class='small'><b>How the map is made:</b> code turns each piece of feedback into numbers from the "
            "words it uses (TF-IDF), compresses them so words that tend to appear together count as related (LSA), "
            "groups similar items with K-means so the agent reads them together, and flattens everything onto two "
            "dimensions (PCA), so feedback that says similar things sits close together. The colours are the agent's "
            "themes, from reading every item; grey dots fit no theme. The axes have no units: only closeness "
            "matters.</div>"
        )
        subtitle = "Each dot is one piece of feedback, placed near similar feedback and coloured by theme"
        return [section("Feedback map", subtitle), card(image + how)]

    def volume_chart(self) -> str:
        days = self.summary["daily"]
        busiest = max([day["count"] for day in days] + [1])
        columns = "".join(
            f"<td valign='bottom' align='center'><div class='tiny'>{day['count']}</div>"
            f"<div class='vbar' style='height:{max(2, round(110 * day['count'] / busiest))}px'></div>"
            f"<div class='tiny'>{day['date'][8:].lstrip('0')}</div>"
            f"<div class='tiny accent'>{day['avgRating'] if day['avgRating'] is not None else '&nbsp;'}</div></td>"
            for day in days
        )
        return (
            "<div class='chart'>Feedback per day <span class='tiny'>(<span class='accent'>average rating</span> below)"
            f"</span></div>{TABLE}<tr>{columns}</tr></table>"
        )

    def themes_chart(self) -> str:
        themes = self.summary["themes"]
        largest = max([theme["count"] for theme in themes] + [1])
        rows = "".join(
            f"<tr><td width='40%' class='cell'>{escape(theme['title'])}</td><td>"
            f"<div class='bar b-{theme['kind']}' style='width:{max(3, round(100 * theme['count'] / largest))}%'>"
            "</div></td>"
            f"<td width='36' align='right' class='tiny'>{theme['count']}</td></tr>"
            for theme in themes
        )
        legend = " ".join(
            f"<span class='c-{kind}'>&#9632; {kind}</span>" for kind in ("problem", "request", "praise", "question")
        )
        return (
            f"<div class='chart'>Items per theme</div>{TABLE}{rows}</table><div class='small'>{legend}</div>"
            "<div class='small'>The agent gives each theme a kind after reading its feedback: "
            "<b>problem</b>, something broken or in the way; <b>request</b>, something customers want added or "
            "changed; <b>praise</b>, something working well; <b>question</b>, customers unsure how something "
            "works.</div>"
        )

    def theme_box(self, theme: dict) -> tuple[str, str]:
        counts = self.theme_counts[theme["id"]]
        rating = f" &middot; average rating {counts['avgRating']}" if counts["avgRating"] is not None else ""
        size = (
            f"{counts['count']} items &middot; {counts['share']}% of all feedback &middot; "
            f"{counts['firstHalf']} then {counts['secondHalf']} across the period"
        )
        private_note = (
            "<div class='note'>No quotes: this feedback is private, so it is described and cited but not quoted "
            "(setup can allow quoting for a pulse that stays inside the company).</div>"
        )
        inner = (
            f"<a name='{escape(theme['id'])}' id='{escape(theme['id'])}'></a>"
            f"<div><span class='pill solid p-{counts['kind']}'>{escape(counts['kind'])}</span></div>"
            f"<div class='title'>{escape(theme['title'])}</div><div class='small'>{size}{rating}</div>"
            f"<div class='text'>{self.cite(theme['summary'])}</div>"
            + ("".join(self.quote(quote) for quote in theme.get("quotes") or []) or private_note)
            + f"<div class='small'>From {self.source_counts(counts)}</div>"
        )
        return inner, f"k-{counts['kind']}"

    def themes(self) -> list[str]:
        """The problem, request and question themes, then the praise themes."""
        issues = [theme for theme in self.content["themes"] if self.theme_counts[theme["id"]]["kind"] != "praise"]
        working = [theme for theme in self.content["themes"] if self.theme_counts[theme["id"]]["kind"] == "praise"]
        rows = []
        if issues:
            rows.append(section("What customers are saying", "Every quote is word for word, with its source"))
            rows += [card(*self.theme_box(theme)) for theme in issues]
        if working:
            rows.append(section("What's working", "What customers praise: worth passing on to the teams behind it"))
            rows.append(grid([self.theme_box(theme) for theme in working]))
        return rows

    def watchlist(self) -> list[str]:
        if not self.content.get("watch"):
            return []
        counts_by_id = {counts["id"]: counts for counts in self.summary.get("watch", [])}
        boxes = []
        for entry in self.content["watch"]:
            counts = counts_by_id.get(entry["id"], {})
            count = counts.get("count", 0)
            inner = (
                f"<div class='title'>{escape(entry['title'])}</div>"
                f"<div class='small'>{count} item{'s' if count != 1 else ''} &middot; "
                f"From {self.source_counts(counts)}</div>"
                f"<div class='text'>{self.cite(entry['why'])}</div>"
                + "".join(self.quote(quote) for quote in entry.get("quotes") or [])
            )
            boxes.append((inner, "watch"))
        return [section("Watchlist", "Rare but serious: only a few items, but worth knowing about"), grid(boxes)]

    def actions(self) -> list[str]:
        """Each action is its draft ticket: who owns it, the title, the issue and the feedback it rests on."""
        if not self.content.get("actions"):
            return []
        rows = [section("Take action", "Most important first, each with a draft ticket for the owning team")]
        for number, action in enumerate(self.content["actions"], 1):
            ticket = action["ticket"]
            issue = CITATION.sub("", ticket["issue"]).replace(" .", ".").strip()  # its items are listed below it
            ticket_html = (
                f"<div class='lbl'>Draft ticket for {escape(action.get('owner'))} &middot; not filed</div>"
                f"<div class='title'>{escape(ticket['title'])}</div><div class='text'>{escape(issue)}</div>"
                f"<div class='small'>Feedback: {self.cite('[' + ', '.join(ticket['items']) + ']')}</div>"
            )
            badge = f"<td width='40' valign='top'><div class='badge'>{number}</div></td>"
            rows.append(card(f"{TABLE}<tr>{badge}<td valign='top'>{ticket_html}</td></tr></table>"))
        return rows

    def questions(self) -> list[str]:
        questions = "".join(f"<li>&ldquo;{escape(question)}&rdquo;</li>" for question in self.content["questions"])
        return [
            section("Ask your agent"),
            card(
                "<div class='text'>Ask the agent in the conversation where this pulse was made, or open the project in "
                "your agent harness. It answers from this pulse's evidence, with every claim cited. For example:"
                f"<ul>{questions}</ul></div><div class='small'>You can also ask it to change the pulse "
                "(&ldquo;make it shorter&rdquo;) or add a connection.</div>"
            ),
        ]

    def footer(self) -> str:
        sources = []
        for connection in self.connections.values():
            ok = connection["status"] == "ok"
            outcome = (
                f"{connection.get('kept', 0)} items"
                if ok
                else f"{connection['status']}: {connection.get('reason', '')}"
            )
            if connection.get("note"):
                outcome += f" ({connection['note']})"
            private = " (private)" if connection.get("private") else ""
            sources.append(f"{self.source_label(connection['id'])}{private}: {escape(outcome)}")
        return row(
            f"<b>Sources.</b> {'; '.join(sources)}.<br/>{escape(self.content['footer'])}<br/>Written by an AI agent. "
            "Every quote was checked word for word against the collected feedback, every number was computed by code, "
            "and private feedback is quoted only when setup allows it. Email addresses, phone numbers and long "
            "reference numbers are removed before anything is written.",
            "foot",
        )

    def evidence(self) -> str:
        """Every cited item, numbered, one short line each (the full text stays with the run)."""
        rows = []
        for number, item_id in enumerate(self.cited, 1):
            item = self.items.get(item_id, {})
            link = f" &middot; <a href='{escape(item['url'])}'>open</a>" if is_web_link(item.get("url")) else ""
            text = (f"{item['title']}: " if item.get("title") else "") + item.get("text", "")
            if len(text) > 160:
                text = text[:157].rsplit(" ", 1)[0] + "…"
            rows.append(
                f"<tr id='ev-{escape(item_id)}'><td class='ev'><b>[{number}]</b> {self.source_tag(item.get('source'))}"
                f"<span class='tiny'>{escape(item_id)} &middot; {escape(item.get('date'))} "
                f"{stars(item.get('rating'), item.get('ratingScale'))}{link}</span><br/>{escape(text)}</td></tr>"
            )
        everything = (
            f"<div class='small'>All {len(self.items)} items collected are kept with this run; "
            "ask your agent about any of them.</div>"
        )
        return section("Evidence", "Every item the pulse cites") + card(f"{TABLE}{''.join(rows)}</table>{everything}")
