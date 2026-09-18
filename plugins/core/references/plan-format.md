# Plan artifact format

A plan is **one markdown file** with **one** fenced ` ```json wf-plan ` block.

Prose carries the context, the decisions and the risks — the things a human reads to judge whether
the plan is right. The fence carries the task DAG — the thing a machine executes. Nothing appears in
both.

## Why one file with a fence

- **Frontmatter is out.** Python 3.14 has no stdlib YAML parser and every script here is stdlib-only.
- **A sidecar `plan.json` is out.** It gets orphaned the first time someone moves or renames the plan.
- **A prose checklist next to the fence is out.** Two task lists drift inside a single session. The
  fence is the *only* task list; if a task is not in the fence, it does not exist.

## Layout

````markdown
# CSV import endpoint

## Context
<why this work exists, what it builds on, what was already established>

## Decisions
| Decision | Choice | Why |

## Risks
<what could go wrong, and what the fallback is>

## Tasks

```json wf-plan
{
  "schema": "wf-plan/1",
  "id": "2026-09-16-csv-import-endpoint",
  "title": "CSV import endpoint",
  "project": "widgets-api",
  "baseCommit": "a217521229e3",
  "branch": "feature/csv-import-endpoint",
  "knowledgeRefs": ["docs/modules/csv-import.md", "docs/tasks/testing.md"],
  "checksSnapshot": [{"id": "precommit", "cmd": "pre-commit run --all-files"}],
  "tasks": [
    {
      "id": "T1",
      "title": "Parse the uploaded CSV rows",
      "description": "<what to do, and what done looks like>",
      "files": ["src/csv_import/parser.cpp", "src/csv_import/parser.h"],
      "dependsOn": [],
      "verify": ["cmake --build build/debug --target csv_import_tests", "ctest --test-dir build/debug -R csv_import_parser"],
      "commit": {"type": "feat", "scope": "csv-import", "subject": "parse uploaded CSV rows"},
      "risk": "low",
      "notes": "<gotchas, links, anything that does not fit above>"
    }
  ]
}
```

## Verification
<how the whole thing is judged done, beyond the per-task checks>
````

## Fields

| Field | Meaning |
|---|---|
| `id` | `YYYY-MM-DD-slug`; also the `Plan-Id` git trailer, so it must be stable once execution starts |
| `baseCommit` | the commit execution starts from; `resume` scans `baseCommit..HEAD` |
| `knowledgeRefs` | docs the plan was written against, so a reader can check the premises |
| `checksSnapshot` | the project checks as they resolved when the plan was written — advisory; the run resolves them again |
| `files` | the paths or globs a task is expected to touch. A **guess**: execution records what was really touched and commits that |
| `dependsOn` | task ids that must land first. **Ordering only** — there is no `parallel` flag |
| `verify` | commands proving this task works. At least one; a task nobody can check is a task nobody can finish |
| `commit` | conventional type, optional scope, and a subject of at most 68 characters with no trailing period |
| `risk` | `low` / `medium` / `high` — flags where to slow down and ask |

## Parallelism is derived, never declared

There is no `"parallel": true`. A hand-set flag is a lie waiting to happen. `wf_plan.py layers`
topologically layers the DAG and calls two tasks parallel-safe only when they share a layer **and**
their glob-expanded `files` sets are disjoint. That catches the real hazard: two "independent" tasks
that both edit `CMakeLists.txt`.

## Run state lives in git

Every task commit carries trailers:

```
Plan-Id: 2026-09-16-csv-import-endpoint
Task-Id: T1
```

`wf_plan.py resume` reconstructs the ledger from those trailers alone. A cache under `plan.runDir`
holds attempt counts and failure detail, but **git wins on conflict**. That cache lives outside the
repo (`wf_config.py state-dir`, keyed off `git rev-parse --git-common-dir`, shared by every worktree of
this repo) — not gitignored, because it was never inside the repo to begin with. So a dead session
loses nothing, deleting the cache loses nothing, and resuming after a fresh clone works.

This is also why `implement-plan` never uses `git commit --amend`: amending rewrites the commit that
carries the `Task-Id`, and the ledger goes with it.

## Commands

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_plan.py" lint   <plan.md>          # exit 5 on a bad plan
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_plan.py" layers <plan.md> --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_plan.py" resume <plan.md> --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_plan.py" show   <plan.md> --task T1
```

`resume` reports `done`, `ready`, `next`, `complete`, plus two things worth reading:

- `orphanTaskIds` — a `Task-Id` committed on this branch that the plan does not define
- a per-task `note` when the plan was edited after that task was committed
