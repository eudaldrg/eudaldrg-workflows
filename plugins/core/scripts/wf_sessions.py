#!/usr/bin/env python3
"""Read Claude Code session transcripts.

This is the only file in the repo that knows the transcript JSONL schema. When
the format shifts there is one place to fix, and `verify` is the canary that says
so out loud instead of silently dropping data.

Everything here is tolerant by construction: unknown line types are counted and
ignored, every optional field goes through .get(), and a line that will not parse
is reported rather than fatal. Only `type` and the conversation core (`uuid`,
`timestamp`, `cwd`, `sessionId`) are treated as load-bearing.

Paths are handled with pathlib and never through a shell: project directories are
named after the cwd with slashes replaced, so they start with `-` and every CLI
tool on the box mistakes them for options.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf_config  # noqa: E402

OK = 0
NOT_FOUND = 3

# Seen in the corpus as of CLI 2.1.269-2.1.273. `verify` flags anything new; the
# point is to notice additions, not to reject them.
KNOWN_TYPES = {
    "agent-name", "ai-title", "assistant", "atis-latch", "attachment",
    "bridge-session", "cost-state", "custom-title", "file-history-delta",
    "file-history-snapshot", "last-prompt", "mode", "permission-mode", "pr-link",
    "queue-operation", "system", "user",
}

# A human prompt is a `user` line that is not a tool result, not injected, and
# not another agent talking. Headless (`-p`) runs carry no `origin` at all, so an
# absent origin is *allowed* — excluding it would drop every scripted session —
# while `promptSource: system` and any non-human origin.kind are excluded.
NON_HUMAN_ORIGINS = {"task-notification", "peer", "coordinator"}

EDIT_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}

# Cues for `corrections`. These are lexical on purpose. The structural signals a
# correction detector would obviously reach for — `is_error` on a tool result,
# `toolDenialKind`, `userModified`, an `absorbed_mid_turn` queue-operation — were
# measured across this whole corpus and *none* of them is ever followed by a human
# prompt. They mark trouble the assistant handled by itself. Meanwhile both
# corrections that graduated into memory carry no structural signal at all and are
# recognisable only by what the human wrote. They are still reported as context.
CORRECTION_CUES = {
    "negation": [
        r"\bi don'?t want\b", r"\bdon'?t\b", r"\bthat'?s not\b", r"\bthat is not\b",
        r"\bnot really\b", r"\bnot what\b", r"\bwrong\b", r"\bstop\b",
    ],
    "dispute": [
        r"\bwhy (did|are|do) you\b", r"\bwhat is this\b", r"\bdid i ask\b",
        r"\byou proposed\b", r"\byour claim\b", r"\bdo you mean\b",
        r"\breason (a bit )?more\b", r"\bare you sure\b",
        r"\bis that (true|right|correct)\b", r"\bi never (asked|said)\b",
        r"\bsomething i asked\b",
    ],
    "redirect": [
        r"\binstead\b", r"\brather\b", r"\byou should\b", r"\bi'?d prefer\b",
        r"\blet'?s not\b", r"\bi had in mind\b",
    ],
    # Deliberately typo-tolerant: the real corpus contains "Wjat do you mean", and
    # an exact-match cue for "what do you mean" missed a genuine correction.
    "opener": [
        r"^(ok(ay)?[,.\s]+)?(no|nope|wait|actually|hold on)\b", r"^that (is|'s) not\b",
        r"^i don'?t\b", r"^why\b", r"^w[hj]at (is|do) (this|you)\b",
    ],
    "pivot": [
        r"\bbut (we|you|i) (are|should|need|want|don'?t|didn'?t|can'?t)\b", r", not\b",
    ],
}
CUES = {name: [re.compile(p, re.I) for p in pats] for name, pats in CORRECTION_CUES.items()}
# A correction usually opens with the redirect; a cue buried in paragraph four of a
# long task description is far more often a coincidence.
CUE_HEAD = 140
CUE_THRESHOLD = 2

COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.DOTALL)
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
STRIP_BLOCKS = re.compile(
    r"<(command-message|command-contents|local-command-stdout|local-command-caveat|"
    r"system-reminder|task-notification)>.*?</\1>",
    re.DOTALL,
)


# --------------------------------------------------------------------------- config


def settings(project: str | None = None) -> dict:
    merged, _, _ = wf_config.load_all(project)
    value, found = wf_config.lookup(merged, "sessions")
    base = {
        "transcriptsDir": "~/.claude/projects",
        "aliases": {},
        "excludePathPrefixes": ["/tmp/"],
        "includeSubagents": True,
    }
    if found and isinstance(value, dict):
        base.update(value)
    return base


def transcripts_dir(config: dict) -> Path:
    return Path(os.path.expanduser(str(config["transcriptsDir"])))


# --------------------------------------------------------------------------- time


def parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def resolve_since(spec: str | None) -> datetime | None:
    """`previous-working-day` is the default because that is the question being
    asked on a Monday morning: what happened since I last worked."""
    if not spec or spec in {"all", "forever"}:
        return None
    now = datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if spec == "today":
        return midnight
    if spec == "yesterday":
        return midnight - timedelta(days=1)
    if spec == "previous-working-day":
        day = midnight - timedelta(days=1)
        while day.weekday() >= 5:  # Saturday, Sunday
            day -= timedelta(days=1)
        return day
    match = re.fullmatch(r"(\d+)([dhw])", spec)
    if match:
        amount = int(match.group(1))
        unit = {"d": "days", "h": "hours", "w": "weeks"}[match.group(2)]
        return now - timedelta(**{unit: amount})
    parsed = parse_ts(spec) or parse_ts(spec + "T00:00:00")
    if parsed is None:
        raise SystemExit(
            f"unrecognised --since {spec!r}; use previous-working-day, today, "
            "yesterday, 7d, 12h, 2w, or an ISO date"
        )
    return parsed if parsed.tzinfo else parsed.astimezone()


# --------------------------------------------------------------------------- text


def message_text(message: object) -> str:
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


def clean_prompt(text: str) -> str:
    """A slash command arrives wrapped in markup. Keep the invocation, drop the
    wrapper — `/core:investigate how do we test` is what the human meant."""
    name = COMMAND_NAME.search(text)
    if name:
        args = COMMAND_ARGS.search(text)
        invocation = name.group(1).strip()
        argument = (args.group(1).strip() if args else "")
        return f"{invocation} {argument}".strip()
    text = STRIP_BLOCKS.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def is_human_prompt(entry: dict) -> bool:
    if entry.get("type") != "user" or "toolUseResult" in entry or entry.get("isMeta"):
        return False
    # A compaction summary arrives as a user turn but nobody typed it; counting it
    # makes a long session look like it opened with a wall of text.
    if entry.get("isCompactSummary"):
        return False
    if entry.get("promptSource") == "system":
        return False
    origin = entry.get("origin")
    kind = origin.get("kind") if isinstance(origin, dict) else None
    return kind is None or kind == "human"


# --------------------------------------------------------------------------- reading


class Reader:
    def __init__(self, config: dict):
        self.config = config
        self.root = transcripts_dir(config)
        self.excluded = [str(p) for p in config.get("excludePathPrefixes") or []]
        self.aliases = {
            str(Path(k).expanduser()): str(Path(v).expanduser())
            for k, v in (config.get("aliases") or {}).items()
        }
        self.unparseable: list[str] = []
        self.unknown_types: dict[str, int] = {}

    # -- discovery

    def main_transcripts(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(self.root.glob("*/*.jsonl"))

    def subagent_transcripts(self, path: Path) -> list[Path]:
        directory = path.parent / path.stem / "subagents"
        return sorted(directory.glob("*.jsonl")) if directory.is_dir() else []

    def subagent_meta(self, path: Path) -> list[dict]:
        directory = path.parent / path.stem / "subagents"
        if not directory.is_dir():
            return []
        out = []
        for meta in sorted(directory.glob("*.meta.json")):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append(
                {
                    "id": meta.name.removesuffix(".meta.json"),
                    "agentType": data.get("agentType"),
                    "description": data.get("description"),
                }
            )
        return out

    # -- parsing

    def entries(self, path: Path):
        try:
            handle = path.open(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.unparseable.append(f"{path}: {exc}")
            return
        with handle:
            for number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    self.unparseable.append(f"{path.name}:{number}: {exc.msg}")
                    continue
                if not isinstance(entry, dict):
                    self.unparseable.append(f"{path.name}:{number}: not an object")
                    continue
                kind = entry.get("type")
                if kind not in KNOWN_TYPES:
                    self.unknown_types[str(kind)] = self.unknown_types.get(str(kind), 0) + 1
                yield entry

    def attribute(self, cwds: list[str]) -> tuple[str | None, str | None]:
        """Last non-excluded cwd wins.

        The directory name cannot be trusted: renaming a project leaves the old
        slug directory in place, and the slug transform maps both `/` and `_` to
        `-`, so it is lossy and not invertible. A session that spans a rename has
        both paths in its own `cwd` field, and the later one is the truth.
        """
        for raw in reversed(cwds):
            if any(raw.startswith(prefix) for prefix in self.excluded):
                continue
            path = self.aliases.get(raw, raw)
            try:
                path = str(Path(path).resolve())
            except OSError:
                pass
            path = self.aliases.get(path, path)
            return Path(path).name, path
        return None, None

    def read_session(self, path: Path) -> dict:
        session: dict = {
            "id": path.stem,  # a subagent file carries its *parent's* sessionId
            "file": str(path),
            "project": None,
            "projectPath": None,
            "title": None,
            "start": None,
            "end": None,
            "branches": [],
            "prompts": [],
            "commits": [],
            "prs": [],
            "filesTouched": [],
            "toolCounts": {},
            "subagents": self.subagent_meta(path),
            "cost": {},
            "versions": [],
            "lines": 0,
        }
        cwds: list[str] = []
        titles = {"ai": None, "custom": None}
        sources = [path]
        if self.config.get("includeSubagents", True):
            sources += self.subagent_transcripts(path)

        for source in sources:
            is_parent = source == path
            self._absorb(session, source, cwds if is_parent else [], titles, is_parent)

        session["project"], session["projectPath"] = self.attribute(cwds)
        session["title"] = titles["custom"] or titles["ai"]
        session["branches"] = sorted(set(session["branches"]))
        session["filesTouched"] = sorted(set(session["filesTouched"]))
        session["versions"] = sorted(set(session["versions"]))
        # One PR is re-announced on every subsequent turn; count it once.
        session["prs"] = _dedupe(session["prs"])
        session["commits"] = _dedupe(session["commits"])
        return session

    def _absorb(
        self, session: dict, source: Path, cwds: list[str], titles: dict, is_parent: bool
    ) -> None:
        tool_names: dict[str, str] = {}
        for entry in self.entries(source):
            session["lines"] += 1
            kind = entry.get("type")
            when = parse_ts(entry.get("timestamp"))
            if when:
                if session["start"] is None or when < session["start"]:
                    session["start"] = when
                if session["end"] is None or when > session["end"]:
                    session["end"] = when
            if entry.get("cwd") and is_parent:
                cwds.append(entry["cwd"])
            if entry.get("gitBranch"):
                session["branches"].append(entry["gitBranch"])
            if entry.get("version"):
                session["versions"].append(entry["version"])

            if kind == "ai-title":
                titles["ai"] = entry.get("aiTitle") or titles["ai"]
            elif kind == "custom-title":
                titles["custom"] = entry.get("customTitle") or titles["custom"]
            elif kind == "cost-state":
                # Rewritten repeatedly; the last one is the session total.
                session["cost"] = {
                    "linesAdded": entry.get("totalLinesAdded"),
                    "linesRemoved": entry.get("totalLinesRemoved"),
                    "usd": entry.get("totalCostUSD"),
                    "durationMs": entry.get("totalDuration"),
                }
            elif kind == "pr-link":
                session["prs"].append(
                    {"number": entry.get("prNumber"), "url": entry.get("prUrl")}
                )
            elif kind == "file-history-delta" and entry.get("trackingPath"):
                session["filesTouched"].append(entry["trackingPath"])
            elif kind == "assistant":
                for block in (entry.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name") or "?"
                        tool_names[block.get("id") or ""] = name
                        session["toolCounts"][name] = session["toolCounts"].get(name, 0) + 1
            elif kind == "user":
                if is_human_prompt(entry) and is_parent:
                    text = clean_prompt(message_text(entry.get("message")))
                    if text:
                        session["prompts"].append(
                            {"at": entry.get("timestamp"), "text": text}
                        )
                    continue
                self._absorb_tool_result(session, entry, tool_names)

    def _absorb_tool_result(self, session: dict, entry: dict, tool_names: dict) -> None:
        result = entry.get("toolUseResult")
        if not isinstance(result, dict):
            return
        operation = result.get("gitOperation")
        if isinstance(operation, dict):
            # Structural, and therefore right. Regexing `git commit` out of Bash
            # inputs false-positives on any script that contains the string.
            commit = operation.get("commit")
            if isinstance(commit, dict) and commit.get("sha"):
                session["commits"].append(
                    {
                        "sha": str(commit.get("sha"))[:12],
                        "kind": commit.get("kind"),
                        "branch": commit.get("branch"),
                        "at": entry.get("timestamp"),
                    }
                )
        used = ""
        for block in (entry.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                used = tool_names.get(block.get("tool_use_id") or "", "")
        if used in EDIT_TOOLS and result.get("filePath"):
            session["filesTouched"].append(result["filePath"])


# --------------------------------------------------------------------------- corrections


def cue_score(text: str) -> tuple[int, dict[str, int]]:
    score = 0
    why: dict[str, int] = {}
    head = text[:CUE_HEAD]
    for name, patterns in CUES.items():
        if not any(p.search(text) for p in patterns):
            continue
        weight = 2 if name == "opener" or any(p.search(head) for p in patterns) else 1
        score += weight
        why[name] = weight
    return score, why


def find_corrections(reader: Reader, path: Path) -> list[dict]:
    """A candidate is a human prompt that reads like it is redirecting Claude.

    This narrows, it does not classify. Every candidate is meant to be read with
    its context by something that can judge; the threshold is set for recall.
    """
    session = reader.read_session(path)
    context = {"acted": False, "tools": [], "toolErrors": 0, "denials": 0, "userModified": 0}
    tool_names: dict[str, str] = {}
    out: list[dict] = []

    for entry in reader.entries(path):
        kind = entry.get("type")
        if kind == "assistant":
            for block in (entry.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    context["acted"] = True
                    tool_names[block.get("id") or ""] = block.get("name") or "?"
                    context["tools"].append(block.get("name") or "?")
            continue
        if kind != "user":
            continue
        if entry.get("toolDenialKind"):
            context["denials"] += 1
        result = entry.get("toolUseResult")
        if isinstance(result, dict):
            if result.get("is_error"):
                context["toolErrors"] += 1
            if result.get("userModified"):
                context["userModified"] += 1
        for block in (entry.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("is_error"):
                context["toolErrors"] += 1

        if not is_human_prompt(entry):
            continue
        text = clean_prompt(message_text(entry.get("message")))
        # A slash command is an invocation, not a correction.
        if text and not text.startswith("/"):
            score, why = cue_score(text)
            if score >= CUE_THRESHOLD:
                out.append(
                    {
                        "session": path.stem,
                        "project": session["project"],
                        "at": entry.get("timestamp"),
                        "score": score,
                        "cues": why,
                        "text": text,
                        "precededBy": {
                            "acted": context["acted"],
                            "tools": sorted(set(context["tools"]))[:8],
                            "toolErrors": context["toolErrors"],
                            "denials": context["denials"],
                            "userModified": context["userModified"],
                        },
                        "transcript": str(path),
                    }
                )
        context = {"acted": False, "tools": [], "toolErrors": 0, "denials": 0, "userModified": 0}
    return out


QUOTED = re.compile(r"[\"\u201c]([^\"\u201c\u201d]{25,})[\"\u201d]")


MEMORY_NAME = re.compile(r"^name:\s*(.+?)\s*$", re.M)
MEMORY_DESC = re.compile(r"^description:\s*[\"']?(.+?)[\"']?\s*$", re.M)
MEMORY_TYPE = re.compile(r"^\s+type:\s*(\w+)\s*$", re.M)


def read_memory(path: Path) -> dict | None:
    """Parse one of Claude Code's own memory files.

    Deliberately not the knowledge-doc parser: these carry a nested `metadata:`
    block, and three regexes beat teaching a flat parser about indentation.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    name = MEMORY_NAME.search(text)
    description = MEMORY_DESC.search(text)
    kind = MEMORY_TYPE.search(text)
    return {
        "name": (name.group(1) if name else path.stem).strip().strip("\"'"),
        "description": description.group(1).strip().replace('\\"', '"') if description else "",
        "type": kind.group(1) if kind else "unknown",
        "file": str(path),
        # Memory files quote what the user actually said under **Why:**. That makes
        # them a labelled set — the only honest way to check a detector that would
        # otherwise be tuned against its author's intuition.
        "quotes": [q.strip() for q in QUOTED.findall(text)],
    }


