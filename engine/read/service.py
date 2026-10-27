import datetime
import email.utils
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from core.config import read_setting
from read import Blocked
from read import NotAllowed
from read import earliest_date
from read import feedback_item

USER_AGENT = "customer-pulse-agent/1.0 (reads customer feedback the user approved)"
REFUSED = (401, 402, 403, 407, 429, 451)  # access refused or rate limited


def fetch(source: dict, since: str, limit: int, timeout: float, max_pages: int) -> list[dict]:
    """Read page by page while the address has {page}, stopping at a page with nothing new enough."""
    headers = authorization(source)
    columns = source.get("columns") or {}
    first_date = earliest_date(since)
    items = []
    for page in range(1, min(int(source.get("maxPages", 1)), max_pages) + 1):
        url = source["url"].replace("{page}", str(page)).replace("{since}", f"{since}T00:00:00Z")
        data = get(url, source["hosts"], timeout, headers)
        entries = value_at(data, source["itemsPath"]) if source.get("itemsPath") else data
        if not isinstance(entries, list):
            entries = [entries] if entries else []
        new_enough = 0
        for index, entry in enumerate(entries):
            if source.get("skipIf") and isinstance(entry, dict) and entry.get(source["skipIf"]):
                continue
            item = to_item(source, columns, entry, f"{page}-{index}")
            if not item or item["date"][:10] < first_date:
                continue
            new_enough += 1
            items.append(item)
            if len(items) >= limit:
                return items
        if not entries or not new_enough or "{page}" not in source["url"]:
            break
    return items


def to_item(source: dict, columns: dict, entry: Any, fallback_id: str) -> dict | None:
    """The entry as a feedback item, or None for an entry without a date or text."""
    date = parse_date(value_at(entry, columns.get("date", "date")))
    title = plain_text(value_at(entry, columns["title"])) if "title" in columns else ""
    text = plain_text(value_at(entry, columns.get("text", "text"))) or title
    if not date or not text:
        return None
    return feedback_item(
        source,
        value_at(entry, columns.get("id", "id")) or fallback_id,
        date,
        text,
        title,
        value_at(entry, columns["rating"]) if "rating" in columns else None,
        value_at(entry, columns["url"]) if "url" in columns else source.get("page"),
    )


def get(url: str, hosts: list[str], timeout: float, headers: dict) -> Any:
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https":
        raise NotAllowed(f"{url} is not https")
    if host not in hosts:
        raise NotAllowed(f"{host} is not an approved host for this source ({', '.join(hosts) or 'none'})")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_host = urllib.parse.urlsplit(response.geturl()).hostname or ""
            if final_host not in hosts:
                raise Blocked(f"redirected to {final_host}, which is not approved (often a login page)")
            return json.loads(response.read().decode("utf8", "replace"))
    except urllib.error.HTTPError as error:
        if error.code in REFUSED:
            raise Blocked(f"{host} answered {error.code}: access refused or rate limited") from error
        raise


def authorization(source: dict) -> dict:
    """The Authorization header: a bearer key from .env, or a fresh OAuth client-credentials token."""
    auth = source.get("auth")
    if not auth:
        return {}
    if auth["type"] == "client_credentials":
        return {"Authorization": f"Bearer {client_credentials_token(auth, source['hosts'])}"}
    key = read_setting(auth["env"])
    if not key:
        if auth.get("optional"):
            return {}
        raise Blocked(f"the key {auth['env']} is not set on this computer; setup stores it in .env")
    return {"Authorization": f"Bearer {key}"}


def client_credentials_token(auth: dict, hosts: list[str]) -> str:
    client_id, client_secret = read_setting(auth["idEnv"]), read_setting(auth["secretEnv"])
    if not (client_id and client_secret):
        raise Blocked(f"{auth['idEnv']} or {auth['secretEnv']} is not set on this computer; setup stores them in .env")
    if (urllib.parse.urlsplit(auth["tokenUrl"]).hostname or "") not in hosts:
        raise NotAllowed("the token address is not an approved host")
    body = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": auth.get("scope", "read"),
    }
    request = urllib.request.Request(
        auth["tokenUrl"],
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        return json.load(urllib.request.urlopen(request, timeout=30))["access_token"]
    except urllib.error.HTTPError as error:
        raise Blocked(f"the token request was refused ({error.code})") from error


def value_at(data: Any, path: str) -> Any:
    """The value at a dotted path like "data.reviews", taking the first element of any list."""
    for key in str(path).split("."):
        if isinstance(data, list):
            data = data[0] if data else None
        data = data.get(key) if isinstance(data, dict) else None
    return data


def parse_date(value: Any) -> str:
    """Unix seconds or milliseconds, an ISO date (kept as written) or an email-style date, as ISO."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) or str(value).isdigit():
        seconds = float(value) / (1000 if float(value) > 1e11 else 1)
        return datetime.datetime.fromtimestamp(seconds, datetime.UTC).isoformat()
    value = str(value).strip()
    if value[:4].isdigit():
        return value
    try:
        return email.utils.parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return ""


def plain_text(value: Any) -> str:
    """HTML tags removed, entities decoded, spaces collapsed."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()
