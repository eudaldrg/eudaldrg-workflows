# Level: milestone

Design one milestone until an implementation plan can be written from it without re-deciding anything.

## Before starting

Read the roadmap entry, the architecture, every ADR the milestone's components touch, and the module
docs for code that already exists (`wf_knowledge.py query --what <component>`). Settle the register
rows whose `Settled by` is this milestone first. Each one is a decision (SKILL.md §3) and an ADR.

## Artifact: `<docsDir>/design/mN-<slug>.md`

- **Goal and exit test**: copied from the roadmap, sharpened if needed (update the roadmap too).
- **Scope / non-goals.**
- **Components touched**: new and changed, with responsibilities.
- **Interfaces and data**: exact shapes, as signatures, schemas or example payloads, not prose. These
  are what the implementation plan's tasks will be verified against.
- **Flows**: the main path and every failure path worth a test (what happens when X is down, malformed,
  slow, duplicated).
- **Decisions**: links to ADRs, one line each. Never restate the reasoning here.
- **Assumptions about later milestones**: what this design assumes about work not done yet, and what it
  would cost if that turned out wrong.
- **Open questions**: each marked `blocking` (changes the plan) or `non-blocking` (the implementer
  decides and records it).

The milestone is `ready` when no `blocking` question is left. Set the roadmap's design status and hand
off to `/core:generate-plan`.
