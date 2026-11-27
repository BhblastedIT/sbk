#!/usr/bin/env python3
"""Where the Inspiration archive lives, and whether Inspiration is on.

Inspiration works on an archive of saved ideas (reels, posts, links, notes) that SBK does not ship:
its folder holds archivio/ (archivio.py, archivio.jsonl and the scripts that fill it, such as
leggi-dm.py and trascrivi-audio.py) and scomponi/ (the reel tools, such as giro.py and scomponi.py).
Inspiration stays off until "inspiration.archive_dir" in sbk.config.json names that folder.
A relative archive_dir is read under your data root (SBK_DATA_ROOT, default ~/.sbk-data).
SB_INSPIRATION_RADICE in the environment wins over the config (a second archive, tests).

Usage: uv run python tools/secondbrain/sb_inspiration_root.py   (prints on/off and the folder)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

CONFIG_KEY = "inspiration.archive_dir"
ENV_KEY = "SB_INSPIRATION_RADICE"

OFF_MESSAGE = (
    "Inspiration is off. It works on an archive of saved ideas with its own scripts, which SBK does "
    'not ship. If you have one, set "inspiration.archive_dir" in sbk.config.json to its folder '
    "(the one that holds archivio/ and scomponi/)."
)


def data_root() -> Path:
    """Your data root: SBK_DATA_ROOT, or ~/.sbk-data (an empty value counts as unset)."""
    return Path(os.environ.get("SBK_DATA_ROOT") or str(Path.home() / ".sbk-data")).expanduser()


def _configured() -> str:
    tools = Path(__file__).resolve().parents[1]
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        from sbk_config import user_cfg
    except ImportError:
        return ""
    v = user_cfg(CONFIG_KEY, "")
    return v.strip() if isinstance(v, str) else ""


def is_on() -> bool:
    """True when an archive is named: SB_INSPIRATION_RADICE or inspiration.archive_dir."""
    return bool(os.environ.get(ENV_KEY) or _configured())


def root() -> Path:
    """The archive folder (it holds archivio/ and scomponi/). Off = <data root>/inspiration, unused."""
    env = os.environ.get(ENV_KEY)
    if env:
        return Path(env).expanduser()
    c = _configured()
    if c:
        p = Path(c).expanduser()
        return p if p.is_absolute() else data_root() / p
    return data_root() / "inspiration"


def needs_archive(script: Path | str) -> str:
    """The sentence for a feature whose archive script is missing."""
    p = Path(script)
    return (
        f"This needs {p.name}, a script of your Inspiration archive that SBK does not ship, "
        f"and it is not in {p.parent}."
    )


def main(argv: list[str]) -> int:
    if argv[1:2] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if is_on():
        print(f"Inspiration: on, archive folder {root()}")
    else:
        print(OFF_MESSAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
