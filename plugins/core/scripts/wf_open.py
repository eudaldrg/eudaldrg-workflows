#!/usr/bin/env python3
"""Open a local file in a browser, portably.

This is the only file in the repo allowed to know that WSL exists. Everything
else must run unchanged on plain Ubuntu, so when the host changes this is the
one file to look at.

Order matters: an explicit $BROWSER beats the desktop default, the desktop
default beats a WSL bridge, and launching a Windows browser is the last resort
because it needs the path translated and cannot see Linux-only files reliably.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

OK = 0
ERR_NO_OPENER = 1
ERR_MISSING = 3


def candidates() -> list[tuple[str, list[str]]]:
    found: list[tuple[str, list[str]]] = []
    browser = os.environ.get("BROWSER", "").strip()
    if browser:
        # $BROWSER may be a colon-separated list, and each entry may have args.
        for entry in browser.split(":"):
            parts = entry.split()
            if parts and shutil.which(parts[0]):
                found.append(("BROWSER", parts))
    for name in ("xdg-open", "wslview", "sensible-browser", "gio", "open"):
        if shutil.which(name):
            found.append((name, [name, "open"] if name == "gio" else [name]))
    if shutil.which("explorer.exe"):
        found.append(("explorer.exe", ["explorer.exe"]))
    return found


def to_windows_path(path: Path) -> str | None:
    if not shutil.which("wslpath"):
        return None
    try:
        out = subprocess.run(
            ["wslpath", "-w", str(path)], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def open_path(path: Path, dry_run: bool = False) -> tuple[bool, str]:
    for name, command in candidates():
        argument = str(path)
        if name == "explorer.exe":
            translated = to_windows_path(path)
            if not translated:
                continue
            argument = translated
        attempt = [*command, argument]
        if dry_run:
            return True, " ".join(attempt)
        try:
            result = subprocess.run(
                attempt,
                capture_output=True,
                text=True,
                timeout=20,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        # explorer.exe reports failure with exit code 1 even when it worked, so
        # it is the one opener whose exit code we deliberately ignore.
        if result.returncode == 0 or name == "explorer.exe":
            return True, " ".join(attempt)
    return False, ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wf_open.py", description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--dry-run", action="store_true", help="print the command, run nothing")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return ERR_MISSING

    opened, command = open_path(path, args.dry_run)
    if not opened:
        # Not an error worth failing a briefing over: print the path and let the
        # human click it. A headless box legitimately has no browser.
        print(f"no way to open a browser here; the file is at:\n{path}", file=sys.stderr)
        return ERR_NO_OPENER
    if not args.quiet:
        print(command if args.dry_run else f"opened {path}")
    return OK


if __name__ == "__main__":
    sys.exit(main())
