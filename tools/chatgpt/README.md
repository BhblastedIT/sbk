<!-- generated from docs/CONNECTING.md -->
# ChatGPT (`cg-`)

Only if you used ChatGPT. Your ChatGPT export is read by the AI history plugin, together with your
Claude.ai and Manus exports and your Claude Code logs: see [AI history](../../docs/CONNECTING.md#ai-history).

The folder `tools/chatgpt/` also keeps an older script, `cg-l1-enrich.py`, which classifies a
`conversations.json` placed in `<data root>/chatgpt/`. The registry marks that source closed. If you
fill `enabled_sources` and leave `chatgpt` out, the pipeline does not run it. The names it tags are
your organisations plus `chatgpt.people` and `chatgpt.companies` in `sbk.config.json` (empty = only
your organisations).

This README repeats the plugin's section of the guide, [docs/CONNECTING.md#chatgpt](../../docs/CONNECTING.md#chatgpt). Where secrets go, where data lands and what `sbk.config.json` holds: [Before you start](../../docs/CONNECTING.md#before-you-start).
