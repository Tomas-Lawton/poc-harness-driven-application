import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ENGINE_DIR = Path(__file__).absolute().parent.parent
PROJECT_ROOT = ENGINE_DIR.parent
PROFILES_DIR = PROJECT_ROOT / "profiles"
RUNS_DIR = PROJECT_ROOT / "runs"
PLAIN_NAME = re.compile(r"^[A-Za-z0-9_-]+$")  # connection ids, key names, warehouse names


def read_setting(name: str) -> str | None:
    """From the environment, else from .env in the project root (never committed)."""
    if os.environ.get(name):
        return os.environ[name]
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.strip().split("=", 1)
            if key.strip() == name:
                return value.strip().strip("\"'")
    return None


def read_json(path: Path | str) -> Any:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def read_json_if_exists(path: Path | str, default: Any = None) -> Any:
    return read_json(path) if Path(path).exists() else default


def write_json(path: Path | str, data: Any, indent: int | None = None) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=indent, ensure_ascii=False)


@dataclass(frozen=True)
class Profile:
    product_name: str
    title: str
    window_days: int
    delivery: str  # chat, email or both
    colours: dict[str, str]


@dataclass(frozen=True)
class Settings:
    key: str
    profile: Profile
    scope: dict  # engine/scope.json
    user_scope: dict  # profiles/<key>/user_scope.json

    @property
    def sources(self) -> list[dict]:
        return self.user_scope["sources"]

    @property
    def timezone(self) -> str:
        return self.user_scope["timezone"]

    @property
    def recipient(self) -> str | None:
        return (self.user_scope.get("recipients") or [None])[0]


def load_settings(profile_key: str) -> Settings:
    """The profile's settings, or stop if they go beyond the use case scope."""
    scope = read_required_json(ENGINE_DIR / "scope.json")
    user_scope = read_required_json(PROFILES_DIR / profile_key / "user_scope.json")
    raw_profile = read_profile(profile_key)
    profile = Profile(
        product_name=raw_profile.get("product", profile_key),
        title=raw_profile.get("title", "Customer Pulse"),
        window_days=parse_days(raw_profile.get("time window", "")),
        delivery=(raw_profile.get("output") or "both").lower(),
        colours=parse_colours(raw_profile.get("colours", "")),
    )
    problems = user_scope_problems(profile_key, scope, user_scope, profile.delivery) + profile_problems(
        profile, raw_profile, scope
    )
    if problems:
        sys.exit(
            f"BLOCKED: profiles/{profile_key} is outside the use case scope:\n  "
            + "\n  ".join(problems)
            + "\nOnly setup can change the user scope (setup/SKILL.md)."
        )
    return Settings(profile_key, profile, scope, user_scope)


def read_required_json(path) -> dict:
    if not path.exists():
        sys.exit(f"FAIL: {os.path.relpath(path, PROJECT_ROOT)} not found")
    return read_json(path)


# PROFILE.md


def read_profile(profile_key: str) -> dict[str, str]:
    """The `name: value` settings at the top of PROFILE.md, names in lower case."""
    path = PROFILES_DIR / profile_key / "PROFILE.md"
    if not path.exists():
        sys.exit(f"FAIL: profiles/{profile_key}/PROFILE.md not found")
    text = path.read_text(encoding="utf-8")
    settings = {}
    if text.startswith("---") and text.count("---") >= 2:
        for line in text.split("---", 2)[1].splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                name, value = line.split(":", 1)
                settings[name.strip().lower()] = value.strip()
    return settings


def parse_days(text: str) -> int:
    """Days in a time window written as "7" or "7 days"; 7 if left out."""
    words = text.split()
    return int(words[0]) if words and words[0].isdigit() else 7


def parse_colours(text: str) -> dict[str, str]:
    """Colours written as "brand #0b2545, accent #c9a227"."""
    pairs = (part.split() for part in text.split(","))
    return {pair[0]: pair[1] for pair in pairs if len(pair) == 2}


def profile_problems(profile: Profile, raw_profile: dict[str, str], scope: dict) -> list[str]:
    problems = []
    if profile.delivery not in ("chat", "email", "both"):
        problems.append("PROFILE.md `output` must be chat, email or both")
    if not 1 <= profile.window_days <= scope["collect"]["maxDays"]:
        problems.append(f"PROFILE.md `time window` must be 1 to {scope['collect']['maxDays']} days")
    for name, colour in profile.colours.items():
        if not re.fullmatch(r"#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?", colour):
            problems.append(f"PROFILE.md colour `{name}` must be a hex colour like #0b2545")
    for name in sorted(set(raw_profile) - {"product", "title", "reader", "time window", "output", "colours"}):
        problems.append(
            f"PROFILE.md sets `{name}`, which is not a profile setting "
            "(connections, recipients and schedule belong in user_scope.json)"
        )
    return problems


# user_scope.json


