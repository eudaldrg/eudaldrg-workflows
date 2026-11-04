#!/usr/bin/env python3
"""Set up a C++ repo: scaffold its build and docs once, generate its hooks and CI, report drift.

Two kinds of output, on purpose (references/cpp-repo-setup.md):

- scaffolded once, owned by the repo afterwards: CMake skeleton, presets, smoke test, check
  scripts, docs/tasks pages, the AGENTS.md section. Never overwritten.
- generated and kept in sync: .pre-commit-config.yaml. It carries a provenance header (template
  version, config hash, body hash; no timestamp) for drift detection.

The CI file is forge-specific: scaffolded once (a reference workflow the repo then owns and edits)
and checked semantically, never for byte drift. The forge comes from the origin URL or `git.forge`;
only GitHub has an adapter, any other forge gets no CI file and a printed checklist. Branch
protection is not C++-specific and lives in wf_protect.py; `protect` here is the same command.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf_config  # noqa: E402
import wf_protect  # noqa: E402
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
        return str(self.git["integrationBranch"])

    @property
    def release(self) -> str:
        return str(self.git["releaseBranch"])

    def sanitizer_variants(self) -> list[str]:
        enabled = self.repo["checks"]["sanitizers"]
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


parse_remote = wf_protect.parse_remote


def detect_forge(settings: Settings, url: str | None = None) -> dict:
    """{'forge': 'github'|'none'|'unsupported', 'host', 'slug', 'reason'}."""
    return wf_protect.detect_forge(settings.git, settings.root, url)


# --------------------------------------------------------------------------- scaffold


def project_name(settings: Settings, explicit: str | None) -> str:
    name = explicit or settings.root.name
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return name if re.match(r"^[A-Za-z_]", name) else f"_{name}"


def values(settings: Settings, name: str | None) -> dict[str, str]:
    repo = settings.repo
    floor = repo["compilerFloor"]
    return {
        "project_name": project_name(settings, name),
        "cxx_standard": str(repo["cxxStandard"]),
        "gcc_floor": str(floor["gcc"]),
        "clang_floor": str(floor["clang"]),
        "msvc_floor": str(floor["msvc"]),
        "msvc_floor_version": str(msvc_version(str(floor["msvc"]))),
        "googletest_tag": str(repo["tools"]["googletest"]),
        "memory_cap_default": "ON" if repo["checks"]["memoryCap"] else "OFF",
        "integration_branch": settings.integration,
        "release_branch": settings.release,
        "branch_prefix": str(settings.git["branchPrefix"]),
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
    if "protectedBranches" not in git and settings.integration not in git.get("protectedBranches+", []):
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
    elif AGENTS_HEADING not in (current := agents.read_text(encoding="utf-8")):
        actions.append({"path": "AGENTS.md", "action": "append",
                        "content": current.rstrip("\n") + "\n\n" + section})
    else:
        actions.append({"path": "AGENTS.md", "action": "keep"})

    if detect_forge(settings)["forge"] == "github":
        exists = (settings.root / CI_FILE).exists()
        actions.append({"path": CI_FILE, "action": "keep" if exists else "write",
                        "content": None if exists else github_ci_body(settings)})

    gitignore = settings.root / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    if not any(line.strip().strip("/") == "build" for line in lines):
        actions.append({"path": ".gitignore", "action": "append" if lines else "write",
                        "content": "\n".join([*lines, "build/"]) + "\n"})

    existing = wf_config.read_layer(wf_config.layer_paths(str(settings.root))["project"])
    additions = project_config_additions(settings, existing)
    if additions:
        merged = copy.deepcopy(existing)
        for key, sub in additions.items():
            merged.setdefault(key, {}).update(sub)
        actions.append({"path": ".claude/workflows.json",
                        "action": "merge" if existing else "write",
                        "content": json.dumps(merged, indent=2) + "\n"})
    return actions


# --------------------------------------------------------------------------- generate: pre-commit


def precommit_body(settings: Settings) -> str:
    tools = settings.repo["tools"]
    checks = settings.repo["checks"]
    lines = [
        "default_stages: [pre-commit]",
        "# Install both stages once per clone:",
        "#   pre-commit install && pre-commit install --hook-type pre-push",
        "# clang-tidy and cppcheck read build/debug/compile_commands.json: run `cmake --preset debug`",
        "# once first. docs/tasks/testing.md has what each hook is for.",
        "repos:",
        "  - repo: https://github.com/pre-commit/mirrors-clang-format",
        f"    rev: v{tools['clangFormat']}",
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
        f"        additional_dependencies: ['clang-tidy=={tools['clangTidy']}']",
        "        types_or: [c++, c]",
    ]
    if checks["cppcheck"]:
        pin = tools["cppcheck"]
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
            "",
            "      - id: cppcheck-version",
            f"        name: cppcheck is the pinned {pin} (warns only)",
            "        # CI builds exactly this version; a different local one can disagree on findings.",
            "        entry: >-",
            "          python -c 'import subprocess;"
            ' out = subprocess.run(["cppcheck", "--version"], capture_output=True, text=True).stdout.split();'
            ' found = out[-1] if out else "none";'
            f' found == "{pin}" or print("warning: cppcheck " + found + " here, but CI pins {pin}:'
            f' findings can differ. Install {pin}, or bump cpp.repo.tools.cppcheck.")\'',
            "        language: python",
            "        pass_filenames: false",
            "        always_run: true",
            "        verbose: true",
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
    floor = settings.repo["compilerFloor"]
    cells = []
    for cell in settings.repo["ci"]["matrix"]:
        compiler = cell["compiler"]
        version = str(cell.get("version", ""))
        if compiler in ("gcc", "clang"):
            if version_tuple(version) < version_tuple(floor[compiler]):
                raise SetupError(
                    f"CI matrix: {compiler} {version} is below the floor "
                    f"({compiler} {floor[compiler]}, cpp.repo.compilerFloor)"
                )
            cc, cxx = (f"gcc-{version}", f"g++-{version}") if compiler == "gcc" else (
                f"clang-{version}", f"clang++-{version}")
            # Clang on Linux uses the system libstdc++; take the one from the GCC floor, since the
            # runner's default may predate it (no <print> before libstdc++ 14).
            packages = cell.get("packages") or (f"g++-{version}" if compiler == "gcc" else
                                                f"clang-{version} libstdc++-{floor['gcc']}-dev")
            cells.append({"name": f"{compiler}-{version}", "compiler": compiler, "os": cell["os"],
                          "cc": cc, "cxx": cxx, "packages": packages})
        else:
            cells.append({"name": "msvc", "compiler": compiler, "os": cell["os"], "cc": "cl",
                          "cxx": "cl", "packages": ""})
    if not cells:
        raise SetupError("cpp.repo.ci.matrix is empty")
    return cells


def linux_cell(cells: list[dict]) -> dict:
    """The cell lint and sanitizers run on: the first Clang one, else the first GCC one."""
    linux = [cell for cell in cells if cell["compiler"] != "msvc"]
    if not linux:
        raise SetupError("CI matrix needs at least one gcc or clang cell: lint and sanitizers run on it")
    return next((cell for cell in linux if cell["compiler"] == "clang"), linux[0])


CI_FILE = ".github/workflows/ci.yml"
APT_CACHE = "awalsh128/cache-apt-pkgs-action@v1.6.3"
CCACHE = "hendrikmuhs/ccache-action@v1.2.24"
CHECKOUT_AND_PYTHON = [
    "      - uses: actions/checkout@v4",
    "      - uses: actions/setup-python@v5",
    "        with:",
    "          python-version: '3.12'",
]
PRECOMMIT_CACHE = [
    "      - uses: actions/cache@v4",
    "        with:",
    "          path: ~/.cache/pre-commit",
    "          key: pre-commit-${{ runner.os }}-${{ hashFiles('.pre-commit-config.yaml') }}",
]


# The distribution's cppcheck differs by release (Ubuntu 24.04 has 2.13), and versions disagree on
# findings, so lint builds the pinned version (cpp.repo.tools.cppcheck) once and caches it.
CPPCHECK_STEPS = [
    "      - uses: actions/cache@v4",
    "        id: cppcheck",
    "        with:",
    "          path: ~/cppcheck",
    "          key: cppcheck-${{ env.CPPCHECK_VERSION }}-${{ runner.os }}",
    "      - name: Build cppcheck ${{ env.CPPCHECK_VERSION }}",
    "        if: steps.cppcheck.outputs.cache-hit != 'true'",
    "        run: |",
    '          curl -sSL "https://github.com/danmar/cppcheck/archive/refs/tags/${CPPCHECK_VERSION}.tar.gz"'
    ' | tar xz -C "$RUNNER_TEMP"',
    '          cmake -S "$RUNNER_TEMP/cppcheck-${CPPCHECK_VERSION}" -B "$RUNNER_TEMP/cppcheck-build" -G Ninja \\',
    '            -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$HOME/cppcheck" \\',
    '            -DFILESDIR="$HOME/cppcheck/share/cppcheck" -DUSE_MATCHCOMPILER=ON',
    '          cmake --build "$RUNNER_TEMP/cppcheck-build"',
    '          cmake --install "$RUNNER_TEMP/cppcheck-build"',
    '      - run: echo "$HOME/cppcheck/bin" >> "$GITHUB_PATH"',
]


def env_lines(env: dict[str, str], indent: str = "    ") -> list[str]:
    return [f"{indent}env:", *(f"{indent}  {key}: {value}" for key, value in env.items())]


def ci_extras(settings: Settings) -> tuple[str, str, dict[str, str], str]:
    """cpp.repo.ci scaffold inputs: (apt suffix, pip suffix, env with values quoted, testWrapper)."""
    ci = settings.repo["ci"]
    apt = " ${{ env.APT_PACKAGES }}" if ci["aptPackages"] else ""
    pip = "".join(f" {package}" for package in ci["pipPackages"])
    env = {key: json.dumps(str(value)) for key, value in ci["env"].items()}
    if ci["aptPackages"]:
        env["APT_PACKAGES"] = " ".join(ci["aptPackages"])
    wrapper = ci["testWrapper"].strip()
    return apt, pip, env, (wrapper + " ") if wrapper else ""


def apt_step(packages: str, version: str, indent_if: str = "") -> list[str]:
    head = [f"      - if: {indent_if}", f"        uses: {APT_CACHE}"] if indent_if else [
        f"      - uses: {APT_CACHE}"]
    return [*head, "        with:", f"          packages: {packages}", f"          version: {version}"]


def ccache_step(key: str, indent_if: str = "") -> list[str]:
    head = [f"      - if: {indent_if}", f"        uses: {CCACHE}"] if indent_if else [
        f"      - uses: {CCACHE}"]
    return [*head, "        with:", f"          key: {key}"]


def github_ci_body(settings: Settings) -> str:
    """The reference workflow: what `scaffold` writes once. The repo owns and edits it after."""
    cells = matrix_cells(settings)
    tool = linux_cell(cells)
    apt, pip, env, wrapper = ci_extras(settings)
    cppcheck = settings.repo["checks"]["cppcheck"]
    lines = [
        "# CI: the commit-stage hooks (lint), the push-stage hook (sanitizers), and a build and test on",
        "# every compiler in the matrix, each pinned at or above the floor in cmake/ProjectSettings.cmake.",
        "# Scaffolded once by /core:setup-cpp-repo; this repo owns the file. Keep both hook stages and",
        "# the floor; `wf_cpp_repo.py check` warns when they go missing.",
        "#",
        "# Speed: apt packages are cached by cache-apt-pkgs-action (bump `version` to refresh) and",
        "# objects by ccache. On pull requests lint checks only the changed files; pushes to the",
        "# protected branches check every file.",
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
    ]
    if cppcheck:
        env = {**env, "CPPCHECK_VERSION": settings.repo["tools"]["cppcheck"]}
    if env:
        lines += [*env_lines(env, indent=""), ""]
    lines += [
        "jobs:",
        "  lint:",
        "    # The commit-stage hooks. `build` is skipped: the test job builds the same preset.",
        "    name: lint",
        f"    runs-on: {tool['os']}",
        *env_lines({"CC": tool["cc"], "CXX": tool["cxx"], "SKIP": "build"}),
        "    steps:",
        "      - uses: actions/checkout@v4",
        "        with:",
        "          fetch-depth: 0  # the PR's base, to diff against",
        *CHECKOUT_AND_PYTHON[1:],
        f"      - run: pip install ninja pre-commit{pip}",
        *apt_step(f"{tool['packages']}{apt}", "lint-1"),
        *(CPPCHECK_STEPS if cppcheck else []),
        *PRECOMMIT_CACHE,
        "      - run: cmake --preset debug",
        "      - name: Hooks on the changed files",
        "        if: github.event_name == 'pull_request'",
        "        run: >-",
        "          pre-commit run --show-diff-on-failure",
        "          --from-ref origin/${{ github.base_ref }} --to-ref HEAD",
        "      - name: Hooks on every file",
        "        if: github.event_name != 'pull_request'",
        "        run: pre-commit run --all-files --show-diff-on-failure",
        "",
        "  test:",
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
        ]
        if cell["packages"]:
            lines.append(f"            packages: {cell['packages']}")
    lines += [
        *env_lines({"CC": "${{ matrix.cc }}", "CXX": "${{ matrix.cxx }}"}),
        "    steps:",
        *CHECKOUT_AND_PYTHON,
        f"      - run: pip install ninja{pip}",
        *apt_step(f"${{{{ matrix.packages }}}}{apt}", "test-${{ matrix.name }}-1", "runner.os == 'Linux'"),
        *ccache_step("test-${{ matrix.name }}", "runner.os == 'Linux'"),
        "      - if: runner.os == 'Windows'",
        "        uses: ilammy/msvc-dev-cmd@v1",
        "      - if: runner.os == 'Linux'",
        "        run: >-",
        "          cmake --preset debug",
        "          -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
        "      - if: runner.os == 'Windows'",
        "        run: cmake --preset debug",
        "      - run: cmake --build --preset debug",
    ]
    if wrapper:
        lines += [
            "      - if: runner.os == 'Linux'",
            f"        run: {wrapper}ctest --preset debug",
            "      - if: runner.os != 'Linux'",
            "        run: ctest --preset debug",
        ]
    else:
        lines.append("      - run: ctest --preset debug")
    variants = settings.sanitizer_variants()
    if variants:
        lines += [
            "",
            "  sanitizers:",
            f"    # The push-stage hook: every test under {', '.join(variants)}.",
            "    name: sanitizers",
            f"    runs-on: {tool['os']}",
            *env_lines({"CC": tool["cc"], "CXX": tool["cxx"],
                        "CMAKE_C_COMPILER_LAUNCHER": "ccache", "CMAKE_CXX_COMPILER_LAUNCHER": "ccache"}),
            "    steps:",
            *CHECKOUT_AND_PYTHON,
            f"      - run: pip install ninja pre-commit{pip}",
            *apt_step(f"{tool['packages']}{apt}", "sanitizers-1"),
            *ccache_step("sanitizers"),
            *PRECOMMIT_CACHE,
            f"      - run: {wrapper}pre-commit run --all-files --hook-stage pre-push",
        ]
    return "\n".join(lines) + "\n"


COMPILER_REF = re.compile(r"\b(g\+\+|gcc|clang\+\+|clang)-(\d+)\b")


def ci_warnings(settings: Settings, text: str) -> list[str]:
    """Semantic problems in the repo's own CI file. Warnings, not drift: the repo owns the file."""
    warnings = []
    runs = [line for line in text.splitlines() if "pre-commit run" in line]
    if not any("--hook-stage pre-push" not in line for line in runs):
        warnings.append("never runs the commit-stage hooks (`pre-commit run`)")
    if settings.sanitizer_variants() and not any("--hook-stage pre-push" in line for line in runs):
        warnings.append("never runs the push-stage hooks (`pre-commit run --hook-stage pre-push`)")
    floor = settings.repo["compilerFloor"]
    for name, version in sorted(set(COMPILER_REF.findall(text))):
        compiler = "gcc" if name in ("gcc", "g++") else "clang"
        if version_tuple(version) < version_tuple(floor[compiler]):
            warnings.append(f"uses {name}-{version}, below the {compiler} floor {floor[compiler]}")
    pin = settings.repo["tools"]["cppcheck"]
    if settings.repo["checks"]["cppcheck"] and pin not in text:
        warnings.append(f"does not build the pinned cppcheck {pin} (cpp.repo.tools.cppcheck)")
    if any(cell["compiler"] == "msvc" for cell in settings.repo["ci"]["matrix"]) and "windows" not in text:
        warnings.append("has no Windows job, but cpp.repo.ci.matrix lists msvc")
    return warnings


