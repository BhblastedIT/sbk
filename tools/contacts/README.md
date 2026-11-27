<!-- generated from docs/CONNECTING.md -->
# Contacts: address-book exports and Google Contacts (`ct-`)

**Status** partial · registry `periodica`, every 30 days (`tools/sorgenti.py`, entry `contacts`).
Tested with synthetic vCard and CSV files and a mocked People API only, never with a real Google
account or a real export; the test runs the kernel's own contacts step (`xs-l1-contacts-enrich.py`) on
what the plugin writes. The scheduled download (`tools/cross-source/xs-l0-refresh.py`) runs
`ct-l0-download.py --all` (step `contacts-google`; nothing to do while `contacts.google_accounts` is
empty), and `xs-pipeline-run.py --ingest` runs `ct-l1-enrich.py` (step `contacts`). The plugin writes
into the kernel's existing address-book slot, `<data root>/contacts/contacts.parquet`, and then runs
that kernel step for you, so the contact merge (`xs-l2-merge.py`, iPhone lane) sees your address
book. A new `contacts-iphone.parquet` also makes `xs-pipeline-run.py --propagate` run the merge again.
**Reads** your own address book, in either of two ways, or both:
- an **export** you make: a vCard file (`.vcf`, versions 2.1, 3.0 and 4.0) from the macOS Contacts
  app, iCloud.com, the iPhone Contacts app, Google Contacts or Outlook desktop (one `.vcf` per
  contact), or a CSV file from Google Contacts, Outlook or Outlook.com (Outlook.com exports CSV
  only). A folder holding several of them works too;
- **Google Contacts** read live through the People API with your own Google app, read-only, only
  the contacts you saved (not your "Other contacts", not a company directory).

