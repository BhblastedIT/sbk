<!-- generated from docs/CONNECTING.md -->
# Email / Gmail (`em-`)

Signs in through your own Google app, which you set up once for the five Google plugins: [Google](../../docs/CONNECTING.md#google).

**Status** mature · registry `continua`, every 3 days.
**Reads** your Gmail messages with their full body, the index of attachments, then contacts and who
writes to whom. It reads the mailboxes you sign in, one browser login each.
**You need** your Google app ([Google](../../docs/CONNECTING.md#google)) with the Gmail API enabled.
**Create it** Sign each mailbox in:
```bash
uv run python tools/email/em-l0-auth.py work        # browser: pick the Google account of this mailbox
uv run python tools/email/em-l0-auth.py personal
uv run python tools/email/em-l0-auth.py --list      # the mailboxes signed in
```
**Where the code looks** the OAuth client (`GOOGLE_OAUTH_CLIENT_SECRET_PATH`, default
`~/.secrets/google-oauth/client_secret.json`, or `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET`),
the refresh token in Keychain `sbk-gmail/<label>`, the labels in `<data root>/emails/accounts.json`.
Container mode: `SBK_GMAIL_TOKEN_<LABEL>`.
**sbk.config.json** `email_accounts` = the labels of `accounts.json`; `own_emails`, `owner`,
`own_names` so SBK recognises you in the mail.
**Download**
```bash
uv run python tools/email/em-l0-download.py --account work --dry-run   # counts only: checks the login
uv run python tools/email/em-l0-download.py --all                      # every mailbox signed in
uv run python tools/email/em-l0-download.py --account work --force     # one mailbox, full history from 2020
uv run python tools/email/em-l0-allegati.py --dry-run                  # attachments: how many and how big
uv run python tools/email/em-l0-allegati.py                            # download document attachments
```
Without `--since` or `--force` each run continues from the last completed one.
**Check** `<data root>/emails/<label>/messages.parquet` and `<data root>/emails/<label>/download.log`;
`<data root>/last-runs.json` gets `email-<label>` for each mailbox that finished without errors.
With `--all`, a mailbox that fails is named at the end and the others still run.
**Tools that act in your mailbox** (they use the same login, `https://mail.google.com/` scope):
- `tools/email/em-draft-create.py --account work --to … --subject … --body …` creates a draft
  (`--send` sends instead, `--reply-to <message id>` threads a reply).
- `tools/email/em-followup-watch.py --mailbox work --to someone@example.example --days 20` tells you
  when a mail you sent has had no reply.
- `tools/email/gsearch.py work "from:someone@example.example" 10` prints the matching messages.
- `tools/email/em-util-inbox-zero.py` keeps sender-to-label rules and turns them into Gmail filters.
  Filters need the extra login `em-l0-auth.py <label> --settings` (scope `gmail.settings.basic`).
**Limits**
- One login reads one mailbox: the account you pick in the browser. If the account does not match
  the address stored for the label, the download stops and writes nothing.
- Spam is skipped; trash is read.
- With a consent screen in *Testing*, the login has to be repeated when Google expires it (see
  [Google](../../docs/CONNECTING.md#google)).
**Alternative, an MCP server** Google runs a Gmail MCP server (Developer Preview,
`https://gmailmcp.googleapis.com/mcp/v1`), with an OAuth client in your own Google Cloud project ([Using
an MCP server](../../docs/CONNECTING.md#using-an-mcp-server-instead-of-a-download)). It lets an agent search and read your mail
live during a session; it does not fill SBK's data folder, so the knowledge layer and the drafts still
need the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#email](../../docs/CONNECTING.md#email). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
