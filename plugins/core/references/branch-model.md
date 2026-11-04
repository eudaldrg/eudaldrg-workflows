# Branch model

One model for every repo: work collects on an **integration branch** and reaches the **release
branch** only when the owner releases. The names are settings (`git.integrationBranch`, default
`dev`; `git.releaseBranch`, default `main`). A repo with no separate integration branch sets both to
the same name and gets the integration rules below on it (trunk-based).

```
feature/<slug> ──squash or rebase──▶ dev ──merge commit──▶ main ── tag vX.Y.Z
                                      ▲                       │
                                      └──── hotfix: same fix ─┘
```

## The rules, and why

| | Rule | Why |
| --- | --- | --- |
| feature → integration | **squash** by default (plan runs, review fixups, any state a later commit undid); **rebase** when every commit is a clean step a reader would want | The integration branch gets finished changes only. Plan trailers (`Plan-Id`, `Task-Id`) and review rounds stay on the feature branch. |
| | never a merge commit; linear history required | The integration branch reads as one line of changes, each linked to its PR. |
| integration → release | **merge commit only**; never squash, never rebase | Squash and rebase both write new commits onto the release branch that the integration branch does not have. The two branches drift, and every later release PR shows old work again and can conflict. A merge commit keeps the integration branch an ancestor of the release branch. |
| | no linear history on the release branch | It would reject the release merge commit. |
| release gate | the expensive checks (simulations, long test suites, packaging) run on the integration → release PR, and again on the push to the release branch if wanted | They block a release that fails them, without slowing every feature PR. |
| release marker | tag the merge commit `vX.Y.Z`; optionally a forge release with the changelog as notes | The tag is what consumers pin; the merge commit is where the release landed. |
| hotfix | branch from the release branch, PR into it (merge commit), then the same fix as a normal PR into the integration branch | The integration branch stays linear. At the next release both sides carry the same change, and git merges it cleanly. |
| messages | a squash or merge commit's message defaults to the PR title and description | The PR is written once, as the commit it becomes (`/core:pull-request`). The forge's defaults concatenate every commit message, trailers included, or say only "Merge pull request #n". |

`git log --first-parent <release>` lists one line per release; `git bisect --first-parent` finds
the release that broke something before descending into it.

## How it is enforced

`scripts/wf_protect.py` turns `git.protection` into the forge's settings and shows the diff before
any write:

- `default` applies to both branches; `release` and `integration` hold what differs by role
  (`mergeMethods`, `linearHistory`); `branches.<name>` overrides one branch or adds another.
- On GitHub each branch gets one repository ruleset named `workflows: <branch>`. Rulesets are the
  only way to allow merge commits into one branch and only squash or rebase into another; the
  repo-wide merge switches cannot tell branches apart. A classic branch protection rule on the same
  branch is removed once the ruleset is in place, because both would apply and the stricter one
  wins.
- The repo-wide switches enable the union of the branches' methods, and set the squash and merge
  commit messages to the PR title and description (`squashMessage`, `mergeMessage`).
- `wf_protect.py methods --base <branch>` reports what the forge will actually offer for a PR into a
  branch, which is what `/core:pull-request` checks before recommending a method.

Other forges get the same policy printed as a checklist.
