#!/usr/bin/env python3
"""Render the shared status line from the JSON Claude Code pipes to stdin.

    <host>:<wd> (<branch><dirty>) <model> [<effort>] <used>/<cap> (<pct>%) $<cost> ($<rate>/hr)

Each segment degrades independently: a field missing from the input JSON (older Claude Code
version, a model without an effort parameter, a non-git directory) just drops that segment rather
than failing the whole line. Stdlib only — see wf_config.py for why.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf_config  # noqa: E402

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"

GIT_TIMEOUT = 2
MIN_BURN_RATE_DURATION_MS = 30_000


def cfg(merged: dict, key: str, default):
    value, found = wf_config.lookup(merged, key)
    return value if found else default


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    return str(n)


def color_for(value: float, warn: float, crit: float) -> str:
    if value >= crit:
        return RED
    if value >= warn:
        return YELLOW
    return ""


def wrap(text: str, color: str) -> str:
    return f"{color}{text}{RESET}" if color else text


def collapse_home(path: str) -> str:
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def git_branch_and_dirty(cwd: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain=v1", "--branch"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout:
        return None
    lines = out.stdout.splitlines()
    header = lines[0].removeprefix("## ")
    branch = header.split("...", 1)[0]
    if branch.startswith("HEAD"):
        branch = "detached"
    dirty = "*" if len(lines) > 1 else ""
    return f"{branch}{dirty}"


def build_line(payload: dict, merged: dict) -> str:
    host = socket.gethostname().split(".")[0]
    cwd = payload.get("workspace", {}).get("current_dir") or payload.get("cwd", "")
    wd = collapse_home(cwd)

    segments = [f"{host}:{wd}"]

    if cwd and cfg(merged, "statusLine.showGitBranch", True):
        branch = git_branch_and_dirty(cwd)
        if branch:
            segments.append(f"({branch})")

    model = payload.get("model", {}).get("display_name")
    if model:
        segments.append(model)

    effort = payload.get("effort", {}).get("level")
    if effort:
        segments.append(f"[{effort}]")

    context = payload.get("context_window")
    if context:
        used = context.get("total_input_tokens")
        cap = context.get("context_window_size")
        pct = context.get("used_percentage")
        if used is not None and cap:
            token_text = f"{format_tokens(used)}/{format_tokens(cap)}"
            if pct is not None:
                warn = cfg(merged, "statusLine.contextWarnPercent", 60)
                crit = cfg(merged, "statusLine.contextCritPercent", 85)
                token_text += " " + wrap(f"({pct:.0f}%)", color_for(pct, warn, crit))
            segments.append(token_text)

    cost = payload.get("cost", {})
    total_cost = cost.get("total_cost_usd")
    if total_cost is not None:
        warn = cfg(merged, "statusLine.costWarnUsd", 3)
        crit = cfg(merged, "statusLine.costCritUsd", 10)
        cost_text = wrap(f"${total_cost:.2f}", color_for(total_cost, warn, crit))
        duration_ms = cost.get("total_duration_ms") or 0
        if cfg(merged, "statusLine.showBurnRate", True) and duration_ms >= MIN_BURN_RATE_DURATION_MS:
            rate = total_cost / (duration_ms / 3_600_000)
            cost_text += f" (${rate:.2f}/hr)"
        segments.append(cost_text)

    return " ".join(segments)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    cwd = payload.get("workspace", {}).get("current_dir") or payload.get("cwd")
    try:
        merged, _, _ = wf_config.load_all(explicit_project=cwd)
    except wf_config.ConfigError:
        merged = {}

    try:
        print(build_line(payload, merged))
    except Exception:
        # A broken status line is worse than a minimal one: never let a formatting
        # bug blank out the whole bar.
        host = socket.gethostname().split(".")[0]
        print(f"{host}:{collapse_home(payload.get('cwd', '') or '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
