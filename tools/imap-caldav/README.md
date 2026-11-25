<!-- generated from docs/CONNECTING.md -->
# IMAP mail and CalDAV / ICS calendars (`ic-`)

**Status** partial · registry `continua`, every 3 days (`tools/sorgenti.py`, entry `imap-caldav`). Tested
with a mocked IMAP server and a mocked CalDAV server only, never against a real account. The scheduled
download (`tools/cross-source/xs-l0-refresh.py`) runs `ic-l0-download.py` for every account. It writes
into the existing mail and calendar slots, so the kernel's own `email` and `calendar` steps of
`xs-pipeline-run.py --ingest` read it with no change.
**Reads** your mail over IMAP (TLS, read-only: nothing is marked as read, moved or deleted), by
default the Inbox and the Sent folder, and your calendars over CalDAV or from a calendar link
(ICS). Works with any provider that offers IMAP with an app password; ready-made settings for
iCloud, Fastmail, Yahoo and Outlook.com.
**You need** an account where IMAP is available to you (Fastmail: not on the Basic plan;
Outlook.com: switched off until you turn it on), and **one** of these per account:
- an **app-specific password** (iCloud, Fastmail, Yahoo, most other providers);
- for **Outlook.com**, an app registration of your own (Microsoft accepts no password on IMAP);
- for calendars without CalDAV, a **calendar link** (ICS).