def ci_report(settings: Settings, forge: dict) -> list[str] | None:
    """Warnings for the CI file, or None when there is none to check."""
    path = settings.root / CI_FILE
    if forge["forge"] != "github" or not path.exists():
        return None
    return ci_warnings(settings, path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- generated files


def generated_specs(settings: Settings) -> dict[str, dict]:
    return {PRECOMMIT: {"body": precommit_body(settings), "source": "wf_cpp_repo.py precommit"}}


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


# Drift kinds that mean the file holds someone's own edits: generate refuses them without --force.
USER_OWNED = {"hand_edited", "not_generated"}


def drift(settings: Settings, rel: str, spec: dict, text: str | None = None) -> dict[str, str]:
    """{kind: message}, empty when clean, most actionable first. `text` saves re-reading the file."""
    path = settings.root / rel
    if text is None:
        if not path.exists():
            return {"missing": "missing"}
        text = path.read_text(encoding="utf-8")
    head, body = split_header(text)
    stamp = stamps(head)
    if "wf-generated-sha256" not in stamp:
        return {"not_generated": "not generated (no provenance header)"}
    kinds = {}
    if sha(body.encode()) != stamp["wf-generated-sha256"]:
        kinds["hand_edited"] = "hand-edited since generation"
    current = f"cpp-repo/{settings.template_version}"
    if stamp.get("wf-template") != current:
        kinds["template"] = f"template moved on ({stamp.get('wf-template')} -> {current})"
    if stamp.get("wf-config-sha256") != settings.config_hash():
        kinds["config"] = "config changed, never regenerated"
    if not kinds and body != spec["body"]:
        kinds["generator"] = "generator changed; regenerate"
    return kinds


def describe(kinds: dict[str, str]) -> str:
    return "; ".join(kinds.values()) or "clean"


# --------------------------------------------------------------------------- commands


def unified(rel: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))


