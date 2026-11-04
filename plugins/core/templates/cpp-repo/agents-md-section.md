## Lint / format / quality gates

**Rule for agents:** code must pass every automated check before it is committed or pushed. Never
bypass a hook (`--no-verify`) and never weaken a check, a lint rule or a test to make something
pass. Adding a check needs no permission; removing or loosening one needs the owner. Silence a
warning only at the line that triggers it (`// NOLINT(<check>)`), with a comment saying why, never
file-wide or project-wide. When a style preference comes up, tighten `.clang-format` / `.clang-tidy`
(through `.claude/workflows.json` and `/core:sync-lint-rules`) rather than writing prose style docs.

`docs/tasks/testing.md` lists what runs at commit, at push and in CI. Once per clone:

```bash
cmake --preset debug
pre-commit install && pre-commit install --hook-type pre-push
```

`.pre-commit-config.yaml` is generated from `.claude/workflows.json` by `/core:setup-cpp-repo`;
edit the config and regenerate, never the file. The CI workflow is this repo's own file: it must keep
running both hook stages, on Linux and Windows, with compilers at or above the floor.

## Branches and pull requests

`{{branch_prefix}}<slug>` → PR into `{{integration_branch}}`, merged by the owner after review by
the method the PR recommends (`/core:pull-request`). A release is `{{integration_branch}}` → `{{release_branch}}` as a merge commit, then a
`vX.Y.Z` tag on `{{release_branch}}`, only when the owner says so. Never merge your own PR.
`docs/tasks/pull-requests.md` has the procedure and its gotchas.

## Public history

Public history is for any reader, not a channel to the owner. Commit messages, PR titles and
bodies, review replies, issues and docs say what changed and why, nothing else. No notes addressed
to the owner, no process asides (a retry, a mistake, a PR that merged early), no tool or AI
attribution. Anything meant for the owner goes in the chat.
