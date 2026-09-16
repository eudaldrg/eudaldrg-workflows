# Why shared C++ lint rules are generated and committed

## The constraint

`clang-format` supports `BasedOnStyle: InheritParentConfig` and `clang-tidy` supports
`InheritParentConfig: true`, but **both only walk parent directories**. Neither tool can include a
config from an arbitrary path. There is no `--style-search-path`; it has been proposed upstream and
is not implemented.

So sharing one canonical rule set across repos that live in different places, and that must also
work for CI and for anyone who clones them, leaves exactly one mechanism: **merge the rules
ourselves and write the result into each project as a committed file.**

## What this costs

These are the price of the approach, not bugs in it.

1. **No live propagation.** Bumping the base rules changes nothing in any project until someone runs
   the sync skill there. Drift detection surfaces the gap; it does not close it. Anyone who does not
   have this plugin installed never even sees the prompt.
2. **Generated files are committed**, so every rules bump produces `.clang-format` / `.clang-tidy`
   churn in pull requests, and can conflict on merge. Deterministic emission and the no-timestamp
   rule keep this to genuine changes only, but do not eliminate it.
3. **The file stops reading as "Google plus eight tweaks."** Because nested structs are emitted
   wholesale, a reviewer loses the at-a-glance sense of how far the project has drifted from stock.
   The `--dump-config` before/after comparison in the sync report partly compensates.
4. **Two sources of truth inside the repo** — `.claude/workflows.json` and the generated files. This
   is the sharpest edge. Someone who edits `.clang-format` directly gets overwritten at the next
   sync. Mitigated three ways, all mandatory: the loud generated-file header; drift detection that
   offers to *fold a hand-edit back* into the overrides rather than discarding it; and keeping any
   project instruction that says "tighten `.clang-format`" updated to say "edit
   `.claude/workflows.json`, then sync" — otherwise the project's own docs will instruct future
   agents to do the wrong thing.

## Rejected alternatives

**Parent-directory inheritance.** Put `.clang-format` in `~/projects/` and have each project use
`BasedOnStyle: InheritParentConfig`. Genuinely works, with zero generation and zero drift, and it is
the most elegant option *on one machine*. Rejected because it breaks the moment the repo is cloned
anywhere else or CI checks it out standalone — which is precisely the requirement. Documented here
so it does not get re-proposed every six months.

**Symlinking `.clang-format` from the plugin into the project.** Dead on arrival: git stores the
symlink target verbatim, so every teammate and every CI checkout gets a dangling link pointing at a
path that does not exist on their machine.

**Emitting `clang-format --dump-config` output as the generated file.** It is 334 lines, unreadable,
and pins every default of the clang-format version that produced it — so it breaks against an older
clang-format that does not recognise the newer keys. It is an excellent *validator* and a terrible
*generator*.

**Depending on PyYAML.** It is present on the current box only as an accident of `pre-commit`'s apt
packaging, CI images will not reliably have it, and its default emitter does not match clang's own
formatting, so every regeneration would churn whitespace. The emitter is hand-rolled against a
deliberately constrained value schema — scalar, flat map of scalars, or list of strings, which
covers every key both tools accept. PyYAML is used opportunistically as a round-trip check when it
happens to import, and skipped silently when it does not.

## Why `Checks` ordering is load-bearing

`clang-tidy`'s `Checks` is an ordered, last-match-wins glob list. Confirmed empirically:
`clang-tidy --dump-config` prepends its defaults and appends file contents verbatim, evaluating left
to right.

Therefore the emitted order is `-*`, then **every enable from every layer**, then **every disable
from every layer** — never interleaved by layer. Interleaving would mean a base enable written after
a project disable silently re-enables the check, which is the worst possible failure mode for a lint
system: the user's explicit override becomes a no-op with no error anywhere.

## Verification that actually catches things

A textual diff of `.clang-tidy` will not tell you that upgrading clang-tidy enabled twelve new
`bugprone-*` checks and broke the build. Comparing the resolved enabled set will:

```bash
clang-tidy --list-checks | tail -n +2 | wc -l
```

Same idea for formatting: compare `clang-format --dump-config` (334 resolved keys) before and after,
not just the generated file.
