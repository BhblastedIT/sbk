<!-- generated from docs/CONNECTING.md -->
# GitHub (`gh-`)

**Status** partial · tested with a mocked GitHub only, never against a real account. Registry `periodica`, every
7 days, inventory group (`tools/sorgenti.py`, entry `github`, `_INVENTARIO`): the inventory L1
(`xs-l1-inventario.py`) reads `repos.json` as before, and a second L1 step, `github_intake`
(`gh-l1-enrich.py`), writes the generic intake files. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`, step `inv-github`) runs `gh-l0-download.py`, and
`xs-pipeline-run.py --ingest` runs `gh-l1-enrich.py`; the kernel reads its two files through
`tools/cross-source/plugin_intake.py` (`xs-l2-merge.py`, `xs-l2-knowledge-extract.py`).
**Reads** with your own token, GET calls only: the repositories you own, collaborate on or reach
through an organization you belong to; their top-level folders and README (optional); the
collaborators of the repositories where you can push; issues and pull requests where you are
author or assignee, open pull requests where your review is requested from you by name (requests
made to a team you are on are left out), pull requests you reviewed and your reviews on them; the
public profile (name, public email, company) of the people found. Nothing is written on GitHub.
**You need** a personal access token of your own GitHub account; the plugin reads one token. A
fine-grained token is the safer one, but it reaches a single owner: either your own account or one
organization. If you want your own repositories and those of one or more organizations together, or
repositories where you are an outside collaborator, you need a classic token (see Limits).
**Create it** (fine-grained, read-only) On GitHub open your profile picture, **Settings**, **Developer
settings**, **Personal access tokens**, **Fine-grained tokens**, **Generate new token**. Give it a
name and an expiration. Under **Resource owner** pick your own account, or the one organization
you want to read (the token reaches only the owner you pick; the plugin uses one token at a time).
Under **Repository access** choose **All repositories** or **Only select repositories**. Under
**Permissions**, **Repository permissions**, set **Metadata: Read-only** (listing repositories and
collaborators needs it), **Issues: Read-only**, **Pull requests: Read-only** and, only if you want
folders and README, **Contents: Read-only**. Generate and copy the token.
Official steps: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
and the permission each endpoint needs:
https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens
(classic) Same path, **Tokens (classic)**, **Generate new token (classic)**, scopes `repo` and
`read:org` (`read:org` is needed to list collaborators,
https://docs.github.com/en/rest/collaborators/collaborators). `repo` also allows writing: the code
only sends GET requests (a test checks it), but the token itself could write, so keep it in the
Keychain and give it an expiration. Scopes: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps
**Where the code looks** Keychain `sbk-github/token` first, then the env `GITHUB_TOKEN`, then
`GITHUB_PERSONAL_ACCESS_TOKEN` (`tools/github/gh_api.py:109`, names at `:62` and `:66`; the lines are in
`.env.example`, section "GitHub"). Both download scripts load `.env` by themselves.
```bash
uv run python -c "import keyring, getpass; keyring.set_password('sbk-github', 'token', getpass.getpass('value: '))"
```
**sbk.config.json** nothing is required. Optional section `github` (`tools/github/gh-l0-download.py:106`,
every field with its `_help` in `sbk.config.example.json`): `since_days` (first-run window for issues
and PRs, default 365), `collaborator_affiliation` (the `affiliation` filter of GitHub's collaborators
endpoint: `direct` by default, `all` for every collaborator you can see, which on organization
repositories includes members with access through teams or base permissions, `outside` for outside
collaborators only), `skip_owners` (owners to leave out), `trees` (folders and README in the full
download, default false; the scheduled download follows this field), `max_profiles_per_run` (300),
`max_reviews_per_run` (500). If `enabled_sources` is not empty, list `github` there: it keeps the
`github_intake` step, and the generic intake reads the `github` folder only when it is listed.
**Download**
```bash
uv run python tools/github/gh-l0-download.py --dry-run   # checks the token, prints your login, writes nothing
uv run python tools/github/gh-l0-download.py             # repos, collaborators, issues, PRs, reviews
uv run python tools/github/gh-l1-enrich.py               # builds the two parquet files (also run by --ingest)
uv run python tools/github/gh-l0-inventory.py            # inventory only (repos + folders + README)
```
**Check** `<data root>/github/download-summary.json` (repos, items, people, API calls left),
`<data root>/github/repos.json`; after the L1, `<data root>/github/processed/plugin-contacts.parquet`
and `plugin-interactions.parquet`, then
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
**Limits**
- A fine-grained token reaches one owner (you or one organization), cannot reach several
  organizations at once, and cannot reach repositories where you are an outside or repository
  collaborator; those cases need a classic token (GitHub's list of gaps, managing-your-personal-
  access-tokens page above). With a fine-grained token on your own account, issues and pull
  requests in organization repositories are found only when the repository is public. An
  organization can also refuse fine-grained or classic tokens, or keep a fine-grained token pending
  until it is approved; until then it reads only public data.
- The scheduled download used to run `gh-l0-inventory.py`, which reads folders and README by default.
  It now runs `gh-l0-download.py`, which reads them only with `github.trees: true` (or `--trees`).
- Collaborators are listed only where you have write access (GitHub refuses it otherwise); the
  plugin skips the others and counts them in `collab_repos_denied`.
- People's email is the public one from their profile, so most rows have a name and a GitHub link
  but no email. `noreply` addresses are dropped. A person with no public name is written with their
  GitHub login as the name.
- Search returns at most 1,000 results per query and 30 searches per minute; the plugin pages by
  update date to go past 1,000 and waits between searches
  (https://docs.github.com/en/rest/search/search). The general limit is 5,000 requests per hour
  (https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).
- A search GitHub rejects (422) stops the whole download with exit 1; what was already read stays in
  `raw/items.json`, but `state.json` and `download-summary.json` are not written for that run.
- Incremental: issues and PRs are searched from the last run minus one day. A role that changed on
  an item nobody updated since (for example you were unassigned) is fixed only by `--full`.
  Pending review requests on open pull requests are re-read in full every run. If GitHub answers a
  search with `incomplete_results`, or a search cannot get past the 1,000-results window, the
  watermark is not moved, so the next run searches the same period again
  (`watermark_kept` in `download-summary.json`).
- Review requests are only the ones made to you by name (`user-review-requested:@me`); a request
  made to a team you are on is not read, because it would count as your own commitment. The
  qualifier is on GitHub's search syntax page
  (https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests)
  and has not been tried against a real account.
- REST API version `2026-03-10` is pinned in the header (`gh_api.py`, `API_VERSION`); GitHub
  supports the previous version, `2022-11-28`, until 2028-03-10
  (https://docs.github.com/en/rest/about-the-rest-api/api-versions).
- The interaction date is the creation date of the issue or PR, the date of your last review for a
  review, and the last update for a pending review request: GitHub's search does not give the date
  you were assigned or asked.
**Alternative, an MCP server** GitHub runs its own GitHub MCP Server
(`https://api.githubcopilot.com/mcp/`), with OAuth or a personal access token you create ([Using an MCP
server](../../docs/CONNECTING.md#using-an-mcp-server-instead-of-a-download)). It lets an agent read your repositories, issues
and pull requests live during a session; it does not fill SBK's data folder, so the knowledge layer and
the drafts still need the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#github](../../docs/CONNECTING.md#github). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
