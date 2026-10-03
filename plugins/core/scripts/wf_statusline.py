#!/usr/bin/env python3
"""Render the shared status line from the JSON Claude Code pipes to stdin.

    <host>:<wd> (<branch><dirty>) <model> [<effort>] <used>/<cap> (<pct>%) cache <state> [$<next>r|w] $<cost> ($<rate>/hr)

When the terminal is too narrow for that on one row (a phone), the segments wrap onto several
rows — Claude Code renders every printed line as its own status row. Width comes from the tmux
pane, then $COLUMNS, then `statusLine.maxWidth` (0 = never wrap).

Each segment degrades independently: a field missing from the input JSON (older Claude Code
version, a model without an effort parameter, a non-git directory) just drops that segment rather
than failing the whole line. Stdlib only — see wf_config.py for why.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf_config  # noqa: E402

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"

GIT_TIMEOUT = 2
TMUX_TIMEOUT = 1
# Claude Code indents/pads the status area a little; stay clear of the right edge.
WIDTH_MARGIN = 2
ANSI_RE = re.compile(r"\033\[[0-9;]*m")
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


def format_remaining(seconds: int) -> str:
    if seconds >= 3600:
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


# (match on lowercased model id/display name, input $/MTok, cache-read multiplier of input).
# Order matters: the more specific "opus 5.5" must precede "opus 5". Fable 5.1 is not listed because
# its input price is not recorded here; an unknown model shows the cache state without an amount.
MODEL_PRICES = (
    (("opus-5-5", "opus 5.5"), 4.0, 0.05),
    (("opus-5", "opus 5"), 5.0, 0.1),
    (("sonnet-5", "sonnet 5"), 2.0, 0.1),
    (("haiku-4-5", "haiku 4.5"), 1.0, 0.1),
)
WRITE_MULTIPLIER = {"5m": 1.25, "1h": 2.0}
DEFAULT_WRITE_TTL = "1h"  # subscription default; used when no TTL is known (state "none")


def model_price(model_id: str, display_name: str) -> tuple[float, float] | None:
    haystack = f"{model_id} {display_name}".lower()
    for needles, price, read_mult in MODEL_PRICES:
        if any(n in haystack for n in needles):
            return price, read_mult
    return None


def next_request_cost(
    tokens: int | None, model_id: str, display_name: str, warm: bool, ttl: str | None
) -> str | None:
    """What re-sending the existing context costs: `$0.07r` (cache read) or `$2.87w` (cache write)."""
    price = model_price(model_id, display_name)
    if not tokens or price is None:
        return None
    input_price, read_mult = price
    if warm:
        return f"${tokens * input_price * read_mult / 1_000_000:.2f}r"
    write_mult = WRITE_MULTIPLIER.get(ttl or "", WRITE_MULTIPLIER[DEFAULT_WRITE_TTL])
    return f"${tokens * input_price * write_mult / 1_000_000:.2f}w"


def cache_segment(
    cache: dict | None,
    warn_seconds: int,
    now: float,
    tokens: int | None = None,
    model_id: str = "",
    display_name: str = "",
) -> str:
    """Always-present cache state plus the next request's cost for the existing context.

    `cache none` (red): nothing known or caching never observed; `cache cold` (red): expired;
    `cache <left>/<ttl>`: warm. Claude Code reports an absolute `expires_at` that moves forward on
    every request, so this only stays accurate if the status line is re-run periodically
    (see `refreshInterval`).
    """
    cache = cache or {}
    ttl = cache.get("ttl") or None
    expires_at = cache.get("expires_at")
    remaining = int(expires_at - now) if isinstance(expires_at, (int, float)) else 0
    if not cache.get("caching_observed"):
        state, color, warm = "cache none", RED, False
    elif not cache.get("warm") or remaining <= 0:
        state, color, warm = "cache cold", RED, False
    else:
        state = f"cache {format_remaining(remaining)}" + (f"/{ttl}" if ttl else "")
        color, warm = (YELLOW if remaining < warn_seconds else ""), True
    text = wrap(state, color)
    cost = next_request_cost(tokens, model_id, display_name, warm, ttl)
    return f"{text} {cost}" if cost else text


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


def visible_len(text: str) -> int:
    return len(ANSI_RE.sub("", text))


def terminal_width(merged: dict) -> int:
    """Best-effort width in columns; 0 means unknown/unlimited.

    The status command has no controlling tty and no COLUMNS, so inside tmux the pane
    is asked directly — it tracks the smallest attached client, which is what the phone is.
    """
    pane = os.environ.get("TMUX_PANE")
    if os.environ.get("TMUX") and pane:
        try:
            out = subprocess.run(
                ["tmux", "display-message", "-p", "-t", pane, "#{pane_width}"],
                capture_output=True,
                text=True,
                timeout=TMUX_TIMEOUT,
            )
            if out.returncode == 0 and out.stdout.strip().isdigit():
                return int(out.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    columns = os.environ.get("COLUMNS", "")
    if columns.isdigit():
        return int(columns)
    return int(cfg(merged, "statusLine.maxWidth", 0))


def pack_rows(units: list[str], width: int) -> list[str]:
    """Greedily join units with spaces into rows no wider than `width` (0 = one row).

    A unit wider than the width gets a row to itself; the terminal truncates it.
    """
    if width <= 0:
        return [" ".join(units)]
    limit = max(width - WIDTH_MARGIN, 1)
    rows: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
        elif visible_len(current) + 1 + visible_len(unit) <= limit:
            current += " " + unit
        else:
            rows.append(current)
            current = unit
    if current:
        rows.append(current)
    return rows


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
    effort = payload.get("effort", {}).get("level")
    model_text = " ".join(part for part in (model, f"[{effort}]" if effort else None) if part)
    if model_text:
        segments.append(model_text)

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

    if cfg(merged, "statusLine.showCache", True):
        model_info = payload.get("model", {})
        segments.append(
            cache_segment(
                payload.get("prompt_cache"),
                cfg(merged, "statusLine.cacheWarnSeconds", 300),
                time.time(),
                (payload.get("context_window") or {}).get("total_input_tokens"),
                model_info.get("id") or "",
                model_info.get("display_name") or "",
            )
        )

    cost = payload.get("cost", {})
    total_cost = cost.get("total_cost_usd")
    if total_cost is not None:
        cost_text = f"${total_cost:.2f}"
        duration_ms = cost.get("total_duration_ms") or 0
        if cfg(merged, "statusLine.showBurnRate", True) and duration_ms >= MIN_BURN_RATE_DURATION_MS:
            warn = cfg(merged, "statusLine.costRateWarnUsdPerHr", 6)
            crit = cfg(merged, "statusLine.costRateCritUsdPerHr", 20)
            rate = total_cost / (duration_ms / 3_600_000)
            cost_text += f" ({wrap(f'${rate:.2f}/hr', color_for(rate, warn, crit))})"
        segments.append(cost_text)

    return "\n".join(pack_rows(segments, terminal_width(merged)))


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
