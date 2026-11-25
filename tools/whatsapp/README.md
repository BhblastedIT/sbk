<!-- generated from docs/CONNECTING.md -->
# WhatsApp (`wa-`)

**Status** mature · registry `a_richiesta` (on request), a reminder every 30 days · no credential, no account to connect.
**How it works** You export your chats yourself and SBK imports the files. The export and import path
is the one the author uses; live reading of WhatsApp is not set up.
**Reads** the text of your chats, one file per chat, from two kinds of export:
- the chat export the WhatsApp app makes on your phone, one chat at a time
  (`tools/whatsapp/wa-l0l3-full.py`);
- a text export of every chat at once, one `.txt` per chat in the layout described below
  (`tools/whatsapp/wa-l0-import-history.py`). The author brought in his whole WhatsApp history this
  way, then added single chats with the phone export.

**You need** your phone with WhatsApp, a way to move the files to your Mac (AirDrop, Files, a cable,
your own cloud drive), and your name in `sbk.config.json` so SBK knows which messages are yours (see
below).

**Export from the phone** WhatsApp exports one chat at a time. For all your chats you repeat the steps
for each chat; every export becomes its own file, and SBK imports them all in one run.
- **iPhone** Open the chat → tap the contact's name or the group name at the top → *Export chat* →
  *Without Media* (SBK reads only the text) or *Attach Media* → save or send the file to your Mac.
  SBK looks for it as `WhatsApp Chat - <name>.zip` (or `.txt`).
- **Android** Open the chat → *More options* (the three vertical dots) → *More* → *Export chat* →
  *Without media* or *Include media* → choose where to send it. SBK looks for it as
  `WhatsApp Chat with <name>.txt` or `WhatsApp Chat with <name>.zip`.

Menu names are those of WhatsApp's own help pages for each phone; they can change with app updates.

**Export of every chat at once** The WhatsApp app has no single button for this. A text export of
every chat at once comes from a separate export tool on a computer that reads your phone's chats;
SBK does not include one. `wa-l0-import-history.py` reads it when it is a folder of `.txt` files, one
per chat, each message in this layout (a line of dashes between messages):
```
----------------------------------------------------
Nora Quinn
2025-03-02 10:15:00 from Nora Quinn (+44 7700 900123) - Read

Photo from the meeting
----------------------------------------------------
Nora Quinn
2025-03-02 10:16:42 to Nora Quinn - Read

Thanks Nora, very useful.
Talk next week
```
Each message is the chat name, a header line, a blank line and the text (one or more lines).
`from <name> (+<phone>)` is a message you received, `to <name>` a message you sent.
The status after the dash can be `Read`, `Delivered`, `Listened`, `Played` or `Received`; lines
`<date time> notification` are system messages and are skipped. Optional `--attachments-dir`: one
sub-folder per chat, files named `<YYYY-MM-DD HH MM SS> - <sender> - <file name>`.

**sbk.config.json**
- `owner`: your name as SBK writes it, e.g. `"Alex Demo"`. Your messages are stored under this name.
- `own_names`: every spelling of your name as your exports show it, lower case, e.g.
  `["alex demo", "alex"]`. If one is missing, your messages count as someone else's.
- Optional, under `whatsapp`: `name_overrides` (`{"<name as exported>": "<real name>"}`),
  `group_name_exclusions` (group names that appear as a sender and must never become a contact),
  `company_keywords` (company names counted in the per-chat analysis).

**Where to put the files** Phone exports (`.zip` or `.txt`, with the names the phone gives them) go in
`<data root>/whatsapp/raw/` or `<data root>/whatsapp/raw-exports/`. The data root is `~/.sbk-data`
unless you set `SBK_DATA_ROOT`. Any other folder works with `--zip-dir <folder>` (searched with its
sub-folders, repeatable). The text export of every chat can stay in any folder you pass with
`--text-dir`.

