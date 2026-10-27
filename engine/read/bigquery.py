import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from core.config import PLAIN_NAME
from core.config import read_setting
from read import Blocked
from read import NotAllowed
from read import feedback_item

API = "https://bigquery.googleapis.com/bigquery/v2"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PLAIN_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,299}$")
FIELDS = ("id", "text", "title", "rating", "url", "date")
PAGE_SIZE = 1000


def fetch(source: dict, since: str, limit: int, timeout: float, max_bytes: int) -> list[dict]:
    if source.get("engine", "bigquery") != "bigquery":
        raise NotAllowed(f"warehouse engine `{source.get('engine')}` is not supported")
    job_project = source.get("jobProject") or source["project"]
    if not PLAIN_NAME.match(job_project):
        raise NotAllowed("warehouse `jobProject` must be a plain name")
    sql = build_sql(source, limit)  # proves every name is plain before anything is sent
    token = access_token(source)
    body = {
        "query": sql,
        "useLegacySql": False,
        "parameterMode": "NAMED",
        "timeoutMs": timeout * 1000,
        "maximumBytesBilled": str(int(max_bytes)),
        "maxResults": PAGE_SIZE,
        "queryParameters": [{"name": "since", "parameterType": {"type": "DATE"}, "parameterValue": {"value": since}}],
    }
    if source.get("location"):
        body["location"] = source["location"]
    response = call(f"{API}/projects/{job_project}/queries", token, body)

    job = response.get("jobReference", {})
    results_url = f"{API}/projects/{job_project}/queries/{job.get('jobId')}?maxResults={PAGE_SIZE}"
    if job.get("location"):
        results_url += f"&location={job['location']}"
    deadline = time.time() + timeout
    while not response.get("jobComplete"):
        if time.time() > deadline:
            raise TimeoutError("BigQuery query did not finish in time")
        time.sleep(1)
        response = call(results_url, token)
    columns = [field["name"] for field in response.get("schema", {}).get("fields", [])]
    rows = response.get("rows", [])
    while response.get("pageToken") and len(rows) < limit:
        response = call(f"{results_url}&pageToken={urllib.parse.quote(response['pageToken'])}", token)
        rows += response.get("rows", [])

    items = []
    for row_number, row in enumerate(rows):
        value = dict(zip(columns, (cell.get("v") for cell in row["f"]), strict=False))
        if value.get("text") and value.get("date"):
            items.append(
                feedback_item(
                    source,
                    value.get("id") or row_number,
                    value["date"],
                    value["text"].strip(),
                    value.get("title"),
                    value.get("rating"),
                    value.get("url"),
                )
            )
    return items


def build_sql(source: dict, limit: int) -> str:
    """The newest rows from the day before @since, every value cast to a string."""
    for part in ("project", "dataset", "table"):
        if not PLAIN_NAME.match(str(source.get(part, ""))):
            raise NotAllowed(f"warehouse `{part}` must be a plain name, got {source.get(part)!r}")
    columns = source["columns"]
    for column in columns.values():
        if not PLAIN_COLUMN.match(str(column)):
            raise NotAllowed(f"warehouse column name {column!r} is not a plain identifier")
    date = columns["date"]
    selected = [f"CAST(`{columns[field]}` AS STRING) AS `{field}`" for field in FIELDS if field in columns]
    return (
        f"SELECT {', '.join(selected)} FROM `{source['project']}.{source['dataset']}.{source['table']}` "
        f"WHERE SAFE_CAST(SUBSTR(CAST(`{date}` AS STRING), 1, 10) AS DATE) >= DATE_SUB(@since, INTERVAL 1 DAY) "
        f"ORDER BY `{date}` DESC LIMIT {int(limit)}"
    )


def call(url: str, token: str, payload: dict | None = None) -> dict:
    """POST the payload (or GET without one); a 401 or 403 is reported as Blocked."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        method="POST" if payload is not None else "GET",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        return json.load(urllib.request.urlopen(request, timeout=120))
    except urllib.error.HTTPError as error:
        body = error.read().decode()
        if error.code in (401, 403):
            raise Blocked(f"BigQuery refused access ({error.code}): {body[:200]}") from error
        raise RuntimeError(f"BigQuery error {error.code}: {body[:300]}") from error


def access_token(source: dict) -> str:
    """A fresh token from the sign-in stored in the .env setting the source names in `auth`."""
    name = (source.get("auth") or {}).get("env")
    if not name:
        raise Blocked("the warehouse connection names no sign-in (`auth`); setup explains how to add one")
    if not read_setting(name):
        raise Blocked(f"the sign-in {name} is not set on this computer; setup stores it in .env")
    try:
        credentials = json.loads(read_setting(name))
        body = urllib.parse.urlencode(
            {
                "client_id": credentials["client_id"],
                "client_secret": credentials["client_secret"],
                "refresh_token": credentials["refresh_token"],
                "grant_type": "refresh_token",
            }
        ).encode()
    except (ValueError, KeyError) as error:
        raise Blocked(f"{name} is not a signed-in user's credentials; setup explains how to get them") from error
    try:
        response = urllib.request.urlopen(credentials.get("token_uri", TOKEN_URL), body, timeout=30)
        return json.load(response)["access_token"]
    except urllib.error.HTTPError as error:
        raise Blocked(f"the sign-in was refused ({error.code}); sign in again through setup") from error
