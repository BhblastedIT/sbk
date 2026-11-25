<!-- generated from docs/CONNECTING.md -->
# Voice Memos (`vm-`)

**Status** mature · registry `spot` (only when there is something new).
**Reads** `.m4a` voice memos and transcribes them on your machine.
**You need** `ffmpeg` (with `ffprobe`), `whisper-cli` from whisper.cpp, and the model file at the fixed
path `~/whisper-models/ggml-large-v3-turbo.bin` (`WHISPER_MODEL` in
`tools/voice-memos/vm-l0-transcribe.py`).
**Create it** Copy your memos out of the Voice Memos app as `.m4a` files (on a Mac, drag them from the
app to a Finder folder; on an iPhone, share them and save to Files).
**Where the code looks** `<data root>/voice-memos/*.m4a` (`VOICE_MEMOS_DIR` in `tools/sbk_config.py`).
**sbk.config.json** `voice_memos.language`: `auto` (default, detected per memo) or a code such as
`en`, `it`, `de`. The env variable `SBK_VOICE_MEMOS_LANGUAGE` wins over the file. Optional,
`voice_memos.people` and `voice_memos.companies`: the names `vm-l1-enrich.py` tags when you say them
in a memo. It looks only for the names you list; empty = no person or company tags:

```json
"voice_memos": {"language": "auto", "people": ["Sam Demo"], "companies": ["Example Ltd"]}
```
**Download**
```bash
uv run python tools/voice-memos/vm-l0-transcribe.py
uv run python tools/voice-memos/vm-l0-transcribe.py --workers 2   # fewer parallel models, less memory
```
**Check** `<data root>/voice-memos/voice-memos.parquet` and the text files in
`<data root>/voice-memos/transcripts/`.
**Limits** Transcription runs locally; nothing is sent out. Each worker loads a Whisper model, so
the default number of workers is computed from the free memory.

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#voice-memos](../../docs/CONNECTING.md#voice-memos). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