def user_scope_problems(profile_key: str, scope: dict, user_scope: dict, delivery: str) -> list[str]:
    problems = []
    try:
        ZoneInfo(user_scope.get("timezone", ""))
    except Exception:
        problems.append(f"timezone `{user_scope.get('timezone')}` is not a valid IANA name")

    most_recipients = scope["send"]["maxRecipients"]
    fewest_recipients = 0 if delivery == "chat" else 1  # a chat-only pulse is never emailed
    if not fewest_recipients <= len(user_scope.get("recipients") or []) <= most_recipients:
        problems.append(f"needs {fewest_recipients} to {most_recipients} recipients")

    sources = user_scope.get("sources") or []
    if not sources:
        problems.append("has no connections")
    seen_ids = set()
    for source in sources:
        source_id = source.get("id")
        if not PLAIN_NAME.match(str(source_id)) or source_id in seen_ids:
            problems.append(f"every connection needs a unique, plain id ({source_id})")
        seen_ids.add(source_id)
        problems += source_problems(profile_key, source, scope)
    return problems


def source_problems(profile_key: str, source: dict, scope: dict) -> list[str]:
    source_id, kind = source.get("id"), source.get("type")
    kinds = scope["connectionTypes"]
    if kind not in kinds:
        return [f"`{source_id}` is a `{kind}`; the use case supports {', '.join(kinds)}"]

    problems = []
    most_items = scope["collect"]["maxItemsPerSource"]
    if source.get("maxItems", 0) > most_items:
        problems.append(f"`{source_id}` maxItems is above the limit of {most_items}")
    columns = source.get("columns") or {}
    if kind in ("warehouse", "file"):
        shape = scope["itemShape"]
        problems += [
            f"`{source_id}` must map the `{field}` column" for field in shape["required"] if field not in columns
        ]
        fields = shape["required"] + shape["optional"]
        problems += [f"`{source_id}` maps `{field}`, not a feedback field" for field in columns if field not in fields]
    if "rating" in columns and not source.get("ratingScale"):
        problems.append(f"`{source_id}` maps a rating but no `ratingScale` (5 for stars, 10 for 0 to 10 scores)")
    if kind == "warehouse":
        for name in ("project", "dataset", "table"):
            if not PLAIN_NAME.match(str(source.get(name, ""))):
                problems.append(f"`{source_id}` needs a plain `{name}` name")
        auth = source.get("auth")
        if auth is not None and (set(auth) != {"env"} or not PLAIN_NAME.match(str(auth["env"]))):
            problems.append(
                f"`{source_id}` auth must only name the .env setting that holds its sign-in (`env`); "
                "never put the credentials themselves here"
            )
    if kind == "file":
        folder = os.path.normpath(PROFILES_DIR / profile_key)
        path = os.path.normpath(os.path.join(folder, str(source.get("file", ""))))
        if not source.get("file") or not path.startswith(folder + os.sep):
            problems.append(f"`{source_id}` needs a file inside the profile folder")
    if kind == "service":
        problems += service_problems(source, kinds["service"])
    return problems


def service_problems(source: dict, rules: dict) -> list[str]:
    """Https to approved hosts only, a page limit, and keys named in .env, never stored."""
    source_id, problems = source.get("id"), []
    hosts = source.get("hosts") or []
    host = host_of(source.get("url"))
    if not host or not hosts:
        problems.append(f"`{source_id}` needs an https `url` and its `hosts`")
    elif host not in hosts:
        problems.append(f"`{source_id}` reads {host}, which is not in its hosts")
    if int(source.get("maxPages", 1)) > rules["maxPages"]:
        problems.append(f"`{source_id}` maxPages is above the limit of {rules['maxPages']}")

    auth = source.get("auth")
    if not auth:
        return problems
    if auth.get("type") == "client_credentials":
        names_ok = PLAIN_NAME.match(str(auth.get("idEnv", ""))) and PLAIN_NAME.match(str(auth.get("secretEnv", "")))
        allowed = {"type", "tokenUrl", "idEnv", "secretEnv", "scope"}
        if not names_ok or host_of(auth.get("tokenUrl")) not in hosts or set(auth) - allowed:
            problems.append(
                f"`{source_id}` client_credentials auth needs `tokenUrl` on an approved host "
                "and `idEnv` and `secretEnv` naming values in .env"
            )
    elif (
        auth.get("type") not in rules["authTypes"]
        or not PLAIN_NAME.match(str(auth.get("env", "")))
        or set(auth) - {"type", "env", "optional"}
    ):
        problems.append(
            f"`{source_id}` auth must name a key in .env (`env`) with a type of {', '.join(rules['authTypes'])}; "
            "never put the key itself here"
        )
    return problems


def host_of(url: object) -> str:
    url = str(url or "")
    return url.split("/")[2] if url.startswith("https://") and url.count("/") >= 2 else ""
