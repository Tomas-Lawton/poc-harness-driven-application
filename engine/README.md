# The engine

The scripts that end each step of a Customer Pulse. The agent does the judgement (themes, tags,
writing); these scripts collect the feedback, count everything, check the agent's work and build
the pulse. Run each step from the repository root: `python3 engine/steps/collect.py <profile key>`.

| Folder | What lives there |
|---|---|
| `steps/` | The four steps: `collect.py`, `summarise.py`, `render.py`, `send.py`. Each ends by running its check. |
| `checks/` | The check for each step, in a module with the same name. |
| `core/` | `config.py` (paths, `.env`, JSON, and PROFILE.md and user_scope.json checked against the scope), `runs.py` (run folders), `text.py` (citations, quotes and numbers in the agent's writing), `page.py` (the pulse page, used as the email and the preview). |
| `read/` | One read-only reader per kind of connection: an online service, a BigQuery table, a CSV file. |
| `pulse.html` | The page's skeleton and its stylesheet. |
| `scope.json` | The use case scope: the most a pulse may ever do. |

Steps work inside the run folder (`runs/<profile key>/<date>/`), so run files are read by name.

## Code style

- Names say what a thing is: `theme`, `item_id`, `settings`, never `t`, `iid` or `cfg`.
- A function gets a docstring only when its name and signature don't already say what it does.
- A step defines `main()` and does nothing at import time.
- The JSON files keep their camelCase keys (they are the contract with the agent); Python names are `snake_case`.
- Error messages are written for the agent: what is wrong and how to fix it.

```bash
ruff format engine tests && ruff check engine tests && pytest
```

The tests in `tests/` check the checks: each one breaks a correct run in one way and confirms the right check catches it.
