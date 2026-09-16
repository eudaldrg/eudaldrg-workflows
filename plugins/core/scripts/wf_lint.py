#!/usr/bin/env python3
"""Generate .clang-format and .clang-tidy from shared base rules plus project overrides.

The clang tools can only inherit from parent directories, never from an arbitrary
path, so shared rules are merged here and written into the project as generated,
committed files. Overrides live in <project>/.claude/workflows.json under `cpp`.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf_config  # noqa: E402

OK = 0
DRIFT = 1
ERROR = 2

YAML_KEYWORDS = {"true", "false", "null", "yes", "no", "on", "off", "y", "n", "~"}
PLAIN_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.+-]*$")
STAMP = re.compile(r"^#\s*(wf-[a-z0-9-]+):\s*(.*)$", re.MULTILINE)


# --------------------------------------------------------------------------- yaml


def scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    text = "" if value is None else str(value)
    if text and PLAIN_SAFE.match(text) and text.lower() not in YAML_KEYWORDS:
        return text
    return "'" + text.replace("'", "''") + "'"


def emit(mapping: dict, indent: int = 0) -> list[str]:
    lines: list[str] = []
    pad = "  " * indent
    for key, value in mapping.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.extend(emit(value, indent + 1))
        elif isinstance(value, list):
            lines.append(f"{pad}{key}:")
            lines.extend(f"{pad}  - {scalar(item)}" for item in value)
        else:
            lines.append(f"{pad}{key}: {scalar(value)}")
    return lines


def emit_folded_list(key: str, items: list[str]) -> list[str]:
    lines = [f"{key}: >"]
    for position, item in enumerate(items):
        suffix = "," if position < len(items) - 1 else ""
        lines.append(f"  {item}{suffix}")
    return lines


def explode(flat: dict) -> dict:
    """Turn dotted keys (BraceWrapping.AfterFunction) into nested mappings."""
    out: dict = {}
    for key, value in flat.items():
        head, dot, rest = key.partition(".")
        if dot:
            nested = out.setdefault(head, {})
            if isinstance(nested, dict):
                nested[rest] = value
        else:
            out[key] = value
    return {k: (explode(v) if isinstance(v, dict) else v) for k, v in out.items()}


def order_format(mapping: dict) -> dict:
    lead = [k for k in ("Language", "BasedOnStyle") if k in mapping]
    rest = sorted(k for k in mapping if k not in lead)
    ordered = {k: mapping[k] for k in (*lead, *rest)}
    return {
        k: (dict(sorted(v.items())) if isinstance(v, dict) else v) for k, v in ordered.items()
    }


# --------------------------------------------------------------------------- merge


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strip_docs(mapping: dict) -> dict:
    return {k: v for k, v in mapping.items() if not k.startswith("_")}


def merge_format(base: dict, overrides: dict, unset: list) -> dict:
    merged = strip_docs(base)
    for key, value in overrides.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    for key in unset:
        merged.pop(key, None)
    return merged


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def merge_tidy(base: dict, cfg: dict) -> dict:
    enables = dedupe([*base.get("checksEnable", []), *cfg.get("checksAdd", [])])
    raw_disables = [*base.get("checksDisable", []), *cfg.get("checksRemove", [])]
    disables = dedupe([d if d.startswith("-") else f"-{d}" for d in raw_disables])

    scalars = dict(base.get("scalars", {}))
    for key, value in cfg.get("scalars", {}).items():
        if value is None:
            scalars.pop(key, None)
        else:
            scalars[key] = value
    # Machine-specific and leaks the username; never emit it.
    scalars.pop("User", None)

    options = dict(base.get("options", {}))
    for key, value in cfg.get("options", {}).items():
        if value is None:
            options.pop(key, None)
        else:
            options[key] = value

    # -* first, then every enable, then every disable: a project's disable must
    # beat a base enable regardless of which layer wrote it.
    return {
        "checks": ["-*", *enables, *disables],
        "scalars": dict(sorted(scalars.items())),
        "options": dict(sorted(options.items())),
    }


# --------------------------------------------------------------------------- render


def render_format(merged: dict) -> str:
    return "\n".join(emit(order_format(explode(merged)))) + "\n"


def render_tidy(merged: dict) -> str:
    lines = emit_folded_list("Checks", merged["checks"])
    lines.extend(emit(merged["scalars"]))
    if merged["options"]:
        lines.append("CheckOptions:")
        lines.extend(emit(merged["options"], 1))
    return "\n".join(lines) + "\n"


def header(version: str, base_hash: str, override_hash: str, body: str, sources: str) -> str:
    # No timestamp on purpose: a timestamp would make every regeneration a diff
    # and destroy drift detection.
    return "\n".join(
        [
            "# " + "=" * 74,
            "#  GENERATED FILE - do not edit by hand.",
            "#  Edit this project's .claude/workflows.json under `cpp`, then run",
            "#  the sync-lint-rules skill (/core:sync-lint-rules) to regenerate.",
            "# " + "=" * 74,
            f"# wf-rules:            {version}",
            f"# wf-source:           {sources}",
            f"# wf-base-sha256:      {base_hash}",
            f"# wf-overrides-sha256: {override_hash}",
            f"# wf-generated-sha256: {sha(body.encode())}",
        ]
    )


def split_header(text: str) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    cut = 0
    while cut < len(lines) and lines[cut].lstrip().startswith("#"):
        cut += 1
    return "".join(lines[:cut]), "".join(lines[cut:]).lstrip("\n")


def stamps(header_text: str) -> dict[str, str]:
    return {key: value.strip() for key, value in STAMP.findall(header_text)}


# --------------------------------------------------------------------------- verify


def dump_config(kind: str, body: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        name = ".clang-format" if kind == "format" else ".clang-tidy"
        (Path(tmp) / name).write_text(body, encoding="utf-8")
        cmd = (
            ["clang-format", "--style=file", "--dump-config"]
            if kind == "format"
            else ["clang-tidy", "--dump-config"]
        )
        try:
            out = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"could not run {cmd[0]}: {exc}"
        if out.returncode != 0:
            return False, (out.stderr or out.stdout).strip()
        noise = [
            line
            for line in (out.stderr or "").splitlines()
            if "error" in line.lower() or "unknown" in line.lower()
        ]
        if noise:
            return False, "\n".join(noise)
        return True, out.stdout


def roundtrip_ok(body: str, expected: dict) -> str | None:
    """Verify with PyYAML when it happens to be importable. Optional by design."""
    try:
        import yaml  # noqa: PLC0415
    except ImportError:
        return None
    try:
        parsed = yaml.safe_load(body)
    except Exception as exc:  # noqa: BLE001
        return f"emitted YAML does not parse: {exc}"
    if parsed != expected:
        return "emitted YAML does not round-trip to the intended structure"
    return "ok"


# --------------------------------------------------------------------------- build


def load_rules(plugin_root: Path) -> tuple[dict, dict, str, str]:
    rules = plugin_root / "rules" / "cpp"
    fmt = json.loads((rules / "base.clang-format.json").read_text(encoding="utf-8"))
    tidy = json.loads((rules / "base.clang-tidy.json").read_text(encoding="utf-8"))
    version = (rules / "VERSION").read_text(encoding="utf-8").strip()
    base_hash = sha(canonical([strip_docs(fmt), strip_docs(tidy)]))
    return fmt, tidy, version, base_hash


def build(project: str | None) -> dict:
    merged_cfg, _, _ = wf_config.load_all(project)
    cpp = merged_cfg.get("cpp", {}) if isinstance(merged_cfg.get("cpp"), dict) else {}
    plugin_root = wf_config.plugin_root()
    root = wf_config.project_root(project)

    base_fmt, base_tidy, version, base_hash = load_rules(plugin_root)
    fmt_cfg = cpp.get("clangFormat", {}) or {}
    tidy_cfg = cpp.get("clangTidy", {}) or {}

    fmt_merged = merge_format(base_fmt, fmt_cfg.get("overrides", {}) or {}, fmt_cfg.get("unset", []) or [])
    tidy_merged = merge_tidy(base_tidy, tidy_cfg)

    fmt_body = render_format(fmt_merged)
    tidy_body = render_tidy(tidy_merged)
    override_hash = sha(canonical({"clangFormat": fmt_cfg, "clangTidy": tidy_cfg}))

    return {
        "root": root,
        "enabled": bool(cpp.get("enabled", False)),
        "version": version,
        "baseHash": base_hash,
        "overrideHash": override_hash,
        "files": {
            ".clang-format": {
                "body": fmt_body,
                "kind": "format",
                "structure": order_format(explode(fmt_merged)),
                "source": "rules/cpp/base.clang-format.json",
            },
            ".clang-tidy": {
                "body": tidy_body,
                "kind": "tidy",
                "structure": None,
                "source": "rules/cpp/base.clang-tidy.json",
            },
        },
    }


def full_text(spec: dict, built: dict) -> str:
    return (
        header(built["version"], built["baseHash"], built["overrideHash"], spec["body"], spec["source"])
        + "\n"
        + spec["body"]
    )


# --------------------------------------------------------------------------- commands


def cmd_show(args: argparse.Namespace) -> int:
    built = build(args.project)
    for name, spec in built["files"].items():
        print(f"===== {name} =====")
        print(full_text(spec, built), end="")
    return OK


def cmd_generate(args: argparse.Namespace) -> int:
    built = build(args.project)
    if not built["enabled"] and not args.force:
        print("cpp.enabled is false for this project; nothing to do", file=sys.stderr)
        return OK
    root: Path = built["root"]
    changed = False
    for name, spec in built["files"].items():
        target = root / name
        new_text = full_text(spec, built)

        ok, detail = dump_config(spec["kind"], spec["body"])
        if not ok:
            print(f"error: {name} rejected by the clang tool:\n{detail}", file=sys.stderr)
            return ERROR
        if spec["structure"] is not None:
            verdict = roundtrip_ok(spec["body"], spec["structure"])
            if verdict not in (None, "ok"):
                print(f"error: {name}: {verdict}", file=sys.stderr)
                return ERROR

        old_text = target.read_text(encoding="utf-8") if target.is_file() else ""
        if old_text == new_text:
            print(f"  unchanged  {name}")
            continue
        changed = True
        diff = difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
        )
        print(f"  {'write' if args.apply else 'would write'}  {name}")
        sys.stdout.writelines(diff)
        if args.apply:
            target.write_text(new_text, encoding="utf-8")
    if not args.apply and changed:
        print("\n(dry run — pass --apply to write)")
    return OK


def cmd_check(args: argparse.Namespace) -> int:
    built = build(args.project)
    if not built["enabled"]:
        return OK
    root: Path = built["root"]
    issues: list[str] = []
    for name, spec in built["files"].items():
        target = root / name
        if not target.is_file():
            issues.append(f"{name}: missing — run sync-lint-rules")
            continue
        head, body = split_header(target.read_text(encoding="utf-8"))
        marks = stamps(head)
        if not marks:
            issues.append(f"{name}: not a generated file (no provenance header)")
            continue
        if marks.get("wf-generated-sha256") != sha(body.encode()):
            issues.append(f"{name}: hand-edited since generation — fold the change into cpp overrides")
        if marks.get("wf-base-sha256") != built["baseHash"]:
            was, now = marks.get("wf-rules"), built["version"]
            moved = f"{was} -> {now}" if was != now else f"{now}, content changed in place"
            issues.append(f"{name}: shared rules moved on ({moved})")
        if marks.get("wf-overrides-sha256") != built["overrideHash"]:
            issues.append(f"{name}: project overrides changed but were never regenerated")
    for issue in issues:
        print(f"drift: {issue}")
    if not issues:
        print("lint rules up to date")
        return OK
    mode = str(wf_config.lookup(wf_config.load_all(args.project)[0], "cpp.driftCheck")[0] or "warn")
    return DRIFT if mode == "block" else OK


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", help="project root (default: cwd's git root)")

    parser = argparse.ArgumentParser(prog="wf_lint.py", description=__doc__, parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", parents=[common], help="print the resolved files")
    show.set_defaults(func=cmd_show)

    gen = sub.add_parser(
        "generate", parents=[common], help="write the generated configs (dry run by default)"
    )
    gen.add_argument("--apply", action="store_true")
    gen.add_argument("--force", action="store_true", help="ignore cpp.enabled")
    gen.set_defaults(func=cmd_generate)

    check = sub.add_parser("check", parents=[common], help="report the three kinds of drift")
    check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    try:
        return args.func(args)
    except wf_config.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
