---
name: setup-cpp-repo
description: Set up a C++ repo with the shared defaults — CMake skeleton with GCC/Clang/MSVC warnings, sanitizers and GoogleTest, Python check scripts, a two-stage pre-commit config, CI on Linux and Windows, the feature→dev→main branch model and its forge protection — with per-repo overrides in .claude/workflows.json. Use when starting a C++ repo, adding quality gates or CI to one, re-pointing an existing repo at the shared setup, or when its generated pre-commit/CI files drift.
argument-hint: "[status | scaffold | generate | check | protect] [path-to-repo]"
allowed-tools: Read, Write, Edit, Bash, Glob
---

# setup-cpp-repo

Read `${CLAUDE_PLUGIN_ROOT}/references/cpp-repo-setup.md` before changing how any of this works. It
has the decisions and what each one rejected.

Everything goes through one script. Without `--apply` every command is a dry run.

```bash
S="${CLAUDE_PLUGIN_ROOT}/scripts/wf_cpp_repo.py"
python3 "$S" status   [--project <path>] [--json]
python3 "$S" scaffold [--project <path>] [--name <cmake-name>] [--apply]
python3 "$S" generate [--project <path>] [--apply] [--force]
python3 "$S" check    [--project <path>] [--json]
python3 "$S" protect  [--project <path>] [--branch B ...] [--apply] [--json]
```

## Two kinds of file

| Kind | Files | After writing |
|---|---|---|
| **Scaffolded once** | `CMakeLists.txt`, `cmake/ProjectSettings.cmake`, `CMakePresets.json`, `tests/smoke_test.cpp`, `scripts/check_build.py`, `scripts/run_sanitizers.py`, `scripts/with_memory_cap.py`, `docs/tasks/testing.md`, `docs/tasks/pull-requests.md`, the AGENTS.md sections, `build/` in `.gitignore`, missing keys in `.claude/workflows.json` | The repo owns them. `scaffold` never overwrites an existing file; it says `keep`. |
| **Generated** | `.pre-commit-config.yaml`, and the forge's CI file (`.github/workflows/ci.yml`) | Kept in sync from `.claude/workflows.json`. Provenance header, drift check, never edited by hand. |

`.clang-format` / `.clang-tidy` are `/core:sync-lint-rules`' job; run it as part of setup.

## Procedure: new repo

1. `status`. It shows the forge it detected, what `scaffold` would write or keep, and the drift
   state of the generated files. Report it to the user, especially the forge line.
2. Settle per-repo overrides **before** writing, in the repo's `.claude/workflows.json`: the
   compiler floor (`cpp.repo.compilerFloor`), the CI matrix (`cpp.repo.ci.matrix`, every gcc/clang
   cell at or above the floor), TSan (`cpp.repo.checks.sanitizers.tsan`, off by default), cppcheck
   (on), the memory cap (off; Linux only). Defaults are in `defaults/workflows.defaults.json` under
   `cpp.repo` and `git`. Ask about the ones you cannot infer from the repo's docs.
3. `scaffold`, show the plan, then `scaffold --apply`. An `append` or `merge` action prints its diff.
4. `/core:sync-lint-rules` to write `.clang-format` and `.clang-tidy`.
5. `generate`, show the diff, then `generate --apply`.
6. Prove the tree works, in this order:

   ```bash
   cmake --preset debug && cmake --build --preset debug && ctest --preset debug
   pre-commit install && pre-commit install --hook-type pre-push
   git add -A && pre-commit run --all-files                      # untracked files are invisible to it
   pre-commit run --all-files --hook-stage pre-push
   ```

   A failure here is a finding about the template or the repo. Fix it; do not weaken a hook.
7. Stop and hand over: the user reviews and commits the tree. Never commit it yourself unless asked.
8. **Forge protection** comes last, and only once CI has run on each protected branch (see below).

## Procedure: existing repo

Same commands, but expect `keep` on most scaffold files: the repo's own CMake and scripts win.
Compare what it has against the templates in `${CLAUDE_PLUGIN_ROOT}/templates/cpp-repo/` and
propose specific changes, one at a time; never replace a working build wholesale. Old bash hook
scripts referenced by a hand-written `.pre-commit-config.yaml` become the Python ones only when
`generate --apply` replaces that file, which needs `--force` because it has no provenance header.
Show the user the diff first.

## Drift

`check` exits 1 on drift and names the kind:

| Drift | Remedy |
|---|---|
| hand-edited since generation | Work out what the edit wanted and express it in `.claude/workflows.json` (or, if it is a gap every repo has, in this plugin's generator), then regenerate. `generate` refuses to overwrite a hand-edit without `--force`. |
| template moved on | The plugin's generator changed (`templates/cpp-repo/VERSION`). Regenerate and show the diff. |
| config changed, never regenerated | Regenerate. |
| missing / not generated | `generate --apply`; a pre-existing hand-written file needs `--force` after the user has seen the diff. |

Bump `templates/cpp-repo/VERSION` in the same change whenever generated output changes.

## Forge protection

The policy is forge-neutral (`git.protection`); the forge comes from the `origin` URL, overridable
with `git.forge` (`auto` | `github` | `none`). Only GitHub has an adapter. For any other forge,
`protect` prints the policy as a checklist for the user to set by hand, and no CI file is generated.

On GitHub, this changes the live repo, outside the working tree. **Confirm every time**:

1. `protect` (no `--apply`) shows, per branch, the diff from the live protection to the policy and
   warns about required checks that never reported on that branch. It writes nothing.
2. If a protected branch does not exist on the remote (`dev` usually does not, at first), ask
   before creating and pushing it.
3. Required checks that never ran block every PR into the branch. Let CI run on the branch first,
   or say plainly that PRs will wait.
4. For **each** branch, show its diff and ask. On a yes, `protect --apply --branch <b>`; it writes
   that one branch and reads it back. A yes for `main` is not a yes for `dev`, and a yes in an earlier
   session is not a yes now.

The defaults, and why: PR required; required checks = every job the generated CI defines;
no force push; no deletion; **0 required approvals**, because the owner opens PRs from their own
account and GitHub does not let an author approve; **no linear history on main**, because a release
is a merge commit; rules apply to admins too.

## Hard rules

- Never overwrite a scaffolded file, and never regenerate a hand-edited generated file without the
  user seeing the diff and agreeing to `--force`.
- Never write forge settings without a per-branch confirmation in this session.
- Never commit, push, merge or tag. Setup ends with a working tree the user reviews.
- Never weaken a check to make the dry run pass; fix the template or report it.
- Nothing project-specific goes into this plugin's templates; per-repo choices live in that repo's
  `.claude/workflows.json`.
- Never mutate a repo from a hook. Drift is detected and reported; regeneration is this skill.
