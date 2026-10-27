import os
from pathlib import Path

from checks.collect import check_collect
from checks.render import check_render
from checks.summarise import check_summarise
from core.config import Settings
from core.config import read_json_if_exists
from core.runs import fingerprint


def check_send(settings: Settings, run_info: dict) -> list[str]:
    errors = check_collect(settings, run_info) + check_summarise(settings) + check_render(settings, run_info)
    if os.environ.get("PULSE_UNATTENDED") == "1":
        errors += verdict_errors()
    if not settings.recipient:
        errors.append("send: this profile has no recipient; setup adds one")
    built_from = Path("out/built_from.sha256")
    if not errors and (not Path("out/email.eml").exists() or not built_from.exists()):
        errors.append("out/email.eml not found; run render.py first")
    elif not errors and built_from.read_text(encoding="utf-8") != fingerprint():
        errors.append("send: the run's files changed after render.py built the email; run render.py again")
    return errors


def verdict_errors() -> list[str]:
    claims = read_json_if_exists("out/claims.json")
    if claims is None:
        return ["verify: out/claims.json not found; run render.py first"]
    verdicts = read_json_if_exists("verdicts.json", {})
    unverified = [claim["id"] for claim in claims if not verdicts.get(claim["id"], {}).get("supported")]
    if not unverified:
        return []
    return [
        f"verify: {len(unverified) or 'all'} cited claims are not confirmed by the verifier (verdicts.json); "
        "an unattended pulse is only sent when every claim is supported by the items it cites"
    ]
