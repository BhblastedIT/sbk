<!-- generated from docs/CONNECTING.md -->
# Pipedrive (`pd-`)

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `pipedrive`). Tested
with a mocked Pipedrive API only, never against a real account. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`) runs `pd-l0-download.py`, and `xs-pipeline-run.py --ingest` runs
`pd-l1-enrich.py` (step `pipedrive`). It writes the generic intake files, which the kernel reads through
`tools/cross-source/plugin_intake.py` (`xs-l2-merge.py`, `xs-l2-knowledge-extract.py`).
**Reads** what your Pipedrive user can see, GET calls only, nothing is written in Pipedrive:
organizations (name), persons (name, emails, phones, organization, job title when Pipedrive sends
it), deals (title, status, value, owner, person, organization, expected close date; archived deals
too), activities (subject, type, due date and time, done, linked persons, attendees, note) and notes
(text, author, what they are attached to). Left out on purpose: custom fields, birthdays, postal
addresses, contact-sync notes, conference links (they can carry passcodes). By default the L1 keeps
only what is yours: deals you own or created, activities you own, created or attend, notes you wrote,
and the persons you own or who appear in those (`pipedrive.scope`, see below).
**You need** a Pipedrive user of your own, with API access. Two ways in, pick one:
- your **personal API token** (the simple route). It is tied to you and to one company:
  if you belong to several Pipedrive companies, each has its own token, and the plugin reads one.
  You have one active token at a time, so regenerating it stops every other tool that uses it.
- an **OAuth app you register yourself** (optional, more steps): a private app in the Developer Hub
  of a free developer sandbox account, with read-only scopes, installed for yourself only.

An admin of your company can turn off API use for your permission set: then the API page is not in
your settings and you cannot get a token. That choice is the company's; ask your admin, the plugin
cannot work around it. Every call also spends your company's shared daily API budget (see Limits).
**Create it** (API token) In Pipedrive open your account name at the top right, **Company settings**
(or **Settings**), **Personal preferences**, **API**, or go straight to
https://app.pipedrive.com/settings/api while signed in. Copy the token. If there is no **API** entry,
your permission set does not allow API use.
Official steps: https://support.pipedrive.com/en/article/how-can-i-find-my-personal-api-key and
https://pipedrive.readme.io/docs/how-to-find-the-api-token; API access per permission set:
https://pipedrive.readme.io/docs/enabling-api-for-company-users
(OAuth, optional) Get a developer sandbox account (https://developers.pipedrive.com/, form on the page),
open **Developer Hub** from its settings menu, **Create an app**, **Create private app**. App name
of your choice; OAuth callback URL `http://127.0.0.1:8765/callback` (one URL per app; another port:
`pipedrive.oauth_redirect_port`). Under **OAuth & access scopes** tick only **Deals: Read only**,
**Contacts: Read only** and **Activities: Read only** (basic user information is always on), never
**Administer account** or a *Full access* scope. Copy the client ID and client secret. A draft app can
be installed only inside the sandbox company; to use it in your real company you make it live with
**Change to live** and install it from its installation link, for yourself (do not add it to other
users). Pipedrive checks the callback URL when you go live, and whether it accepts a loopback address
is not documented: if it refuses, use the API token. Then run `pd-l0-auth.py` once.
Official steps: https://pipedrive.readme.io/docs/developer-sandbox-account,
https://pipedrive.readme.io/docs/marketplace-registering-a-private-app,
https://pipedrive.readme.io/docs/marketplace-oauth-authorization, scopes:
https://pipedrive.readme.io/docs/marketplace-scopes-and-permissions-explanations
**Where the code looks** API token: Keychain `sbk-pipedrive/api-token` first, then the env
`PIPEDRIVE_API_TOKEN` (`tools/pipedrive/pd_api.py:171`, names at `:60-70`). OAuth: client ID from the
Keychain `sbk-pipedrive/client-id`, the env `PIPEDRIVE_CLIENT_ID` or `pipedrive.client_id`; client
secret from `sbk-pipedrive/client-secret` or `PIPEDRIVE_CLIENT_SECRET`; refresh token (written by
`pd-l0-auth.py`) in `sbk-pipedrive/refresh-token`, or the file named by `PIPEDRIVE_TOKEN_FILE`, or
`PIPEDRIVE_REFRESH_TOKEN`. With both set, the API token wins unless `pipedrive.auth` says `oauth`.
The lines are in `.env.example`, section "Pipedrive". The scripts load `.env` by themselves.
```bash
uv run python -c "import keyring, getpass; keyring.set_password('sbk-pipedrive', 'api-token', getpass.getpass('value: '))"
```
**sbk.config.json** nothing is required. Optional section `pipedrive` (every field with its `_help`
in `sbk.config.example.json`): `auth` (`auto`, `api_token` or `oauth`), `scope` (`mine` by default,
`all` keeps every deal, activity, note and person the download saw), `since_days` (first run only:
how many days back by last update; empty = everything you can see), `include_archived_deals`
(default true), `max_requests_per_run` (default 2000; a run that reaches it stops and the next run
continues), `client_id` and `oauth_redirect_port` (OAuth only). If `enabled_sources` is not empty,
list `pipedrive` there: the generic intake reads the `pipedrive` folder only when it is listed.
**Download**
```bash
uv run python tools/pipedrive/pd-l0-download.py --dry-run   # checks the credential, prints your user and company, writes nothing
uv run python tools/pipedrive/pd-l0-download.py             # organizations, persons, deals, activities, notes
uv run python tools/pipedrive/pd-l1-enrich.py               # builds the two parquet files (also run by --ingest)
uv run python tools/pipedrive/pd-l0-auth.py                 # OAuth route only: sign in once in the browser
```
**Check** `<data root>/pipedrive/download-summary.json` (counts per entity, `complete`, `api_calls`,
`api_tokens_estimate`, `burst_limit_per_2s`); after the L1, `<data root>/pipedrive/processed/plugin-contacts.parquet`
and `plugin-interactions.parquet`, then
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
In your Pipedrive company, admins see API usage in the **API Usage Dashboard** of Company settings.
**Limits**
- Daily API budget: one budget per company, shared by every user and every integration, 30,000
  tokens x plan multiplier (Lite 1, Growth 2, Premium 5, Ultimate 7) x seats, reset at midnight
  server time; admins get an email at 75% and 100%, and once it is used up every call gets HTTP 429
  for everyone in the company until the reset. One page of up to 500 records costs 10 tokens on the
  v2 lists, 20 for archived deals and for notes (v1), 2 for your user. The plugin caps each run at
  `max_requests_per_run` and writes its estimate in `api_tokens_estimate`
  (https://pipedrive.readme.io/docs/core-api-concepts-rate-limiting; costs from the `x-token-cost`
  of each endpoint in the API reference, https://developers.pipedrive.com/docs/api/v1).
- Burst limit: per token, rolling 2-second window (API token 20 to 120 requests per plan, OAuth 80 to
  480). The plugin sends at most one request every 0.2 seconds, waits on 429 as the headers say and
  gives up after five tries (exit 1, what was read is kept). Pipedrive blocks with a Cloudflare 403
  the token integrations that keep calling after a 429.
- Incremental by `update_time`: each entity is asked for what changed since its last complete pass
  minus one hour, on Pipedrive's clock. A run stopped by the cap or by a 429 resumes from the newest
  record it read. Notes come from the v1 endpoint with offset pages; each page starts ten records
  early, so a note edited or deleted while the run pages through them does not make it skip
  another one (more than ten such changes inside one page still could; `--full` brings it back).
- Deletions: deals deleted in the last 30 days are removed from the local copy on each run (Pipedrive
  keeps them that long). Deleted persons, organizations, activities and notes are not seen by an
  incremental run and stay in the local copy until `--full`, which re-reads every list and drops
  what Pipedrive no longer lists (a `--full` run cut short by the cap prunes only the lists it read
  to the end).
- Persons: job title arrives only when contact sync is on for the company (Pipedrive's rule). Only
  the primary (else the first) email and phone go into the contact row.
- Commitments: every open activity you own becomes a commitment (due = its due date), and so does
  every open deal you own (due = its expected close date, when set): many open deals mean many
  commitments. A colleague's deal or activity never carries a due date
  in your files, so it does not become your commitment even with `scope: all`. Won deals are written
  as `done`, lost deals as `closed`, the outcome stays in the title. Activity types meeting, lunch and
  call become `meeting`, email becomes `message`, task, deadline and custom types become `record`.
- A person's first and last contact dates come from past events only: a planned call does not
  count until its date has passed.
- Links: Pipedrive's API docs do not describe the web app URLs. The plugin writes
  `https://<company>.pipedrive.com/person/<id>`, `/deal/<id>`, `/organization/<id>`, and for
  activities and notes the page they are attached to plus `#activity-<id>` / `#note-<id>`: the pattern
  has not been checked against a real account.
- Leads, products, projects, files, email sync, custom fields and user lists are not read. People who
  are only colleagues in Pipedrive (users) appear only as activity attendees.
- OAuth: the access token lasts 60 minutes and is refreshed by the plugin; the refresh token expires
  if unused for 60 days, then `pd-l0-auth.py` again. A sandbox account with no app created within 45
  days, or no private app made live within six months, is deleted by Pipedrive.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#pipedrive](../../docs/CONNECTING.md#pipedrive). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
