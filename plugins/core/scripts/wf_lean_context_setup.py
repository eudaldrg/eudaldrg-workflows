#!/usr/bin/env python3
"""Apply, inspect or revert the lean startup context settings in ~/.claude/settings.json.

Touches only three keys and leaves every other setting alone:

  permissions.deny          gains "Artifact" (merged into any existing list, no duplicates)
  env.ENABLE_TOOL_SEARCH    "true" (MCP tool schemas are deferred behind ToolSearch)
  promptSuggestionEnabled   false (no per-turn full-context suggestion request)

The reasoning and the measurements are in references/lean-context.md. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OK = 0
ERR_CONFLICT = 1
ERR_BAD_JSON = 2

DENY_TOOL = "Artifact"
TOOL_SEARCH_VAR = "ENABLE_TOOL_SEARCH"
TOOL_SEARCH_VALUE = "true"
SUGGESTION_KEY = "promptSuggestionEnabled"


def settings_path(override: str | None) -> Path:
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "settings.json"


def load_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a JSON object")
    for key, kind in (("permissions", dict), ("env", dict)):
        if key in data and not isinstance(data[key], kind):
            raise ValueError(f"{path}: \"{key}\" must be a JSON object")
    deny = data.get("permissions", {}).get("deny")
    if deny is not None and not isinstance(deny, list):
        raise ValueError(f"{path}: \"permissions.deny\" must be a JSON array")
    return data


def current_state(settings: dict) -> dict:
    """What each of our three settings holds now; None means unset."""
    return {
        "deny": DENY_TOOL in settings.get("permissions", {}).get("deny", []),
        "toolSearch": settings.get("env", {}).get(TOOL_SEARCH_VAR),
        "suggestions": settings.get(SUGGESTION_KEY),
    }


def conflicts(settings: dict) -> list[str]:
    """Explicit values the user chose that apply would overwrite."""
    state = current_state(settings)
    found = []
    if state["toolSearch"] not in (None, TOOL_SEARCH_VALUE):
        found.append(f"env.{TOOL_SEARCH_VAR} = {json.dumps(state['toolSearch'])}")
    if state["suggestions"] not in (None, False):
        found.append(f"{SUGGESTION_KEY} = {json.dumps(state['suggestions'])}")
    return found


def apply_changes(settings: dict) -> list[str]:
    """Mutate settings into the lean state; return a description of each change made."""
    changes = []
    permissions = settings.setdefault("permissions", {})
    deny = permissions.setdefault("deny", [])
    if DENY_TOOL not in deny:
        deny.append(DENY_TOOL)
        changes.append(f"permissions.deny += {json.dumps(DENY_TOOL)}")
    env = settings.setdefault("env", {})
    if env.get(TOOL_SEARCH_VAR) != TOOL_SEARCH_VALUE:
        env[TOOL_SEARCH_VAR] = TOOL_SEARCH_VALUE
        changes.append(f"env.{TOOL_SEARCH_VAR} = {json.dumps(TOOL_SEARCH_VALUE)}")
    if settings.get(SUGGESTION_KEY) is not False:
        settings[SUGGESTION_KEY] = False
        changes.append(f"{SUGGESTION_KEY} = false")
    return changes


def revert_changes(settings: dict) -> tuple[list[str], list[str]]:
    """Remove our values, back to Claude Code's defaults. Values someone else set are kept.

    Returns (changes made, values left alone because this script did not set them)."""
    changes, kept = [], []
    permissions = settings.get("permissions", {})
    deny = permissions.get("deny", [])
    if DENY_TOOL in deny:
        permissions["deny"] = [entry for entry in deny if entry != DENY_TOOL]
        changes.append(f"permissions.deny -= {json.dumps(DENY_TOOL)}")
        if not permissions["deny"]:
            del permissions["deny"]
        if not permissions:
            del settings["permissions"]
    env = settings.get("env", {})
    if env.get(TOOL_SEARCH_VAR) == TOOL_SEARCH_VALUE:
        del env[TOOL_SEARCH_VAR]
        changes.append(f"env.{TOOL_SEARCH_VAR} removed")
        if not env:
            del settings["env"]
    elif TOOL_SEARCH_VAR in env:
        kept.append(f"env.{TOOL_SEARCH_VAR} = {json.dumps(env[TOOL_SEARCH_VAR])}")
    if settings.get(SUGGESTION_KEY) is False:
        del settings[SUGGESTION_KEY]
        changes.append(f"{SUGGESTION_KEY} removed")
    elif SUGGESTION_KEY in settings:
        kept.append(f"{SUGGESTION_KEY} = {json.dumps(settings[SUGGESTION_KEY])}")
    return changes, kept


def write_settings(path: Path, settings: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def read_or_report(path: Path) -> dict | None:
    try:
        return load_settings(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def print_changes(changes: list[str], verb: str) -> None:
    for change in changes:
        print(f"  {verb}: {change}")


def cmd_status(args: argparse.Namespace) -> int:
    path = settings_path(args.settings_path)
    settings = read_or_report(path)
    if settings is None:
        return ERR_BAD_JSON
    state = current_state(settings)
    print(f"{path}:")
    tool_search, suggestions = state["toolSearch"], state["suggestions"]
    rows = [
        ("Artifact denied", "yes" if state["deny"] else "no"),
        (f"env.{TOOL_SEARCH_VAR}",
         json.dumps(tool_search) if tool_search is not None else "unset (auto)"),
        (SUGGESTION_KEY, json.dumps(suggestions) if suggestions is not None else "unset (on)"),
    ]
    for label, value in rows:
        print(f"  {label + ':':<25} {value}")
    pending = apply_changes(json.loads(json.dumps(settings)))
    if not pending:
        print("lean context is fully applied")
        return OK
    print("apply would change:")
    print_changes(pending, "set")
    blocking = conflicts(settings)
    if blocking:
        print("apply needs --force to overwrite: " + "; ".join(blocking))
    return OK


def cmd_apply(args: argparse.Namespace) -> int:
    path = settings_path(args.settings_path)
    settings = read_or_report(path)
    if settings is None:
        return ERR_BAD_JSON
    blocking = conflicts(settings)
    if blocking and not args.force:
        print(
            f"error: {path} already sets a value this would overwrite:\n  "
            + "\n  ".join(blocking)
            + "\nPass --force to overwrite it.",
            file=sys.stderr,
        )
        return ERR_CONFLICT
    changes = apply_changes(settings)
    if not changes:
        print(f"{path}: lean context already applied, nothing to do")
        return OK
    if args.dry_run:
        print(f"{path}: would change")
        print_changes(changes, "set")
        return OK
    write_settings(path, settings)
    print(f"{path}: updated")
    print_changes(changes, "set")
    return OK


def cmd_revert(args: argparse.Namespace) -> int:
    path = settings_path(args.settings_path)
    settings = read_or_report(path)
    if settings is None:
        return ERR_BAD_JSON
    changes, kept = revert_changes(settings)
    for value in kept:
        print(f"  kept (not set by this script): {value}")
    if not changes:
        print(f"{path}: nothing to revert")
        return OK
    if args.dry_run:
        print(f"{path}: would change")
        print_changes(changes, "revert")
        return OK
    write_settings(path, settings)
    print(f"{path}: updated")
    print_changes(changes, "revert")
    return OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wf_lean_context_setup.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--settings-path", help="override ~/.claude/settings.json (testing)")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="show each setting and what apply would change")
    status.set_defaults(func=cmd_status)

    apply_ = sub.add_parser("apply", help="write the lean settings into settings.json")
    apply_.add_argument("--dry-run", action="store_true", help="print the changes, write nothing")
    apply_.add_argument("--force", action="store_true",
                        help=f"overwrite an explicit {TOOL_SEARCH_VAR} or {SUGGESTION_KEY} value")
    apply_.set_defaults(func=cmd_apply)

    revert = sub.add_parser("revert", help="remove the lean settings, back to Claude Code defaults")
    revert.add_argument("--dry-run", action="store_true", help="print the changes, write nothing")
    revert.set_defaults(func=cmd_revert)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
