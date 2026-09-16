#!/usr/bin/env python3
"""Read-only preflight for init-model-agnostic.

Reports the facts a decision needs: git state, symlink support, and the exact
shape of every agent-instruction file in the repo. Emits JSON and changes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SOURCE_OF_TRUTH = "AGENTS.md"

# Symlink targets: same markdown-prose contract as AGENTS.md.
LINKABLE = ["CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md", "AGENT.md", "QWEN.md"]

# Different format or deprecated: report, never convert.
REPORT_ONLY = [
    ".cursorrules",
    ".windsurfrules",
    ".cursor/rules",
    ".clinerules",
    "CONVENTIONS.md",
    "CRUSH.md",
    ".junie/guidelines.md",
    ".claude/CLAUDE.md",
]

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "build", "dist", "__pycache__", ".mypy_cache"}


def git(root: Path, *args: str) -> tuple[int, str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15
        )
        # Only trailing newlines: porcelain status encodes state in leading columns.
        return out.returncode, out.stdout.rstrip("\n")
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def resolve_root(explicit: str | None) -> tuple[Path, bool]:
    start = Path(explicit).resolve() if explicit else Path(
        os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    ).resolve()
    code, out = git(start, "rev-parse", "--show-toplevel")
    if code == 0 and out.strip():
        return Path(out.strip()).resolve(), True
    return start, False


def probe_symlinks(root: Path, is_git: bool) -> bool:
    # Probe inside .git/ when possible: always ignored, same filesystem, never
    # visible in the worktree even if cleanup fails.
    parent = root / ".git" if is_git and (root / ".git").is_dir() else root
    probe = parent / ".wf-symlink-probe"
    try:
        if probe.is_symlink() or probe.exists():
            probe.unlink()
        probe.symlink_to("probe-target")
        return probe.is_symlink()
    except (OSError, NotImplementedError):
        return False
    finally:
        try:
            if probe.is_symlink() or probe.exists():
                probe.unlink()
        except OSError:
            pass


def digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def inspect(root: Path, relative: str, tracked: dict[str, str]) -> dict:
    path = root / relative
    info: dict = {"path": relative, "kind": "absent", "tracked": relative in tracked}
    if relative in tracked:
        info["indexMode"] = tracked[relative]
    if path.is_symlink():
        target = os.readlink(path)
        resolves = path.exists()
        points_at_truth = False
        if resolves:
            try:
                points_at_truth = path.resolve() == (root / SOURCE_OF_TRUTH).resolve()
            except OSError:
                points_at_truth = False
        info.update(
            kind="symlink",
            target=target,
            targetIsAbsolute=os.path.isabs(target),
            targetResolves=resolves,
            targetIsSourceOfTruth=points_at_truth,
        )
        if path.exists() and path.is_file():
            info["size"] = path.stat().st_size
            info["sha256"] = digest(path)
        return info
    if path.is_dir():
        info["kind"] = "dir"
        return info
    if path.is_file():
        info.update(kind="regular", size=path.stat().st_size, sha256=digest(path))
        try:
            first = path.read_text(encoding="utf-8", errors="replace").splitlines()[:3]
            info["head"] = first
        except OSError:
            pass
    return info


def find_nested(root: Path) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if Path(dirpath) == root:
            continue
        for name in ("AGENTS.md", "CLAUDE.md"):
            if name in filenames:
                found.append(str((Path(dirpath) / name).relative_to(root)))
    return sorted(found)


def classify(agents: dict, claude: dict) -> str:
    if claude["kind"] == "symlink":
        if not claude.get("targetResolves"):
            return "symlink-dangling"
        if not claude.get("targetIsSourceOfTruth"):
            return "symlink-wrong-target"
        if claude.get("targetIsAbsolute"):
            return "symlink-absolute"
        return "already-conformant"
    if agents["kind"] == "symlink":
        return "inverted"
    if agents["kind"] == "regular" and claude["kind"] == "absent":
        return "agents-only"
    if agents["kind"] == "absent" and claude["kind"] == "regular":
        return "claude-only"
    if agents["kind"] == "regular" and claude["kind"] == "regular":
        return "both-identical" if agents.get("sha256") == claude.get("sha256") else "both-differ"
    if agents["kind"] == "absent" and claude["kind"] == "absent":
        return "neither"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="repo to scan (default: cwd's git root)")
    args = parser.parse_args()

    root, is_git = resolve_root(args.project)

    tracked: dict[str, str] = {}
    branch = None
    dirty: list[str] = []
    in_progress = None
    core_symlinks = None
    detached = False
    unborn = False
    if is_git:
        code, out = git(root, "ls-files", "-s")
        if code == 0:
            for line in out.splitlines():
                meta, _, name = line.partition("\t")
                if name:
                    tracked[name] = meta.split()[0]
        # symbolic-ref works on an unborn branch, where rev-parse HEAD just fails.
        sym_code, sym = git(root, "symbolic-ref", "--short", "-q", "HEAD")
        has_commits = git(root, "rev-parse", "--verify", "-q", "HEAD")[0] == 0
        branch = sym.strip() if sym_code == 0 else None
        unborn = not has_commits
        detached = has_commits and sym_code != 0
        _, status = git(root, "status", "--porcelain")
        for line in status.splitlines():
            if not line.strip():
                continue
            name = line[3:]
            if " -> " in name:
                name = name.split(" -> ", 1)[1]
            dirty.append({"status": line[:2], "path": name.strip('"')})
        git_dir = root / ".git"
        if (git_dir / "MERGE_HEAD").exists():
            in_progress = "merge"
        elif (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
            in_progress = "rebase"
        elif (git_dir / "CHERRY_PICK_HEAD").exists():
            in_progress = "cherry-pick"
        code, out = git(root, "config", "--get", "core.symlinks")
        core_symlinks = out.strip() if code == 0 else None

    agents = inspect(root, SOURCE_OF_TRUTH, tracked)
    claude = inspect(root, "CLAUDE.md", tracked)

    report = {
        "root": str(root),
        "isGitRepo": is_git,
        "branch": branch,
        "detachedHead": detached,
        "unbornBranch": unborn,
        "inProgressOperation": in_progress,
        "dirtyFiles": dirty,
        "coreSymlinks": core_symlinks,
        "symlinkSupport": probe_symlinks(root, is_git),
        "sourceOfTruth": agents,
        "linkable": [inspect(root, name, tracked) for name in LINKABLE],
        "reportOnly": [
            info
            for info in (inspect(root, name, tracked) for name in REPORT_ONLY)
            if info["kind"] != "absent"
        ],
        "nested": find_nested(root),
        "case": classify(agents, claude),
    }

    blockers = []
    warnings = []
    if detached:
        blockers.append("detached HEAD")
    if in_progress:
        blockers.append(f"{in_progress} in progress")
    if not report["symlinkSupport"]:
        blockers.append("filesystem does not support symlinks")

    touched = {SOURCE_OF_TRUTH, *LINKABLE}
    # Modified tracked files can lose work; untracked ones only lack an undo path.
    modified = sorted(e["path"] for e in dirty if e["path"] in touched and e["status"] != "??")
    untracked = sorted(e["path"] for e in dirty if e["path"] in touched and e["status"] == "??")
    if modified:
        blockers.append(f"uncommitted changes to files we would touch: {', '.join(modified)}")
    if untracked:
        warnings.append(f"untracked files we would touch (no git undo): {', '.join(untracked)}")
    if unborn:
        warnings.append("branch has no commits yet; git mv is unavailable, plain mv will be used")
    if not is_git:
        warnings.append("not a git repository; no undo is available for any change")

    report["blockers"] = blockers
    report["warnings"] = warnings

    json.dump(report, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
