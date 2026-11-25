#!/usr/bin/env python3
""




















from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path






DOCS_ALLOWED = {
    "docs/sbk/rules",
    "docs/sbk/guides",
    "docs/sbk/security",
    "docs/sbk/integrations",
    "docs/sbk/clickup",
    "docs/sbk/deploy",
    "docs/sbk/specs",
    "docs/sbk/notes",
    "docs/sbk/playbooks",
    "docs/sbk/platform-docs",
    "docs/sbk/sources",
    "docs/sbk/knowledge",
    "docs/sbk/mac-ops",
}


DOCS_FILE_EXCEPTIONS = {
    "docs/README.md",
}


DOCS_AUDITS_JSON_RE = re.compile(r"^docs/sbk/audits/[^/]+\.json$")


BINARY_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tiff",
    ".webp",
    ".ico",
    ".svg",
    ".docx",
    ".xlsx",
    ".pptx",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".mp4",
    ".mp3",
    ".mov",
    ".avi",
    ".mkv",
    ".wav",
    ".flac",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
}


BINARY_ALLOWED_PREFIXES = {
    "dashboard/static",
    "dashboard/app/static",


    "tools/secondbrain/app/SBK.icon",
}



FORBIDDEN_PATH_PATTERNS = [
    re.compile(r"~/\.partner(?:/|['\"])", re.IGNORECASE),
    re.compile(re.escape(str(Path.home())) + r"(?:/|['\"])", re.IGNORECASE),
    re.compile(r"~/Downloads(?:/|['\"])", re.IGNORECASE),
    re.compile(r"~/Desktop(?:/|['\"])", re.IGNORECASE),
]


TOOLS_CHECK_EXTENSIONS = {".py", ".sh", ".md"}







def _staged_files():
    # type: () -> list[tuple[str, str]]
    ""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-status", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    entries = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            entries.append((parts[0], parts[1]))
    return entries


def _is_docs_allowed(path):
    # type: (str) -> bool
    ""
    if path in DOCS_FILE_EXCEPTIONS:
        return True
    if DOCS_AUDITS_JSON_RE.match(path):
        return True
    for allowed in DOCS_ALLOWED:
        if path.startswith(allowed + "/") or path == allowed:
            return True
    return False


def _is_binary_allowed(path):
    # type: (str) -> bool
    ""
    for prefix in BINARY_ALLOWED_PREFIXES:
        if path.startswith(prefix + "/") or path.startswith(prefix):
            return True
    return False


def _check_forbidden_paths(path):
    # type: (str) -> list[str]
    ""
    problems = []
    try:

        result = subprocess.run(
            ["git", "show", ":" + path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
        content = result.stdout
    except (subprocess.SubprocessError, OSError):
        return []

    for i, line in enumerate(content.splitlines(), 1):

        if "# perimetro-ok:" in line or "# perimetro-ok " in line:
            continue
        for pat in FORBIDDEN_PATH_PATTERNS:
            if pat.search(line):
                problems.append(
                    f"{path}:{i}: forbidden path ({pat.pattern}). "
                    "If it is a read-only reference: "
                    "add `# perimetro-ok: <reason>`"
                )
                break

    return problems


def check():
    # type: () -> list[str]
    ""
    staged = _staged_files()
    if not staged:
        return []

    problems = []

    for status, path in staged:

        if path.startswith("docs/") and not _is_docs_allowed(path):
            problems.append(
                f"{path}: outside the allowed docs/ folders. "
                "Keep dossiers in ~/.sbk-data/work/<organization>/<project>/, "
                "or docs/sbk/<subfolder>/ for the system documents."
            )


        ext = os.path.splitext(path)[1].lower()
        if ext in BINARY_EXTENSIONS and not _is_binary_allowed(path):
            problems.append(
                f"{path}: binary file ({ext}) not allowed in git. "
                "Binaries go in ~/.sbk-data/work/ "
                "or in dashboard/static/."
            )


        if path.startswith("tools/") and ext in TOOLS_CHECK_EXTENSIONS:
            if status in ("A", "M"):
                fp = _check_forbidden_paths(path)
                problems.extend(fp)

    return problems







def main():
    # type: () -> int
    problems = check()
    if problems:
        print(f"sb-solo-struttura: {len(problems)} problem(s) found:")
        for p in problems:
            print("  - " + p)
        print()
        print(
            "Fix and re-run git add. Dossiers go in ~/.sbk-data/work/<organization>/<project>/."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
