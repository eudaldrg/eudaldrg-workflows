#!/usr/bin/env python3
"""Resolve the layered workflows configuration.

Three layers, deep-merged, later wins:

    plugin defaults  ${CLAUDE_PLUGIN_ROOT}/defaults/workflows.defaults.json
    home             ~/.claude/workflows.json
    project          <git-toplevel>/.claude/workflows.json

Stdlib only, so this runs in CI and on machines where the plugin is not installed.
Env overrides for testing: WF_PLUGIN_ROOT, WF_HOME_CONFIG, WF_PROJECT_DIR.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

OK = 0
ERR_USAGE = 2
ERR_MISSING_KEY = 3
ERR_BAD_JSON = 4
ERR_SCHEMA = 5

LAYERS = ("plugin", "home", "project")
OPERATORS = {"+": "append", "^": "prepend", "-": "remove"}


class ConfigError(Exception):
    def __init__(self, message: str, code: int = ERR_BAD_JSON):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- paths


def plugin_root() -> Path:
    for var in ("WF_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT"):
        value = os.environ.get(var)
        if value:
            return Path(value)
    return Path(__file__).resolve().parent.parent


def home_config_path() -> Path:
    override = os.environ.get("WF_HOME_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "workflows.json"


def project_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    override = os.environ.get("WF_PROJECT_DIR")
    if override:
        return Path(override).resolve()
    start = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        out = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(start).resolve()


def layer_paths(explicit_project: str | None = None) -> dict[str, Path]:
    return {
        "plugin": plugin_root() / "defaults" / "workflows.defaults.json",
        "home": home_config_path(),
        "project": project_root(explicit_project) / ".claude" / "workflows.json",
    }


# --------------------------------------------------------------------------- state (worktree-shared)

# Anything generated per-project that must not be pushed and must survive `git worktree`
# (plans, run caches, ...) lives outside the repo entirely, keyed by the repo's shared git
# directory rather than by any one worktree's path. `--git-common-dir` resolves to the same
# place from every linked worktree; `--show-toplevel` would not.


def state_home() -> Path:
    override = os.environ.get("WF_STATE_HOME")
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "wf"


def git_common_dir(start: Path) -> Path | None:
    """The repo's shared .git dir, absolute, or None outside a git repo.

    `--path-format=absolute` needs git >= 2.31; older git returns a path that may be
    relative to `start`, so that case is resolved by hand.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode == 0 and out.stdout.strip():
        return Path(out.stdout.strip()).resolve()
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    common = Path(out.stdout.strip())
    return (common if common.is_absolute() else start / common).resolve()


STATE_ID_FILE = "wf-state-id"


def state_digest(anchor: Path, in_git: bool) -> str:
    """The state directory name for a repo. Inside git it is stored in the shared git dir on first
    use, so it travels with the repo when it is moved or renamed. It starts as the hash of the
    current path, which is what every state directory was named before the id file existed, so
    existing state keeps its name. (A `cp -r` of a repo copies the id too and shares its plans.)"""
    digest = hashlib.sha256(str(anchor).encode("utf-8")).hexdigest()[:16]
    if not in_git:
        return digest
    id_file = anchor / STATE_ID_FILE
    try:
        stored = id_file.read_text(encoding="utf-8").strip()
    except OSError:
        stored = ""
    if re.fullmatch(r"[0-9a-f]{16}", stored):
        return stored
    try:
        id_file.write_text(digest + "\n", encoding="utf-8")
    except OSError:
        pass  # read-only git dir: fall back to the path hash, as before
    return digest


def state_anchor(explicit_project: str | None = None) -> tuple[Path, Path]:
    """(anchor, root): anchor is what state is keyed on (one per repo, shared across all its
    worktrees); root is this call's own project root (one per worktree)."""
    root = project_root(explicit_project)
    common = git_common_dir(root)
    return (common if common is not None else root), root


