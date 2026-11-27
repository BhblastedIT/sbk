<!-- generated from docs/CONNECTING.md -->
# HubSpot (`hs-`)

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `hubspot`). Tested
with a mocked HubSpot only, never against a real account. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`) runs `hs-l0-download.py`, and `xs-pipeline-run.py --ingest` runs
`hs-l1-enrich.py` (step `hubspot`). It writes the generic intake files, which the kernel reads through
`tools/cross-source/plugin_intake.py` (`xs-l2-merge.py`, `xs-l2-knowledge-extract.py`).
**Reads** with your own user-level app, read-only: the contacts, deals, notes and tasks you own (or,
with `only_mine` off, every one your HubSpot user can see), the contacts and companies linked to them,
and the stage names of your deal pipelines. For each contact: name, email, phone, company, job title.
For each deal: name, stage, pipeline, amount, close date, owner. For each note: its text and date. For
each task: subject, body, status, priority, due date. Nothing is written to HubSpot: the plugin only
reads (GET, plus the search and batch-read endpoints).
**You need**
- a HubSpot user in the account (any plan; the API limits differ by plan);
- the **Developer tools access** permission on your user, to upload the app to HubSpot
  ([HubSpot permissions guide](https://knowledge.hubspot.com/user-management/hubspot-user-permissions-guide));
- the **HubSpot Marketplace access** permission on your user, plus the permissions that match the
  app's scopes (view contacts, companies, deals), to install it
  ([who can install an app](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/manage-apps-in-hubspot)).
  HubSpot's user-level page says instead that each user whose permissions match the app's scopes can
  install a user-level app
  ([User-level access](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/user-level-apps));
  which of the two rules applies to a private user-level app was not verified. If your user is not
  allowed, HubSpot refuses the install and this plugin has no other route;
- Node.js 20 or newer and the HubSpot CLI 8.15.0 or newer (the version HubSpot names for user-level
  apps), on the machine where you upload the app;
- Python and a browser on the machine where you sign in.

The app is **user-level**: HubSpot ties its API access to your own user permissions, so the plugin
sees what you see in HubSpot and nothing more. If you can see only your own records in HubSpot, that is all
it reads.
**Create it** You build your own app from the project in this folder, used only by you:
1. Install the HubSpot CLI and connect it to your account
   ([Install the HubSpot CLI](https://developers.hubspot.com/docs/developer-tooling/local-development/hubspot-cli/install-the-cli)):
   ```bash
   npm install -g @hubspot/cli@latest
   hs account auth
   ```
   Follow the prompts: HubSpot asks you to make a personal access key for the CLI and paste it.
2. Upload the app. The project is `tools/hubspot/hubspot-project/` (read-only scopes, `"isUserLevel": true`,
   `"distribution": "private"`, redirect URL `http://localhost:8723/oauth-callback`):
   ```bash
   cd tools/hubspot/hubspot-project
   hs project upload
   ```
