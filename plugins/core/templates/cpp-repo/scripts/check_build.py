"""Commit-time gate: build/debug must compile.

clang-tidy catches most compile errors in the files a commit touches, but not a link error or a
break in a file the commit did not touch, so this runs a real incremental build. Run by the
pre-commit `build` hook and safe to run by hand: python scripts/check_build.py

Scaffolded by the setup-cpp-repo skill; this repo owns it. docs/tasks/testing.md has the why.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build" / "debug"


def main() -> int:
    if not (BUILD_DIR / "CMakeCache.txt").is_file():
        print("check_build: build/debug is not configured; run `cmake --preset debug` once first.",
              file=sys.stderr)
        return 1
    return subprocess.run(["cmake", "--build", str(BUILD_DIR)], cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
