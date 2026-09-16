---
name: sync-lint-rules
description: Regenerate a C++ project's .clang-format and .clang-tidy from the shared base rules in this plugin plus that project's own overrides, and report drift. Use when C++ lint rules need syncing or refreshing, when .clang-format or .clang-tidy are out of date or were hand-edited, or when asked to share, update or standardize clang-format/clang-tidy settings across projects.
argument-hint: "[--check | --apply] [path-to-repo]"
allowed-tools: Read, Write, Edit, Bash, Glob
---

# sync-lint-rules

Shared C++ lint rules live in this plugin; the clang tools can only inherit from **parent
directories**, never from an arbitrary path, so the rules are merged here and written into each
project as generated, committed files. Read
`${CLAUDE_PLUGIN_ROOT}/references/cpp-lint-rationale.md` before changing how any of this works —
it records what this approach costs and which alternatives were rejected and why.

## Procedure

Default to reporting. Only write when the user asked to apply, and always show the diff first.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_lint.py" check    [--project <path>]
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_lint.py" show     [--project <path>]
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_lint.py" generate [--project <path>] [--apply]
```

`generate` without `--apply` is a dry run that prints a unified diff. It refuses to write if the
clang tool rejects the result — every generated file is validated by running
`clang-format --dump-config` / `clang-tidy --dump-config` against it in a temp directory first.

A project only participates when its config sets `cpp.enabled` to true:

```json
{ "cpp": { "enabled": true } }
```

## The three kinds of drift

`check` distinguishes them because the remedies differ:

| Drift | Meaning | Remedy |
|---|---|---|
| hand-edited since generation | someone edited the generated file | **offer to fold the edit back** into `cpp.clangFormat.overrides` as a proper override, then regenerate. Do not silently discard it |
| shared rules moved on | the base rules changed | show what changed in `rules/cpp/CHANGELOG.md`, then offer to regenerate |
| overrides changed, never regenerated | the project config was edited | regenerate |

For a hand-edit, work out the key-level delta by comparing the file against `show` output. For
`.clang-format` that is unambiguous. For `.clang-tidy`'s `Checks` it is not — a changed glob could
be an add or a remove — so show the diff and ask rather than guessing.

## Where rules go

- **Shared, applies everywhere:** `${CLAUDE_PLUGIN_ROOT}/rules/cpp/base.clang-*.json`. Bump
  `rules/cpp/VERSION` and add a `CHANGELOG.md` entry in the same change, so projects that fall
  behind can see what they are missing.
- **One project only:** that project's `.claude/workflows.json` under `cpp`. Never edit the
  generated `.clang-format` / `.clang-tidy` directly.

Overrides support `clangFormat.overrides` (flat keys, plus dotted keys like
`BraceWrapping.AfterFunction` which expand to nested YAML), `clangFormat.unset`,
`clangTidy.checksAdd`, `clangTidy.checksRemove`, `clangTidy.scalars` and `clangTidy.options`.

`Checks` is emitted as `-*`, then **every enable from every layer, then every disable from every
layer**. That ordering is load-bearing: clang-tidy is last-match-wins, so it is what guarantees a
project's `checksRemove` beats a base `checksEnable`. Never interleave by layer.

## After generating

Verify semantically, not just textually — a textual diff will not tell you that a clang-tidy
upgrade quietly enabled twelve new checks:

```bash
cd <project> && clang-tidy --list-checks | tail -n +2 | wc -l
```

Compare against the previous count when the rules or the toolchain changed, and mention any large
swing.

Then check the project actually runs these rules. `pre-commit` is the single entry point:

```bash
cd <project> && pre-commit run --all-files
ls <project>/.git/hooks/pre-commit     # absent means `pre-commit install` was never run
```

If `.pre-commit-config.yaml` pins a `mirrors-clang-format` revision, compare it against the system
`clang-format --version`. Two different clang-format versions will disagree silently, and the
generated file may use keys the older one does not recognise — `cpp.minClangFormatVersion` records
the floor.

## Hard rules

- Never commit, push, or open a PR. Show the diff, write the files when asked, and stop.
- Never write a generated file that the clang tool itself rejects.
- Never regenerate from a hook. Hooks detect and report; mutation is always an explicit invocation.
- Never emit `User:` into `.clang-tidy` — it leaks the username and makes the file machine-specific.
- Preserve the provenance header exactly; it carries the hashes drift detection depends on, and it
  deliberately contains no timestamp so that regenerating with no changes produces no diff.