def state_root(explicit_project: str | None = None) -> Path:
    """The external, worktree-shared directory for this repo. Created on demand."""
    anchor, root = state_anchor(explicit_project)
    # The anchor is the git common dir inside a repo, and the project root itself outside one.
    base = state_home() / state_digest(anchor, in_git=anchor != root)
    base.mkdir(parents=True, exist_ok=True)

    meta_path = base / "meta.json"
    meta = read_layer(meta_path)
    roots = set(meta.get("roots") or [])
    changed = meta.get("anchor") != str(anchor) or str(root) not in roots
    if changed:
        roots.add(str(root))
        meta_path.write_text(
            json.dumps({"anchor": str(anchor), "roots": sorted(roots)}, indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
    return base


def state_path(explicit_project: str | None, dotted: str, default: str) -> Path:
    """Resolve a dotted config key (e.g. `plan.dir`) as a subdir of `state_root`, creating it."""
    merged, _, _ = load_all(explicit_project)
    value, found = lookup(merged, dotted)
    sub = str(value) if found and value else default
    target = state_root(explicit_project) / sub
    target.mkdir(parents=True, exist_ok=True)
    return target


# --------------------------------------------------------------------------- loading


def read_layer(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read: {exc}") from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a JSON object")
    return data


# --------------------------------------------------------------------------- merging


def _is_id_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, dict) and "id" in item for item in value)
    )


def _stamp(prov: dict, path: tuple[str, ...], value: object, layer: str) -> None:
    dotted = ".".join(path)
    if isinstance(value, dict) and value:
        for key, sub in value.items():
            _stamp(prov, path + (key,), sub, layer)
    else:
        prov[dotted] = layer


def _merge_id_lists(current: list, incoming: list) -> list:
    result = [copy.deepcopy(item) for item in current]
    index = {item["id"]: position for position, item in enumerate(result)}
    for item in incoming:
        if item["id"] in index:
            target = result[index[item["id"]]]
            for key, value in item.items():
                if value is None:
                    target.pop(key, None)
                else:
                    target[key] = copy.deepcopy(value)
        else:
            index[item["id"]] = len(result)
            result.append(copy.deepcopy(item))
    return result


def _apply_operator(current: object, op: str, operand: object) -> list:
    base = list(current) if isinstance(current, list) else []
    if not isinstance(operand, list):
        operand = [operand]
    if op == "-":
        if _is_id_list(base):
            drop = {item["id"] if isinstance(item, dict) else item for item in operand}
            return [item for item in base if item.get("id") not in drop]
        return [item for item in base if item not in operand]
    if _is_id_list(base) and _is_id_list(operand):
        merged = _merge_id_lists(base, operand)
        if op == "^":
            added = [item for item in merged if item not in base]
            return added + [item for item in merged if item not in added]
        return merged
    addition = [copy.deepcopy(item) for item in operand]
    return addition + base if op == "^" else base + addition


def _merge_into(dst: dict, src: dict, prov: dict, layer: str, path: tuple[str, ...]) -> None:
    plain: dict[str, object] = {}
    operations: list[tuple[str, str, object]] = []
    for key, value in src.items():
        if len(key) > 1 and key[-1] in OPERATORS:
            operations.append((key[:-1], key[-1], value))
        else:
            plain[key] = value

    for key, value in plain.items():
        here = path + (key,)
        if value is None:
            dst.pop(key, None)
            prov[".".join(here)] = f"{layer} (deleted)"
            continue
        current = dst.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            _merge_into(current, value, prov, layer, here)
        elif _is_id_list(value) and _is_id_list(current):
            dst[key] = _merge_id_lists(current, value)
            prov[".".join(here)] = f"{layer} (merged by id)"
        else:
            dst[key] = copy.deepcopy(value)
            _stamp(prov, here, value, layer)

    for key, op, operand in operations:
        here = path + (key,)
        dst[key] = _apply_operator(dst.get(key), op, operand)
        prov[".".join(here)] = f"{layer} ({OPERATORS[op]})"


def merge_layers(loaded: list[tuple[str, dict]]) -> tuple[dict, dict]:
    merged: dict = {}
    prov: dict = {}
    for name, data in loaded:
        _merge_into(merged, data, prov, name, ())
    return merged, prov


def load_all(explicit_project: str | None = None) -> tuple[dict, dict, dict[str, Path]]:
    paths = layer_paths(explicit_project)
    loaded = [(name, read_layer(paths[name])) for name in LAYERS]
    merged, prov = merge_layers(loaded)
    return merged, prov, paths


# --------------------------------------------------------------------------- lookup


def lookup(config: dict, dotted: str) -> tuple[object, bool]:
    parts = dotted.split(".")
    current: object = config
    position = 0
    while position < len(parts):
        if not isinstance(current, dict):
            return None, False
        key = parts[position]
        if key in current:
            current = current[key]
            position += 1
            continue
        # A config key may itself contain dots (clang-tidy options, BraceWrapping.*),
        # so on a miss, retry treating everything remaining as one literal key.
        remainder = ".".join(parts[position:])
        if remainder in current:
            return current[remainder], True
        return None, False
    return current, True


