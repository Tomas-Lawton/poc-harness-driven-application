import copy
import json
from pathlib import Path

import pytest

from checks.collect import check_collect
from checks.render import check_render
from checks.send import verdict_errors
from checks.summarise import check_summarise
from core.config import ENGINE_DIR
from core.config import Profile
from core.config import Settings
from core.config import read_json
from core.config import source_problems

RUN_INFO = {
    "since": "2026-10-21",
    "until": "2026-10-27",
    "dateLabel": "Tuesday 27 October 2026",
    "windowLabel": "21 Oct to 27 Oct 2026",
}
TEXTS = [
    "The app crashes every time I open my statement.",
    "Since the update the app crashes on login.",
    "The app crashes when I try to pay a bill.",
    "Crashes again, the app closes as soon as I log in.",
    "The app crashes whenever I check my balance.",
    "Great service at the branch today.",
]
CRASHES = [f"tickets-00{number}" for number in range(1, 6)]
THEME = {
    "id": "app-crashes",
    "title": "The app crashes on login and when opening statements",
    "kind": "problem",
    "summary": "Customers say the app crashes when they open it or log in.",
    "evidence": [
        {"item": "tickets-001", "quote": "The app crashes every time I open my statement."},
        {"item": "tickets-002", "quote": "Since the update the app crashes on login."},
    ],
    "scores": {"impact": 3, "actionability": 2},
    "decision": "keep",
    "reason": "It stops people using the app.",
    "computed": {"count": 5, "share": 83.3, "trend": "steady", "score": 8, "items": CRASHES},
}
PLAN = {
    "headline": "App crashes are the main problem.",
    "actions": [{"theme": "app-crashes"}],
    "themes": ["app-crashes"],
}
CONTENT = {
    "meta": {"dateLabel": RUN_INFO["dateLabel"], "windowLabel": RUN_INFO["windowLabel"]},
    "subject": "Pulse: app crashes",
    "preheader": "App crashes are the main problem.",
    "headline": "App crashes are the main problem this week.",
    "actions": [
        {
            "theme": "app-crashes",
            "owner": "Head of mobile",
            "ticket": {
                "title": "Fix the app crash on login",
                "issue": "The app crashes on login and when opening statements.",
                "items": ["tickets-001", "tickets-002"],
            },
        }
    ],
    "themes": [
        {
            "id": "app-crashes",
            "title": "The app crashes",
            "summary": "Customers say the app crashes when they open it or log in [tickets-001, tickets-002].",
            "quotes": THEME["evidence"],
        }
    ],
    "watch": [],
    "questions": ["Did the crashes start with the latest release?", "Which phones are affected?"],
    "footer": "Read from the tickets connection.",
}


def write(name: str, data: object) -> None:
    Path(name).write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def settings() -> Settings:
    user_scope = {
        "timezone": "Australia/Sydney",
        "recipients": ["reader@example.com"],
        "sources": [{"id": "tickets", "type": "file", "file": "data/tickets.csv"}],
    }
    profile = Profile(product_name="Acme", title="Pulse", window_days=7, delivery="both", colours={})
    return Settings("acme", profile, read_json(ENGINE_DIR / "scope.json"), user_scope)


@pytest.fixture
def run(tmp_path, monkeypatch) -> Path:
    """A run folder where every check passes; each test breaks one thing."""
    monkeypatch.chdir(tmp_path)
    items = [
        {"id": f"tickets-00{number}", "source": "tickets", "date": "2026-10-25", "text": text}
        for number, text in enumerate(TEXTS, 1)
    ]
    write("items.json", {"items": items})
    write("themes.json", {"themes": [THEME]})
    write("summary.json", {"totals": {"items": 6}, "untaggedShare": 17, "themes": [THEME["computed"]]})
    write("plan.json", PLAN)
    write("live_content.json", CONTENT)
    return tmp_path


def change(name: str, edit) -> None:
    data = read_json(name)
    edit(data)
    write(name, data)


def errors_mention(errors: list[str], text: str) -> bool:
    return any(text in error for error in errors)


def test_a_correct_run_passes_every_check(run, settings):
    assert check_collect(settings, RUN_INFO) == []
    assert check_summarise(settings) == []
    assert check_render(settings, RUN_INFO) == []


# Collect


def test_an_item_from_an_unapproved_connection_is_caught(run, settings):
    change("items.json", lambda data: data["items"][0].update(source="somewhere-else"))
    assert errors_mention(check_collect(settings, RUN_INFO), "not an approved connection")