def forge_note(forge: dict) -> str:
    if forge["forge"] == "github":
        return f"forge: github ({forge['slug']})"
    return f"forge: {forge['forge']} ({forge['reason']}); no CI file is scaffolded"


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
    for rel, spec in generated_specs(settings).items():
        path = settings.root / rel
        new = full_text(settings, spec)
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        if old == new:
            print(f"unchanged {rel}")
            continue
        changed = True
        kinds = drift(settings, rel, spec, old) if old else {}
        owned = [message for kind, message in kinds.items() if kind in USER_OWNED]
        if owned and not args.force:
            print(f"refusing {rel}: {owned[0]}. Fold what it wants into .claude/workflows.json, "
                  "or pass --force to replace it.", file=sys.stderr)
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
    """Drift in the generated files (exit 1), plus warnings about the repo's own CI file (exit 0)."""
    settings = load(args.project)
    forge = detect_forge(settings)
    report = {rel: drift(settings, rel, spec) for rel, spec in generated_specs(settings).items()}
    ci = ci_report(settings, forge)
    if args.json:
        print(json.dumps({"forge": forge, "files": report, "ciWarnings": ci}, indent=2))
    else:
        print(forge_note(forge))
        for rel, kinds in report.items():
            print(f"{rel}: {describe(kinds)}")
        for warning in ci or []:
            print(f"warning: {CI_FILE} {warning}")
    return DRIFT if any(report.values()) else OK


