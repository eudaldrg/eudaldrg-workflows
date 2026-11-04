---
aliases: [pr, pull request, branches, release, tag, merge, force push]
---

# Pull requests

The branch model, how to open, update and review a pull request, and the failures that look like
success.

## Branch model

- Work happens on `{{branch_prefix}}<slug>` branches cut from the remote `{{integration_branch}}`
  (`git fetch origin {{integration_branch}} && git checkout -b {{branch_prefix}}<slug> origin/{{integration_branch}}`).
- Every change reaches `{{integration_branch}}` through a PR. The owner reviews it and squash-merges it.
  The squash commit's message defaults to the PR title and description (a repo setting), so write
  the description as that commit message: the final state of the change and why, with no
  per-commit trailers or shas, and keep it current as review changes the branch.
- A release is a PR from `{{integration_branch}}` into `{{release_branch}}`, merged as a **merge
  commit** (not squashed, so `{{release_branch}}` keeps the integration history), then tagged
  `vX.Y.Z` on `{{release_branch}}`. Only when the owner says so.
- `{{release_branch}}` and `{{integration_branch}}` are protected on the forge: PR required, the CI
  checks required, no force push, no deletion. No approval count is required, because the owner
  opens PRs from their own account and cannot approve them; "the owner reviews" is a rule here, not a
  forge setting. Linear history is not required on `{{release_branch}}`: it would reject the release
  merge commit.

Pushing, opening a PR and merging need the owner's go-ahead each time, unless
`.claude/workflows.json` says otherwise for plan runs (`git.askBeforePush`, `git.askBeforePR`).
Never merge your own PR.

## Before pushing

- Run the push-time checks if the pre-push hook is not installed (`ls .git/hooks/pre-push`):
  `pre-commit run --all-files --hook-stage pre-push`.
- **Check the PR's state before pushing more commits to its branch.** The owner may already have
  merged it, and commits pushed to a merged branch go nowhere:

  ```bash
  gh pr view <branch> --json state,mergedAt
  ```

  If it is merged, cut a new branch from the updated `{{integration_branch}}` for the follow-up.

## Updating a PR's title or body

`gh pr edit` can fail silently: some `gh` versions print a GraphQL "Projects (classic) is being
deprecated" warning and leave the old title and body in place, which reads like a warning on a
successful edit. Use the REST API and read the result back:

```bash
gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -f title="..." -F body=@body.md
gh api repos/<owner>/<repo>/pulls/<n> --jq .body | head
```

Keep the body in a file (`-F body=@file`) so quoting and newlines survive.

## Reviewing what a branch adds

Diff against the merge-base with three dots, and against the `origin/` ref, so commits that landed
on the base since the branch was cut do not show up as removals and a stale local base does not
inflate the diff:

```bash
git diff --stat origin/{{integration_branch}}...HEAD
git log --stat origin/{{integration_branch}}..HEAD
```

## After rewriting local history

A branch whose commits were reshuffled needs a force push. Use `--force-with-lease`, and only when
the owner says so. Old commits stay reachable by SHA through the PR's refs, so a force push does not
purge a secret committed by mistake: rotate the secret.