def test_an_item_outside_the_window_is_caught(run, settings):
    change("items.json", lambda data: data["items"][0].update(date="2026-09-01"))
    assert errors_mention(check_collect(settings, RUN_INFO), "outside the window")


# Themes and tags


def test_an_invented_quote_is_caught(run, settings):
    change(
        "themes.json", lambda data: data["themes"][0]["evidence"][0].update(quote="The app is the worst I have used.")
    )
    assert errors_mention(check_summarise(settings), "does not appear word for word")


def test_a_quote_from_an_item_not_in_the_theme_is_caught(run, settings):
    quote = {"item": "tickets-006", "quote": "Great service at the branch today."}
    change("themes.json", lambda data: data["themes"][0]["evidence"].append(quote))
    assert errors_mention(check_summarise(settings), "must name an item tagged with this theme")


def test_a_kept_theme_below_the_keep_score_is_caught(run, settings):
    change("themes.json", lambda data: data["themes"][0]["computed"].update(score=2))
    assert errors_mention(check_summarise(settings), "is kept with score 2")


def test_quoting_private_feedback_is_caught_when_setup_said_no(run, settings):
    change("items.json", lambda data: [item.update(private=True) for item in data["items"]])
    settings.user_scope["privateQuotes"] = False
    assert errors_mention(check_summarise(settings), "quotes a private item")


def test_too_much_untagged_feedback_is_caught(run, settings):
    change("summary.json", lambda data: data.update(untaggedShare=60))
    assert errors_mention(check_summarise(settings), "fit no kept theme")


# The writing


def test_a_sentence_without_a_citation_is_caught(run, settings):
    change("live_content.json", lambda data: data["themes"][0].update(summary=THEME["summary"]))
    assert errors_mention(check_render(settings, RUN_INFO), "cites no items")


def test_citing_an_item_outside_the_theme_is_caught(run, settings):
    summary = "Customers say the app crashes [tickets-001, tickets-002, tickets-006]."
    change("live_content.json", lambda data: data["themes"][0].update(summary=summary))
    assert errors_mention(check_render(settings, RUN_INFO), "not tagged with this theme")


def test_a_number_not_counted_by_code_is_caught(run, settings):
    change("live_content.json", lambda data: data.update(headline="App crashes affected 42 customers this week."))
    assert errors_mention(check_render(settings, RUN_INFO), "uses the number 42")


def test_a_changed_quote_is_caught(run, settings):
    quotes = copy.deepcopy(THEME["evidence"])
    quotes[0]["quote"] = "The app crashes all the time."
    change("live_content.json", lambda data: data["themes"][0].update(quotes=quotes))
    assert errors_mention(check_render(settings, RUN_INFO), "is not one of the theme's checked quotes")


def test_a_week_with_no_feedback_passes(run, settings):
    write("items.json", {"items": []})
    write("themes.json", {"themes": []})
    write("summary.json", {"totals": {"items": 0}, "untaggedShare": 0, "themes": []})
    write("plan.json", {"headline": "No feedback came in.", "quietWeek": True, "actions": [], "themes": []})
    quiet = {**CONTENT, "headline": "No feedback came in this week.", "actions": [], "themes": []}
    write("live_content.json", quiet)
    assert check_collect(settings, RUN_INFO) + check_summarise(settings) + check_render(settings, RUN_INFO) == []


# The send gate


def test_an_unattended_send_needs_every_claim_confirmed(run):
    Path("out").mkdir()
    write("out/claims.json", [{"id": "claim-1"}, {"id": "claim-2"}])
    write("verdicts.json", {"claim-1": {"supported": True}})
    assert errors_mention(verdict_errors(), "not confirmed by the verifier")
    write("verdicts.json", {"claim-1": {"supported": True}, "claim-2": {"supported": True}})
    assert verdict_errors() == []


# The user scope


@pytest.mark.parametrize(
    ("source", "problem"),
    [
        ({"id": "x", "type": "file", "file": "../../secrets.csv", "columns": {"date": "d", "text": "t"}}, "inside"),
        ({"id": "x", "type": "service", "url": "https://evil.example/api", "hosts": ["good.example"]}, "not in its"),
        (
            {"id": "x", "type": "service", "url": "https://a.example/", "hosts": ["a.example"], "auth": {"key": "abc"}},
            "never put the key itself here",
        ),
        ({"id": "x", "type": "email-inbox"}, "the use case supports"),
    ],
    ids=["file outside the profile", "unapproved host", "a key stored in the scope", "unknown kind of connection"],
)
def test_a_connection_outside_the_use_case_is_refused(source, problem):
    scope = read_json(ENGINE_DIR / "scope.json")
    assert errors_mention(source_problems("acme", source, scope), problem)