def memory_by_project(reader: Reader) -> list[dict]:
    """Memory grouped by the project it really belongs to.

    Memory is stored per slug directory, and the slug is exactly the thing that
    cannot be trusted: it is derived from a path that may since have been renamed.
    So each directory is re-attributed through the sessions inside it, the same way
    a session is, and a directory whose project no longer resolves is called out
    rather than silently listed under a stale name.
    """
    groups: list[dict] = []
    for slug in sorted(p for p in reader.root.iterdir() if p.is_dir()):
        directory = slug / "memory"
        if not directory.is_dir():
            continue
        memories = [
            entry
            for path in sorted(directory.glob("*.md"))
            if path.name != "MEMORY.md" and (entry := read_memory(path))
        ]
        if not memories:
            continue  # an empty memory dir says nothing; listing it is noise
        project, project_path = None, None
        for transcript in sorted(slug.glob("*.jsonl")):
            cwds = [e["cwd"] for e in reader.entries(transcript) if e.get("cwd")]
            project, project_path = reader.attribute(cwds)
            if project:
                break
        groups.append(
            {
                "slug": slug.name,
                "project": project,
                "projectPath": project_path,
                # Orphaned: nothing in this directory says which live project it
                # belongs to any more, so its rules are invisible to that project.
                "orphaned": project is None or not Path(project_path or "").is_dir(),
                "memories": memories,
            }
        )
    return groups


