<!-- generated from docs/CONNECTING.md -->
# Jira and Confluence (`as-`)

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `atlassian`). Tested
with a mocked Jira and Confluence only, never against a real site. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`) runs `as-l0-download.py`, and `xs-pipeline-run.py --ingest` runs
`as-l1-enrich.py` (step `atlassian`). It writes the generic intake files, which the kernel reads through
`tools/cross-source/plugin_intake.py` (`xs-l2-merge.py`, `xs-l2-knowledge-extract.py`).
**Reads** with your own API token, GET calls only, on your Atlassian Cloud site: the Jira issues you
created or reported, are assigned to, or watch, with status, due date, project, type, description
(first 4,000 characters), reporter, creator, assignee and, when an issue has more than one watcher,
the watcher list; the Confluence pages you created or edited, with space, version, creator, last
editor and contributors. Nothing is written in Jira or Confluence.
**You need** your Atlassian Cloud site address (for example `https://your-site.atlassian.net`), the
email of your Atlassian account, and an API token you create yourself in your account. No admin
role and no app to install.
**Create it** You open https://id.atlassian.com/manage-profile/security/api-tokens (your Atlassian
account, **Security**, **Create and manage API tokens**). If you log in with a password or Google,
Atlassian first emails you a one-time code. Then either:
- **Create API token** (without scopes): give it a name and an expiry (1 to 365 days), **Create**,
  **Copy to clipboard**. One token covers Jira and Confluence. This is the simplest route.
- **Create API token with scopes** (Atlassian recommends it as more secure): name, expiry, then
  pick the **app** and the scopes. For Jira choose `read:jira-work` and `read:jira-user`; for
  Confluence `search:confluence` and `read:confluence-user`. If the list offers only granular
  scopes, the ones the endpoints name are, for Jira, `read:issue-details:jira`,
  `read:issue-meta:jira`, `read:field-configuration:jira`, `read:audit-log:jira`,
  `read:avatar:jira`, `read:issue.watcher:jira`, `read:user:jira`, `read:group:jira`,
  `read:application-role:jira`, and for Confluence `read:content-details:confluence`. The creation page asks for one app, so
  for both products you create two tokens and store them as the Jira and the Confluence token below.
  A scoped token cannot call your site address: the plugin then goes through
  `https://api.atlassian.com/ex/jira/<cloud id>` and `.../ex/confluence/<cloud id>`, and finds the
  cloud id of your site by itself.
You copy the token at once: Atlassian does not show it again.
Official steps: https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/
Basic auth with email and token: https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/
Scopes: https://developer.atlassian.com/cloud/jira/platform/scopes-for-oauth-2-3LO-and-forge-apps/ and
https://developer.atlassian.com/cloud/confluence/scopes-for-oauth-2-3LO-and-forge-apps/
**Where the code looks** (`tools/atlassian/as_api.py`, `resolve_token` and `load_settings`)
- token for Jira: Keychain `sbk-atlassian/jira-token`, env `ATLASSIAN_JIRA_API_TOKEN`, then the
  shared token Keychain `sbk-atlassian/api-token`, env `ATLASSIAN_API_TOKEN`;
- token for Confluence: Keychain `sbk-atlassian/confluence-token`, env
  `ATLASSIAN_CONFLUENCE_API_TOKEN`, then the same shared token;
- site: `atlassian.site` in `sbk.config.json`, else env `ATLASSIAN_SITE`; email: `atlassian.email`,
  else `ATLASSIAN_EMAIL`; cloud id (only for scoped tokens, optional): `atlassian.cloud_id`, else
  `ATLASSIAN_CLOUD_ID`.
