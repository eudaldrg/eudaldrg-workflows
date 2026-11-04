"""Run a command under a cgroup memory cap, so a runaway test is killed on its own.

A terminal multiplexer session is often a systemd scope that is stopped as a whole when the
kernel OOM-kills anything inside it, taking the shell and any agent session with it. A cap turns a
test that allocates without bound into an ordinary test failure.

Used as the ctest launcher when ENABLE_TEST_MEMORY_CAP is ON, and safe to use by hand:
    python scripts/with_memory_cap.py ./build/debug/bin/my_tests

TEST_MEMORY_MAX sets the cap (a systemd size such as 2G or 512M, default 4G); 0 or "infinity"
turns it off. Without a systemd user session (other OSes, most CI containers) the command runs
uncapped and says so once on stderr.

Scaffolded by the setup-cpp-repo skill; this repo owns it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def has_user_systemd() -> bool:
    if sys.platform != "linux" or shutil.which("systemd-run") is None:
        return False
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime, "bus").is_socket()


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: with_memory_cap.py <command> [args...]", file=sys.stderr)
        return 2
    cap = os.environ.get("TEST_MEMORY_MAX", "4G")
    cmd = argv
    if cap not in ("0", "infinity"):
        if has_user_systemd():
            cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                   "-p", f"MemoryMax={cap}", "-p", "MemorySwapMax=0", "--", *argv]
        elif not os.environ.get("WITH_MEMORY_CAP_WARNED"):
            print("with_memory_cap: no systemd user session, running without a memory cap",
                  file=sys.stderr)
            os.environ["WITH_MEMORY_CAP_WARNED"] = "1"
    if os.name == "posix":
        os.execvp(cmd[0], cmd)  # no Python parent left waiting for every test
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
