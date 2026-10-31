#!/usr/bin/env python3
"""Set up a C++ repo: scaffold its build and docs once, generate its hooks and CI, report drift.

Two kinds of output, on purpose (references/cpp-repo-setup.md):

- scaffolded once, owned by the repo afterwards: CMake skeleton, presets, smoke test, check
  scripts, docs/tasks pages, the AGENTS.md section. Never overwritten.
- generated and kept in sync: .pre-commit-config.yaml and the forge's CI file. They carry a
  provenance header (template version, config hash, body hash; no timestamp) for drift detection.

Forge-specific parts (CI file, branch protection) go through an adapter picked from the origin
URL or `git.forge`. Only GitHub has one; any other forge gets no CI file and a printed checklist.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf_config  # noqa: E402
from wf_lint import canonical, sha, split_header, stamps  # noqa: E402

OK = 0
DRIFT = 1
ERROR = 2

TEMPLATE_DIR = "templates/cpp-repo"
MARKER = re.compile(r"\{\{([a-z_]+)\}\}")
NOT_SCAFFOLDED = {"VERSION", "agents-md-section.md"}
AGENTS_HEADING = "## Lint / format / quality gates"
PRECOMMIT = ".pre-commit-config.yaml"
SANITIZER_VARIANTS = (("asanUbsan", "asan-ubsan"), ("tsan", "tsan"))


class SetupError(Exception):
    pass


# --------------------------------------------------------------------------- config


@dataclass
class Settings:
    root: Path
    cpp: dict
    repo: dict
    git: dict
    template_version: str

    @property
    def integration(self) -> str:
        return str(self.git.get("integrationBranch", "dev"))

    @property
    def release(self) -> str:
        return str(self.git.get("releaseBranch", "main"))

    def sanitizer_variants(self) -> list[str]:
        enabled = self.repo.get("checks", {}).get("sanitizers", {})
        return [variant for key, variant in SANITIZER_VARIANTS if enabled.get(key)]

    def config_hash(self) -> str:
        relevant = {
            "repo": self.repo,
            "branches": [self.release, self.integration],
        }
        return sha(canonical(relevant))


def load(project: str | None) -> Settings:
    merged, _, _ = wf_config.load_all(project)
    cpp = merged.get("cpp") if isinstance(merged.get("cpp"), dict) else {}
    git = merged.get("git") if isinstance(merged.get("git"), dict) else {}
    version_file = wf_config.plugin_root() / TEMPLATE_DIR / "VERSION"
    return Settings(
        root=wf_config.project_root(project),
        cpp=cpp,
        repo=cpp.get("repo", {}) or {},
        git=git,
        template_version=version_file.read_text(encoding="utf-8").strip(),
    )


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(text)))


def msvc_version(vs_version: str) -> int:
    """Visual Studio 17.8 -> MSVC_VERSION 1938 (15.x = 191x, 16.x = 192x, 17.x = 193x/194x)."""
    major, minor = (list(version_tuple(vs_version)) + [0, 0])[:2]
    if major < 15:
        raise SetupError(f"Visual Studio {vs_version} predates the MSVC_VERSION scheme this supports")
    return 1910 + 10 * (major - 15) + minor


# --------------------------------------------------------------------------- forge


def origin_url(root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def parse_remote(url: str | None) -> tuple[str | None, str | None]:
    """(host, owner/repo) from an ssh or https remote URL."""
    if not url:
        return None, None
    match = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^:/]+)(?::\d+)?[:/](.+?)(?:\.git)?/?$", url)
    if not match:
        return None, None
    return match.group(1).lower(), match.group(2)


def detect_forge(settings: Settings, url: str | None = None) -> dict:
    """{'forge': 'github'|'none'|'unsupported', 'host', 'slug', 'reason'}."""
    configured = settings.git.get("forge", "auto")
    host, slug = parse_remote(url if url is not None else origin_url(settings.root))
    if configured == "none":
        return {"forge": "none", "host": host, "slug": slug, "reason": "git.forge is none"}
    if configured == "github" or (host and (host == "github.com" or host.endswith(".github.com"))):
        return {"forge": "github", "host": host, "slug": slug, "reason": "origin is GitHub"
                if configured == "auto" else "git.forge is github"}
    if host:
        return {"forge": "unsupported", "host": host, "slug": slug,
                "reason": f"no adapter for {host}; only GitHub has one"}
    return {"forge": "none", "host": None, "slug": None, "reason": "no origin remote"}


# --------------------------------------------------------------------------- scaffold


def project_name(settings: Settings, explicit: str | None) -> str:
    name = explicit or settings.root.name
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return name if re.match(r"^[A-Za-z_]", name) else f"_{name}"


def values(settings: Settings, name: str | None) -> dict[str, str]:
    floor = settings.repo.get("compilerFloor", {})
    return {
        "project_name": project_name(settings, name),
        "cxx_standard": str(settings.repo.get("cxxStandard", 23)),
        "gcc_floor": str(floor.get("gcc", "14")),
        "clang_floor": str(floor.get("clang", "18")),
        "msvc_floor": str(floor.get("msvc", "17.8")),
        "msvc_floor_version": str(msvc_version(str(floor.get("msvc", "17.8")))),
        "googletest_tag": str(settings.repo.get("tools", {}).get("googletest", "v1.18.0")),
        "memory_cap_default": "ON" if settings.repo.get("checks", {}).get("memoryCap") else "OFF",
        "integration_branch": settings.integration,
        "release_branch": settings.release,
        "branch_prefix": str(settings.git.get("branchPrefix", "feature/")),
    }


def render_template(text: str, subs: dict[str, str], source: str) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in subs:
            raise SetupError(f"{source}: unknown template marker {{{{{key}}}}}")
        return subs[key]

    return MARKER.sub(replace, text)


def template_files() -> list[Path]:
    base = wf_config.plugin_root() / TEMPLATE_DIR
    return sorted(
        path for path in base.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
        and path.relative_to(base).as_posix() not in NOT_SCAFFOLDED
    )


def project_config_additions(settings: Settings, existing: dict) -> dict:
    """Keys the project layer needs and does not set yet."""
    additions: dict = {}
    if not (existing.get("cpp") or {}).get("enabled"):
        additions.setdefault("cpp", {})["enabled"] = True
    git = existing.get("git") or {}
    protected = list(git.get("protectedBranches", [])) + list(git.get("protectedBranches+", []))
    if settings.integration not in protected and "protectedBranches" not in git:
        additions.setdefault("git", {})["protectedBranches+"] = [settings.integration]
    return additions


def scaffold_actions(settings: Settings, name: str | None) -> list[dict]:
    """Each action: {path, action: write|keep|append|merge, content?}."""
    subs = values(settings, name)
    base = wf_config.plugin_root() / TEMPLATE_DIR
    actions: list[dict] = []
    for source in template_files():
        rel = source.relative_to(base).as_posix()
        target = settings.root / rel
        content = render_template(source.read_text(encoding="utf-8"), subs, rel)
        actions.append({"path": rel, "action": "keep" if target.exists() else "write",
                        "content": content})

    section = render_template((base / "agents-md-section.md").read_text(encoding="utf-8"), subs,
                              "agents-md-section.md")
    agents = settings.root / "AGENTS.md"
    if not agents.exists():
        actions.append({"path": "AGENTS.md", "action": "write",
                        "content": f"# {subs['project_name']}\n\n{section}"})
    elif AGENTS_HEADING not in agents.read_text(encoding="utf-8"):
        current = agents.read_text(encoding="utf-8")
        actions.append({"path": "AGENTS.md", "action": "append",
                        "content": current.rstrip("\n") + "\n\n" + section})
    else:
        actions.append({"path": "AGENTS.md", "action": "keep"})

    gitignore = settings.root / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    if not any(line.strip().strip("/") == "build" for line in lines):
        actions.append({"path": ".gitignore", "action": "append" if lines else "write",
                        "content": "\n".join([*lines, "build/"]) + "\n"})

    config_path = settings.root / ".claude" / "workflows.json"
    try:
        existing = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except json.JSONDecodeError as exc:
        raise SetupError(f"{config_path}: {exc}") from exc
    additions = project_config_additions(settings, existing)
    if additions:
        merged = json.loads(json.dumps(existing))
        for key, sub in additions.items():
            merged.setdefault(key, {}).update(sub)
        actions.append({"path": ".claude/workflows.json",
                        "action": "merge" if existing else "write",
                        "content": json.dumps(merged, indent=2) + "\n"})
    return actions


# --------------------------------------------------------------------------- generate: pre-commit


def precommit_body(settings: Settings) -> str:
    tools = settings.repo.get("tools", {})
    checks = settings.repo.get("checks", {})
    # The body must not start with a comment: split_header() reads leading comments as header.
    lines = [
        "default_stages: [pre-commit]",
        "# Install both stages once per clone:",
        "#   pre-commit install && pre-commit install --hook-type pre-push",
        "# clang-tidy and cppcheck read build/debug/compile_commands.json: run `cmake --preset debug`",
        "# once first. docs/tasks/testing.md has what each hook is for.",
        "repos:",
        "  - repo: https://github.com/pre-commit/mirrors-clang-format",
        f"    rev: v{tools.get('clangFormat', '21.1.8')}",
        "    hooks:",
        "      - id: clang-format",
        "        types_or: [c++, c]",
        "",
        "  - repo: local",
        "    hooks:",
        "      - id: clang-tidy",
        "        name: clang-tidy",
        "        # -Wno-unknown-warning-option: build/debug may be configured with GCC, whose",
        "        # warning flags clang-tidy does not know.",
        "        entry: clang-tidy -p build/debug --quiet --extra-arg=-Wno-unknown-warning-option",
        "        language: python",
        f"        additional_dependencies: ['clang-tidy=={tools.get('clangTidy', '21.1.6')}']",
        "        types_or: [c++, c]",
    ]
    if checks.get("cppcheck", True):
        lines += [
            "",
            "      - id: cppcheck",
            "        name: cppcheck",
            "        # --language=c++: otherwise every .h is parsed as C. --library=googletest teaches",
            "        # it the TEST macros.",
            "        entry: >-",
            "          cppcheck --language=c++ --library=googletest",
            "          --enable=warning,performance,portability --error-exitcode=1 --inline-suppr",
            "          --suppress=missingInclude --suppress=missingIncludeSystem",
            "        language: system",
            "        types_or: [c++, c]",
        ]
    lines += [
        "",
        "      - id: build",
        "        name: incremental build (build/debug must compile)",
        "        entry: python scripts/check_build.py",
        "        language: python",
        "        pass_filenames: false",
        "        always_run: true",
    ]
    variants = settings.sanitizer_variants()
    if variants:
        args = " ".join(f"--variant {variant}" for variant in variants)
        lines += [
            "",
            "      - id: sanitizers",
            f"        name: test suite under sanitizers ({', '.join(variants)})",
            f"        entry: python scripts/run_sanitizers.py {args}",
            "        language: python",
            "        pass_filenames: false",
            "        always_run: true",
            "        stages: [pre-push]",
        ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- generate: GitHub CI


def matrix_cells(settings: Settings) -> list[dict]:
    """Normalise and floor-check the CI matrix."""
    floor = settings.repo.get("compilerFloor", {})
    cells = []
    for cell in settings.repo.get("ci", {}).get("matrix", []):
        compiler = cell["compiler"]
        version = str(cell.get("version", ""))
        if compiler in ("gcc", "clang"):
            if version_tuple(version) < version_tuple(floor.get(compiler, "0")):
                raise SetupError(
                    f"CI matrix: {compiler} {version} is below the floor "
                    f"({compiler} {floor.get(compiler)}, cpp.repo.compilerFloor)"
                )
            cc, cxx = (f"gcc-{version}", f"g++-{version}") if compiler == "gcc" else (
                f"clang-{version}", f"clang++-{version}")
            # Clang on Linux uses the system libstdc++; take the one from the GCC floor, since the
            # runner's default may predate it (no <print> before libstdc++ 14).
            packages = f"g++-{version}" if compiler == "gcc" else (
                f"clang-{version} libstdc++-{floor.get('gcc', '14')}-dev")
            install = cell.get("install") or (
                f"sudo apt-get update && sudo apt-get install -y {packages}")
            cells.append({"name": f"{compiler}-{version}", "os": cell["os"], "cc": cc, "cxx": cxx,
                          "install": install, "linux": True})
        else:
            cells.append({"name": "msvc", "os": cell["os"], "cc": "cl", "cxx": "cl",
                          "install": "", "linux": False})
    if not cells:
        raise SetupError("cpp.repo.ci.matrix is empty")
    return cells


def linux_cell(cells: list[dict]) -> dict:
    """The cell lint and sanitizers run on: the first Clang one, else the first GCC one."""
    linux = [cell for cell in cells if cell["linux"]]
    if not linux:
        raise SetupError("CI matrix needs at least one gcc or clang cell: lint and sanitizers run on it")
    return next((cell for cell in linux if cell["name"].startswith("clang")), linux[0])


def ci_job_names(settings: Settings) -> list[str]:
    cells = matrix_cells(settings)
    names = ["lint"] + [f"test ({cell['name']})" for cell in cells]
    if settings.sanitizer_variants():
        names.append("sanitizers")
    return names


def _setup_steps(cell: dict, precommit: bool, extra_apt: str = "") -> list[str]:
    pip = "pip install ninja pre-commit" if precommit else "pip install ninja"
    install = cell["install"] + (f" && sudo apt-get install -y {extra_apt}" if extra_apt else "")
    lines = [
        "      - uses: actions/checkout@v4",
        "      - uses: actions/setup-python@v5",
        "        with:",
        "          python-version: '3.12'",
        f"      - run: {pip}",
        "      - name: Install toolchain",
        f"        run: {install}",
    ]
    if precommit:
        lines += [
            "      - uses: actions/cache@v4",
            "        with:",
            "          path: ~/.cache/pre-commit",
            "          key: pre-commit-${{ runner.os }}-${{ hashFiles('.pre-commit-config.yaml') }}",
        ]
    return lines


def github_ci_body(settings: Settings) -> str:
    cells = matrix_cells(settings)
    tool = linux_cell(cells)
    lines = [
        "name: ci",
        "",
        "on:",
        "  pull_request:",
        "  push:",
        f"    branches: [{settings.release}, {settings.integration}]",
        "",
        "permissions:",
        "  contents: read",
        "",
        "concurrency:",
        "  group: ci-${{ github.ref }}",
        "  cancel-in-progress: true",
        "",
        "jobs:",
        "  lint:",
        "    # The commit-stage hooks: clang-format, clang-tidy, cppcheck, incremental build.",
        "    name: lint",
        f"    runs-on: {tool['os']}",
        "    env:",
        f"      CC: {tool['cc']}",
        f"      CXX: {tool['cxx']}",
        "    steps:",
        *_setup_steps(tool, precommit=True,
                      extra_apt="cppcheck" if settings.repo.get("checks", {}).get("cppcheck", True)
                      else ""),
        "      - run: cmake --preset debug",
        "      - run: pre-commit run --all-files --show-diff-on-failure",
        "",
        "  test:",
        "    # Build and run the tests on every compiler, each pinned at or above the floor.",
        "    name: test (${{ matrix.name }})",
        "    runs-on: ${{ matrix.os }}",
        "    strategy:",
        "      fail-fast: false",
        "      matrix:",
        "        include:",
    ]
    for cell in cells:
        lines += [
            f"          - name: {cell['name']}",
            f"            os: {cell['os']}",
            f"            cc: {cell['cc']}",
            f"            cxx: {cell['cxx']}",
            f"            install: {json.dumps(cell['install'] or 'echo using the runner MSVC')}",
        ]
    lines += [
        "    env:",
        "      CC: ${{ matrix.cc }}",
        "      CXX: ${{ matrix.cxx }}",
        "    steps:",
        "      - uses: actions/checkout@v4",
        "      - uses: actions/setup-python@v5",
        "        with:",
        "          python-version: '3.12'",
        "      - run: pip install ninja",
        "      - name: Install compiler",
        "        if: runner.os == 'Linux'",
        "        run: ${{ matrix.install }}",
        "      - name: MSVC developer environment",
        "        if: runner.os == 'Windows'",
        "        uses: ilammy/msvc-dev-cmd@v1",
        "      - run: cmake --preset debug",
        "      - run: cmake --build --preset debug",
        "      - run: ctest --preset debug",
    ]
    variants = settings.sanitizer_variants()
    if variants:
        lines += [
            "",
            "  sanitizers:",
            f"    # The push-stage hook: every test under {', '.join(variants)}.",
            "    name: sanitizers",
            f"    runs-on: {tool['os']}",
            "    env:",
            f"      CC: {tool['cc']}",
            f"      CXX: {tool['cxx']}",
            "    steps:",
            *_setup_steps(tool, precommit=True),
            "      - run: pre-commit run --all-files --hook-stage pre-push",
        ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- generated files


def generated_specs(settings: Settings, forge: dict) -> dict[str, dict]:
    specs = {PRECOMMIT: {"body": precommit_body(settings), "source": "wf_cpp_repo.py precommit"}}
    if forge["forge"] == "github":
        specs[".github/workflows/ci.yml"] = {"body": github_ci_body(settings),
                                             "source": "wf_cpp_repo.py github-ci"}
    return specs


def header(settings: Settings, spec: dict) -> str:
    # No timestamp: regenerating with no changes must produce no diff.
    return "\n".join([
        "# " + "=" * 74,
        "#  GENERATED FILE - do not edit by hand.",
        "#  Edit this project's .claude/workflows.json (cpp.repo, git), then run",
        "#  /core:setup-cpp-repo (wf_cpp_repo.py generate --apply) to regenerate.",
        "# " + "=" * 74,
        f"# wf-template:         cpp-repo/{settings.template_version}",
        f"# wf-source:           {spec['source']}",
        f"# wf-config-sha256:    {settings.config_hash()}",
        f"# wf-generated-sha256: {sha(spec['body'].encode())}",
    ])


def full_text(settings: Settings, spec: dict) -> str:
    return header(settings, spec) + "\n" + spec["body"]


def drift(settings: Settings, rel: str, spec: dict) -> list[str]:
    """Empty when clean. Otherwise the kinds of drift, most actionable first."""
    path = settings.root / rel
    if not path.exists():
        return ["missing"]
    head, body = split_header(path.read_text(encoding="utf-8"))
    stamp = stamps(head)
    if "wf-generated-sha256" not in stamp:
        return ["not generated (no provenance header)"]
    kinds = []
    if sha(body.encode()) != stamp["wf-generated-sha256"]:
        kinds.append("hand-edited since generation")
    if stamp.get("wf-template") != f"cpp-repo/{settings.template_version}":
        kinds.append(f"template moved on ({stamp.get('wf-template')} -> cpp-repo/{settings.template_version})")
    if stamp.get("wf-config-sha256") != settings.config_hash():
        kinds.append("config changed, never regenerated")
    if not kinds and body != spec["body"]:
        kinds.append("generator changed; regenerate")
    return kinds


# --------------------------------------------------------------------------- commands


def unified(rel: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))


def forge_note(forge: dict) -> str:
    if forge["forge"] == "github":
        return f"forge: github ({forge['slug']})"
    return f"forge: {forge['forge']} ({forge['reason']}); no CI file is generated"


def cmd_scaffold(args: argparse.Namespace) -> int:
    settings = load(args.project)
    actions = scaffold_actions(settings, args.name)
    for item in actions:
        rel, action = item["path"], item["action"]
        target = settings.root / rel
        if action == "keep":
            print(f"keep    {rel} (exists; the repo owns it)")
            continue
        print(f"{action:<7} {rel}")
        if action in ("append", "merge"):
            print(unified(rel, target.read_text(encoding="utf-8"), item["content"]), end="")
        if args.apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item["content"], encoding="utf-8", newline="\n")
    if not args.apply:
        print("\n(dry run; pass --apply to write)")
    return OK


def cmd_generate(args: argparse.Namespace) -> int:
    settings = load(args.project)
    forge = detect_forge(settings)
    print(forge_note(forge))
    changed = False
    for rel, spec in generated_specs(settings, forge).items():
        path = settings.root / rel
        new = full_text(settings, spec)
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        if old == new:
            print(f"unchanged {rel}")
            continue
        changed = True
        kinds = drift(settings, rel, spec)
        if "hand-edited since generation" in kinds and not args.force:
            print(f"refusing {rel}: hand-edited since generation. Fold the edit into "
                  ".claude/workflows.json, or pass --force to discard it.", file=sys.stderr)
            print(unified(rel, old, new), end="")
            return DRIFT
        print(unified(rel, old, new), end="")
        if args.apply:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new, encoding="utf-8", newline="\n")
            print(f"wrote {rel}")
    if changed and not args.apply:
        print("\n(dry run; pass --apply to write)")
    return OK


def cmd_check(args: argparse.Namespace) -> int:
    settings = load(args.project)
    forge = detect_forge(settings)
    report = {rel: drift(settings, rel, spec) for rel, spec in generated_specs(settings, forge).items()}
    if args.json:
        print(json.dumps({"forge": forge, "files": report}, indent=2))
    else:
        print(forge_note(forge))
        for rel, kinds in report.items():
            print(f"{rel}: {'; '.join(kinds) if kinds else 'clean'}")
    return DRIFT if any(report.values()) else OK


def cmd_status(args: argparse.Namespace) -> int:
    settings = load(args.project)
    forge = detect_forge(settings)
    actions = scaffold_actions(settings, args.name)
    generated = {rel: drift(settings, rel, spec) for rel, spec in generated_specs(settings, forge).items()}
    status = {
        "root": str(settings.root),
        "cppEnabled": bool(settings.cpp.get("enabled")),
        "forge": forge,
        "scaffold": {item["path"]: item["action"] for item in actions},
        "generated": generated,
        "sanitizers": settings.sanitizer_variants(),
        "ciJobs": ci_job_names(settings) if forge["forge"] == "github" else [],
    }
    if args.json:
        print(json.dumps(status, indent=2))
        return OK
    print(f"root: {status['root']}  cpp.enabled: {status['cppEnabled']}")
    print(forge_note(forge))
    for rel, action in status["scaffold"].items():
        print(f"  scaffold  {action:<7} {rel}")
    for rel, kinds in generated.items():
        print(f"  generated {rel}: {'; '.join(kinds) if kinds else 'clean'}")
    print(f"sanitizer variants: {', '.join(status['sanitizers']) or 'none'}")
    if status["ciJobs"]:
        print(f"CI jobs: {', '.join(status['ciJobs'])}")
    return OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", help="repo root (default: the current git repo)")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="what scaffold and generate would do, and drift")
    status.add_argument("--name", help="CMake project name (default: the repo directory name)")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    scaffold = sub.add_parser("scaffold", help="write the one-shot files that do not exist yet")
    scaffold.add_argument("--name", help="CMake project name (default: the repo directory name)")
    scaffold.add_argument("--apply", action="store_true")
    scaffold.set_defaults(func=cmd_scaffold)

    generate = sub.add_parser("generate", help="regenerate .pre-commit-config.yaml and the CI file")
    generate.add_argument("--apply", action="store_true")
    generate.add_argument("--force", action="store_true", help="overwrite a hand-edited file")
    generate.set_defaults(func=cmd_generate)

    check = sub.add_parser("check", help="report drift in the generated files; exit 1 on drift")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (SetupError, wf_config.ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
