<!-- generated from docs/CONNECTING.md -->
# Zoom (`zm-`)

**Status** partial · registry `continua`, every 7 days (`tools/sorgenti.py`, entry `zoom`). Tested with a
mocked Zoom API only, never against a real account. The scheduled download
(`tools/cross-source/xs-l0-refresh.py`) runs `zm-l0-download.py`, and `xs-pipeline-run.py --ingest` runs
`zm-l1-enrich.py` (step `zoom`). It writes the generic intake contract
(`tools/cross-source/plugin_intake.py`): the people you met reach the contact merge (`xs-l2-merge.py`)
and the person facts (`xs-l2-knowledge-extract.py`). Meetings are written as `done`, so they never
become commitments, and no kernel stage reads the transcript text yet.
**Reads** the meetings you host that have a cloud recording, the participant list of each one, and
the audio transcript (VTT) Zoom makes from the recording. With `--include-unrecorded` (or
`zoom.include_unrecorded`) also your past scheduled meetings without a recording (participants only).
**You need** a Zoom account on a **Pro plan or higher** with cloud recording on (Zoom lists
recordings and past participants only on paid plans), and **Create audio transcript** turned on in
your cloud-recording settings if you want transcripts (on your own Pro account you are the owner,
so you can turn it on: [Zoom support guide](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0065911)).
Python and a browser on the same machine for the one-time login.
**Create it** You create your own app, used only by you:
1. Go to the [Zoom App Marketplace](https://marketplace.zoom.us/), sign in, click **Develop** →
   **Build an app** → **General app**.
2. On **Basic Info**, under *Select how the app is managed*, choose **User-managed** (the app sees
   only your own data).
3. In **App Credentials** turn on **Use Public Client OAuth** and copy the **public client ID**.
   You do not need the client secret.
4. Set the public client's redirect URL to `http://127.0.0.1/callback` and add the same URL to the
   OAuth allow list. Use `127.0.0.1`, not `localhost`; Zoom ignores the port.
5. On **Scopes** add these user-level scopes (no `:admin` ones):
   `user:read:user`, `cloud_recording:read:list_user_recordings`,
   `meeting:read:list_past_participants`, and optionally `meeting:read:list_meetings`.
6. Put the public client ID in `sbk.config.json` as `zoom.client_id` (or export `ZOOM_CLIENT_ID` in
   your shell: the Zoom scripts do not load `.env` by themselves), then sign in once:
   ```bash
   uv run python tools/zoom/zm-l0-auth.py
   ```
   The browser opens on zoom.us, you click **Allow**, and the login is stored.

Official guides: [Create an OAuth app](https://developers.zoom.us/docs/integrations/create/) ·
[PKCE and loopback redirect](https://developers.zoom.us/docs/integrations/PKCE/) ·
[OAuth scopes](https://developers.zoom.us/docs/integrations/oauth-scopes-overview/).
**Where the code looks**
- the env variable `ZOOM_CLIENT_ID`, else `zoom.client_id` in `sbk.config.json`, else Keychain
  `sbk-zoom/client-id` (`tools/zoom/zm_api.py:156`).
- the login: Keychain `sbk-zoom/default` (`tools/zoom/zm_api.py:180`), written by
  `zm-l0-auth.py` and replaced at every download, because Zoom hands out a new refresh token each
  time (`tools/zoom/zm_api.py:201`). Without a Keychain: `ZOOM_TOKEN_FILE` (a file the plugin
  keeps up to date, mode 600), then `ZOOM_REFRESH_TOKEN` as a one-time seed, both exported in your
  shell. The lines are in `.env.example`, section "Zoom".
**sbk.config.json** section `zoom` (with its `_help` lines in `sbk.config.example.json`): `client_id`
(optional), `history_days` (first run, default 90), `overlap_days` (default 7), `include_unrecorded`
(default false). If `enabled_sources` is not empty, list `zoom` there.
**Download**
```bash
uv run python tools/zoom/zm-l0-download.py            # incremental after the first run
uv run python tools/zoom/zm-l0-download.py --days 365 # first run further back
uv run python tools/zoom/zm-l1-enrich.py              # raw -> intake parquet (also run by --ingest)
```
**Check** `<data root>/zoom/download-summary.json` (meetings, transcripts, participant lists,
`missing_scopes`), the files in `<data root>/zoom/raw/`, then
`<data root>/zoom/processed/plugin-contacts.parquet` and `plugin-interactions.parquet`, and
`uv run python tools/cross-source/xs-l2-knowledge-extract.py --source plugins --dry-run`.
**Limits**
- Free plan: no cloud recordings and no past-participant lists through the API, so nothing to read.
- Only meetings you **host**. Meetings you joined as a guest are not in your recordings.
- Zoom shows the email of people outside your account only in some cases (registration, calendar
  invite through Zoom's calendar integration, authenticated join); otherwise they appear by name.
- Participant lists exist for the last 15 months and, by default, not for one-person meetings.
- Transcripts come only from cloud recordings with *Create audio transcript* on; local recordings
  and meetings without recording have none.
- Your refresh token lasts 90 days without use: if you do not download for longer, sign in again.
- Made for a Zoom account you own. If someone else runs your account, its settings may stop you
  from building the app or turning transcripts on; this plugin does not cover that case.
- A transcript or participant list that is not ready yet is asked again on the next run if the
  meeting still falls inside the re-read window (`overlap_days` before the last completed day).
  If Zoom keeps failing on one item (server or network error), the saved day does not move, so
  nothing is skipped for good.
- The plugin sends one request every 0.5 s and stops cleanly at Zoom's daily limit, keeping what
  it downloaded.
- Recording passcodes in Zoom's answer are never written to disk, and `pwd=` is removed from links.
**Alternative, an MCP server** Zoom runs its own Zoom MCP server
(`https://mcp.zoom.us/mcp/zoom/streamable`), with OAuth and PKCE on your Zoom account ([Using an MCP
server](../../docs/CONNECTING.md#using-an-mcp-server-instead-of-a-download)). It lets an agent ask about your meetings live
during a session; it does not fill SBK's data folder, so the knowledge layer and the drafts still need
the download above.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#zoom](../../docs/CONNECTING.md#zoom). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
