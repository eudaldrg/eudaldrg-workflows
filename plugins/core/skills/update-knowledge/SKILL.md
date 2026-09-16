---
name: update-knowledge
description: Write or refresh project documentation about a component or an activity, on the two-axis docs/modules and docs/tasks convention. Use after learning something worth keeping, when a doc has gone stale, or when asked to document a module, a procedure, or how something works in this repo.
argument-hint: "[what to document]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash
---

# update-knowledge

Add or refresh a doc on one of the two axes. Read
`${CLAUDE_PLUGIN_ROOT}/references/knowledge-format.md` first — it defines the convention, the
frontmatter subset, and how to decide which axis something belongs on.

## Pick the axis

- A *thing* that exists in the codebase → `docs/modules/<name>.md`
- *Doing* something — a procedure, workflow, command sequence → `docs/tasks/<name>.md`
- *Why a choice was made*, with alternatives and consequences → an **ADR** in `decisions/`, which this
  skill does not manage. Say so and stop rather than putting rationale on the wrong axis.

If it genuinely fits either, it is usually two docs. If it is genuinely unclear, ask.

## Extend before creating

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_knowledge.py" list [--where <project>] --json
```

If a doc on that axis already covers the subject, **extend it** — that is the default. Append a dated
section rather than rewriting:

```markdown
## Update (2026-09-16): parser now validates the checksum
```

Create a new doc only when the subject is genuinely distinct. Two overlapping docs on one axis are
worse than one long doc, because retrieval then has to choose and will sometimes choose wrong.

## Writing the doc

Name it after the thing, kebab-case. Open with an H1 and a one-sentence summary — those two lines are
what every listing shows, so make the first sentence say what this *is*.

Add frontmatter when it earns its place:

```markdown
---
aliases: [feed, ingest]
sources: [src/feed_handler/**]
decisions: [decisions/0001-feed-source-selection.md]
---
```

- `sources` — globs for the code this describes. Fill from what the work actually touched, not from a
  guess. Forward globs that match nothing yet are correct and useful: they start the staleness signal
  the day that code lands.
- `aliases` — only names someone would plausibly search for. Check `list` output first: two docs
  claiming one alias breaks resolution for both.
- `decisions` — ADRs that constrain this component.

Write what is not obvious from reading the code: why it is shaped this way, what it assumes, what
breaks it, the gotcha someone hit. Do not narrate the implementation — that rots on the next refactor
and the code already says it.

## Refreshing a stale doc

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_knowledge.py" stale [--where <project>] --json
```

For each `possibly-stale` doc, **read the doc and read the diff** of the source files that moved before
changing anything:

```bash
git log --oneline -- <the sources that moved>
git diff <doc's last commit>..HEAD -- <those sources>
```

Then either correct the doc, or — if it is still accurate — say so and leave it alone. An empty commit
touching the doc to silence the signal is a lie; do not do it. If the doc is still right, the honest
move is to leave the signal and mention it, or set `verified` explicitly.

## Hard rules

- Never restructure `decisions/` or write ADRs from here.
- Never rewrite `AGENTS.md`. If a new doc deserves a mention in its prose index, draft the paragraph in
  the surrounding style and let the user place it.
- Never commit. Write the files and report what changed; committing is the user's call.
- Never fabricate `sources` globs to make a doc look thorough. A wrong glob produces false staleness
  forever after.
