import json
import os
import time
import urllib.request

KEY = os.environ.get("ANTHROPIC_API_KEY")
if not KEY:
    print("no key")
    raise SystemExit


def bench(model, max_tokens=350):
    body = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": [
                {
                    "role": "user",
                    "content": "Scrivi un paragrafo tecnico di circa 300 parole su come funziona lo streaming SSE. Non fermarti prima.",
                }
            ],
        }
    ).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    t0 = time.time()
    ttft = None
    out_tokens = 0
    text_chunks = 0
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            for raw in r:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    ev = json.loads(data)
                except:
                    continue
                if ev.get("type") == "content_block_delta":
                    if ttft is None:
                        ttft = time.time() - t0
                    text_chunks += 1
                if ev.get("type") == "message_delta":
                    out_tokens = ev.get("usage", {}).get("output_tokens", out_tokens)
                if ev.get("type") == "message_stop":
                    break
        total = time.time() - t0
        gen = total - (ttft or 0)
        tps = out_tokens / gen if gen > 0 and out_tokens else 0
        return f"  {model:26} TTFT={(ttft or 0):.2f}s  total={total:.2f}s  out={out_tokens}tok  ~{tps:.0f} tok/s"
    except urllib.error.HTTPError as e:
        return f"  {model:26} HTTP {e.code}: {e.read().decode()[:120]}"
    except Exception as e:
        return f"  {model:26} ERR {e}"


for m in ["claude-haiku-4-5-20251001", "claude-sonnet-5", "claude-opus-4-8"]:
    print(bench(m))