def render(value: object, as_json: bool) -> str:
    if as_json or isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


# --------------------------------------------------------------------------- checks


def applicable_checks(merged: dict, root: Path) -> list[dict]:
    """Checks whose `when` holds, in `order`.

    Ordering is an explicit field rather than list position because layers merge
    checks by id: a project that appends `configure` and `build` to a base list
    that already has `precommit` would otherwise run them in the wrong order.
    """
    checks, found = lookup(merged, "implement.checks")
    if not found or not isinstance(checks, list):
        return []
    applicable = [
        check
        for check in checks
        if isinstance(check, dict) and evaluate_when(check.get("when"), root)
    ]
    return sorted(applicable, key=lambda check: check.get("order", 100))


def evaluate_when(predicate: object, root: Path) -> bool:
    if not predicate or predicate == "always":
        return True
    if not isinstance(predicate, str):
        return True
    negated = predicate.startswith("!")
    expression = predicate[1:] if negated else predicate
    if expression.startswith("exists:"):
        result = (root / expression[len("exists:") :]).exists()
    else:
        return True
    return not result if negated else result


# --------------------------------------------------------------------------- validation

KNOWN_TOP_LEVEL = {
    "version", "init", "knowledge", "plan", "implement", "sessions", "briefing", "autoLearn", "sessionWrap",
    "cpp", "git", "gitDiff", "statusLine", "projects",
}

ENUMS = {
    "init.fallbackOnNoSymlinks": {"stub", "copy", "abort"},
    "init.nestedAgentsMd": {"leave", "mirror"},
    "plan.format": {"markdown", "html"},
    "briefing.format": {"markdown", "html"},
    "cpp.driftCheck": {"off", "warn", "block"},
    "git.commitStyle": {"conventional", "free"},
    "autoLearn.mode": {"ask", "queue"},
    "sessionWrap.mode": {"ask", "queue"},
}

TYPES = {
    "version": int,
    "init.toolFiles": list,
    "init.maxFilesTouched": int,
    "init.stageChanges": bool,
    "implement.checks": list,
    "implement.checkTimeoutSeconds": int,
    "implement.maxAttemptsPerTask": int,
    "implement.finalFullCheck": bool,
    "knowledge.consultShared": bool,
    "sessions.aliases": dict,
    "sessions.excludePathPrefixes": list,
    "sessions.includeSubagents": bool,
    "briefing.sources": list,
    "briefing.openBrowser": bool,
    "autoLearn.hook.enabled": bool,
    "autoLearn.minScore": int,
    "gitDiff.enabled": bool,
    "gitDiff.difftastic.enabled": bool,
    "gitDiff.delta.enabled": bool,
    "statusLine.showGitBranch": bool,
    "statusLine.showBurnRate": bool,
    "statusLine.contextWarnPercent": int,
    "statusLine.contextCritPercent": int,
    "projects": dict,
}


def validate(merged: dict, loaded: list[tuple[str, dict]], strict: bool) -> list[str]:
    problems: list[str] = []
    notes: list[str] = []

    for name, data in loaded:
        for key in data:
            base = key[:-1] if len(key) > 1 and key[-1] in OPERATORS else key
            if base not in KNOWN_TOP_LEVEL:
                notes.append(f"{name}: unknown top-level key {key!r} (preserved)")
        if name == "project" and "projects" in data:
            notes.append(
                "project: 'projects' registry belongs in the home layer only; it will be merged "
                "but is not portable to other machines"
            )

    for dotted, expected in TYPES.items():
        value, found = lookup(merged, dotted)
        if found and not isinstance(value, expected):
            if expected is int and isinstance(value, bool):
                pass
            elif isinstance(value, expected):
                continue
            else:
                problems.append(
                    f"{dotted}: expected {expected.__name__}, got {type(value).__name__}"
                )

    for dotted, allowed in ENUMS.items():
        value, found = lookup(merged, dotted)
        if found and value not in allowed:
            problems.append(f"{dotted}: {value!r} not one of {sorted(allowed)}")

    checks, found = lookup(merged, "implement.checks")
    if found and isinstance(checks, list):
        seen: set[str] = set()
        for position, check in enumerate(checks):
            if not isinstance(check, dict):
                problems.append(f"implement.checks[{position}]: must be an object")
                continue
            if "id" not in check:
                problems.append(
                    f"implement.checks[{position}]: missing 'id' (required for merge-by-id)"
                )
                continue
            if check["id"] in seen:
                problems.append(f"implement.checks: duplicate id {check['id']!r}")
            seen.add(check["id"])
            if "cmd" not in check:
                problems.append(f"implement.checks[{check['id']}]: missing 'cmd'")
            if "order" in check and not isinstance(check["order"], (int, float)):
                problems.append(f"implement.checks[{check['id']}]: 'order' must be a number")
            scoped = check.get("scopedCmd")
            if scoped is not None and "{files}" not in str(scoped):
                problems.append(
                    f"implement.checks[{check['id']}]: 'scopedCmd' must contain {{files}}"
                )

    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    if strict:
        problems.extend(f"strict: {note}" for note in notes)
    return problems


