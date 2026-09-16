#!/usr/bin/env python3
"""Resolve project knowledge across two orthogonal axes.

  docs/modules/<name>.md   WHAT — a component: what it is, how it works
  docs/tasks/<name>.md     WHY  — an activity: how you do a thing here

There is no index file. The directory listing is the index; everything else a doc
needs to say about itself lives in its own frontmatter, so it moves and dies with
the file. Shared activity docs live in the plugin's knowledge/tasks/.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf_config  # noqa: E402

OK = 0
NOT_FOUND = 3

AXES = {"modules": "what", "tasks": "why"}
LIST_KEYS = {"aliases", "sources", "decisions", "related"}


# --------------------------------------------------------------------------- docs


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """A deliberately small subset: scalars and flat [a, b] string lists."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end]
    rest = text[end + 4 :].lstrip("\n")
    meta: dict = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("'\"") for v in value[1:-1].split(",")]
            meta[key] = [v for v in items if v]
        elif key in LIST_KEYS:
            meta[key] = [value.strip("'\"")] if value else []
        else:
            meta[key] = value.strip("'\"")
    return meta, rest


def read_doc(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"path": str(path), "error": str(exc)}
    meta, body = parse_frontmatter(raw)
    title = ""
    summary = ""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            continue
        if title and not stripped.startswith("#"):
            summary = stripped
            break
    return {
        "name": path.stem,
        "path": str(path),
        "title": title or path.stem,
        "summary": summary[:200],
        "aliases": meta.get("aliases", []),
        "sources": meta.get("sources", []),
        "decisions": meta.get("decisions", []),
        "verified": meta.get("verified"),
        "hasFrontmatter": bool(meta),
    }


def axis_dir(root: Path, docs_dir: str, axis: str) -> Path:
    return root / docs_dir / axis


def list_axis(root: Path, docs_dir: str, axis: str) -> list[dict]:
    directory = axis_dir(root, docs_dir, axis)
    if not directory.is_dir():
        return []
    return [read_doc(p) for p in sorted(directory.glob("*.md"))]


# --------------------------------------------------------------------------- resolve


def normalize(name: str) -> str:
    name = re.sub(r"[\s_]+", "-", name.strip().lower())
    name = re.sub(r"[^a-z0-9-]", "", name)
    return re.sub(r"s$", "", name)


def resolve(docs: list[dict], query: str) -> dict:
    if not query:
        return {"status": "not-requested"}
    exact = [d for d in docs if d["name"] == query]
    if exact:
        return {"status": "ok", "doc": exact[0], "matchedBy": "name"}

    target = normalize(query)
    near = [d for d in docs if normalize(d["name"]) == target]
    if len(near) == 1:
        return {"status": "ok", "doc": near[0], "matchedBy": "normalized"}
    if len(near) > 1:
        return {"status": "ambiguous", "candidates": [d["name"] for d in near]}

    by_alias = [d for d in docs if any(normalize(a) == target for a in d["aliases"])]
    if len(by_alias) == 1:
        return {"status": "ok", "doc": by_alias[0], "matchedBy": "alias"}
    if len(by_alias) > 1:
        # Two docs claiming one alias is a content bug; never silently pick.
        return {
            "status": "alias-conflict",
            "alias": query,
            "candidates": [d["name"] for d in by_alias],
        }
    return {"status": "miss", "available": [d["name"] for d in docs]}


# --------------------------------------------------------------------------- staleness


def git(root: Path, *args: str) -> tuple[int, str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30
        )
        return out.returncode, out.stdout.rstrip("\n")
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def last_commit_times(root: Path, pathspecs: list[str]) -> dict[str, int]:
    """One git call for every path we care about, rather than one per document."""
    if not pathspecs:
        return {}
    code, out = git(
        root, "log", "--format=%x01%ct", "--name-only", "--no-merges", "--", *pathspecs
    )
    if code != 0 or not out:
        return {}
    times: dict[str, int] = {}
    for chunk in out.split("\x01"):
        if not chunk.strip():
            continue
        lines = chunk.splitlines()
        try:
            when = int(lines[0].strip())
        except (ValueError, IndexError):
            continue
        for path in lines[1:]:
            path = path.strip()
            if path and path not in times:
                times[path] = when
    return times


def check_stale(root: Path, docs: list[dict]) -> list[dict]:
    tracked = [d for d in docs if d["sources"]]
    if not tracked:
        return []
    specs: list[str] = []
    for doc in tracked:
        specs.append(str(Path(doc["path"]).relative_to(root)))
        specs.extend(doc["sources"])
    times = last_commit_times(root, specs)

    results = []
    for doc in tracked:
        rel = str(Path(doc["path"]).relative_to(root))
        doc_time = times.get(rel)
        matched = {
            path: when
            for path, when in times.items()
            if path != rel
            and any(fnmatch.fnmatch(path, glob) for glob in doc["sources"])
        }
        newest = max(matched.values(), default=None)
        if doc_time is None:
            state, detail = "uncommitted", "doc is not committed yet"
        elif newest is None:
            state, detail = "current", "no tracked file matches its sources globs yet"
        elif newest > doc_time:
            movers = sorted(p for p, w in matched.items() if w > doc_time)
            state = "possibly-stale"
            detail = f"{len(movers)} source file(s) changed since the doc: {', '.join(movers[:5])}"
        else:
            state, detail = "current", "sources unchanged since the doc was last edited"
        results.append({"name": doc["name"], "path": rel, "state": state, "detail": detail})
    return results


