#!/usr/bin/env python3
"""Point the user's global statusLine setting at this plugin's wf_statusline.py.

Edits ~/.claude/settings.json in place, touching only the top-level "statusLine" key so any
other settings (permissions, hooks, model, ...) survive untouched. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf_config  # noqa: E402

OK = 0
ERR_EXISTING_FOREIGN = 1
ERR_BAD_JSON = 2

MARKER = "wf_statusline.py"


def settings_path(override: str | None) -> Path:
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "settings.json"


def desired_block() -> dict:
    script = wf_config.plugin_root() / "scripts" / "wf_statusline.py"
    return {
        "type": "command",
        "command": f"python3 {script}",
        "padding": 1,
    }


def load_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a JSON object")
    return data


def cmd_show(args: argparse.Namespace) -> int:
    print(json.dumps({"statusLine": desired_block()}, indent=2))
    return OK


def cmd_apply(args: argparse.Namespace) -> int:
    path = settings_path(args.settings_path)
    try:
        settings = load_settings(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return ERR_BAD_JSON

    existing = settings.get("statusLine")
    block = desired_block()
    if existing and existing != block and not args.force:
        existing_cmd = existing.get("command", "") if isinstance(existing, dict) else ""
        if MARKER not in existing_cmd:
            print(
                f"error: {path} already has a statusLine that was not set up by this plugin:\n"
                f"  {json.dumps(existing)}\n"
                "Pass --force to overwrite it.",
                file=sys.stderr,
            )
            return ERR_EXISTING_FOREIGN

    settings["statusLine"] = block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"wrote statusLine to {path}")
    return OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wf_statusline_setup.py", description=__doc__)
    parser.add_argument("--settings-path", help="override ~/.claude/settings.json (testing)")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="print the statusLine block this would write")
    show.set_defaults(func=cmd_show)

    apply_ = sub.add_parser("apply", help="write the statusLine block into settings.json")
    apply_.add_argument("--force", action="store_true", help="overwrite a foreign statusLine")
    apply_.set_defaults(func=cmd_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
