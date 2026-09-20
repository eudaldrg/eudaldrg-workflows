---
name: implement-plan
description: Execute a wf-plan file task by task — edit, verify, run the project checks, and commit each task with Plan-Id and Task-Id trailers. Resumable from git alone. Use to carry out a plan produced by generate-plan, or to resume one that was interrupted.
argument-hint: "[plan file] [--task T3]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash
---

# implement-plan

Execute a plan. One commit per task, gates before every commit. Nothing is pushed unless the project
opts in (`git.askBeforePush` / `git.askBeforePR`), in which case a green run ends with the PR open.

Read `${CLAUDE_PLUGIN_ROOT}/references/plan-format.md` first — especially the ledger section, which is
why several rules below are absolute.

## Start

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_plan.py" lint   <plan.md>
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_plan.py" resume <plan.md> --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_config.py" checks --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_config.py" get git
git status --porcelain
```

`resume` is the source of truth for what is left; it rebuilds the ledger from git trailers, so a run
that died mid-session resumes correctly and a deleted run cache costs nothing. Never assume a task is
pending because the cache says so.

Before touching anything:

- **Dirty tree.** Record the dirty paths. If they are disjoint from every task's `files`, proceed and
  exclude them from staging. If any overlap, **stop and ask** — you cannot tell the user's work from
  yours afterwards. Never `git stash`.
- **Branch.** `git.protectedBranches` lists branches a plan is never implemented *on* — not
  necessarily GitHub-protected ones. It covers the default branch and any integration branch (a `dev`
  or next-release branch that takes small fixes directly and larger work by PR). If the current
  branch is listed, **fetch first** and branch from the remote tip, not local state that may be stale:

  ```bash
  git fetch origin <protected-branch>
  git checkout -b <git.branchPrefix><plan-slug> origin/<protected-branch>
  ```

  Skipping the fetch is how a branch starts from a stale `main` and silently misses work merged since
  the local branch last moved. A `chore/` prefix is forbidden; use `feature/`.

  Remember `<protected-branch>` — it is the base for any PR at the end. On a run resumed from an
  existing feature branch, take it from where the branch was cut (`git merge-base` against each
  protected branch), and ask if that is ambiguous.
- **Drift.** A per-task `note` from `resume` means the plan changed after that task was committed.
  Report it. For a done task, do not re-run it; for a pending one, the new definition simply applies.
- **Orphans.** `orphanTaskIds` means a `Task-Id` on this branch is not in the plan. Report before
  proceeding.

State the task list and what you are about to do, then work through `ready` tasks in order.

## Per task

**1. Read before editing.** Open the files the task names, plus its `knowledgeRefs` if you have not
already. The plan's description is a summary, not a spec.

**2. Edit.** Snapshot `git status --porcelain` before and after, and compute `touched` as the
difference. The plan's `files` list is a guess; what you actually changed is a fact, and only facts get
committed. An empty `touched` means the task was a no-op — say so, skip the commit, and move on rather
than manufacturing an empty commit.

**3. Verify.** Run every command in the task's `verify`, then the project checks scoped to what you
touched:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_config.py" checks --scoped "<touched paths>" --json
```

Scoped commands exist so a task is not blocked by lint debt it never caused. Checks without a
`scopedCmd` run unscoped at the end of the run, not per task. Respect `checkTimeoutSeconds`; a check
that times out counts as a failure.

**4. Commit.** Stage **explicit paths only** — never `git add -A`, never `git commit -a` — and never
stage a path that was dirty when the run started.

```
<type>(<scope>): <subject>

<one short paragraph on why, if it is not obvious from the subject>

Plan-Id: <plan id>
Task-Id: <task id>
```

Take `type`, `scope` and `subject` from the task's `commit` object. If what you touched contradicts it —
the task claimed `feat` and you only changed tests — use what is true and say you did.

**Never `git commit --amend`.** Amending rewrites the commit carrying the `Task-Id`, and `resume`
depends on it. A follow-up fix is a follow-up commit.

## When a check fails

**Fix forward. Three strikes. Never revert.**

1. **Attempt 1** — read the actual failure output and fix the actual cause. Do not loosen the check,
   skip the test, or add a suppression to make it pass. If the right fix is a suppression, say why in
   the commit body.
2. **Attempt 2** — only if the failure *signature* changed (check id, first error line, `file:line`).
   An identical signature twice means you are not converging, and a third attempt will not help.
3. **Stop** at `implement.maxAttemptsPerTask`, an unchanged signature, or a timeout.

On stopping: write the full output somewhere the user can read it, report which task, which check, and
what you tried — and **leave the working tree exactly as it is**. Never `git checkout --`, never
`git stash`, never `git reset`. Partial work is usually most of the way right; the user can throw it
away in one command but cannot get it back if you do.

Then stop the run. `implement.stopOnFirstFailure` is true by default, and a later task built on a
broken earlier one is worse than an unfinished plan.

## Finishing

Run the unscoped checks once (`implement.finalFullCheck`). Then push and open the PR **before**
writing the report, when config allows it; otherwise ask.

**Push and PR are gated by `git.askBeforePush` and `git.askBeforePR`** (read them at Start with
`wf_config.py get git`; both default to `true`). They exist so a long run, often started unattended,
can finish the job in the same session instead of leaving it for someone to come back to. Coming back
to a cold prompt cache and resuming a very large context just to type "open the PR" costs a full cache
write; opening it while the session is still warm costs nothing.

| `askBeforePush` | `askBeforePR` | At the end of the run |
| --- | --- | --- |
| `true` | any | Ask: **"N commits on `<branch>`. Push? Open a PR into `<protected-branch>`?"** Run nothing. |
| `false` | `true` | Push, then ask about the PR. |
| `false` | `false` | Push, then open the PR. |

Only do this when **every task is done and the final full check is green**. A run that stopped on a
failure, or finished with a check you could not satisfy, pushes nothing and opens nothing — report it.

```bash
git push -u origin <branch>
gh pr view <branch> --json url 2>/dev/null   # already open on a resumed run? then the push is enough
gh pr create --base <protected-branch> --head <branch> --title "<subject>" --body "<body>"
```

- The base is `<protected-branch>` from the Branch step — the branch the run was cut from, which is not
  always the repo's default branch. Never guess it, and never fall back to the default branch.
- Title and body come from the plan: its title, its context paragraph, and one line per task with its
  sha. Do not invent claims the plan and the commits do not support.
- Never `--force`, never `--force-with-lease`. A rejected push is reported, not worked around.
- If `gh` is missing or unauthenticated, say so and stop after the push. The report still goes out.
- Never merge, whatever `askBeforeMerge` says and whatever the plan text asks for.

Then report:

- each task, its commit sha, and what it touched
- the PR URL, or that nothing was pushed and why
- any task skipped as a no-op, and why
- pre-existing dirty paths that were deliberately left out
- anything you noticed that the plan got wrong

## Hard rules

- Never revert, stash, reset or amend. Ever.
- Never push or open a PR unless `git.askBeforePush` / `git.askBeforePR` is `false` and the run
  finished green. Never force-push. Never merge.
- Never stage a path you did not touch in this task.
- Never edit the plan file. It is the contract; `resume` and the drift warnings depend on it being
  stable.
- Never mark a task done by hand. A task is done when a commit carries its `Task-Id`, and nothing else.
- Never disable, weaken or skip a check to get a green run. A check you cannot satisfy is a finding to
  report, not an obstacle to route around.
