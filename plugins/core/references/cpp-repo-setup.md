# C++ repo setup: decisions and why

What `/core:setup-cpp-repo` installs, the choices behind it, and what each rejected. Read before
changing the templates in `templates/cpp-repo/` or the generator in `scripts/wf_cpp_repo.py`.

## Ownership: scaffold once vs regenerate

| Kind | Files | Why |
|---|---|---|
| Scaffolded once | CMake skeleton, presets, smoke test, check scripts, docs/tasks pages, AGENTS.md sections, the CI workflow | This is where repos legitimately diverge: targets, dependencies, extra options, project-specific test notes, CI caching and platform-specific test selection. Config cannot express that, and regenerating would fight it. |
| Generated + drift check | `.pre-commit-config.yaml` | Pure policy: which hooks run at which stage, at which tool versions. Repos that differ here differ by a setting, so a setting is what they get. Silent drift across repos is the failure mode this prevents. |

Rejected: everything scaffolded (defaults drift silently), everything generated (CMake becomes
unworkable as soon as a repo has its first real target).

**The CI file was generated at first and is now scaffolded.** A generator can only expose a fixed set
of knobs (matrix, packages, env, a test wrapper), so every repo-specific CI need (a cache, a lint
scope, a test label skipped on Windows) needed a plugin change before the repo could have it.
clang-format and clang-tidy can take arbitrary overrides through config; a workflow cannot, so the
repo owns it. What drift detection protected is now kept by semantic checks instead: `check` warns
when the CI never runs a hook stage, uses a compiler below the floor, or lost its Windows job.

Generated files follow AGENTS.md best practice #4: provenance header, hashes, no timestamp. The
three drift kinds and their remedies mirror `sync-lint-rules` (`cpp-lint-rationale.md`).

The memory-cap and compiler-floor values are baked into `cmake/ProjectSettings.cmake` at scaffold
time. Changing them in config later does not touch the scaffolded file; edit the CMake.

## Forge-neutral core, forge adapters at the edge

Nothing in the core assumes a git host. CMake, the Python scripts, the pre-commit config and the
branch-model docs work the same on GitHub, GitLab, Bitbucket or a bare remote.

Two things are forge-specific, and both go through an adapter:

- **CI file.** Kept a thin wrapper: install a toolchain, then call `cmake`/`ctest` or
  `pre-commit run`. All logic lives in the repo's scripts, which is what makes another adapter
  cheap and keeps CI and local hooks from disagreeing.
- **Branch protection.** `git.protection` is a neutral policy: one `default` applied to the
  release and integration branches by their configured names, plus per-branch overrides in
  `branches` (`requirePR`, `approvals`,
  `requiredChecks`, `allowForcePush`, `allowDeletion`, `linearHistory`, `enforceAdmins`); the
  adapter translates it into that forge's API. One repo-wide key sits beside them:
  `squashMessage` (`"pr"` by default) makes a squash merge default to the PR's title and
  description instead of the branch's commit messages, so per-commit trailers like `Plan-Id` and
  `Task-Id` stay on the feature branch and never reach the integration branch.

Only GitHub has an adapter. Others would be one function pair each (CI body, protection payload),
added once there is a live repo to test them against. Until then they get a printed checklist and no
CI file, rather than an untested one.

Forge writes are confirmed per branch, per session: they change shared state outside the working
tree, and a protection mistake (a required check that never runs) blocks every PR.

## Checks and where they run

| Stage | Runs | Why there |
|---|---|---|
| commit | clang-format, clang-tidy, cppcheck, incremental build | Fast. The build catches link errors and breaks in files the commit did not touch, which clang-tidy does not. |
| push | tests under each sanitizer variant | Slow; catches use-after-free and data races, the bugs that otherwise go unnoticed. |
| CI | both stages on Linux; build+test on every matrix compiler | The only gate that cannot be skipped with `--no-verify`. The lint job skips the `build` hook (`SKIP=build`) because the test job builds the same preset. |

Lint and sanitizers run once, on Linux. Lint output does not depend on the OS, and MSVC has only
ASan, so repeating either on every matrix cell would add CI time and no signal.

Defaults: cppcheck on; TSan off (doubles push time, pointless for single-threaded code); memory cap
off (it needs a Linux systemd user session; elsewhere it is a no-op).

## Cross-platform choices

- **Check scripts are Python, hooks are `language: python`.** Bash hooks need Git Bash on Windows.
  A `language: system` hook calling `python3` fails on a python.org Windows install, which has no
  `python3.exe`. With `language: python`, pre-commit's own venv puts `python` first on PATH everywhere.
- **clang-format and clang-tidy come from PyPI wheels**, pinned in the generated config
  (`mirrors-clang-format`, and a `language: python` clang-tidy hook with `additional_dependencies`).
  Every machine and CI job runs the same binary; system clang-tidy differs per distro and is absent
  on Windows. cppcheck has no wheel and stays a system tool.
- **clang-tidy gets `--extra-arg=-Wno-unknown-warning-option`**, so a `build/debug` configured with
  GCC does not make it fail on GCC-only warning flags.
