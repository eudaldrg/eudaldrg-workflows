---
name: pull-request
description: Open or update a pull request the shared way — one topic per PR, the right base branch, a title and description sized to the change, and a recommended merge method (rebase, squash or merge commit) chosen from the branch's shape. Use whenever a branch is about to become a PR, when a PR's description needs refreshing after review, when deciding how a PR should be merged, or when another skill reaches its "open the PR" step.
argument-hint: "[branch]"
allowed-tools: Read, Grep, Glob, Bash
---

# pull-request

How a branch becomes a pull request, and how it should be merged. Other skills that end in a PR
(`implement-plan`, any ad-hoc change) follow this one. The project's own
`docs/tasks/pull-requests.md` adds its specifics (branch names, checks, gotchas); where the two
disagree, the project wins.

Opening, updating and merging are still gated: push and open only with the user's go-ahead (or
`git.askBeforePush` / `git.askBeforePR` set to `false` for plan runs), and **never merge**.

## 1. Scope: one topic per PR

Before opening, read what the branch adds: `git log --oneline <base>..HEAD` and
`git diff --stat <base>...HEAD`.

- One PR, one topic a reviewer can hold in their head. A README rewrite and a change to the
  project's procedures are two PRs, even if each is one line.
- If the branch mixes topics, split it before opening: a new branch per topic from the base, each
  with its own commits. Do not explain the mix in a message instead.
- Size follows the topic, not a process. A few lines need no plan, no task list and no long
  description; a milestone does.

## 2. Base branch

- Feature work: the integration branch (`git.integrationBranch`, often `dev`), from the commit the
  branch was cut from. Cut new work from the freshly fetched remote base, never a stale local one.
- A release: integration branch → release branch (`git.releaseBranch`, often `main`), only when the
  owner says so.
- If the PR a change belongs to is already merged, the change is a new branch and a new PR. Check
  with `gh pr view <branch> --json state` before pushing more commits to an existing branch.

## 3. Recommended merge method

Decide from the commits as they will land, and state it in the description (section 4).

| Branch shape | Method | Why |
| --- | --- | --- |
| One commit | **rebase** | The commit message is already the record. |
| Several commits, each a self-contained step a reader of the base branch would want, with messages that describe the change | **rebase** | Keeps the steps. |
| Fixups, review rounds, reverts, or any state a later commit undid | **squash** | The base branch gets the final state only. |
| Commits that carry plan structure: `Plan-Id` / `Task-Id` trailers, `T1:`-style subjects, one commit per plan task | **squash** | Plan structure is how the work was run, not what changed. It stays on the feature branch. |
| Integration → release | **merge commit** | The release branch keeps the integration history and the tag marks the merge. |

When in doubt between rebase and squash, squash. A plan run almost always squashes.

## 4. Title and description

Both are public history (see the project's AGENTS.md): what changed and why, for any reader. No
notes to the owner, no process asides, no tool or AI attribution, no mention of the workflow that
produced the change.

- **Title:** the repo's commit style (`<type>(<scope>): <subject>`). For a rebase it is usually the
  single commit's subject.
- **Description, rebase:** 1–3 sentences on what the PR adds and why; the commits carry the detail.
- **Description, squash:** it becomes the commit message, because the forge defaults a squash to
  the PR title and description (`setup-cpp-repo`, `git.protection.squashMessage: "pr"`). Write it
  as that commit: the final state, grouped by area for a large change, with the non-obvious why.
  Testing and known limitations may follow as sections. No trailers, no per-commit shas (they
  disappear), no states a later commit reversed, no fixes to problems the branch itself introduced.
- **Last line, always:** `Merge: <method> (<reason in a few words>)`, e.g.
  `Merge: rebase (one commit)` or `Merge: squash (plan commits)`.
- Claim only what the commits and the checks support. Say what was not tested.

```bash
gh pr create --base <base> --head <branch> --title "<title>" --body-file <file>
```

## 5. After review

- Review changes go on the same branch as new commits; never force-push.
- When the branch changes, update the description so it still describes the final state, and
  re-check the merge method: a one-commit PR that gained review fixups now squashes.
- Resolve the review threads the change addressed; leave the rest for the reviewer.

## Hard rules

- Never merge, whatever the config or the plan text says.
- Never force-push.
- Never put two topics in one PR to save a round trip.
- Never write process, workflow or tool details into a title, description or commit message.
