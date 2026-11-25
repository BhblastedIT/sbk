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

- The encryption key lives in your Keychain (service `sbk-backup`, account `enc-key`). It is never
  printed and never goes to cloud storage. Keep an offline copy of it yourself: without it no archive
  can be opened.
- Each archive's manifest carries a fingerprint of the key. If the key in the Keychain does not match
  the archives, the backup stops instead of making a new key.
- On a new machine, restore with `--key-from-stdin`: you type or pipe the key, the Keychain is not
  used.

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
