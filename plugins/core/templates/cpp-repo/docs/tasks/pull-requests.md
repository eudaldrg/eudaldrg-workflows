---
aliases: [pr, pull request, branches, release, tag, merge]
---

# Pull requests

This repo's branch model, merge methods and release steps. How to write and update a PR in general
is in the workflows plugin's `pull-request` skill.

## Branch model

- Work happens on `{{branch_prefix}}<slug>` branches cut from the remote `{{integration_branch}}`
  (`git fetch origin {{integration_branch}} && git checkout -b {{branch_prefix}}<slug> origin/{{integration_branch}}`).
- Every change reaches `{{integration_branch}}` through a PR, one topic per PR. The owner reviews it
  and merges it by the method its description recommends (`/core:pull-request`): rebase for one
  commit or clean steps, squash for review fixups or plan commits. A squash takes the PR title and
  description as its message (a repo setting), so a squash PR's description is written as that
  commit.
- A release is a PR from `{{integration_branch}}` into `{{release_branch}}`, merged as a **merge
  commit** (not squashed, so `{{release_branch}}` keeps the integration history), then tagged
  `vX.Y.Z` on `{{release_branch}}`. Only when the owner says so.
- A hotfix is a branch from `{{release_branch}}`, a PR into it (merge commit), then the same fix as
  a normal PR into `{{integration_branch}}`.
- `{{release_branch}}` and `{{integration_branch}}` are protected on the forge: PR required, the CI
  checks required, no force push, no deletion. No approval count is required, because the owner
  opens PRs from their own account and cannot approve them; "the owner reviews" is a rule here, not a
  forge setting. `{{integration_branch}}` accepts squash and rebase only and is linear;
  `{{release_branch}}` accepts merge commits only and is not linear, because a squashed or rebased
  release would leave the two branches with different commits.

## Before pushing

Run the push-time checks if the pre-push hook is not installed (`ls .git/hooks/pre-push`):
`pre-commit run --all-files --hook-stage pre-push`.