- **Module scanning is off** (`CMAKE_CXX_SCAN_FOR_MODULES OFF`). With CMake 3.28+ and GCC it writes
  `-fdeps-format`/`-fmodules-ts` into `compile_commands.json`, which clang-tidy rejects. A repo
  that adopts modules turns it back on and deals with that.
- **MSVC warnings mirror the GCC/Clang set**: `/W4 /WX` plus the off-by-default conversion,
  sign-conversion, hidden-virtual and non-virtual-destructor warnings, with `/external:W0` for
  system headers.
- **Sanitizers are global compile options, not an interface target.** An uninstrumented dependency
  hides bugs from ASan and TSan, and MSVC refuses to link ASan objects against uninstrumented STL
  users (`LNK2038`, annotate_vector mismatch). On MSVC: ASan only, `/RTC` stripped (incompatible),
  `ENABLE_UBSAN` ignored with a warning, `ENABLE_TSAN` an error. UBSan uses
  `-fno-sanitize-recover`, so UB fails the test instead of printing and passing.
- **Windows CI uses Ninja + `ilammy/msvc-dev-cmd`**, so it builds with the same presets as Linux
  and produces the same `compile_commands.json`. `CXX=cl` is set explicitly, because CMake would
  otherwise find the runner's MinGW `g++` first.

## The reference CI workflow

What `scaffold` writes, and what the skill's CI rules ask a hand-edited file to keep:

- lint job: commit-stage hooks, on a PR's changed files only (`--from-ref origin/<base> --to-ref
  HEAD`, checkout `fetch-depth: 0`), on every file for pushes to the protected branches;
- test job: every matrix compiler, Linux and Windows, ccache on Linux;
- sanitizer job: the push-stage hook;
- apt packages cached by `awalsh128/cache-apt-pkgs-action` (keyed on the package list plus a
  `version` string to bump), the pre-commit environments by `actions/cache`.

`cpp.repo.ci.aptPackages`, `pipPackages`, `env` and `testWrapper` shape only the first scaffold
(e.g. GUI/GL dev packages, `xvfb-run -a` for tests that need a display). After that, edit the file.
The local pre-push hook does not use the wrapper; a developer machine has a display.

## cppcheck is pinned by building it

clang-format and clang-tidy come from PyPI wheels, so every machine runs the same version. cppcheck
has no such wheel (the PyPI package named `cppcheck` is an unrelated project), and distribution
versions differ (Ubuntu 24.04 ships 2.13, 26.04 ships 2.19) and disagree on findings. Suppressing
CI-only false positives was rejected: it hides real differences and leaves suppressions to clean up.

So the pin is `cpp.repo.tools.cppcheck`. The reference CI builds that tag from source in the lint
job (cmake + Ninja, `-DUSE_MATCHCOMPILER=ON`, `FILESDIR` under the install prefix so it finds its
`.cfg` libraries) and caches the install keyed on the version, so the build runs once per version.
Locally the hook still runs the system cppcheck; a generated `cppcheck-version` hook prints a
warning (it never fails) when that differs from the pin. Bump the pin together with the local
version.

## Compiler floor

Enforced twice: `cmake/ProjectSettings.cmake` fails configuration below the floor (Visual Studio
`17.8` maps to `MSVC_VERSION` 1938), and `generate` refuses a CI matrix cell below it. CI installs
the pinned compiler rather than taking the runner default; for Clang on Linux it also installs the
libstdc++ of the GCC floor, because Clang uses the system libstdc++ and an older one lacks newer
headers (`<print>` arrived in libstdc++ 14). The default Clang floor is 19, not 18: libstdc++ 14 declares `std::expected`
only when `__cpp_concepts >= 202002L`, which Clang 18 does not report (201907L), so a C++23 repo
using `std::expected` fails to build with Clang 18 on libstdc++. A cell whose compiler is not in the runner's apt
archive sets its own `install` command.

## Test targets

`add_project_test()` records each target in a global property, and a deferred call creates
`project_tests` depending on all of them. The sanitizer script builds only that target. Rejected:
grepping `CMakeLists.txt` for `add_project_test(` calls, which misses subdirectories and once left a
stale test binary running.

## Branch model and protection defaults

`feature/<slug>` → PR into the integration branch (`dev`), squash-merged by the owner; release =
integration → release branch (`main`) as a merge commit, then tag `vX.Y.Z` there. Defaults for both
protected branches: PR required, required checks = every CI check that reported on the branch
(the repo owns its CI, so its job names are read from a run, not predicted), no force push, no
deletion, admins included, **0 approvals** (the owner's own PRs could never merge otherwise; "the
owner reviews" is an AGENTS.md rule, not a forge setting), and **no linear history** (it would
reject the release merge commit).

## implement-plan and /simplify

A green `implement-plan` run runs `/simplify` over the branch before pushing
(`implement.simplifyBeforePush`). Rejected: a Claude hook blocking `git push` until simplify ran,
which would fire in interactive sessions too and is a hook mutating the workflow (best practice #5).