# --------------------------------------------------------------------------- scope


def resolve_where(where: str | None) -> tuple[str, Path]:
    if not where or where == ".":
        root = wf_config.project_root(None)
        return root.name, root
    candidate = Path(where).expanduser()
    if candidate.is_dir():
        return candidate.resolve().name, candidate.resolve()
    merged, _, _ = wf_config.load_all(None)
    registry, found = wf_config.lookup(merged, "projects")
    if found and isinstance(registry, dict) and where in registry:
        path = Path(str(registry[where].get("path", ""))).expanduser()
        if path.is_dir():
            return where, path.resolve()
        raise SystemExit(f"registry entry '{where}' points at a missing path: {path}")
    raise SystemExit(f"unknown project '{where}'; not a directory and not in the registry")


def shared_tasks() -> list[dict]:
    directory = wf_config.plugin_root() / "knowledge" / "tasks"
    if not directory.is_dir():
        return []
    return [read_doc(p) for p in sorted(directory.glob("*.md"))]


def docs_dir_for(root: Path) -> str:
    merged, _, _ = wf_config.load_all(str(root))
    value, found = wf_config.lookup(merged, "knowledge.docsDir")
    return str(value) if found else "docs"


# --------------------------------------------------------------------------- commands


def cmd_list(args: argparse.Namespace) -> int:
    name, root = resolve_where(args.where)
    docs_dir = docs_dir_for(root)
    payload = {"project": name, "root": str(root), "docsDir": docs_dir, "axes": {}}
    for axis in AXES:
        payload["axes"][axis] = list_axis(root, docs_dir, axis)
    if args.json:
        print(json.dumps(payload, indent=2))
        return OK
    for axis in AXES:
        entries = payload["axes"][axis]
        print(f"{axis}/ ({AXES[axis]}) — {len(entries)} doc(s) in {docs_dir}/{axis}/")
        for doc in entries:
            alias = f"  [{', '.join(doc['aliases'])}]" if doc["aliases"] else ""
            print(f"    {doc['name']:<24} {doc['title']}{alias}")
        if not entries:
            print("    (none yet)")
    return OK


def cmd_query(args: argparse.Namespace) -> int:
    name, root = resolve_where(args.where)
    docs_dir = docs_dir_for(root)
    modules = list_axis(root, docs_dir, "modules")
    tasks = list_axis(root, docs_dir, "tasks")

    what = resolve(modules, args.what or "")
    why = resolve(tasks, args.why or "")

    shared: list[dict] = []
    merged, _, _ = wf_config.load_all(str(root))
    consult, _ = wf_config.lookup(merged, "knowledge.consultShared")
    if args.why and consult is not False:
        hit = resolve(shared_tasks(), args.why)
        if hit["status"] == "ok":
            shared.append(hit["doc"])

    related: list[str] = []
    for outcome in (what, why):
        if outcome.get("status") == "ok":
            related.extend(outcome["doc"]["decisions"])

    payload = {
        "project": name,
        "root": str(root),
        "what": what,
        "why": why,
        "shared": shared,
        "related": sorted(set(related)),
        "read": [
            outcome["doc"]["path"]
            for outcome in (what, why)
            if outcome.get("status") == "ok"
        ]
        + [doc["path"] for doc in shared],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for axis, outcome in (("what", what), ("why", why)):
            status = outcome["status"]
            if status == "ok":
                print(f"{axis}: {outcome['doc']['path']}  ({outcome['matchedBy']})")
            elif status == "miss":
                available = ", ".join(outcome["available"]) or "(none)"
                print(f"{axis}: no match. available: {available}")
            elif status != "not-requested":
                print(f"{axis}: {status} — {outcome.get('candidates')}")
        for doc in shared:
            print(f"shared: {doc['path']}")
        for ref in payload["related"]:
            print(f"related: {ref}")
    missed = any(o["status"] == "miss" for o in (what, why))
    return NOT_FOUND if missed else OK


def cmd_stale(args: argparse.Namespace) -> int:
    name, root = resolve_where(args.where)
    docs_dir = docs_dir_for(root)
    docs = list_axis(root, docs_dir, "modules") + list_axis(root, docs_dir, "tasks")
    results = check_stale(root, docs)
    if args.json:
        print(json.dumps({"project": name, "docs": results}, indent=2))
        return OK
    if not results:
        print("no docs declare `sources`; nothing to check")
        return OK
    for item in results:
        print(f"  {item['state']:<15} {item['path']}  — {item['detail']}")
    return OK


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--where", help="project path or registry name (default: current)")
    common.add_argument("--json", action="store_true")

    parser = argparse.ArgumentParser(prog="wf_knowledge.py", description=__doc__, parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", parents=[common], help="enumerate both axes")
    listing.set_defaults(func=cmd_list)

    query = sub.add_parser("query", parents=[common], help="resolve a module and/or an activity")
    query.add_argument("--what", help="module name")
    query.add_argument("--why", help="activity name")
    query.set_defaults(func=cmd_query)

    stale = sub.add_parser("stale", parents=[common], help="docs whose sources moved since the doc")
    stale.set_defaults(func=cmd_stale)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