# --------------------------------------------------------------------------- doctor

TOOLS = [
    ("python3", ["--version"], True, "already present"),
    ("git", ["--version"], True, "sudo apt install git"),
    ("rg", ["--version"], True, "sudo apt install ripgrep"),
    ("jq", ["--version"], True, "sudo apt install jq"),
    ("clang-format", ["--version"], False, "sudo apt install clang-format"),
    ("clang-tidy", ["--version"], False, "sudo apt install clang-tidy"),
    ("pre-commit", ["--version"], False, "pipx install pre-commit"),
    ("difft", ["--version"], False, "/core:setup-git-diff (downloads the release binary)"),
    ("delta", ["--version"], False, "sudo apt install git-delta"),
]


def doctor() -> int:
    missing_required = 0
    for name, args, required, hint in TOOLS:
        path = shutil.which(name)
        if path:
            try:
                out = subprocess.run(
                    [name, *args], capture_output=True, text=True, timeout=10
                )
                version = (out.stdout or out.stderr).strip().splitlines()[0]
            except (OSError, subprocess.SubprocessError, IndexError):
                version = "unknown version"
            print(f"  ok       {name:<14} {version}")
        else:
            label = "MISSING " if required else "optional"
            print(f"  {label} {name:<14} not found — {hint}")
            if required:
                missing_required += 1
    if missing_required:
        print(f"\n{missing_required} required tool(s) missing.", file=sys.stderr)
    return OK if missing_required == 0 else 1


# --------------------------------------------------------------------------- commands


def cmd_get(args: argparse.Namespace) -> int:
    merged, _, _ = load_all(args.project)
    value, found = lookup(merged, args.key)
    if not found:
        if args.default is not None:
            print(args.default)
            return OK
        print(f"key not found: {args.key}", file=sys.stderr)
        return ERR_MISSING_KEY
    print(render(value, args.type == "json"))
    return OK


