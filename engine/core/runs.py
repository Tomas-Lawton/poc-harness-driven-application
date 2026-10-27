import datetime
import hashlib
import os
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from core.config import PROFILES_DIR
from core.config import PROJECT_ROOT
from core.config import RUNS_DIR
from core.config import Settings
from core.config import load_settings
from core.config import read_json
from core.config import read_json_if_exists
from core.config import write_json


def step_command(step: str, profile_key: str) -> str:
    """How to run a step, with the same Python this one runs with (the project's .venv when it is there)."""
    python = (
        os.path.relpath(sys.executable, PROJECT_ROOT) if sys.executable.startswith(str(PROJECT_ROOT)) else "python3"
    )
    return f"{python} engine/steps/{step}.py {profile_key}"


def start_run(profile_key: str) -> tuple[Settings, dict]:
    """Start today's run folder afresh (in the profile's timezone), write run.json, and move into it.

    A second run on the same day replaces the first: its items get new ids, so earlier tags and
    themes would point at the wrong feedback.
    """
    settings = load_settings(profile_key)
    now = datetime.datetime.now(ZoneInfo(settings.timezone))
    today = now.date()
    since = today - datetime.timedelta(days=settings.profile.window_days - 1)

    run_dir = RUNS_DIR / profile_key / today.isoformat()
    if run_dir.exists():
        shutil.rmtree(run_dir)
    (run_dir / "out").mkdir(parents=True)
    run_info = {
        "key": profile_key,
        "date": today.isoformat(),
        "dateLabel": f"{now:%A} {now.day} {now:%B %Y}",
        "since": since.isoformat(),
        "until": today.isoformat(),
        "windowLabel": f"{since.day} {since:%b} to {today.day} {today:%b} {today.year}",
        "folder": os.path.relpath(run_dir, PROJECT_ROOT),
        "startedAt": now.isoformat(timespec="seconds"),
    }
    write_json(run_dir / "run.json", run_info, indent=2)
    os.chdir(run_dir)
    return settings, run_info


def open_latest_run(profile_key: str) -> tuple[Settings, dict]:
    folders = sorted((RUNS_DIR / profile_key).glob("????-??-??"))
    if not folders:
        sys.exit(f"FAIL: no run for `{profile_key}` yet; start with: {step_command('collect', profile_key)}")
    os.chdir(folders[-1])
    return load_settings(profile_key), read_json("run.json")


def profile_key_from_command_line() -> str:
    if len(sys.argv) >= 2:
        return sys.argv[1]
    profiles = ", ".join(sorted(folder.name for folder in PROFILES_DIR.glob("*") if folder.is_dir()))
    step = os.path.basename(sys.argv[0]).removesuffix(".py")
    sys.exit(f"usage: {step_command(step, '<profile key>')}. Profiles: {profiles or 'none yet (setup creates one)'}")


def read_items() -> dict[str, dict]:
    return {item["id"]: item for item in read_json_if_exists("items.json", {"items": []})["items"]}


def fingerprint() -> str:
    """A hash of the files the pulse is built from, so send.py can tell if they changed after render."""
    digest = hashlib.sha256()
    for name in ("items.json", "themes.json", "summary.json", "plan.json", "live_content.json"):
        digest.update(Path(name).read_bytes() if Path(name).exists() else b"")
    return digest.hexdigest()
