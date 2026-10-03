#!/usr/bin/env python3
"""Read and check a plan artifact, and reconstruct a run's progress from git.

A plan is one markdown file. Prose carries context, decisions and risks; a single
fenced ```json wf-plan block carries the task DAG. The fence is the *only* task
list — a prose checklist next to a JSON DAG drifts inside a single session.

Run state is not stored here. Every task commit carries `Plan-Id` and `Task-Id`
git trailers, so `resume` rebuilds the ledger from history alone: a dead session,
a deleted run cache or a fresh clone all still resume correctly.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf_config  # noqa: E402

OK = 0
ERR_MISSING = 3
ERR_SCHEMA = 5

SCHEMA = "wf-plan/1"
FENCE = re.compile(r"^```json\s+wf-plan\s*$(.*?)^```\s*$", re.MULTILINE | re.DOTALL)
GLOB_CHARS = set("*?[")
RISKS = {"low", "medium", "high"}
# Conventional types minus `chore`, which is not used (see AGENTS.md); releases are `build`.
COMMIT_TYPES = {"feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci"}

# A conventional-commit subject line should survive `git log --oneline` in an
# 80-column terminal once the type, scope and sha are prepended.
MAX_SUBJECT = 68


# --------------------------------------------------------------------------- parsing


class PlanError(Exception):
    def __init__(self, message: str, code: int = ERR_SCHEMA):
        super().__init__(message)
        self.code = code


def read_plan(path: Path) -> tuple[dict, str]:
    """Return (plan, raw_fence_text). The fence text is what gets hashed."""
    if not path.is_file():
        raise PlanError(f"{path}: no such plan file", ERR_MISSING)
    text = path.read_text(encoding="utf-8")
    blocks = FENCE.findall(text)
    if not blocks:
        raise PlanError(f"{path}: no ```json wf-plan fence found")
    if len(blocks) > 1:
        raise PlanError(f"{path}: {len(blocks)} wf-plan fences; exactly one is allowed")
    raw = blocks[0]
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlanError(f"{path}: wf-plan fence is not valid JSON: line {exc.lineno}: {exc.msg}")
    if not isinstance(plan, dict):
        raise PlanError(f"{path}: wf-plan fence must be a JSON object")
    return plan, raw


def digest(value: object) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def task_hash(task: dict) -> str:
    """Hash only what changes the work, so reordering or renaming a note is free."""
    return digest({key: task.get(key) for key in ("title", "description", "files", "verify")})


def tasks_of(plan: dict) -> list[dict]:
    tasks = plan.get("tasks")
    return tasks if isinstance(tasks, list) else []


# --------------------------------------------------------------------------- lint


def lint(plan: dict) -> list[str]:
    problems: list[str] = []
    if plan.get("schema") != SCHEMA:
        problems.append(f"schema: expected {SCHEMA!r}, got {plan.get('schema')!r}")
    for key in ("id", "title", "baseCommit"):
        if not plan.get(key):
            problems.append(f"{key}: required and must be non-empty")
    tasks = tasks_of(plan)
    if not tasks:
        problems.append("tasks: at least one task is required")

    seen: set[str] = set()
    for position, task in enumerate(tasks):
        label = task.get("id") or f"[{position}]"
        if not isinstance(task, dict):
            problems.append(f"tasks[{position}]: must be an object")
            continue
        if not task.get("id"):
            problems.append(f"tasks[{position}]: missing 'id'")
        elif task["id"] in seen:
            problems.append(f"tasks[{label}]: duplicate id")
        seen.add(task.get("id"))

        if not task.get("title"):
            problems.append(f"tasks[{label}]: missing 'title'")
        verify = task.get("verify")
        if not isinstance(verify, list) or not verify:
            problems.append(
                f"tasks[{label}]: needs at least one 'verify' command — a task nobody can "
                "check is a task nobody can finish"
            )
        files = task.get("files")
        if not isinstance(files, list) or not files:
            problems.append(f"tasks[{label}]: 'files' must list the paths or globs it touches")
        risk = task.get("risk")
        if risk is not None and risk not in RISKS:
            problems.append(f"tasks[{label}]: risk {risk!r} not one of {sorted(RISKS)}")

        commit = task.get("commit")
        if not isinstance(commit, dict):
            problems.append(f"tasks[{label}]: missing 'commit' object")
            continue
        if commit.get("type") not in COMMIT_TYPES:
            problems.append(
                f"tasks[{label}]: commit.type {commit.get('type')!r} is not a conventional type"
            )
        subject = commit.get("subject") or ""
        if not subject:
            problems.append(f"tasks[{label}]: commit.subject is required")
        elif len(subject) > MAX_SUBJECT:
            problems.append(
                f"tasks[{label}]: commit.subject is {len(subject)} chars, max {MAX_SUBJECT}"
            )
        elif subject.endswith("."):
            problems.append(f"tasks[{label}]: commit.subject should not end with a period")

    known = {task.get("id") for task in tasks if isinstance(task, dict)}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for dep in task.get("dependsOn") or []:
            if dep not in known:
                problems.append(f"tasks[{task.get('id')}]: dependsOn {dep!r} does not exist")
            if dep == task.get("id"):
                problems.append(f"tasks[{task.get('id')}]: depends on itself")

    cycle = find_cycle(tasks)
    if cycle:
        problems.append(f"dependsOn: cycle {' -> '.join(cycle)}")
    return problems


def find_cycle(tasks: list[dict]) -> list[str] | None:
    graph = {
        task["id"]: [d for d in (task.get("dependsOn") or []) if d != task["id"]]
        for task in tasks
        if isinstance(task, dict) and task.get("id")
    }
    state: dict[str, int] = {}
    stack: list[str] = []

    def walk(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for dep in graph.get(node, []):
            if dep not in graph:
                continue
            if state.get(dep) == 1:
                return stack[stack.index(dep) :] + [dep]
            if state.get(dep, 0) == 0:
                found = walk(dep)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in graph:
        if state.get(node, 0) == 0:
            found = walk(node)
            if found:
                return found
    return None


# --------------------------------------------------------------------------- layers


def tracked_files(root: Path) -> list[str]:
    code, out = git(root, "ls-files")
    return out.splitlines() if code == 0 else []


def expand(files: list[str], tracked: list[str]) -> set[str]:
    """Literals count as themselves even when they do not exist yet — most of a
    plan's files are about to be created, and an unexpanded glob is not a reason
    to call two tasks independent."""
    out: set[str] = set()
    for entry in files:
        if GLOB_CHARS & set(entry):
            out.update(p for p in tracked if fnmatch.fnmatch(p, entry))
        else:
            out.add(entry.rstrip("/"))
    return out


def overlap(a: dict, b: dict, tracked: list[str]) -> list[str]:
    a_files, b_files = a.get("files") or [], b.get("files") or []
    a_set, b_set = expand(a_files, tracked), expand(b_files, tracked)
    shared = set(a_set & b_set)
    # A glob in one task and a literal in the other never meet in the expansion
    # above when the literal is a file that does not exist yet.
    for globs, literals in ((a_files, b_set), (b_files, a_set)):
        for pattern in globs:
            if GLOB_CHARS & set(pattern):
                shared.update(p for p in literals if fnmatch.fnmatch(p, pattern))
    return sorted(shared)


def layer(tasks: list[dict]) -> list[list[str]]:
    pending = {
        task["id"]: set(d for d in (task.get("dependsOn") or []) if d != task["id"])
        for task in tasks
        if task.get("id")
    }
    known = set(pending)
    layers: list[list[str]] = []
    done: set[str] = set()
    while pending:
        ready = sorted(
            task_id for task_id, deps in pending.items() if not (deps & known) - done
        )
        if not ready:
            break  # a cycle; lint reports it properly
        layers.append(ready)
        done.update(ready)
        for task_id in ready:
            pending.pop(task_id)
    return layers


def layer_report(plan: dict, root: Path) -> dict:
    tasks = tasks_of(plan)
    by_id = {task["id"]: task for task in tasks if task.get("id")}
    tracked = tracked_files(root)
    report = {"planId": plan.get("id"), "layers": [], "unreachable": []}
    for index, group in enumerate(layer(tasks), start=1):
        conflicts = []
        for i, first in enumerate(group):
            for second in group[i + 1 :]:
                shared = overlap(by_id[first], by_id[second], tracked)
                if shared:
                    conflicts.append({"tasks": [first, second], "sharedFiles": shared[:10]})
        blocked = {t for conflict in conflicts for t in conflict["tasks"]}
        report["layers"].append(
            {
                "layer": index,
                "tasks": group,
                "parallelSafe": sorted(set(group) - blocked),
                "serialize": sorted(blocked),
                "conflicts": conflicts,
            }
        )
    placed = {task_id for group in report["layers"] for task_id in group["tasks"]}
    # A cycle leaves tasks in no layer at all. Saying nothing would quietly drop
    # them from the run; lint explains the cycle, this just refuses to hide it.
    report["unreachable"] = sorted(set(by_id) - placed)
    return report


# --------------------------------------------------------------------------- resume


def git(root: Path, *args: str) -> tuple[int, str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60
        )
        return out.returncode, out.stdout.rstrip("\n")
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def ledger(root: Path, plan_id: str, base: str) -> dict[str, list[dict]]:
    """Rebuild which tasks are committed, from trailers alone."""
    code, out = git(root, "rev-parse", "--verify", "-q", f"{base}^{{commit}}")
    if code != 0:
        raise PlanError(f"baseCommit {base!r} is not in this repository", ERR_MISSING)
    code, out = git(
        root,
        "log",
        "--no-merges",
        "--format=%H%x1f%(trailers:key=Task-Id,valueonly)%x1f"
        "%(trailers:key=Plan-Id,valueonly)%x1f%s%x1e",
        f"{base}..HEAD",
    )
    found: dict[str, list[dict]] = {}
    if code != 0:
        return found
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        parts = record.split("\x1f")
        if len(parts) < 4:
            continue
        sha, task_ids, plan_ids, subject = parts[0], parts[1], parts[2], parts[3]
        if plan_id and plan_ids.strip() and plan_id not in plan_ids.split():
            continue  # another plan's commit sharing this branch
        for task_id in task_ids.split():
            found.setdefault(task_id, []).append({"sha": sha[:12], "subject": subject})
    return found


def run_cache_path(root: Path, plan_id: str) -> Path:
    run_dir = wf_config.state_path(str(root), "plan.runDir", "runs")
    return run_dir / f"{plan_id}.json"


def read_cache(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}  # the cache is a convenience; git is the truth


def resume_report(plan: dict, raw: str, root: Path) -> dict:
    plan_id = str(plan.get("id") or "")
    base = str(plan.get("baseCommit") or "")
    committed = ledger(root, plan_id, base)
    cache = read_cache(run_cache_path(root, plan_id))
    cached_tasks = cache.get("tasks") if isinstance(cache.get("tasks"), dict) else {}

    tasks = tasks_of(plan)
    by_id = {task["id"]: task for task in tasks if task.get("id")}
    done = set(committed)
    states = []
    for task in tasks:
        task_id = task.get("id")
        entry = cached_tasks.get(task_id) if isinstance(cached_tasks, dict) else None
        entry = entry if isinstance(entry, dict) else {}
        current = task_hash(task)
        state = "done" if task_id in done else "pending"
        note = ""
        if state == "done" and entry.get("hash") and entry["hash"] != current:
            # The definition moved after the work landed: the commit no longer
            # matches the plan. Warn; never silently re-run and never re-commit.
            note = "plan edited after this task was committed — review the commit against the plan"
        if state == "pending" and entry.get("attempts"):
            note = f"{entry['attempts']} previous attempt(s); last failure: {entry.get('lastFailure', '?')}"
        states.append(
            {
                "id": task_id,
                "title": task.get("title"),
                "state": state,
                "hash": current,
                "commits": committed.get(task_id, []),
                "dependsOn": task.get("dependsOn") or [],
                "note": note,
            }
        )

    ready = [
        s["id"]
        for s in states
        if s["state"] == "pending" and all(d in done for d in s["dependsOn"])
    ]
    orphans = sorted(set(committed) - set(by_id))
    return {
        "planId": plan_id,
        "planHash": digest(raw),
        "baseCommit": base,
        "branch": current_branch(root),
        "tasks": states,
        "done": sorted(done & set(by_id)),
        "ready": ready,
        "next": ready[0] if ready else None,
        "orphanTaskIds": orphans,
        "cache": str(run_cache_path(root, plan_id)),
        "complete": not [s for s in states if s["state"] == "pending"],
    }


def current_branch(root: Path) -> str:
    code, out = git(root, "symbolic-ref", "--short", "-q", "HEAD")
    return out if code == 0 else "(detached)"


# --------------------------------------------------------------------------- commands


def load(args: argparse.Namespace) -> tuple[dict, str, Path]:
    plan, raw = read_plan(Path(args.plan).expanduser())
    return plan, raw, wf_config.project_root(args.project)


def cmd_lint(args: argparse.Namespace) -> int:
    plan, raw, _ = load(args)
    problems = lint(plan)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": not problems,
                    "planHash": digest(raw),
                    "tasks": len(tasks_of(plan)),
                    "problems": problems,
                },
                indent=2,
            )
        )
        return ERR_SCHEMA if problems else OK
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return ERR_SCHEMA
    print(f"plan ok — {len(tasks_of(plan))} task(s), hash {digest(raw)}")
    return OK


def cmd_layers(args: argparse.Namespace) -> int:
    plan, _, root = load(args)
    report = layer_report(plan, root)
    if args.json:
        print(json.dumps(report, indent=2))
        return ERR_SCHEMA if report["unreachable"] else OK
    for group in report["layers"]:
        print(f"layer {group['layer']}: {', '.join(group['tasks'])}")
        if group["parallelSafe"] and len(group["tasks"]) > 1:
            print(f"    parallel-safe: {', '.join(group['parallelSafe'])}")
        for conflict in group["conflicts"]:
            shared = ", ".join(conflict["sharedFiles"])
            print(f"    serialize {' + '.join(conflict['tasks'])} — both touch {shared}")
    if report["unreachable"]:
        print(f"unreachable (dependency cycle): {', '.join(report['unreachable'])}")
        return ERR_SCHEMA
    return OK


def cmd_resume(args: argparse.Namespace) -> int:
    plan, raw, root = load(args)
    report = resume_report(plan, raw, root)
    if args.json:
        print(json.dumps(report, indent=2))
        return OK
    print(f"plan {report['planId']} on {report['branch']} (base {report['baseCommit'][:12]})")
    for task in report["tasks"]:
        marker = "x" if task["state"] == "done" else " "
        shas = " ".join(c["sha"] for c in task["commits"])
        print(f"  [{marker}] {task['id']:<5} {task['title']}  {shas}")
        if task["note"]:
            print(f"        ! {task['note']}")
    for orphan in report["orphanTaskIds"]:
        print(f"  ?  {orphan} committed but not in the plan")
    print(f"next: {report['next'] or '(nothing pending)'}")
    return OK


def cmd_show(args: argparse.Namespace) -> int:
    plan, _, _ = load(args)
    for task in tasks_of(plan):
        if task.get("id") == args.task:
            task = dict(task)
            task["hash"] = task_hash(task)
            print(json.dumps(task, indent=2))
            return OK
    print(f"no task {args.task!r} in this plan", file=sys.stderr)
    return ERR_MISSING


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("plan", help="path to the plan markdown file")
    common.add_argument("--project", help="treat this directory as the project root")
    common.add_argument("--json", action="store_true")

    parser = argparse.ArgumentParser(prog="wf_plan.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    checker = sub.add_parser("lint", parents=[common], help="validate the wf-plan fence")
    checker.set_defaults(func=cmd_lint)

    layers = sub.add_parser("layers", parents=[common], help="derive execution layers")
    layers.set_defaults(func=cmd_layers)

    resume = sub.add_parser("resume", parents=[common], help="rebuild progress from git trailers")
    resume.set_defaults(func=cmd_resume)

    show = sub.add_parser("show", parents=[common], help="print one task as JSON")
    show.add_argument("--task", required=True)
    show.set_defaults(func=cmd_show)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