def cmd_dump(args: argparse.Namespace) -> int:
    paths = layer_paths(args.project)
    if args.layer != "merged":
        data = read_layer(paths[args.layer])
        print(json.dumps(data, indent=2 if args.pretty else None, ensure_ascii=False))
        return OK
    merged, prov, _ = load_all(args.project)
    if args.explain:
        print(json.dumps({"config": merged, "source": prov}, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(merged, indent=2 if args.pretty else None, ensure_ascii=False))
    return OK


def cmd_validate(args: argparse.Namespace) -> int:
    paths = layer_paths(args.project)
    loaded = [(name, read_layer(paths[name])) for name in LAYERS]
    merged, _ = merge_layers(loaded)
    problems = validate(merged, loaded, args.strict)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return ERR_SCHEMA
    print("config ok")
    return OK


def cmd_path(args: argparse.Namespace) -> int:
    paths = layer_paths(args.project)
    target = paths[args.layer]
    print(target)
    return OK if target.is_file() else ERR_MISSING_KEY


def cmd_root(args: argparse.Namespace) -> int:
    print(project_root(args.project))
    return OK


def cmd_checks(args: argparse.Namespace) -> int:
    merged, _, _ = load_all(args.project)
    root = project_root(args.project)
    applicable = applicable_checks(merged, root)
    if args.scoped:
        applicable = [
            {**check, "cmd": check["scopedCmd"].replace("{files}", args.scoped)}
            for check in applicable
            if check.get("scopedCmd")
        ]
    if args.json:
        print(json.dumps(applicable, separators=(",", ":"), ensure_ascii=False))
    else:
        for check in applicable:
            print(f"{check.get('id')}\t{check.get('cmd')}")
    return OK


def cmd_projects(args: argparse.Namespace) -> int:
    if args.scan:
        base = Path(args.scan).expanduser().resolve()
        discovered = {
            entry.name: {
                "path": str(entry),
                "description": "",
                "tags": [],
            }
            for entry in sorted(base.iterdir())
            if entry.is_dir() and (entry / ".git").exists()
        }
        print(json.dumps({"projects": discovered}, indent=2, ensure_ascii=False))
        return OK
    merged, _, _ = load_all(args.project)
    registry, found = lookup(merged, "projects")
    if not found or not isinstance(registry, dict):
        registry = {}
    if args.json:
        print(json.dumps(registry, separators=(",", ":"), ensure_ascii=False))
        return OK
    for name, entry in sorted(registry.items()):
        path = Path(str(entry.get("path", ""))).expanduser()
        # Registry paths are a hint, not a fact: directories get renamed.
        status = "ok" if path.is_dir() else "MISSING"
        print(f"{status:<8} {name:<20} {path}  {entry.get('description', '')}")
    return OK


def cmd_doctor(_: argparse.Namespace) -> int:
    return doctor()


def cmd_state_dir(args: argparse.Namespace) -> int:
    if not args.key:
        print(state_root(args.project))
        return OK
    print(state_path(args.project, args.key, args.default))
    return OK


def cmd_state_gc(args: argparse.Namespace) -> int:
    base = state_home()
    if not base.is_dir():
        print("no state root yet")
        return OK
    stale = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        meta = read_layer(entry / "meta.json")
        anchor = meta.get("anchor")
        if not anchor or not Path(str(anchor)).exists():
            stale.append(entry)
    if not stale:
        print("nothing stale")
        return OK
    print(
        "stale = the repo is no longer at its recorded path: deleted, or moved and not used since.\n"
        "A moved repo re-links its state the next time a plan command runs inside it; do that\n"
        "before --apply to keep its plans.\n"
    )
    for entry in stale:
        if args.apply:
            shutil.rmtree(entry)
            print(f"removed  {entry.name}\t{entry}")
        else:
            print(f"stale    {entry.name}\t{entry}")
    if stale and not args.apply:
        print("\nre-run with --apply to delete", file=sys.stderr)
    return OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wf_config.py", description=__doc__)
    parser.add_argument("--project", help="treat this directory as the project root")
    sub = parser.add_subparsers(dest="command", required=True)

    get = sub.add_parser("get", help="print one dotted key")
    get.add_argument("key")
    get.add_argument("--default")
    get.add_argument("--type", choices=("raw", "json"), default="raw")
    get.set_defaults(func=cmd_get)

    dump = sub.add_parser("dump", help="print a layer or the merged config")
    dump.add_argument("--layer", choices=(*LAYERS, "merged"), default="merged")
    dump.add_argument("--pretty", action="store_true")
    dump.add_argument("--explain", action="store_true", help="annotate which layer won each leaf")
    dump.set_defaults(func=cmd_dump)

    check = sub.add_parser("validate", help="check types, enums and unknown keys")
    check.add_argument("--strict", action="store_true")
    check.set_defaults(func=cmd_validate)

    where = sub.add_parser("path", help="print the file path of one layer")
    where.add_argument("layer", choices=LAYERS)
    where.set_defaults(func=cmd_path)

    sub.add_parser("root", help="print the resolved project root").set_defaults(func=cmd_root)

    checks = sub.add_parser("checks", help="list checks whose 'when' predicate holds")
    checks.add_argument("--json", action="store_true")
    checks.add_argument(
        "--scoped", metavar="FILES", help="emit only scoped checks, with {files} substituted"
    )
    checks.set_defaults(func=cmd_checks)

    projects = sub.add_parser("projects", help="list or discover known projects")
    projects.add_argument("--json", action="store_true")
    projects.add_argument("--scan", metavar="DIR", help="emit a registry built from DIR/*/.git")
    projects.set_defaults(func=cmd_projects)

    sub.add_parser("doctor", help="report missing prerequisites").set_defaults(func=cmd_doctor)

    state = sub.add_parser(
        "state-dir",
        help="resolve (and create) a path under this repo's external, worktree-shared state root",
    )
    state.add_argument(
        "key", nargs="?", help="dotted config key naming the subdir, e.g. plan.dir; omit for the bare root"
    )
    state.add_argument("--default", default="", help="subdir name to use if the key is unset")
    state.set_defaults(func=cmd_state_dir)

    gc = sub.add_parser(
        "state-gc", help="list (or, with --apply, delete) state dirs whose repo no longer exists"
    )
    gc.add_argument("--apply", action="store_true")
    gc.set_defaults(func=cmd_state_gc)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
