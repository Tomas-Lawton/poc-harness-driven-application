# Connections

Each connection in `user_scope.json` → `sources` has a short `id` (letters, digits, dashes and underscores; it becomes the start of every item id, like `zendesk-012`), a plain `label`, and a `type`: `service`, `warehouse` or `file`. It maps the provider's field names onto the feedback fields: `date` and `text` are required; `id`, `title`, `rating` and `url` are optional. Dates must be ISO (`2026-10-23` or a full timestamp) or Unix times; other formats are skipped. `maxItems` should cover the window; each run reads the newest 500 items across all connections.

**Ratings:** map a rating or score to `rating` and set `ratingScale` to its top value (5 for stars, 10 for 0 to 10 scores).

Test each connection with `collect.py` and show the user a sample before keeping it.

## Online service

Any JSON API, read with plain GET requests to the hosts you record (`engine/read/service.py`). There is no connector code: write the connection from the provider's API docs.

- Choose a read endpoint that lists recent feedback, newest first.
- Use `{page}` in the address for paging and `{since}` for the window start, where the API supports them.
- Map fields in `columns`; dotted paths work (`user.name`). Set `itemsPath` if the items are nested, and `skipIf` to a field that marks entries that aren't feedback (`pull_request` on GitHub).
- `hosts` lists every host the connection may call, including the token address.

**Keys.** Ask for a **read-only** key and say in one line where to create it; if the provider only offers keys that can write, say so and suggest a file export. Store it in `.env` in the project root and name it in `auth`, never the key itself:

- A bearer key: `{"type": "bearer", "env": "INTERCOM_TOKEN"}`. Add `"optional": true` when the API also works without one.
- An OAuth client whose tokens expire: store the client id and secret in `.env` and use `{"type": "client_credentials", "tokenUrl": "...", "idEnv": "...", "secretEnv": "...", "scope": "read"}`. The reader fetches a fresh read-only token every run.

Connections with a key are private unless the data is public and the user agrees to `"private": false`.

**Starting points** (check the provider's current docs; these change):

| Provider | Address | Notes |
|---|---|---|
| Zendesk | `https://<sub>.zendesk.com/api/v2/tickets.json?sort_by=created_at&sort_order=desc&per_page=100&page={page}` | OAuth client (Confidential), `tokenUrl: https://<sub>.zendesk.com/oauth/tokens`, scope `read`; `itemsPath: tickets` |
| Intercom | `https://api.intercom.io/conversations` | Bearer; `itemsPath: conversations` |
| GitHub Issues | `https://api.github.com/repos/<owner>/<repo>/issues?state=all&sort=created&direction=desc&since={since}&per_page=100&page={page}` | Bearer, optional; `skipIf: pull_request` |

```json
{"id": "zendesk", "type": "service", "label": "Zendesk tickets",
 "url": "https://acme.zendesk.com/api/v2/tickets.json?sort_by=created_at&sort_order=desc&page={page}",
 "hosts": ["acme.zendesk.com"],
 "auth": {"type": "client_credentials", "tokenUrl": "https://acme.zendesk.com/oauth/tokens",
          "idEnv": "ZENDESK_CLIENT_ID", "secretEnv": "ZENDESK_CLIENT_SECRET", "scope": "read"},
 "itemsPath": "tickets",
 "columns": {"id": "id", "date": "created_at", "title": "subject", "text": "description"},
 "maxPages": 10}
```

## Internal warehouse or data store

One BigQuery table or view (`engine/read/bigquery.py`). Ask for the project, dataset and table, and what each column holds. If feedback is spread over tables, suggest the data owner makes one view. The pulse reads BigQuery as the person who signs in, so their account needs read access to that dataset (BigQuery Data Viewer, plus Job User on the project). Always private.

**Sign-in.** Ask the user to run `gcloud auth application-default login` themselves (`--no-launch-browser` on a remote machine). Put the contents of the file it writes (`~/.config/gcloud/application_default_credentials.json`) on one line in `.env`, for example `BIGQUERY_CREDENTIALS={...}`, and name it in the connection's `auth`. Tell the user the pulse reads as them, and stops working if they sign out, revoke it or leave.

```json
{"id": "survey", "type": "warehouse", "engine": "bigquery", "project": "...", "dataset": "...", "table": "...",
 "auth": {"env": "BIGQUERY_CREDENTIALS"}, "columns": {"date": "created_at", "text": "body"}}
```

## File

A CSV export saved in `profiles/<key>/data/` (offer to move it). Read its header row, map the columns, and ask whether it's private.

```json
{"id": "tickets", "type": "file", "file": "data/tickets.csv", "columns": {"date": "Created", "text": "Body"}, "private": true}
```
