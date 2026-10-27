---
name: customer-pulse-setup
description: Sets up or changes a Customer Pulse in one short conversation: the user's connections (online service, internal warehouse or data store, file), time window, output format (chat, email or both) and schedule. Writes the user scope (with the user's confirmation) and the profile, deploys a scheduled run on Google Cloud if wanted, then runs the first pulse. Use when the user says "Use the setup skill", or at the start of a conversation when no user profile exists (even a plain "hi"), or to change a profile, a connection, the recipient, email or the schedule.
---

# Customer Pulse setup

Setup writes two files for a client:

- **`profiles/<key>/user_scope.json`: what the pulse may reach.** Connections, recipient, schedule. Only setup writes it, and only after the user confirms. It can only narrow `engine/scope.json`; every script refuses anything outside it.
- **`profiles/<key>/PROFILE.md`: how the pulse is presented.** A few settings, then the client's own words. The user can change it any time.

## Rules

- **The user is not technical.** Never ask them to run commands or edit files. Install what's missing yourself and ask only for what you can't know.
- **Ask all six questions below, one per message, in order.** Keep each message to a line or two. Never skip a question because it has a default: offer the default so they can say "yes". Skip only what they've already answered.
- **Don't build anything until all six are answered.** Then summarise once and ask the user to confirm before saving.
- **Every connection is read only.** Never offer write access or posting.
- **Stay in the project and the sandbox.** One virtual environment in `.venv/` (see [pulse/SKILL.md](../pulse/SKILL.md)); if `python3 -m venv` fails because `ensurepip` is missing, use `uv venv .venv && uv pip install --python .venv/bin/python3 -r requirements.txt`. Profiles go in `profiles/`, secrets in `.env`, runs in `runs/`. Never install system-wide, use `sudo`, or change the user's global settings. Keep the harness's sandbox on; if it blocks something, tell the user and let them allow it.
- **Mention only what the user uses.** Don't bring up warehouses, Google Cloud or sign-ins unless their connections or schedule need them. If they do, ask before using `gcloud` and let the user sign in themselves.

## The six questions

1. **About you:** the product or company and who reads the pulse. If not clear, follow up with their city (for the timezone) and what matters most.
2. **Connections:** what they use for customer feedback. Offer examples; they can name anything:
   > Helpdesks: Zendesk, Intercom, Freshdesk, Jira Service Management, HubSpot · Issue trackers: GitHub Issues · Surveys and reviews: Typeform, SurveyMonkey, Trustpilot, Canny · A data warehouse table · Or any export file · Or try it with no accounts, using [example data](#example-data)
3. **Time window:** how much feedback each pulse covers. Default the last 7 days; up to 31.
4. **Output:** in the chat and by email (the default), or only one. For email, ask the details in [Email](#email).
5. **Schedule:** on request, or automatically ("every Monday at 8am").
6. **Look** (optional): the pulse's name and colours, a **logo** (square PNG or JPG, at least 128×128) and a **header image** (about 1280×320, no text on it; it sits darkened behind the title). Save them as `profiles/<key>/assets/logo.png` and `header.png` (or `.jpg`); offer to move files they point you to.

The user names their tools; you work out each connection from [connections.md](connections.md). If a service can't be read with a read-only bearer key or an OAuth client, explain why and offer a file export.

## Then

1. **Create `profiles/<key>/`** with a short lowercase key (`capital-bank`). Write `PROFILE.md`. Only these settings exist, one value each, no notes after them:
   ```
   ---
   product: Capital Bank of Australia
   title: Weekly Customer Pulse
   reader: Priya Raman, General Manager, Customer Experience
   time window: 7 days
   output: both
   colours: brand #0b2545, brand2 #13315c, accent #c9a227
   ---
   **Who it's for.** ... **What matters.** ... **Tone.** ... **Standing instructions.** ...
   ```
   `output` is `chat`, `email` or `both`. Write the free text in the user's words: who reads it, what matters, what is urgent, what to keep apart, how to route tickets, the tone. Never invent facts about the company.
2. **Write `user_scope.json`:**
   ```json
   {"timezone": "Australia/Sydney", "recipients": ["reader@company.com"], "sources": [...], "schedule": null}
   ```
   For a chat-only pulse, leave `recipients` empty. Test each connection by running `collect.py` and showing the user a few items from `items.json`. Keep it only when they confirm.
3. **Set up [Email](#email) and the [Schedule](#schedule)** if chosen. Read back the connections, recipient and schedule, and ask the user to confirm. That confirmation is the approval.
4. **Run the first pulse** with [pulse/SKILL.md](../pulse/SKILL.md) and present it in the chosen output. If the output includes email, run `send.py`, and either confirm it was sent or show exactly why it was blocked. Never finish setup without one or the other.

## Example data

When the user wants to try the pulse without their own accounts, set it up with the example: 300 feedback items from Nimbus Air, a fictional airline. Still ask the six questions, but offer these answers so they can just say yes:

- **About you:** product `Nimbus Air`, profile key `nimbus-air`, timezone `Australia/Sydney`; ask who reads it and what matters, or suggest "Head of Customer Experience" and "safety, delays and refunds".
- **Connection:** copy `example/nimbus-air-feedback.csv` to `profiles/nimbus-air/data/feedback.csv`, then move every `created` date forward by the same number of days so the newest is today (a throwaway script; keep the times and timezone). Then add:
  ```json
  {"id": "surveys", "type": "file", "label": "Post-flight surveys", "file": "data/feedback.csv",
   "columns": {"id": "id", "date": "created", "text": "comment", "rating": "stars"}, "ratingScale": 5, "private": false}
  ```
- **Output:** chat only, so no email setup is needed. **Schedule:** on request.

## Email

The pulse is sent as the email itself, from a Gmail account the user owns, to the recipient in the user scope. Ask for the **address to send from** and the **address to send to** (they can be the same). Then walk them through an app password:

1. Use a personal Gmail account; work and school accounts often block app passwords.
2. At https://myaccount.google.com/security, turn on **2-Step Verification** if it is off.
3. At https://myaccount.google.com/apppasswords, type a name such as `Customer Pulse` and click **Create**.
4. Google shows a 16-letter password once. That is the app password, not their normal password.

They can paste it in the chat, or (better) paste it into `.env` themselves after `SMTP_PASSWORD=`. Write `.env` in the project root and tell them its full path; it is never committed:

```
SMTP_HOST=smtp.gmail.com
SMTP_USER=you@gmail.com
SMTP_PASSWORD=app-password
```

`SMTP_PORT` defaults to 587. Set `SMTP_FROM` only if the pulse should come from a different address than `SMTP_USER`. Save the recipient in `user_scope.json` → `recipients`. Send email only with `send.py`; changing the recipient later is a user scope change.

## Schedule

Record it in `user_scope.json` → `schedule`, for example `{"days": ["Mon"], "time": "08:00"}`. A scheduled run has nobody in the chat, so it always sends by email. It carries only `pulse/SKILL.md`, never this skill, so it can't change its own reach, and it can only write to `runs/`. To deploy one, follow [schedule.md](schedule.md). This path is designed but not yet proven end to end: tell the user so.

## Changing things later

- **Focus, tone, look, output:** edit `PROFILE.md`. Save preferences only there, never in your harness's memory, which is shared across clients.
- **Private feedback is quoted word for word** by default. If the user asks not to, set `"privateQuotes": false` in `user_scope.json`; private themes are then described and cited but not quoted.
- **A connection, the recipient or the schedule:** a user scope change. Follow the sections above and confirm with the user.
- **A new kind of connection, write access, looser limits, posting replies:** a change to the use case itself, not setup. Say so.