For each contact: name, every phone and e-mail (the preferred one first), organization, job title
and birthday.
**You need** for an export, nothing but the file. For Google Contacts, the Google app you already
made for the other Google plugins ([Google](../../docs/CONNECTING.md#google)), with the **People API** enabled in the same
project.
**Create it**
- *An export.* On a Mac: Contacts → select the contacts → **File → Export → Export vCard**
  ([Apple guide](https://support.apple.com/guide/contacts/export-or-archive-contacts-adrbdcfd32e6/mac)).
  On iCloud.com: Contacts → select them → the Actions button → **Export vCard**
  ([Apple guide](https://support.apple.com/guide/icloud/import-export-and-print-contacts-mmfba748b2/icloud)).
  On an iPhone: Contacts → **Lists** → touch and hold a list → **Export**, then save the file
  ([Apple guide](https://support.apple.com/guide/iphone/export-contacts-iph075ddebf2/ios)). In Google
  Contacts: select the contacts → **More actions → Export**, as vCard or Google CSV
  ([Google guide](https://support.google.com/contacts/answer/7199294)). In Outlook.com or Outlook on
  the web: **People → Manage contacts → Export contacts**, which gives a `.csv`
  ([Microsoft guide](https://support.microsoft.com/en-us/outlook/export-contacts-from-outlook-com-or-outlook-on-the-web)).
  Then import it, giving it a label you choose:
  ```bash
  uv run python tools/contacts/ct-l0-import.py ~/Downloads/contacts.vcf --label phone
  ```
- *Google Contacts.* In your Google Cloud project, *APIs & Services* → *Library*, enable the
  **People API** ([Google guide](https://developers.google.com/people/v1/getting-started)). Then sign
  each Google account in once; the browser asks you to allow "See and download your contacts"
  (`https://www.googleapis.com/auth/contacts.readonly`, the only scope this plugin asks):
  ```bash
  uv run python tools/contacts/ct-l0-auth.py --account personal
  ```

Official references: [people.connections.list](https://developers.google.com/people/api/rest/v1/people.connections/list) ·
[Read and manage contacts](https://developers.google.com/people/v1/contacts) ·
[Person resource](https://developers.google.com/people/api/rest/v1/people) ·
[OAuth scopes](https://developers.google.com/identity/protocols/oauth2/scopes) ·
[Refresh token expiration](https://developers.google.com/identity/protocols/oauth2) ·
[vCard 4.0, RFC 6350](https://www.rfc-editor.org/rfc/rfc6350) ·
[vCard 3.0, RFC 2426](https://www.rfc-editor.org/rfc/rfc2426).
**Where the code looks**
- your Google app: `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET`, else the Desktop-app JSON
  (`GOOGLE_OAUTH_CLIENT_SECRET_PATH`, else `~/.secrets/google-oauth/client_secret.json`), through
  `tools/google_oauth.py` (`tools/contacts/ct_google.py:125`). The first browser login
  (`ct-l0-auth.py`) reads only the JSON file (`google_oauth.browser_login`); the two variables are
  enough afterwards, to refresh the login.
- the Google login: Keychain `sbk-gcontacts/<label>` (`ct_google.py:114`), written by `ct-l0-auth.py`;
  without a Keychain, the env variable `SBK_GCONTACTS_TOKEN_<LABEL>` (`ct_google.py:117`), a refresh
  token or `{"refresh_token": …}`, exported in your shell. The lines are in `.env.example`, section
  "Contacts".
- exports: nothing secret; the copy lives in `<data root>/contacts/raw/imports/<label>/`.
**sbk.config.json** section `contacts` (with its `_help` lines in `sbk.config.example.json`):
`google_accounts`, the labels `ct-l0-download.py --all` reads (the scheduled download uses it; empty
= nothing to download). If `enabled_sources` is not empty, list `contacts` there.
**Download**
```bash
uv run python tools/contacts/ct-l0-import.py ~/Downloads/contacts.vcf --label phone   # an export, any time you make a new one
uv run python tools/contacts/ct-l0-download.py --account personal                     # Google Contacts, incremental after the first run
uv run python tools/contacts/ct-l0-download.py --all                                  # every label in contacts.google_accounts
uv run python tools/contacts/ct-l1-enrich.py                                          # writes the slot, then runs xs-l1-contacts-enrich.py
```
**Check** `uv run python tools/contacts/ct-l0-auth.py --account personal --check` (prints how many
contacts the login can read), then `<data root>/contacts/download-summary.json` (one entry per export
label and per Google label: contacts read, added, changed, removed, birthdays not understood), the rows
of `<data root>/contacts/contacts.parquet` whose `source` is `contacts:import:<label>` or
`contacts:google:<label>` (their `kind` column is `org`, `group` or `location` for a card that is not a
person, empty otherwise), and `<data root>/contacts/processed/contacts-iphone.parquet` (the kernel step's
output, read by the merge).
**Limits**
- The address book enriches people other sources know (phone, organization), matched by phone, e-mail
  or name. A card nobody else knows becomes a contact of its own: keyed by its e-mail when it has one,
  otherwise by its phone (`xs-l2-merge.py`, iPhone lane). Company cards (`KIND:org` in a vCard 4, or the
  `X-ABShowAs:COMPANY` flag of Apple Contacts) stay out: the slot writes `kind` `org` for them (`group`
  and `location` cards likewise), the kernel step marks them `is_business`, and the merge never turns
  them into people, nor a WhatsApp chat from a company card's number. With only the address book
  connected, `--ingest` builds a knowledge base of those people; they have no
  relationship score until a source with interactions (mail, calendar, WhatsApp...) arrives.
- Birthdays are written in the slot's `birthday` column (`YYYY-MM-DD`, or `--MM-DD` when the year is
  unknown), but the kernel step reads birthdays only from `iphone-contacts.json`, so today they do not
  reach the later stages.
- Job title is written in the slot; the kernel contacts step reads it but does not carry it into
  `contacts-iphone.parquet`, so it does not reach the merge.
- A contact without a name is left out by the kernel contacts step (its log counts them), so e-mail-only
  or phone-only entries do not reach `contacts-iphone.parquet`.
- A new export of a label replaces the previous one (kept once in `raw/imports/<label>/previous/`):
  import the whole address book, not a part of it, or use another label for the part.
- The same person in two exports, or in an export and Google, is written once only when name, first
  e-mail and first phone are all equal; otherwise there are two rows, which the merge matches to the
  same person.
- CSV: Google and Microsoft show their column names only as pictures, so the column map is built on the
  usual names (`First Name`, `Last Name`, `Company`/`Organization Name`, `Job Title`/`Organization
  Title`, `E-mail Address`/`E-mail 1 - Value`, `… Phone`/`Phone 1 - Value`, `Birthday`) and tested on
  synthetic files only. Outlook's `Title` column is the honorific and is not read as a job title. A
  birthday written like `4/15/1985` depends on your locale and is left out (counted in the summary).
- vCard 2.1 (Outlook desktop, older phones) is not an RFC: its quoted-printable form is read the
  common way. Photos, notes and addresses are not read. Fax numbers are left out. The copy of
  your export kept in `raw/imports/<label>/` is the whole file as you exported it (mode 600),
  photos, notes and addresses included. A file with a UTF-8 or UTF-16 byte-order mark is read too.
- Google Contacts: only the contacts you saved (`READ_SOURCE_TYPE_CONTACT`), not "Other contacts"
  (another scope) and not a Workspace directory. Google keeps a sync token for 7 days: after a longer
  pause the next run reads the whole list again (automatic), and so does a run that finds
  `people.json` missing or the requested fields changed (Google wants a sync request to repeat the
  first call's parameters). Google applies an extra fixed quota to the first page of a full read and
  answers 429 when it is exceeded; the plugin retries up to five times, waiting as long as a
  `Retry-After` header asks or, without one, a growing pause (Google does not document that header
  for this API), and sends one request at a time, at most two per second. The per-minute quota numbers
  are in your project's console (APIs & Services → People API → Quotas): no public Google page with
  them was found.
- With your Google app in *Testing*, the login lasts 7 days ([Google](../../docs/CONNECTING.md#google), *Testing status and
  the 7-day login*): sign in again with `ct-l0-auth.py`.
- In container mode (`SBK_CONTAINERIZED=1`) there is no Keychain to store a login: run
  `ct-l0-auth.py` outside the container and give the container `SBK_GCONTACTS_TOKEN_<LABEL>`;
  inside it the login command stops with one line that says so.
- `contacts/contacts.parquet` is shared with `microsoft365`: run one of them at a time. While that file
  holds only plugin rows, `ct-l1-enrich.py` also copies your `iphone-contacts.json` into it (source
  `iphone-contacts-json`), the same rule `microsoft365` follows; a file with rows of any other origin is
  left as it is, apart from this plugin's own rows.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#contacts](../../docs/CONNECTING.md#contacts). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