3. In HubSpot open **Development** → **Projects** → **sbk-hubspot-reader**, click the app
   (`sbk_hubspot_reader`), open the **Auth** tab and copy the **Client ID** and the **Client secret**
   ([Create a new app using the CLI](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/create-an-app)).
   If the **Distribution** tab asks for approved accounts, add the account you are in
   ([Install a privately distributed OAuth app](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/manage-apps-in-hubspot#install-a-privately-distributed-oauth-app)).
4. Put the client ID in `sbk.config.json` as `hubspot.client_id` (or export `HUBSPOT_CLIENT_ID` in
   your shell: the HubSpot scripts do not load `.env` by themselves) and the client secret in the
   Keychain, so it stays out of your shell history:
   ```bash
   uv run python -c "import keyring, getpass; keyring.set_password('sbk-hubspot', 'client-secret', getpass.getpass('value: '))"
   ```
5. Sign in once:
   ```bash
   uv run python tools/hubspot/hs-l0-auth.py
   ```
   The browser opens on HubSpot, you pick your account and click **Connect app**, and the login is
   stored. If HubSpot shows an error about the scopes, copy the install URL from the app's **Auth** tab
   and pass it: `uv run python tools/hubspot/hs-l0-auth.py --install-url "<that URL>"`.

Official guides: [User-level access](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/user-level-apps) ·
[Working with OAuth](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/oauth/working-with-oauth) ·
[OAuth v3 tokens](https://developers.hubspot.com/docs/api-reference/legacy/authentication/manage-oauth-tokens) ·
[Scopes](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes).
**Where the code looks**
- client ID: the env variable `HUBSPOT_CLIENT_ID`, else `hubspot.client_id` in `sbk.config.json`, else Keychain
  `sbk-hubspot/client-id` (`client_id` in `tools/hubspot/hs_api.py`).
- client secret: Keychain `sbk-hubspot/client-secret`, else `HUBSPOT_CLIENT_SECRET` (`client_secret` in
  `tools/hubspot/hs_api.py`). Never in `sbk.config.json`.
- the login: Keychain `sbk-hubspot/default` (another name with `--label`), written by `hs-l0-auth.py`
  and replaced whenever HubSpot hands out a new refresh token. Without a Keychain: `HUBSPOT_TOKEN_FILE`
  (a file the plugin keeps up to date, mode 600), then `HUBSPOT_REFRESH_TOKEN` as a one-time seed, both
  exported in your shell (`load_refresh_token` in `tools/hubspot/hs_api.py`). The lines are in
  `.env.example`, section "HubSpot".
**sbk.config.json** section `hubspot`: `client_id` (optional), `only_mine` (default true),
`redirect_port` (default 8723), `overlap_hours` (default 24), `history_days` (first run, default 0 =
everything), `max_details` (default 2000), `app_host` (default `app.hubspot.com`). If `enabled_sources` is not empty, list `hubspot` there.
**Download**
```bash
uv run python tools/hubspot/hs-l0-download.py                 # incremental after the first run
uv run python tools/hubspot/hs-l0-download.py --all-visible   # everything you can see, not only yours
uv run python tools/hubspot/hs-l0-download.py --full          # forget the saved state, read again
uv run python tools/hubspot/hs-l1-enrich.py                   # raw -> intake parquet (also run by --ingest)
```
**Check** `<data root>/hubspot/download-summary.json` (records found per type, `only_mine_applied`,
`user_level`, `warnings`, what is left for the next run), the files in `<data root>/hubspot/raw/`, then
`<data root>/hubspot/processed/plugin-contacts.parquet` and `plugin-interactions.parquet`. After the
pipeline: `uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
**Limits**
- A token that HubSpot reports as account-level is refused, because it would read every record the
  scopes allow, whoever you are in HubSpot. HubSpot cannot turn an existing app into a user-level one:
  build a new app from the project in this folder.
- "Only mine" needs your owner id, read from HubSpot's owners API, which is not in HubSpot's list of
  APIs for user-level apps. If HubSpot refuses it, the download reads everything you can see, says so in
  `download-summary.json`, and writes no due dates, so other people's deals and tasks never become your
  commitments.
- Due dates (deal close date, task due date) reach the intake only for items you own; for the others the
  date stays in the text. Likewise only items you own count as your interactions with a person
  (`interactions`, `first_seen`, `last_seen`); a contact with none of yours has those empty, and the
  CRM's own dates (when the record was created, when anyone last contacted it) are not used.
- Deals, notes and tasks are linked to contacts and companies with one read per record; with many
  records the links arrive over more runs (`max_details`).
- A record deleted in HubSpot stays in your files until a download with `--full`.
- One search returns at most 10,000 records; the plugin starts again from the last date it saw, so a
  bigger account is read in more queries.
- API limits of a privately distributed app: 100 requests every 10 seconds on Free and Starter, 190 on
  Professional and Enterprise, with a daily cap
  ([usage guidelines](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines);
  that page names platform versions 2025.2 and 2026.03, this app is 2026.09, so the same limits are
  assumed); search: 5 requests per second
  ([CRM search](https://developers.hubspot.com/docs/api-reference/latest/crm/search-the-crm)).
  At the daily cap the run stops, keeps what it read and continues next time.
- The login listens on `localhost` (HubSpot accepts `http://localhost` and no IP address as a redirect).
  If port 8723 is busy, change `redirect_port` and the redirect URL in `app-hsmeta.json`, upload again.
**Alternative, an MCP server** HubSpot runs its own MCP server (`https://mcp.hubspot.com`, OAuth with PKCE
through an MCP connector you create in your HubSpot account, limited to what your user can see:
[HubSpot MCP server](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server)).
It lets an agent ask your CRM questions live during a session; it does not fill SBK's data folder, so
the knowledge layer and the drafts still need the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#hubspot](../../docs/CONNECTING.md#hubspot). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
