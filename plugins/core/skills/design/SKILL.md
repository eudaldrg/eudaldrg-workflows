---
name: design
description: Design a project or feature before any implementation plan: the roadmap and MVP cut, the architecture (components, contracts, storage, decision register), one milestone's design, and the ADRs those decisions produce. Resumes from the repo's design files. Use when asked to design, architect, scope an MVP, plan milestones, weigh design alternatives, or write or review an ADR.
argument-hint: "[roadmap | architecture | <milestone> | adr <question>]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash
---

# design

Architecture work, done with the human, persisted in files, ending where `/core:generate-plan` begins.
This skill runs in the main session on purpose. Design is a conversation, and a forked agent would
paraphrase both sides of it.

## Where design state lives

```
<docsDir>/roadmap.md               milestones, MVP cut, exit tests, design status per milestone
<docsDir>/architecture.md          components, data flow, contracts, decision register
<docsDir>/design/<milestone>.md    one milestone, detailed enough to plan from
decisions/NNNN-<slug>.md           one ADR per decision — format: references/adr-format.md
```

`<docsDir>` comes from `wf_config.py get knowledge.docsDir`. Nothing about the design lives only in a
conversation: if it was decided, it is in one of these files before the session ends.

## 1. Find where we are

Read whichever of the files above exist. The request decides the level, and the files provide the
context:

- **A new feature or change** ("I want to add X"): it belongs to a milestone. Place it in an existing
  one or propose a new one on the roadmap first (roadmap level), then design it (milestone level).
  Every feature goes through the same stages: proposed on the roadmap, designed, planned, done.
- **A specific decision** ("should this be X or Y?"): architecture level, one register row.
- **"What's pending?"**: report from the files: milestones by design status, `open` and `provisional`
  decisions, and provisional ones whose *revisit when* may have fired. Change nothing.
- **No specific request** (bare `/core:design`): the first that applies: no roadmap → roadmap level;
  decisions the next milestone needs are `open` → architecture level; otherwise the earliest milestone
  not `ready` → milestone level.

Say which level and why in one line, then read that level's file in `levels/` and follow it. Each level
ends by updating its artifact and the roadmap's design status.

## 2. Load the lenses that apply

Lenses are topical design knowledge (database design, API design, C++ structural patterns, game
architecture, MVP scoping…), one file each, with a `when` line in their frontmatter. Load one only
when its `when` matches the thing being designed, so none of them pay rent otherwise:

- shared: `${CLAUDE_PLUGIN_ROOT}/skills/design/lenses/*.md`
- project: `<docsDir>/design/lenses/*.md`, for conventions only this project has

A project lens refines a shared one; where they conflict, the project wins and says so. See
`lenses/README.md` for how to write one, including knowledge distilled from a book.

## 3. How every decision is made

1. **State the question**, not the answer: "how do readers learn about new rows?", not "use SSE".
2. **Give at least two real options**, the status quo or "do nothing" among them when it exists. For
   each: what it makes easy, what it makes hard, and what it costs to reverse.
3. **Recommend one and say why.** Then the human decides. Never record an unconfirmed decision as
   `accepted`.
4. **Decide whether it is an ADR at all** (`references/adr-format.md`, "Is it an ADR at all?"). Most
   choices are not: they go in the design doc, which is meant to change. Prefer a change policy or a
   setting to a frozen choice.
5. **Say how settled it is.** New ADRs are `proposed`. `provisional` with a *revisit when* if a
   later milestone may change it. Only the human makes one `accepted`, once reversing it has become
   expensive. Deciding provisionally now beats leaving it open, as long as the trigger is written
   down.
6. **Write it where it belongs**: the decision as an ADR, the design that follows from it in the design
   doc, the entry in the architecture's decision register.

Ask one decision at a time. Batch only decisions that are genuinely independent and small.

## 4. What never goes in an ADR

Implementation notes ("as implemented"), dated update logs, experiment results, review history,
protocol reference, how-to steps. They go, respectively, in `docs/modules`, git history,
`docs/investigations`, the PR, a reference doc, `docs/tasks`. An ADR is short and holds one decision.
`references/adr-format.md` has the format, the status lifecycle, and how an ADR may change.

## 5. Hand-off

A milestone is `ready` when its design doc has no open question that would change the plan and
`/core:simplify-design` has reviewed it. Then say so and name `/core:generate-plan <milestone>` as the
next step. Do not write the plan from here.