**Import**
```bash
# chats exported from the phone
uv run python tools/whatsapp/wa-l0l3-full.py --list                       # dry run: which exports it found, writes nothing
uv run python tools/whatsapp/wa-l0l3-full.py --skip-analysis              # import
uv run python tools/whatsapp/wa-l0l3-full.py --zip-dir ~/Downloads/whatsapp --skip-analysis

# a text export of every chat at once
uv run python tools/whatsapp/wa-l0-import-history.py --text-dir <txt folder> --dry-run
uv run python tools/whatsapp/wa-l0-import-history.py --text-dir <txt folder>
uv run python tools/whatsapp/wa-l0-import-history.py --text-dir <txt folder> --attachments-dir <folder>

# then contacts and interactions (the pipeline runs this step for you with --ingest)
uv run python tools/whatsapp/wa-l1-enrich.py
uv run python tools/whatsapp/wa-check-ego-invariant.py                    # every row has you on one side
```
Both imports take `--declare complete` when the files are every chat of your phone, or
`--declare chat-only` when they are only some; it is written in the import receipt.

**Check**
- `<data root>/whatsapp/chats/<chat>.json`, one per chat, and `chats/chats-index.json`.
- `<data root>/whatsapp/_ricevute-import.jsonl`: one `start` and one `end` line per import, with how
  many chats came in, how many were new or updated and how many messages were added. A `start`
  without its `end` is an import that stopped half way.
- After `wa-l1-enrich.py` (or `xs-pipeline-run.py --ingest`):
  `<data root>/whatsapp/processed/contacts-whatsapp.parquet` and `interactions-whatsapp.parquet`.
- `wa-check-ego-invariant.py` prints `I-WA   green`. `I-WA2 RED` means many chats do not contain you:
  a spelling of your name is missing from `own_names`.

**Limits**
- Manual: SBK sees only what you exported. For newer messages you export again and import again; the
  same message is never written twice, nothing already imported is removed, and a chat file that a
  re-export replaces is kept in `chats/_superseded/`.
- When the same chat is exported twice, the phone import keeps the larger file.
- The phone import reads only the text of the export. Photos, voice notes and videos inside a `.zip`
  are not imported; they appear in the text only as "image omitted" or `<attached: …>` lines.
- The phone import looks only for the file names above (`WhatsApp Chat - <name>` and
  `WhatsApp Chat with <name>`, `.zip` or `.txt`). If your files have another name, rename them to
  that pattern before importing. Dates with `/`, `.` or `-`, day/month or month/day, and 24-hour or
  12-hour (AM/PM) clocks are read.
- Everything runs on your machine; the imports send nothing anywhere.

**Other WhatsApp scripts, not set up or tested by the author** They stay in `tools/whatsapp/` and each
says so at the top of the file:
- `wa-l0-chatstorage.py` reads a copy of the iPhone's chat database (`ChatStorage.sqlite`). SBK has no
  step that gets that copy from a phone.
- `wa-l1-transcribe-audio.py` and `wa-l1-inject-transcripts.py`: voice notes transcribed on your Mac
  with whisper.cpp, then written into the chats. The transcription needs the relationship scores of a
  later pipeline stage and stops without them.
- `wa-l1-process-videos.py`: video audio transcribed locally, keyframes with `ffmpeg`.
- `wa-l1-extract-docs.py` and `wa-l1-extract-photos.py`: text of documents and of screenshots from the
  attachments indexed by `--attachments-dir`. The pipeline runs them only when you ask, after the WhatsApp
  step: `uv run python tools/cross-source/xs-pipeline-run.py --ingest --whatsapp-extras` (or `--all
  --whatsapp-extras`). Without the flag the plan lists them as outside the run. With no attachments they do
  nothing. `wa-l1-extract-photos.py --vision` sends photos to the Anthropic API (needs `ANTHROPIC_API_KEY`)
  and runs only when you add that flag; the pipeline never adds it.
- `wa-l1-fetch-links.py --fetch` opens on the web every link shared in your chats; without `--fetch` it
  only counts them.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#whatsapp](../../docs/CONNECTING.md#whatsapp). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
