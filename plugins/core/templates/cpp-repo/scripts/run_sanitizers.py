"""Push-time gate: every test binary under each sanitizer configuration this repo uses.

Each variant is its own CMake preset and build directory, because ThreadSanitizer cannot share a
binary with AddressSanitizer. Only the `project_tests` target is built: it depends on every
add_project_test() target, so no test binary can be left stale or unbuilt.

    python scripts/run_sanitizers.py                       # asan-ubsan only
    python scripts/run_sanitizers.py --variant asan-ubsan --variant tsan

The variants come from the generated .pre-commit-config.yaml (cpp.repo.checks.sanitizers in
.claude/workflows.json), so this script needs no config of its own and runs the same in CI.
On Windows (MSVC) only AddressSanitizer exists: asan-ubsan runs ASan alone and tsan is skipped.

Scaffolded by the setup-cpp-repo skill; this repo owns it. docs/tasks/testing.md has the why.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRESETS = {"asan-ubsan": "asan", "tsan": "tsan"}
UNSUPPORTED_ON_WINDOWS = {"tsan"}


def run(cmd: list[str], env: dict[str, str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variant", action="append", choices=sorted(PRESETS),
                        help="sanitizer variant to run; repeatable (default: asan-ubsan)")
    args = parser.parse_args(argv)
    variants = args.variant or ["asan-ubsan"]

    env = dict(os.environ)
    # Fail on the first report and show where it came from.
    if os.name != "nt":  # MSVC's ASan has no LeakSanitizer and no UBSan
        env.setdefault("UBSAN_OPTIONS", "print_stacktrace=1:halt_on_error=1")
        env.setdefault("ASAN_OPTIONS", "detect_leaks=1")
    jobs = str(os.cpu_count() or 2)

    for variant in variants:
        if os.name == "nt" and variant in UNSUPPORTED_ON_WINDOWS:
            print(f"==> {variant}: skipped, MSVC has no ThreadSanitizer (it runs on Linux)")
            continue
        preset = PRESETS[variant]
        print(f"==> {variant}: preset {preset}", flush=True)
        try:
            # Configure once; `cmake --build` reconfigures by itself when CMake inputs change.
            if not (ROOT / "build" / preset / "CMakeCache.txt").is_file():
                run(["cmake", "--preset", preset], env)
            run(["cmake", "--build", "--preset", preset, "--target", "project_tests"], env)
            run(["ctest", "--preset", preset, "-j", jobs], env)
        except subprocess.CalledProcessError as exc:
            print(f"==> {variant}: FAILED ({exc.returncode})", file=sys.stderr)
            return 1
        print(f"==> {variant}: clean")
    print("==> all sanitizer variants clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
