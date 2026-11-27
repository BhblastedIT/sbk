---
name: backup
description: How to make and verify an encrypted, layered backup of your SBK data — which layer a file belongs to, how to copy a layer, how to prove a restore works, what not to do. Invoke when making, verifying, rotating, restoring, or deleting a backup, and when a new folder appears in the data.
---

# SBK backup

> This skill describes the method. Sizes and current state are not written here: generate them with
> the commands below.

## Principle

- The live data (`~/.sbk-data`, or `SBK_DATA_ROOT`) is the source of truth. The backup keeps what
  cannot be rebuilt, **always encrypted**.
- Decide **file by file**; when in doubt, keep it.
- Never be left without an intact archive: create and verify the new one first, then remove the old.

## The layers (decided by `tools/infrastructure/sb_livelli.py`)

| Layer | What |
|---|---|
| L1 | never skip: what cannot be downloaded again (the knowledge base, your own records, closed sources) |
| L2 | sources the server still has, so they can be downloaded again |
| L3 | everything else worth keeping, and everything the rules do not recognize |
| L4 | outside the backup: caches, builds, logs, temporary and partial files |

Each top-level folder of the data root has one row in `RADICI` (in `sb_livelli.py`) with its layer
and the reason. Two flags can go with a row: `delicato` (sensitive: leaves the machine encrypted
only) and `solo_usb` (goes to an external disk only, never to cloud storage).

## Commands

```bash
L=tools/infrastructure/sb_livelli.py
uv run python $L --where <path>             # layer and rule for a file or a folder
uv run python $L --summary                  # size per layer and per source (walks the whole data root)
uv run python $L --check --self-test        # the rules, tested against planted faults
uv run python $L --list 1                   # the files of one layer, one per line

B=tools/infrastructure/sb-backup.py
uv run python $B --level 1 --dry-run        # one layer: estimate and space guard, nothing written
uv run python $B --level 1                  # encrypted and verified copy of layer 1
uv run python $B --list                     # existing archives
uv run python $B --trial <archive>          # restore trial: HMAC plus a sample compared with the live data
uv run python $B --restore <archive> --to <empty-folder>
uv run python $B --self-check               # encryption round trip on a dummy archive
```

`uv run python $B --help` lists every option (destination, `--keep`, space guard).

## The key

- The first backup generates the encryption key and stores it in your Keychain (service `sbk-backup`,
  account `enc-key`). That is the only copy: SBK writes it to no file, never prints it and never sends
  it to cloud storage. Without it no archive can be opened.
- Keep an offline copy yourself (a password manager, paper). This prints the key, so run it only where
  you mean to:

  ```bash
  uv run python -c "import keyring; print(keyring.get_password('sbk-backup', 'enc-key'))"
  ```

- Each archive's manifest carries a fingerprint of the key. If the key in the Keychain does not match
  the archives, or the Keychain has no key while encrypted archives exist, the backup stops instead of
  making a new key.
- On a new machine, put your copy back in the Keychain (it asks for the key without showing it):

  ```bash
  uv run python -c "import getpass, keyring; keyring.set_password('sbk-backup', 'enc-key', getpass.getpass('key: '))"
  ```

  Or restore without the Keychain with `--key-from-stdin`: you type or pipe the key.
- In container mode (`SBK_CONTAINERIZED=1`) there is no Keychain: the key comes from
  `SBK_BACKUP_ENC_KEY`, which you generate and keep yourself. Without it the backup stops; it never
  makes a key it cannot store.

## What is backed up outside the data root

The rows in `FUORI` (in `sb_livelli.py`) add folders outside the data root. Their paths are derived
from where you cloned the repo and from `CLAUDE_CONFIG_DIR` (default `~/.claude`):

- the repo's `sbk/` folder (your identity files, git-ignored);
- Claude Code's memory, sessions and workflow state of this repo's project, your Claude rules,
  settings, hooks and skills, and your prompt history (layer 1); the project's sub-agent transcripts
  and tool outputs and the prior versions of files the sessions changed, last 60 days (layer 3,
  external disk only);
- your `~/Downloads` folder, only if you ask for it in `sbk.config.json` with
  `"backup": {"include_downloads": true}` (layer 3, external disk only). It is off by default.

The copies of the knowledge base taken before a large re-read are not outside: they sit in
`<data root>/backups-knowledge/` (layer 3), with the rest of the data root.

A layer 1 archive also carries a git bundle of the repo with its uncommitted and untracked files.
`uv run python $L --summary` shows what each of them weighs on your machine.

## What is verified and how

- Each archive is written as `.parziale` (partial), verified, and only then takes its final name.
- `--self-check` tests the encryption on a dummy archive. **It does not verify a real archive.**
- The real proof is a restore: `--trial <archive>`, or `--restore` into an empty folder and a
  comparison of a few files with the live data.
- Restore authenticates the whole archive before extracting, and refuses a non-empty folder and
  paths that escape it.

## Rotation and space

- `--keep N` decides how many archives of each kind stay. Only archives with a manifest count, not
  partial ones.
- A free-space guard runs before writing. `--skip-space-check` turns it off; it fixes nothing.

## Operating rules

- A new folder in the data root: add its row in `RADICI` with layer and reason, in the same commit
  that creates the code writing it.
- Partial files from an interrupted run are reported in the log; remove them by hand once you have
  checked them.