def cmd_status(args: argparse.Namespace) -> int:
    settings = load(args.project)
    forge = detect_forge(settings)
    actions = scaffold_actions(settings, args.name)
    generated = {rel: drift(settings, rel, spec) for rel, spec in generated_specs(settings).items()}
    status = {
        "root": str(settings.root),
        "cppEnabled": bool(settings.cpp.get("enabled")),
        "forge": forge,
        "scaffold": {item["path"]: item["action"] for item in actions},
        "generated": generated,
        "sanitizers": settings.sanitizer_variants(),
        "ciWarnings": ci_report(settings, forge),
    }
    if args.json:
        print(json.dumps(status, indent=2))
        return OK
    print(f"root: {status['root']}  cpp.enabled: {status['cppEnabled']}")
    print(forge_note(forge))
    for rel, action in status["scaffold"].items():
        print(f"  scaffold  {action:<7} {rel}")
    for rel, kinds in generated.items():
        print(f"  generated {rel}: {describe(kinds)}")
    print(f"sanitizer variants: {', '.join(status['sanitizers']) or 'none'}")
    for warning in status["ciWarnings"] or []:
        print(f"warning: {CI_FILE} {warning}")
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

    protect = sub.add_parser("protect", help="show (default) or apply branch protection on the "
                             "forge; same as wf_protect.py protect")
    wf_protect.add_protect_arguments(protect)
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
