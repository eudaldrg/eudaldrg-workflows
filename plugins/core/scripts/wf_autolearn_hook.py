#!/usr/bin/env python3
"""Stop hook: queue correction candidates from the session that just ended.

Off by default (`autoLearn.hook.enabled`). It exists because catching a
correction while the session is fresh beats rediscovering it a week later, but
it stays opt-in because a hook that runs on every session end should be the
user's choice, not the plugin's.

It obeys the standing rule for hooks in this repo: **detect and report, never
mutate**. It writes only to the plugin's own data directory, never to the
user's repository, never to the transcript, and never to a config file. Nothing
is applied; `/core:auto-learn` is where a human decides.

Any failure is silent. A broken hook must never be the reason a session cannot
end, so every path here exits 0.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def data_dir() -> Path:
    override = os.environ.get("CLAUDE_PLUGIN_DATA")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "plugin-data" / "core"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        return 0

    try:
        import wf_config
        import wf_sessions

        merged, _, _ = wf_config.load_all(payload.get("cwd"))
        enabled, found = wf_config.lookup(merged, "autoLearn.hook.enabled")
        if not found or enabled is not True:
            return 0

        transcript = payload.get("transcript_path")
        if not transcript:
            return 0
        path = Path(transcript)
        if not path.is_file():
            return 0

        minimum, has_min = wf_config.lookup(merged, "autoLearn.minScore")
        threshold = int(minimum) if has_min else wf_sessions.CUE_THRESHOLD
        limit, has_limit = wf_config.lookup(merged, "autoLearn.maxCandidatesPerRun")
        cap = int(limit) if has_limit else 25

        reader = wf_sessions.Reader(wf_sessions.settings(payload.get("cwd")))
        candidates = [
            item
            for item in wf_sessions.find_corrections(reader, path)
            if item["score"] >= threshold
        ][:cap]
        if not candidates:
            return 0

        relative, has_rel = wf_config.lookup(merged, "autoLearn.pendingFile")
        target = data_dir() / (str(relative) if has_rel else "learnings/pending.jsonl")
        target.parent.mkdir(parents=True, exist_ok=True)

        # Append-only, one JSON object per line: concurrent sessions ending at the
        # same moment cannot corrupt each other, and nothing is ever overwritten.
        seen = set()
        if target.is_file():
            for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    seen.add(json.loads(line).get("at"))
                except json.JSONDecodeError:
                    continue
        with target.open("a", encoding="utf-8") as handle:
            for item in candidates:
                if item["at"] in seen:
                    continue
                item["queuedBy"] = "stop-hook"
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
