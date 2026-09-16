---
name: init-model-agnostic
description: Convert a repository to use AGENTS.md as the single source of truth for agent instructions, with CLAUDE.md and other tool-specific files as relative symlinks to it. Use when a repo has a CLAUDE.md but no AGENTS.md, when bootstrapping a repo for agent use, or when asked to "make this repo model agnostic", "standardize agent instructions", or "set up AGENTS.md".
argument-hint: "[path-to-repo]"
allowed-tools: Read, Glob, Grep, Bash, Write, Edit
---

# init-model-agnostic

Make one `AGENTS.md` the source of truth and point every tool-specific instruction file at it
with a **relative symlink**. AGENTS.md is read natively by most agent tools; Claude Code and
Gemini CLI still need their own filename, which is what the symlinks solve.

## Procedure

### 1. Scan (read-only)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_init_scan.py" [--project <path>]
```

Emits JSON: `root`, `isGitRepo`, `branch`, `detachedHead`, `unbornBranch`, `inProgressOperation`,
`symlinkSupport`, `dirtyFiles`, `sourceOfTruth`, `linkable[]`, `reportOnly[]`, `nested[]`, `case`,
`blockers[]`, `warnings[]`. It changes nothing.

Read the configured symlink set:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_config.py" get init.toolFiles
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_config.py" get init.optionalToolFiles
```

### 2. Stop on blockers

If `blockers` is non-empty, **do not mutate anything**. Print them and stop, with the specific
remedy:

| Blocker | Remedy to tell the user |
|---|---|
| detached HEAD | check out a branch first |
| merge/rebase/cherry-pick in progress | finish or abort it first |
| uncommitted changes to files we would touch | commit or stash them yourself — this skill never stashes |
| filesystem does not support symlinks | see the fallback in step 4 |

Surface `warnings` too, but they do not stop the run.

### 3. Pick the action from `case`

| `case` | Action | Ask first? |
|---|---|---|
| `already-conformant` | nothing — report and exit | — |
| `agents-only` | `ln -s AGENTS.md CLAUDE.md` | no |
| `claude-only` | `git mv CLAUDE.md AGENTS.md`, then symlink | **yes** — show size and first lines |
| `both-identical` | `rm CLAUDE.md`, then symlink | no |
| `both-differ` | **never auto-merge** — see below | **yes, mandatory** |
| `symlink-absolute` | repoint to a relative target | no — it is a latent bug that breaks on clone |
| `symlink-wrong-target` | if the target has real content, adopt it as root `AGENTS.md` and repoint | **yes** |
| `symlink-dangling` | remove the dead link, then treat as `agents-only` or `neither` | **yes** |
| `inverted` (AGENTS.md is a symlink to CLAUDE.md) | materialise AGENTS.md, symlink CLAUDE.md | **yes** |
| `neither` | **do not invent content** — offer the template, or recommend running `/init` first and re-running | **yes** |

For `both-differ`: show `diff -u AGENTS.md CLAUDE.md`, copy the losing file to `init.backupDir`
first, confirm that directory is gitignored, then offer exactly three options — AGENTS.md wins with
CLAUDE.md's unique content appended under `## (merged from CLAUDE.md — review me)`; CLAUDE.md wins;
or abort. Default to the first. Never pick silently.

### 4. Other tool files

Create symlinks only for names in `init.toolFiles` / `init.optionalToolFiles`, and ask per file.
Use a target relative to the link's own directory — for a file in a subdirectory that means
`ln -s ../AGENTS.md .github/copilot-instructions.md`. Warn that Copilot truncates hard, so a long
AGENTS.md may be largely ignored.

Anything in `reportOnly` (`.cursorrules`, `.windsurfrules`, `.clinerules`, …) is **reported, never
converted** — deprecated and a different format. Nested `AGENTS.md`/`CLAUDE.md` in subdirectories
are **left alone**; nearest-file-wins scoping is legitimate. Never flatten them.

If `symlinkSupport` is false, follow `init.fallbackOnNoSymlinks`: `stub` (default) writes a short
`CLAUDE.md` pointing at AGENTS.md with a content hash for drift detection; `copy` writes a byte
copy; `abort` stops.

### 5. Confirm, then execute

Print the complete plan as literal shell commands and take **one** confirmation covering all of
them, even when every individual case is a no-ask case. Then run them. Stage with `git add` when
`init.stageChanges` is true.

### 6. Verify and report

```bash
git -C <root> status --short
readlink <root>/CLAUDE.md          # must print exactly: AGENTS.md
git -C <root> ls-files -s CLAUDE.md # must show mode 120000
```

Report what changed, then list follow-ups you did **not** do. In particular, if the adopted file
still opens with a Claude-specific header (`# CLAUDE.md`, "guidance to Claude Code"), offer to make
it tool-neutral — a file named AGENTS.md that calls itself CLAUDE.md contradicts itself. Suggest a
commit message; do not commit.

## Hard rules

- **Never** run `git commit`, `git push`, `git stash`, `git reset`, `git checkout --`, or any `gh`
  command. Staging is the furthest this skill goes.
- **Never** overwrite or delete a file with content without first copying it to `init.backupDir`.
- **Never** write outside the resolved repo root. Refuse if the root is `/` or `$HOME`.
- Prefer `git mv` over `mv` for tracked files so `git log --follow` traverses the rename.
- Abort if more than `init.maxFilesTouched` files would change.
- When the target repo is not the one the session started in, say so explicitly and confirm before
  touching it.