The download script loads `.env` by itself.
```bash
uv run python -c "import keyring, getpass; keyring.set_password('sbk-atlassian', 'api-token', getpass.getpass('value: '))"
```
**sbk.config.json** section `atlassian`: `site` and `email` (required unless set in `.env`);
optional `token_kind` (`auto` by default: tries your site, then the api.atlassian.com route for a
scoped token; `unscoped` or `scoped` to skip the try), `cloud_id`, `products` (default
`["jira", "confluence"]`), `jira_projects` and `confluence_spaces` (keys to restrict the reading,
empty = all you can see), `since_days` (first Jira download, 365), `confluence_since_days` (first
Confluence download, 180), `max_watcher_calls_per_run` (200). List `atlassian` in `enabled_sources`
if that list is not empty.
**Download**
```bash
uv run python tools/atlassian/as-l0-download.py --dry-run   # checks the token(s), prints who you are and the route, writes nothing
uv run python tools/atlassian/as-l0-download.py             # Jira issues and Confluence pages, incremental
uv run python tools/atlassian/as-l0-download.py --full      # re-reads everything, drops what no longer matches
uv run python tools/atlassian/as-l1-enrich.py               # builds the two parquet files (also run by --ingest)
```
**Check** `<data root>/atlassian/download-summary.json` (route per product, issues, pages,
watcher lists read, API calls, `products_skipped` if one product refused); after the L1,
`<data root>/atlassian/processed/plugin-contacts.parquet` and `plugin-interactions.parquet`, then
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
**Limits**
- Atlassian Cloud only (`*.atlassian.net`); Jira and Confluence Data Center or Server are not read.
- People's email is the one their profile shows you: depending on each person's profile visibility
  it comes back empty, and the contact is then matched by name only. App accounts (automation, bots)
  are left out, and so are deleted accounts, which Atlassian shows as "Former user"
  (https://support.atlassian.com/confluence-cloud/docs/what-happens-when-an-account-is-deactivated-vs-deleted/):
  otherwise every deleted person would merge into one contact.
- A due date counts as your commitment only on issues you are assigned to or created or reported:
  on an issue you only watch the due date is not written, because the kernel would count every open
  issue with a due date as yours. Jira can make you watch every issue you create or comment on
  (the autowatch setting of your profile or of the site), so "issues you watch" can be many.
- An issue is `done` when its status category is done or it has a resolution date; any other
  status is `open`. The status name, project and type go in the `text` column. The Jira status
  category keys in Atlassian's example (`in-flight`, `completed`) differ from the usual `done`; the
  resolution date is the fallback. Not checked against a real site.
- Watcher lists are read only for issues with more than one watcher, again only when the issue
  changed (or after 30 days), at most `max_watcher_calls_per_run` per run; the rest waits for the
  next run (`watchers_left_for_next_run`). Seeing other watchers needs the "View voters and
  watchers" permission in the project; otherwise the list is skipped (`watchers_denied`).
- Incremental: Jira issues updated since the last run plus one hour (relative JQL minutes, so the
  time zone of your Jira profile does not matter), Confluence pages modified since the day before
  the last run. An issue that stopped matching (you were unassigned, stopped watching) stays until
  `--full`.
- Confluence contributors come from the search expansion `content.history.contributors.publishers`;
  if Confluence does not return it, creator and last editor are still read. Atlassian's example
  `_links.next` carries only the query, the limit and the cursor, so the plugin adds the
  expansions back when it follows that link. The interaction date
  of a page is its last modification, not the date of your own edit.
- A scoped token for Jira alone, with Confluence enabled, makes the Confluence part fail: the plugin
  skips it, names it in `products_skipped` and still writes Jira. With `--only confluence` it stops
  with the error instead.
- The cloud id comes from `https://<your-site>/_edge/tenant_info`, which Atlassian documents in a
  support article (https://support.atlassian.com/jira/kb/retrieve-my-atlassian-sites-cloud-id/) but
  not in the versioned REST API: if it ever stops answering, set `atlassian.cloud_id` by hand.
- Rate limits: a 429 or 5xx is retried after `Retry-After` when present, otherwise with exponential
  backoff and jitter, five times at most. Atlassian says API-token traffic follows the burst limits
  (https://developer.atlassian.com/cloud/jira/platform/rate-limiting/,
  https://developer.atlassian.com/cloud/confluence/rate-limiting/).
- API tokens expire after at most one year; an organization using Atlassian Guard can block API
  tokens of external users
  (https://support.atlassian.com/security-and-access-policies/docs/set-api-token-access/). Both show
  up as HTTP 401.
- Jira issue search uses the enhanced endpoint `GET /rest/api/3/search/jql`; the older
  `/rest/api/3/search` is marked "currently being removed"
  (https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/).
- Atlassian also offers an official remote MCP server (`https://mcp.atlassian.com/v2/mcp`)
  (https://support.atlassian.com/atlassian-ai-gateway/docs/get-started-with-the-atlassian-remote-mcp-server/);
  SBK does not use it, the plugin calls the REST APIs directly.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#atlassian](../../docs/CONNECTING.md#atlassian). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