def memory_corrections(reader: Reader) -> list[dict]:
    """Only the `feedback` memories — project and reference notes are not corrections."""
    return [
        memory
        for group in memory_by_project(reader)
        for memory in group["memories"]
        if memory["type"] == "feedback"
    ]


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower())


def longest_shared_phrase(quote: str, text: str) -> int:
    """Length, in words, of the longest run the two share.

    Quotes in memory are elided with ellipses, so an exact substring test fails on
    material that is plainly the same sentence. Bag-of-words overlap fails the
    other way: a long quote scores 0.75 against an unrelated long prompt purely on
    common English. A contiguous run is the test that means what it looks like.
    """
    a = normalise(quote).split()
    b = normalise(text).split()
    if not a or not b:
        return 0
    best = 0
    previous = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        current = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


# Five consecutive words in common is well past coincidence for English prose, and
# short enough to survive the ellipses that memory quotes are full of.
PHRASE_MATCH = 5


def _dedupe(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


# --------------------------------------------------------------------------- commands


def collect(reader: Reader, since: datetime | None, include_scratch: bool) -> list[dict]:
    sessions = []
    for path in reader.main_transcripts():
        if since is not None:
            # An mtime older than the window means no entry inside it: the file
            # cannot have been written after its last line. Cheap and safe.
            try:
                if datetime.fromtimestamp(path.stat().st_mtime).astimezone() < since:
                    continue
            except OSError:
                pass
        session = reader.read_session(path)
        if since is not None and (session["end"] is None or session["end"] < since):
            continue
        if session["project"] is None and not include_scratch:
            continue
        sessions.append(session)
    return sorted(sessions, key=lambda s: s["end"] or datetime.min.replace(tzinfo=timezone.utc))


def jsonable(session: dict, full: bool) -> dict:
    out = dict(session)
    out["start"] = session["start"].isoformat() if session["start"] else None
    out["end"] = session["end"].isoformat() if session["end"] else None
    if session["start"] and session["end"]:
        out["minutes"] = round((session["end"] - session["start"]).total_seconds() / 60)
    if not full:
        out["prompts"] = [p["text"][:200] for p in session["prompts"]]
        out.pop("file", None)
    return out


def cmd_list(args: argparse.Namespace) -> int:
    reader = Reader(settings(args.project))
    since = resolve_since(args.since)
    sessions = collect(reader, since, args.include_scratch)
    if args.filter_project:
        sessions = [s for s in sessions if s["project"] == args.filter_project]
    if args.json:
        print(json.dumps(
            {
                "since": since.isoformat() if since else None,
                "sessions": [jsonable(s, args.full) for s in sessions],
            },
            indent=2,
        ))
        return OK
    if not sessions:
        print(f"no sessions since {since.date() if since else 'ever'}")
        return OK
    for session in sessions:
        when = session["end"].astimezone().strftime("%a %d %b %H:%M") if session["end"] else "?"
        print(f"{session['id'][:8]}  {when}  {session['project'] or '(scratch)'}")
        print(f"          {session['title'] or '(untitled)'}")
        bits = [
            f"{len(session['prompts'])} prompt(s)",
            f"{len(session['commits'])} commit(s)",
            f"{len(session['filesTouched'])} file(s)",
        ]
        if session["subagents"]:
            bits.append(f"{len(session['subagents'])} subagent(s)")
        print(f"          {', '.join(bits)}")
    return OK


def cmd_show(args: argparse.Namespace) -> int:
    reader = Reader(settings(args.project))
    matches = [p for p in reader.main_transcripts() if p.stem.startswith(args.session)]
    if not matches:
        print(f"no session starting with {args.session!r}", file=sys.stderr)
        return NOT_FOUND
    if len(matches) > 1:
        print(f"ambiguous: {', '.join(p.stem[:8] for p in matches)}", file=sys.stderr)
        return NOT_FOUND
    session = reader.read_session(matches[0])
    if args.json:
        print(json.dumps(jsonable(session, True), indent=2))
        return OK
    print(f"{session['id']}  {session['title'] or '(untitled)'}")
    print(f"project: {session['project']} ({session['projectPath']})")
    print(f"window:  {session['start']} → {session['end']}")
    print(f"branches: {', '.join(session['branches']) or '(none)'}")
    for prompt in session["prompts"]:
        print(f"  > {prompt['text'][:160]}")
    for commit in session["commits"]:
        print(f"  commit {commit['sha']} on {commit['branch']}")
    for pr in session["prs"]:
        print(f"  PR #{pr['number']} {pr['url']}")
    for agent in session["subagents"]:
        print(f"  subagent {agent['agentType']}: {agent['description']}")
    if session["filesTouched"]:
        print(f"  files: {', '.join(session['filesTouched'][:20])}")
    return OK


def cmd_search(args: argparse.Namespace) -> int:
    reader = Reader(settings(args.project))
    since = resolve_since(args.since)
    needle = args.query.lower()
    hits = []
    for session in collect(reader, since, True):
        for prompt in session["prompts"]:
            if needle in prompt["text"].lower():
                hits.append({
                    "session": session["id"],
                    "project": session["project"],
                    "title": session["title"],
                    "at": prompt["at"],
                    "text": prompt["text"],
                })
    if args.json:
        print(json.dumps({"query": args.query, "hits": hits}, indent=2))
        return OK if hits else NOT_FOUND
    for hit in hits:
        print(f"{hit['session'][:8]}  {hit['at']}  {hit['project']}")
        print(f"    {hit['text'][:200]}")
    if not hits:
        print(f"no prompt matches {args.query!r}")
        return NOT_FOUND
    return OK


def cmd_memory(args: argparse.Namespace) -> int:
    reader = Reader(settings(args.project))
    groups = memory_by_project(reader)

    # Which projects produced correction candidates but recorded no rule? That is
    # the gap in-session capture left behind, and the only thing a retrospective
    # sweep can fix.
    candidates: dict[str, int] = {}
    for path in reader.main_transcripts():
        for item in find_corrections(reader, path):
            key = item["project"] or "(scratch)"
            candidates[key] = candidates.get(key, 0) + 1

    recorded = {
        group["project"]: len(group["memories"]) for group in groups if group["project"]
    }
    gaps = [
        {"project": name, "candidates": count, "memories": recorded.get(name, 0)}
        for name, count in sorted(candidates.items())
        if name != "(scratch)" and recorded.get(name, 0) == 0
    ]

    payload = {
        "projects": groups,
        "gaps": gaps,
        "orphaned": [g["slug"] for g in groups if g["orphaned"]],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return OK
    for group in groups:
        label = group["project"] or "(unresolved)"
        flag = "  ORPHANED" if group["orphaned"] else ""
        print(f"{label}  ({len(group['memories'])} memories){flag}")
        print(f"    slug: {group['slug']}")
        for memory in group["memories"]:
            print(f"    {memory['type']:<10} {memory['name']:<26} {memory['description'][:70]}")
    for gap in gaps:
        print(f"\ngap: {gap['project']} has {gap['candidates']} correction candidate(s) "
              f"and no memory file")
    return OK


def cmd_corrections(args: argparse.Namespace) -> int:
    reader = Reader(settings(args.project))
    since = resolve_since(args.since)
    paths = reader.main_transcripts()
    if args.session:
        paths = [p for p in paths if p.stem.startswith(args.session)]
        if not paths:
            print(f"no session starting with {args.session!r}", file=sys.stderr)
            return NOT_FOUND

    candidates: list[dict] = []
    for path in paths:
        for item in find_corrections(reader, path):
            when = parse_ts(item["at"])
            if since is not None and (when is None or when < since):
                continue
            candidates.append(item)
    candidates.sort(key=lambda c: (-c["score"], c["at"] or ""))

    payload: dict = {
        "since": since.isoformat() if since else None,
        "candidates": candidates,
        "note": (
            "Candidates are narrowed by what the human wrote, not by tool errors or "
            "denials: those were measured across this corpus and never precede a human "
            "prompt. Read each one with its context before believing it."
        ),
    }

    if args.validate:
        known = memory_corrections(reader)
        # Every human prompt on disk, so a memory whose prompt was never recorded
        # can be told apart from one the filter simply failed to surface.
        all_prompt_text = " ".join(
            prompt["text"]
            for path in paths
            for prompt in reader.read_session(path)["prompts"]
        )
        results = []
        for memory in known:
            best = {"sharedWords": 0, "text": None, "session": None}
            for quote in memory["quotes"]:
                for candidate in candidates:
                    shared = longest_shared_phrase(quote, candidate["text"])
                    if shared > best["sharedWords"]:
                        best = {
                            "sharedWords": shared,
                            "text": candidate["text"][:120],
                            "session": candidate["session"][:8],
                        }
            # Absent from every transcript is a fact about the corpus, not a miss by
            # the detector: a prompt that was never written to disk cannot be found.
            on_disk = any(
                longest_shared_phrase(q, joined) >= PHRASE_MATCH
                for q in memory["quotes"]
                for joined in [all_prompt_text]
            )
            results.append(
                {
                    "memory": memory["name"],
                    "quotes": len(memory["quotes"]),
                    "promptOnDisk": on_disk,
                    "rediscovered": best["sharedWords"] >= PHRASE_MATCH,
                    "bestMatch": best,
                }
            )
        payload["validation"] = results

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for candidate in candidates:
            cues = ", ".join(f"{k}x{v}" for k, v in candidate["cues"].items())
            print(f"score {candidate['score']}  {candidate['session'][:8]}  "
                  f"{candidate['project']}  [{cues}]")
            print(f"    {candidate['text'][:180]}")
        print(f"\n{len(candidates)} candidate(s)")
        for item in payload.get("validation", []):
            if item["rediscovered"]:
                mark = "found     "
            elif not item["promptOnDisk"]:
                mark = "no prompt "
            else:
                mark = "MISSED    "
            print(f"  {mark} {item['memory']}  "
                  f"(longest shared phrase: {item['bestMatch']['sharedWords']} words)")
    if args.validate:
        missed = [
            i for i in payload["validation"]
            if not i["rediscovered"] and i["promptOnDisk"]
        ]
        return NOT_FOUND if missed else OK
    return OK


def cmd_verify(args: argparse.Namespace) -> int:
    reader = Reader(settings(args.project))
    paths = reader.main_transcripts()
    sessions = [reader.read_session(path) for path in paths]
    subagents = sum(len(reader.subagent_transcripts(p)) for p in paths)
    report = {
        "transcriptsDir": str(reader.root),
        "mainTranscripts": len(paths),
        "subagentTranscripts": subagents,
        "linesRead": sum(s["lines"] for s in sessions),
        "unparseableLines": reader.unparseable,
        "unknownTypes": reader.unknown_types,
        "sessionsWithNoProject": [s["id"][:8] for s in sessions if not s["project"]],
        "humanPrompts": sum(len(s["prompts"]) for s in sessions),
        "commits": sum(len(s["commits"]) for s in sessions),
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for key, value in report.items():
            if isinstance(value, list) and len(value) > 6:
                value = f"{len(value)} items"
            print(f"  {key}: {value}")
    problems = bool(reader.unparseable) or bool(reader.unknown_types)
    if problems:
        print(
            "\nschema drift: the reader met something it did not recognise. It kept "
            "going, but wf_sessions.py is the place to teach it.",
            file=sys.stderr,
        )
    return OK


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", help="treat this directory as the project root for config")
    common.add_argument("--json", action="store_true")

    window = argparse.ArgumentParser(add_help=False)
    window.add_argument("--since", default="previous-working-day")
    window.add_argument("--include-scratch", action="store_true")

    parser = argparse.ArgumentParser(prog="wf_sessions.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", parents=[common, window], help="sessions in a time window")
    listing.add_argument("--filter-project", metavar="NAME")
    listing.add_argument("--full", action="store_true", help="untruncated prompts in --json")
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show", parents=[common], help="one session in detail")
    show.add_argument("session", help="session id or unique prefix")
    show.set_defaults(func=cmd_show)

    search = sub.add_parser("search", parents=[common, window], help="find a past prompt")
    search.add_argument("query")
    search.set_defaults(func=cmd_search)

    memory = sub.add_parser(
        "memory", parents=[common], help="rules already recorded, by project, plus the gaps"
    )
    memory.set_defaults(func=cmd_memory)

    corrections = sub.add_parser(
        "corrections", parents=[common, window], help="human prompts that look like redirections"
    )
    corrections.add_argument("--session", help="limit to one session id or prefix")
    corrections.add_argument(
        "--validate", action="store_true",
        help="check the detector against corrections already in Claude Code's memory",
    )
    corrections.set_defaults(func=cmd_corrections)

    verify = sub.add_parser("verify", parents=[common], help="report anything unrecognised")
    verify.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
