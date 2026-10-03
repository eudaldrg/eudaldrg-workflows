# Project knowledge: two axes, no index

Knowledge is organised on two **orthogonal** axes, stored as two independent sets of documents:

```
<project>/
  docs/
    modules/            WHAT — one doc per component
      feed-handler.md   what it is, how it works, what it talks to
      order-book.md
    tasks/              WHY — one doc per activity
      testing.md        how you do this thing in this repo
      replay.md
      profiling.md
  decisions/            ADRs — a third category, owned by the design skill (references/adr-format.md)
```

A question names a point on each axis — "I'm debugging the feed handler" — and the answer is the
module doc **and** the activity doc. Two lookups. There is no ranked search, because there is nothing
to rank.

## There is no index file

`ls docs/modules/` is the WHAT axis. `ls docs/tasks/` is the WHY axis. A separate index would be a
second copy of facts that already exist, and would start lying the first time someone renames a file
without updating it.

Everything else a document needs to say about itself lives **in that document**, so it moves, renames
and is deleted along with it:

```markdown
---
aliases: [webhook, ingest, notifications]
sources: [src/webhook_handler/**]
decisions: [decisions/0001-webhook-source-selection.md]
---

# Webhook handler

Ingests upstream webhook events and normalizes them for the notification queue.
```

| Field | Meaning |
|---|---|
| `aliases` | other names this doc answers to. Two docs claiming one alias is reported as a conflict, never silently resolved |
| `sources` | globs for the code this doc describes. Drives staleness and reverse lookup. **May match nothing yet** — declaring `src/webhook_handler/**` before that directory exists is deliberate |
| `decisions` | ADRs that constrain this component; surfaced alongside the doc |
| `verified` | optional explicit commit sha, when the automatic staleness signal is not precise enough |

Frontmatter is a small subset — scalars and flat `[a, b]` string lists. It is entirely optional: a doc
without it still resolves by filename, it just gets no staleness signal and no reverse lookup.

The title is the H1 and the summary is the first paragraph. Neither is ever stored twice.

Nothing about an individual document belongs in `.claude/workflows.json`. That file says only *where to
look* (`knowledge.docsDir`) and *whether to consult the shared set* (`knowledge.consultShared`).

## Staleness carries no stored state

A doc's last commit is compared against the last commit of anything matching its `sources`. If the
sources moved later, the doc is **possibly stale**. Two states, not four, and no field to maintain or
re-stamp.

The known weakness: fixing a typo in the doc marks it current again. That is the accepted cost of not
maintaining a `verified` field; set one explicitly when it matters.

The whole check is **one `git log` call regardless of how many documents exist**.

## Which axis does this belong on?

- Describes a *thing* that exists in the codebase, and would still be true if nobody ran anything →
  **module**.
- Describes *doing* something — a procedure, a workflow, a command sequence → **task**.
- Records *why a choice was made*, with alternatives and consequences → **ADR**, and it stays in
  `decisions/`. Note this is a different sense of "why" from the task axis: the task axis is "what are
  you trying to do", not "why is it like this".

If a doc would genuinely fit either axis, it is usually two docs.

## Shared knowledge

`${CLAUDE_PLUGIN_ROOT}/knowledge/tasks/` holds cross-project activity docs — how profiling is
approached, how optimization work is framed. **Activities only**: modules are inherently
project-specific.

When a project doc and a shared doc exist for the same activity, **both are returned**, project first.
They are not merged and there is no conflict resolution: two documents, both shown, the reader decides.