**Create it** (pick your provider; each is your own password or your own app, used only by you)
- **iCloud**: two-factor authentication must be on. Sign in at
  [account.apple.com](https://account.apple.com/) → **Sign-In and Security** → **App-Specific
  Passwords** → **Generate an app-specific password**. Server `imap.mail.me.com:993`, user name
  usually the part of your address before the @ (the preset does this; put the full address in
  `username` if it is refused). Calendar: Apple documents no CalDAV address for other apps, so in
  Calendar on iCloud.com turn on **Public Calendar** for a calendar and **Copy** its link; anyone
  who has that link can view that calendar.
  [Mail server settings](https://support.apple.com/en-us/102525) ·
  [App-specific passwords](https://support.apple.com/en-us/102654) ·
  [Share a calendar](https://support.apple.com/guide/icloud/share-a-calendar-mm6b1a9479/icloud)
- **Fastmail**: **Settings → Privacy & Security → Connected apps & API tokens → Manage app
  passwords and access → New app password**, access **Mail, Contacts & Calendars**. One password
  serves IMAP (`imap.fastmail.com:993`) and CalDAV (`https://caldav.fastmail.com/`); the user name
  is your full Fastmail address.
  [Server names and ports](https://www.fastmail.help/hc/en-us/articles/1500000278342-Server-names-and-ports) ·
  [App passwords](https://www.fastmail.help/hc/en-us/articles/360058752854-App-passwords)
- **Yahoo**: [Account Security page](https://login.yahoo.com/account/security) → under
  **External connections** click **Create app password** → name it → **Generate password**. IMAP
  `imap.mail.yahoo.com:993`, CalDAV `https://caldav.calendar.yahoo.com` with the same app password.
  [IMAP settings](https://help.yahoo.com/kb/SLN4075.html) ·
  [App passwords](https://help.yahoo.com/kb/SLN15241.html) ·
  [Calendar sync](https://help.yahoo.com/kb/SLN4707.html)
- **Outlook.com** (personal Microsoft account):
  1. In Outlook.com: **Settings → Mail → Forwarding and IMAP** → turn on **Let devices and apps
     use IMAP** → **Save**.
  2. In the [Microsoft Entra admin center](https://entra.microsoft.com/): **Entra ID → App
     registrations → New registration**, any name, *Supported account types* **Personal accounts
     only** → **Register**. Copy the **Application (client) ID**.
  3. In that app: **Authentication → Advanced settings → Allow public client flows → Yes** (the
     sign-in uses the device code flow, which needs it). No client secret, no redirect URL.
  4. Put the client ID in `sbk.config.json` (`oauth_client_id` of that account) and sign in once:
     `uv run python tools/imap-caldav/ic-l0-auth.py --account <label> --xoauth2`. It prints a code
     and a Microsoft address; open it, enter the code, sign in with your Outlook.com account and
     accept. The plugin asks only `https://outlook.office.com/IMAP.AccessAsUser.All` and
     `offline_access` for your own mailbox.
  5. Calendar: Outlook.com has no CalDAV. **Settings → Calendar → Shared calendars → Publish a
     calendar** → choose the calendar → **Publish** → copy the **ICS** link. Anyone with the link
     can view or subscribe to that calendar.
  [IMAP settings](https://support.microsoft.com/en-us/office/pop-imap-and-smtp-settings-for-outlook-com-d088b986-291d-42b8-9564-9c414e2aa040) ·
  [OAuth for IMAP](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth) ·
  [Register an app](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) ·
  [Device code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code) ·
  [Publish a calendar](https://support.microsoft.com/en-us/outlook/share-your-calendar-in-outlook-com)
- **Any other provider**: its help pages give the IMAP host (port 993, SSL/TLS) and, if it offers
  one, the CalDAV address; create an app password there if it has them.

Then store the secrets (hidden prompt, saved in the Keychain):
```bash
uv run python tools/imap-caldav/ic-l0-auth.py --account demo_fastmail --imap --caldav
uv run python tools/imap-caldav/ic-l0-auth.py --account demo_icloud --imap --ics
```
**Where the code looks** (Keychain first, then the env var; `<LABEL>` is the account label in upper case;
the env lines are in `.env.example`, section "IMAP / CalDAV / ICS")
- mailbox password: Keychain `sbk-mailbox/<label>`, env `SBK_MAILBOX_PASSWORD_<LABEL>`
  (`tools/imap-caldav/ic_common.py:100`)
- CalDAV password: `sbk-caldav/<label>`, env `SBK_CALDAV_PASSWORD_<LABEL>` (`ic_common.py:101`)
- calendar link: `sbk-ics/<label>`, env `SBK_ICS_URL_<LABEL>` (`ic_common.py:102`)
- Outlook.com: `sbk-imap-oauth/<label>`, env `SBK_IMAP_OAUTH_REFRESH_<LABEL>` (`ic_common.py:103`),
  rewritten when Microsoft hands out a new refresh token (`ic_common.py:443`)
**sbk.config.json** section `imap_caldav`: `accounts` (one entry per label: `preset`, `email`,
optional `username`, `folders` = `auto` / `all` / list, `mail_since`, `max_message_mb`,
`calendar` = `none` / `caldav` / `ics`, `caldav_url`, `calendar_include` / `calendar_exclude`,
`imap_host` / `imap_port` without a preset, `oauth_client_id` for Outlook.com), plus
`calendar_past_days` (730) and `calendar_future_days` (365) for recurring events.
`sbk.config.example.json` ships `accounts` empty and three worked entries under `_example_accounts`
(Fastmail, iCloud, Outlook.com) to copy into `accounts`. If `enabled_sources` is not empty, listing
`imap-caldav` there also keeps the `email` and `calendar` steps that read these slots. Add each address
you configure to `own_emails`, so the email L1 does not count you as a contact.
**Download**
```bash
uv run python tools/imap-caldav/ic-l0-download.py --check          # sign in and list folders / calendars
uv run python tools/imap-caldav/ic-l0-download.py                  # every account, incremental
uv run python tools/imap-caldav/ic-l0-download.py --account demo_fastmail --mail-only --since 2026-01-01
uv run python tools/cross-source/xs-pipeline-run.py --ingest       # the kernel rereads the slots
```
**Check** `<data root>/imap-caldav/download-summary.json` (per account: new messages, flag
changes, calendars fetched/removed, events, errors), then
`<data root>/emails/<label>/messages.parquet` and `<data root>/calendars/<label>/events.parquet`.
**Limits**
- Read-only and additive: a message deleted on the server stays in your copy; a calendar object
  deleted on the server leaves `events.parquet` and is kept in
  `<data root>/imap-caldav/raw/<label>/removed.parquet`.
- Mail folders are read in full on the first run (or from `mail_since`); later runs fetch only
  new UIDs. If a server renumbers a folder (UIDVALIDITY changes) that folder is read again, without
  duplicates. Flag changes (read, starred) are picked up only on servers with CONDSTORE.
- Messages above `max_message_mb` are cut; attachments are listed (name, type, size) but not saved.
- Recurring events are expanded only between `calendar_past_days` and `calendar_future_days`,
  at most 1,000 instances per series. Time zones with Windows names (some Outlook feeds) are kept
  as local time without offset.
- CalDAV sync-collection (RFC 6578) is not used: a changed calendar costs one listing of its
  ETags. Objects the server does not return in a `calendar-multiget` are asked again at the next
  run.
- A calendar link is downloaded whole when it changes, then stored per event: an event that is
  over and no longer in the feed (many links publish only a limited past) is kept; a future event
  that disappears from the feed is moved to `removed.parquet`. The last two copies of the whole
  feed are kept (`feed-current.ics`, `feed-previous.ics`).
- Large mailboxes: messages are requested in groups of at most 50 and about 32 MB, and written to
  disk every 500 messages, so memory stays bounded.
- Gmail and Google Calendar have their own plugins (`email`, `calendar`); a label already in
  `emails/accounts.json` is refused, so the two never write the same folder.
- Outlook.com: Microsoft's registration guide lists as prerequisites "An Azure account that has an
  active subscription", with at least the Application Developer role
  ([Register an app](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app),
  read 2026-11-25). Answers on Microsoft Q&A (not an official doc page) say a personal account can
  no longer create an app registration outside a directory. What that subscription costs was not
  checked. A work or school Microsoft 365 mailbox is out of scope here (the plugin uses the
  `consumers` sign-in only); the `microsoft365` plugin reads those through Graph.
- Fastmail Basic plans have no IMAP or CalDAV. Yahoo may refuse to create an app password from a
  browser you have not used to sign in for several days in a row.
- No provider page checked documents IMAP or CalDAV rate limits; Fastmail applies unnamed fair-use
  limits.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#imap-caldav](../../docs/CONNECTING.md#imap-caldav). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
