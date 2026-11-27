<!-- generated from docs/CONNECTING.md -->
# Telegram (`tg-`)

**Status** partial · registry `a_richiesta` (on request), a reminder every 30 days (`tools/sorgenti.py`,
entry `telegram`). The scheduled download lists it as manual: you export, then import.
`xs-pipeline-run.py --ingest` runs `tg-l1-enrich.py` (step `telegram`). Tested only with exports made by
hand following Telegram's published schema, never with a real Telegram export. It writes the generic
intake contract (`tools/cross-source/plugin_intake.py`): the people you chat with reach the contact
merge (`xs-l2-merge.py`) and the person facts (`xs-l2-knowledge-extract.py`), and the promises found in
your messages can become commitments.

**How it works** You export your data yourself from Telegram Desktop and SBK imports the files, as
with WhatsApp. There is no Telegram login: no API id, no bot, no session, nothing goes to the network.

**Reads** from the export's `result.json`:
- your personal chats and your groups (private groups and private supergroups by default), both
  sides of the conversation in personal chats, and in groups only if you untick **Only my
  messages** (step 2 below); groups you have left come with your own messages only, because
  Telegram Desktop always exports them that way;
- the contacts list, used only to add a phone number to the people you chat with;
- your Telegram user id, so SBK knows which messages are yours.

It writes one interaction per chat and day (`kind=message`, the day's messages as text) and one
interaction per promise found in a message ("I'll send you the deck tomorrow", "ti mando il file
domani"). Bots, saved messages, channels and public groups are left out unless you list them.
Media files are never copied, only the kind of media a message had (`[photo]`, `[voice_message]`).

**You need** Telegram Desktop on a computer, signed in to your account
([desktop.telegram.org](https://desktop.telegram.org/)), and enough free disk for the export.

**Create it**
1. Open Telegram Desktop and go to **Settings → Advanced → Export Telegram data**.
2. Tick **Personal chats** and **Private groups**, and under Private groups **untick Only my
   messages**: it is ticked by default, and then your groups hold only what you wrote. Keep
   **Contacts list** ticked if you want phone numbers. Leave **Account information** ticked: it
   carries your user id, which tells SBK which messages are yours. Untick **Photos** (the only media
   type ticked by default) and leave the other media unticked: SBK reads only the text.
3. Under **Location and format**, choose **Machine-readable JSON** (or **Both**), pick a folder, and
   click **Export**.
4. If you signed in to Telegram Desktop only recently, Telegram makes you wait 24 hours, or confirm the
   request from another device you are signed in on, before the export starts.

Telegram writes a folder with a `result.json` in it. To export one chat only, open the chat's **⋮**
menu → **Export chat history**, also as JSON.

Official guides: [Telegram data export schema](https://core.telegram.org/import-export) ·
[Exporting Telegram data](https://bugs.telegram.org/c/60).

**Where the code looks** For the export folder you pass on the command line, or, when you pass none,
`<data root>/telegram/exports/` and its sub-folders. There is no credential, so nothing goes in `.env`
or the Keychain.

**sbk.config.json** set `owner`, and `own_names` if your Telegram name is written differently. The
export's user id identifies you whenever the export has **Account information**; your names are used
only when it does not. Optional section `telegram` (with its `_help` lines in `sbk.config.example.json`):
`chat_types` (default personal chats, private groups, private supergroups), `exclude_chats` (chat names
or ids to leave out), `group_contacts_max_senders` (default 30), `detect_promises` (default true),
`promise_patterns` (your own regular expressions, replacing the built-in English and Italian ones),
`promise_open_days` (default 30), `max_text_chars` (default 20000), `timezone` (only for exports made
before Telegram wrote `date_unixtime`), `own_user_id`. If `enabled_sources` is not empty, list `telegram`
there.

**Import**
```bash
uv run python tools/telegram/tg-l0-import.py ~/Downloads/Telegram\ Desktop/DataExport_2026-11-25 --dry-run   # counts, writes nothing
uv run python tools/telegram/tg-l0-import.py ~/Downloads/Telegram\ Desktop/DataExport_2026-11-25
uv run python tools/telegram/tg-l0-import.py                 # searches <data root>/telegram/exports/
uv run python tools/telegram/tg-l1-enrich.py                 # raw -> intake parquet
```
Import a newer export the same way: only new or edited messages are added. An export already imported
is skipped (`--force` reads it again).

**Check** `<data root>/telegram/download-summary.json` (export files read, chats, new messages, how you
were identified), the chats in `<data root>/telegram/raw/chats/`, then
`<data root>/telegram/processed/plugin-contacts.parquet` and `plugin-interactions.parquet`, and
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
`tg-l1-enrich.py` prints who it took to be "you" (`you = user id from the personal_information of the
export`). If it says `unknown`, set `owner` and `own_names`, or `telegram.own_user_id`. If the import
says `group(s) hold only your own messages`, the export was made with **Only my messages** ticked:
export again with it unticked.

**Limits**
- Import only: nothing arrives on its own. The 30 days are only a reminder to export again.
- Telegram writes no email addresses. People are matched in SBK by phone (when they are in your
  contacts list) or by name. A person who is not in your contacts list, or whose name differs from the
  name in your other sources, may stay a separate person. In the contact merge
  (`contacts-merged.parquet`) a Telegram person is matched to a contact you already have by phone or
  by name; otherwise one with a phone (everyone in your contacts list) becomes a contact keyed by that
  phone ([A first run](../../docs/CONNECTING.md#after-a-download)). They also become a person in the knowledge base
  (`xs-l2-knowledge-extract.py`), so Telegram alone gives you people.
- Phone numbers come only from your contacts list: by user id, otherwise by a full name that appears
  only once in the list. Members of groups who are not in your contacts list have no phone.
- In groups where more than `group_contacts_max_senders` people wrote, the members are named in that
  day's interactions but get no contact row of their own, unless you also chat with them elsewhere.
  Large community groups would otherwise fill your contacts with strangers.
- Promise detection is a list of patterns, not a language model. It catches common first-person
  phrasings in English and Italian and misses everything else. It can also flag a sentence that is not
  a promise. A due date is found only for today, tomorrow, the day after, a weekday name, next week, or
  an ISO date written in the same sentence. Promises older than `promise_open_days` are written as
  `closed`, which means "no longer tracked", not "kept". A promise from someone else becomes a
  commitment only when it has a due date.
- Days follow the clock of the computer that made the export, as Telegram writes it.
- A message you deleted in Telegram stays in your data folder after a newer import. Delete the chat's
  file in `raw/chats/` if you want it gone.
- `result.json` is read in one piece. A very large export (years of big groups) needs several times its
  size in memory: export fewer chat types, or export the big chats one by one (only a single-chat
  export offers a date range), if the import runs out of memory.
- No kernel stage reads the message text yet (`text` column).
- Not covered: secret chats (Telegram's export documentation does not list them), channels and public
  groups (off by default), media files, live reading.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#telegram](../../docs/CONNECTING.md#telegram). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
