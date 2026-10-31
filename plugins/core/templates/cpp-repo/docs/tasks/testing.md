---
aliases: [testing, tests, ctest, sanitizers, asan, tsan, quality gates, pre-commit, pre-push, ci]
sources: [.pre-commit-config.yaml, scripts/check_build.py, scripts/run_sanitizers.py, cmake/ProjectSettings.cmake]
---

# Testing

How to run the tests, which automated checks run when, and where each one runs.

## Run

```bash
cmake --preset debug                    # once per clone; clang-tidy and cppcheck need its compile_commands.json
cmake --build --preset debug
ctest --preset debug                    # every discovered test
python scripts/run_sanitizers.py        # what the pre-push hook runs
```

On Windows, run these from a Developer PowerShell for Visual Studio, so Ninja finds `cl.exe`.

Add a test binary with `add_project_test(<name> <sources...>)` in a `CMakeLists.txt`. It links
GoogleTest, the shared options and warnings, registers every `TEST` with ctest, and joins the
`project_tests` target the sanitizer run builds.

## The checks

What runs today. This list is the floor, not a limit: adding a check needs no permission, removing
or weakening one needs the owner (AGENTS.md).

- **Every commit** (`.pre-commit-config.yaml`, default stage): clang-format, clang-tidy, cppcheck
  when enabled, and `scripts/check_build.py`, an incremental `cmake --build build/debug`. The build
  is there because clang-tidy catches most compile errors in changed files but not a link error or
  a break in a file the commit did not touch. Kept fast: one build directory, no tests.
- **Every push** (pre-push stage): `scripts/run_sanitizers.py`, every test binary under each
  sanitizer variant the config lists, each in its own preset and build directory (ThreadSanitizer
  cannot share a binary with AddressSanitizer). UBSan is built with `-fno-sanitize-recover`, so
  undefined behaviour fails the test instead of printing and passing.
- **Every PR and push to a protected branch** (CI): the same two hook stages on Linux, plus build and
  test on every compiler in the CI matrix. The compilers are pinned at or above the project's floor
  (`cmake/ProjectSettings.cmake` refuses anything older), not left to the runner's default.

Install both hook stages once per clone; a fresh clone has neither:

```bash
pre-commit install
pre-commit install --hook-type pre-push
```

A local hook is advisory: it runs only where installed, and `--no-verify` skips it. The CI checks
that branch protection requires are the real gate.

clang-format and clang-tidy are pinned in `.pre-commit-config.yaml` and installed by pre-commit
from PyPI, so every machine and CI run uses the same binaries regardless of what the system has.
cppcheck is a system tool (`apt install cppcheck`, `winget install cppcheck`).

## Sanitizers per platform

| Variant | Linux (GCC, Clang) | Windows (MSVC) |
|---|---|---|
| `asan-ubsan` (preset `asan`) | ASan + UBSan | ASan only; MSVC has no UBSan |
| `tsan` (preset `tsan`) | TSan | skipped; MSVC has no TSan |

## Memory cap

When `ENABLE_TEST_MEMORY_CAP` is ON, every discovered test runs through
`scripts/with_memory_cap.py`, in its own systemd scope with `MemoryMax=4G` and swap off, so a test
that allocates without bound fails on its own instead of getting the whole terminal session
OOM-killed. `TEST_MEMORY_MAX=2G` changes the cap, `0` turns it off. Without a systemd user session
the test runs uncapped and the launcher says so once. A test killed by the cap fails with exit 137
and no gtest output.
