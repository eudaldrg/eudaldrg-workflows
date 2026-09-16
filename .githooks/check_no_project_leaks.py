#!/usr/bin/env python3
"""Block commits that mention another project on this machine by name.

This repo is public and shared across every project on the machine; a reference to a sibling
project (its directory name, or an entry in the personal ~/.claude/workflows.json project
registry) in a commit almost always means an example leaked out of that project's own context.
Genericize the example instead. False positives go in .githooks/leak_allowlist.json.

Stdlib only. Enable both hooks with:

    git config core.hooksPath .githooks
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = REPO_ROOT / ".githooks" / "leak_allowlist.json"
MIN_TERM_LENGTH = 4


def repo_root_name() -> str:
    return REPO_ROOT.name


def sibling_project_names() -> set[str]:
    parent = REPO_ROOT.parent
    if not parent.is_dir():
        return set()
    return {
        entry.name
        for entry in parent.iterdir()
        if entry.is_dir() and entry.name != repo_root_name() and (entry / ".git").exists()
    }


def registry_project_names() -> set[str]:
    path = Path(os.environ.get("WF_HOME_CONFIG", "")) if os.environ.get("WF_HOME_CONFIG") else (
        Path.home() / ".claude" / "workflows.json"
    )
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    registry = data.get("projects", {})
    if not isinstance(registry, dict):
        return set()
    names: set[str] = set()
    for key, entry in registry.items():
        names.add(key)
        if isinstance(entry, dict) and entry.get("path"):
            names.add(Path(str(entry["path"])).expanduser().name)
    return names


def allowlist() -> set[str]:
    if not ALLOWLIST_PATH.is_file():
        return set()
    try:
        data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(term).lower() for term in data.get("allow", [])}


def build_blocklist() -> set[str]:
    candidates = sibling_project_names() | registry_project_names()
    allowed = allowlist()
    return {
        name
        for name in candidates
        if len(name) >= MIN_TERM_LENGTH and name.lower() not in allowed
    }


def scan_text(text: str, blocklist: set[str]) -> list[str]:
    hits = []
    for name in sorted(blocklist):
        pattern = re.compile(re.escape(name), re.IGNORECASE)
        if pattern.search(text):
            hits.append(name)
    return hits


def staged_added_lines() -> str:
    out = subprocess.run(
        ["git", "diff", "--cached", "--no-color", "-U0"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    added = [
        line[1:]
        for line in out.stdout.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    return "\n".join(added)


def report(hits: list[str], context: str) -> None:
    print(f"error: {context} mentions {', '.join(hits)} — looks like a reference to another "
          "project on this machine.", file=sys.stderr)
    print(
        "Genericize the example, or if this is a false positive add the term to "
        f"{ALLOWLIST_PATH.relative_to(REPO_ROOT)}'s \"allow\" list.",
        file=sys.stderr,
    )


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_no_project_leaks.py {diff|message <path>}", file=sys.stderr)
        return 2

    blocklist = build_blocklist()
    if not blocklist:
        return 0

    if argv[0] == "diff":
        text = staged_added_lines()
        context = "this commit"
    elif argv[0] == "message" and len(argv) > 1:
        text = Path(argv[1]).read_text(encoding="utf-8")
        context = "this commit message"
    else:
        print("usage: check_no_project_leaks.py {diff|message <path>}", file=sys.stderr)
        return 2

    hits = scan_text(text, blocklist)
    if hits:
        report(hits, context)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
