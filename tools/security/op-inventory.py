#!/usr/bin/env python3
""








import collections
import json
import os
import subprocess
import sys

# Uses your own 1Password CLI login: turn on "Integrate with 1Password CLI" in the
# 1Password desktop app (Settings > Developer), then `op` asks you to unlock.
# Only item titles and categories are read, never a secret value.
env = dict(os.environ)
try:
    _who = subprocess.run(["op", "whoami"], capture_output=True, text=True, env=env, timeout=60)
except FileNotFoundError:
    sys.exit("1Password CLI (op) not found: install it and sign in through the desktop app.")
if _who.returncode != 0:
    sys.exit("1Password CLI is not signed in: unlock the desktop app with CLI integration on, then retry.")


def op(*a):
    r = subprocess.run(
        ["op", *a, "--format=json"], capture_output=True, text=True, env=env, timeout=60
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except:
        return None


vaults = op("vault", "list") or []
inv = {}
total = 0
for v in vaults:
    items = op("item", "list", "--vault", v["id"]) or []
    inv[v["name"]] = [(i.get("title", ""), i.get("category", "")) for i in items]
    total += len(inv[v["name"]])

path = os.path.expanduser("~/.sbk-credentials/passwordmanager-inventory.md")
os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
with open(path, "w") as f:
    f.write(
        f"# Password manager inventory (metadata only, no secrets)\n> {total} items in {len(inv)} vaults.\n\n"
    )
    for vn in sorted(inv):
        rows = inv[vn]
        cats = collections.Counter(c for _, c in rows)
        f.write(
            f"## {vn}  ({len(rows)})\ncategories: "
            + ", ".join(f"{k}×{n}" for k, n in cats.most_common())
            + "\n"
        )
        for t, c in sorted(rows):
            f.write(f"- {t}  [{c}]\n")
        f.write("\n")
os.chmod(path, 0o600)
print(f"{total} items in {len(inv)} vaults → {path}")
