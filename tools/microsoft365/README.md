<!-- generated from docs/CONNECTING.md -->
# Microsoft 365 / Outlook (`ms-`)

**Status** partial · registry `continua`, every 3 days (`tools/sorgenti.py`, entry `microsoft365`). Tested
with a mocked Microsoft Graph and identity platform only, never against a real account. The scheduled
download (`tools/cross-source/xs-l0-refresh.py`) runs `ms-l0-download.py --all`. Its files go into the
kernel's existing mail, calendar and address-book slots, and the tests run the kernel's own readers
(`em-l1-enrich`, `ca-l1-extract`, `xs-l1-contacts-enrich`) on them; in `xs-pipeline-run.py --ingest` the
`email` and `calendar` steps read them.
**Reads** your Outlook mail (every folder except Junk, Deleted Items, Outbox and Outlook's system
folders), your own calendars (past and upcoming events, with attendees and their answers) and your
Outlook contacts. Works with a personal Microsoft account (Outlook.com, Hotmail, Live) and with a
work or school Microsoft 365 account **only if your organization lets you register an app and lets
users consent to these permissions**. If the sign-in shows a page asking for an administrator's
approval, this plugin cannot be used with that account: it never asks for admin consent.
**You need** a Microsoft account that can open the Microsoft Entra admin center and register an
app. Microsoft's registration guide lists as prerequisites an Azure account with an active
subscription (it links the free one), at least the Application Developer role, and a tenant,
for which your *Default Directory* is enough. Python and a browser for the one-time sign-in (or
`--device-code` to sign in from another device).
**Create it** You register your own app, used only by you:
1. Go to the [Microsoft Entra admin center](https://entra.microsoft.com), then **Entra ID** →
   **App registrations** → **New registration**.
2. Give it a name. Under **Supported account types** choose **Any Entra ID Tenant + Personal
   Microsoft accounts** (personal and work sign-in), or **Personal accounts only**, or, for a work
   account in your own organization's directory, **Single tenant only**. Click **Register**.
3. On **Overview**, copy the **Application (client) ID** (and, for a single-tenant app, the
   **Directory (tenant) ID**).
4. **Authentication** → **Add a platform** → **Mobile and desktop applications**, and add the
   redirect URI `http://localhost` exactly. The plugin listens on a free local port; Microsoft
   ignores the port of a localhost redirect.
5. Still in **Authentication**, under **Advanced settings**, set **Allow public client flows** to
   **Yes** (needed only for `--device-code`). Do not create a client secret: the app is a public
   client.
6. Nothing to add under **API permissions**: at the first sign-in the plugin asks, for your own
   account only, `User.Read`, `Mail.Read`, `Calendars.Read`, `Contacts.Read` and `offline_access`
   (`SCOPES` in `tools/microsoft365/ms_graph.py`), and you consent to them yourself. If you want
   them listed on the app, add the same five Microsoft Graph permissions there (not the
   *Application permissions* type, which this plugin never uses).
7. Put the client ID in `sbk.config.json` as `microsoft365.client_id` (and `microsoft365.tenant` =
   your tenant id for a single-tenant app), or export `SBK_MS365_CLIENT_ID` (and `SBK_MS365_TENANT`)
   in your shell: these scripts do not load `.env` by themselves. Then sign in once per mailbox,
   choosing a label that is not one of your Gmail labels:
   ```bash
   uv run python tools/microsoft365/ms-l0-auth.py --account outlook
   uv run python tools/microsoft365/ms-l0-auth.py --account outlook --device-code   # no browser here
   ```
   The browser opens on login.microsoftonline.com, you sign in and accept, and the sign-in is
   stored. Signing a label in again asks for the same five permissions, plus `Chat.Read` if
   [teams](../../docs/CONNECTING.md#teams) added it; any other scope recorded on that sign-in is not asked again, and the
   script names it.

Official guides: [Register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) ·
[Desktop app registration (redirect `http://localhost`, public client flows)](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-registration) ·
[Authorization code flow with PKCE](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow) ·
[Device code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code) ·
[Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference) ·
[How users consent in an organization](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-user-consent).
**Where the code looks**
- client ID: the env variable `SBK_MS365_CLIENT_ID`, else `microsoft365.client_id` in `sbk.config.json`
  (`tools/microsoft365/ms_graph.py:191`); tenant: `SBK_MS365_TENANT`, else `microsoft365.tenant`,
  else `common` (`ms_graph.py:196`).
- the sign-in: Keychain `sbk-microsoft365/<label>` (`ms_graph.py:237`), written by `ms-l0-auth.py`
  and replaced by every download, because Microsoft returns a new refresh token at each use
  (`ms_graph.py:273`). Without a Keychain: `SBK_MS365_TOKEN_FILE` (a JSON file the plugin keeps up
  to date, mode 600), then `SBK_MS365_TOKEN_<LABEL>` as a read-only seed, both exported in your shell. The lines are in
  `.env.example`, section "Microsoft 365 / Outlook". In container mode (`SBK_CONTAINERIZED=1`) the seed is
  read first, because it stands in for the Keychain (`tools/secrets_adapter.py`): set it for the first run,
  then unset it so the newer token in `SBK_MS365_TOKEN_FILE` is used.
**sbk.config.json** section `microsoft365` (every field with its `_help` in `sbk.config.example.json`):
`client_id`, `tenant`, `accounts` (labels for `--all`, which the scheduled download uses),
`default_account`, `timezone`, `mail_history_days` (365), `mail_headers` (true),
`calendar_history_days` (365), `calendar_future_days` (90), `calendar_overlap_days` (14),
`page_size` (50). If `enabled_sources` is not empty, listing `microsoft365` there also keeps the
`email` and `calendar` steps that read this plugin's files.
**Download**
```bash
uv run python tools/microsoft365/ms-l0-download.py --account outlook          # incremental after the first run
uv run python tools/microsoft365/ms-l0-download.py --account outlook --since 2024-01-01 --full
uv run python tools/microsoft365/ms-l0-download.py --all                      # every label in microsoft365.accounts
uv run python tools/cross-source/xs-l1-contacts-enrich.py                     # contacts stage, outside the runner
uv run python tools/cross-source/xs-pipeline-run.py --ingest                  # mail and calendar L1 and the rest
```
**Check** `uv run python tools/microsoft365/ms-l0-auth.py --account outlook --check` (prints the
signed-in address), then `<data root>/microsoft365/outlook/download-summary.json` (folders, messages
changed and removed, calendar window, contacts read, `errors`), and the slot files
`<data root>/emails/outlook/messages.parquet`, `<data root>/calendars/outlook/events.parquet`,
`<data root>/contacts/contacts.parquet` (rows with `source` = `microsoft365:outlook`).
**Limits**
- Work or school accounts: if the organization blocks user consent, requires users to be assigned
  to apps, or blocks app registration, the plugin cannot be used there. Microsoft recommends that
  organizations block the device code flow, so `--device-code` may be refused on work accounts;
  use the browser sign-in.
- Only your own mailbox, calendars and contacts. Calendars other people share with you are
  skipped (the plugin asks for `Calendars.Read`, which covers your own calendars), and so are
  other mailboxes, the Exchange online archive and Teams chats (those are the [teams](../../docs/CONNECTING.md#teams) plugin's).
- A mail folder or calendar that answers 403 or 404 is skipped for that run and named in the
  summary (`folders_skipped`, `calendars_skipped`); its rows stay as they are.
- Attachments are not listed: `has_attachments` is set, `attachment_count` stays 0.
- Contacts: the default folder and the contact folders Graph lists at the top level, not deeper ones.
- The calendar is re-read in a moving window: an event deleted before that window stays in the slot.
- The first mail download keeps the whole round in memory before writing; on a very large mailbox
  lower `mail_history_days` for the first run.
- The refresh token lasts 90 days by default and can be revoked earlier: if you do not download for
  longer, or the token is revoked, sign in again.
- Microsoft limits each app and mailbox pair to 10,000 requests per 10 minutes and 4
  concurrent requests; the plugin sends one request at a time, at most 10 per second
  (`MIN_INTERVAL_S`), and waits on 429 answers as told by `Retry-After`.
- Whether Graph accepts the Internet headers inside a mail delta query is not stated in Microsoft's
  docs; if a mailbox refuses them, the plugin goes on without (and the kernel then has fewer
  bulk-mail signals for that mailbox).
- The contacts step (`xs-l1-contacts-enrich.py`) runs inside `xs-pipeline-run.py` only through the
  [contacts](../../docs/CONNECTING.md#contacts) plugin's step, after an export or a Google Contacts download: with Outlook
  contacts alone, run it yourself.
  Two downloads writing `contacts/contacts.parquet` at the same time are not coordinated: run one at
  a time.
- If `contacts/contacts.parquet` does not exist yet, or holds only rows this plugin wrote, the
  download also copies your `iphone-contacts.json` into it at every run (source
  `iphone-contacts-json`), because the kernel stops reading that JSON as the address book once
  the parquet exists. A parquet with rows from any other source is left as it is.
- A mail update that Graph returns with only some properties patches the row already in the
  slot; such an update for a message never downloaded is not written.
- Global Microsoft cloud only (login.microsoftonline.com, graph.microsoft.com), not national clouds.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#microsoft365](../../docs/CONNECTING.md#microsoft365). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
