# ADR format

An Architecture Decision Record (Nygard, 2011) captures **one architecturally significant decision**:
the question, the options that were really on the table, what was chosen, and what it costs.
"Significant" means **expensive to reverse**. An ADR is what someone reads when they want to change
the decision, so it has to show the trade-off, not just the outcome.

## Is it an ADR at all?

Write an ADR only if all three hold. `/core:simplify-design` applies the same test to existing ones.

1. **It is expensive to reverse**, now or soon: a contract between components, a data or wire format
   with data or users depending on it, a threading or ownership model, a pattern that will spread
   across the codebase, an external commitment. If one commit (or one LLM session) can undo it, it is
   not an ADR.
2. **It constrains something, and says what that protects against.** "Because otherwise …" must
   have an answer. A choice among roughly equivalent options with nothing to protect is a preference.
   Record it in the design doc and move on.
3. **It cannot be a setting instead.** If the right value depends on the machine or the load (core
   affinity, buffer sizes, which exchanges are enabled), the decision is "this is configurable", not
   the value.

Everything else goes in the design doc, which is meant to change as the project learns.

### Decide how to change things, not only what they are

Often the durable decision is a **change policy**, not a choice. "No backward-compatibility promise
until there are external users; a serialization format change must migrate all stored data or keep a
reader for it" makes every format change cheap and safe, while "use format X" just sits there waiting
to be superseded. Prefer the change policy. Such a policy is usually a good ADR in its own right.

### Staged plans are one decision

"v1: one core, one book. Target: sharded by symbol. Trigger: one core cannot keep up." The decision
is the seam that makes the stage change cheap (books keyed by symbol behind per-feed queues), not the
v1 configuration. Write it staged so reaching the target is not a reversal.

## Status

- `proposed`: the default. Being discussed or used, still cheap to change. A young project with no
  users and no data to keep has little that is more than `proposed`.
- `provisional`: chosen, but a known later event may change it. Requires *Revisit when*.
- `accepted`: reversing it is now expensive (users, stored data, many dependents), and that cost has
  been weighed. Only a human moves an ADR here.
- `superseded`: replaced by a later ADR. Moved to `decisions/superseded/`.
- `rejected`: considered and not taken. Moved to `decisions/superseded/` if kept at all.

## Template

```markdown
# NNNN. <The question, answered in a few words>

- Status: proposed | provisional | accepted
- Date: YYYY-MM-DD (of the status)
- Settled at: <milestone>          # the roadmap milestone this belongs to
- Revisit when: <trigger>          # required for provisional
- Supersedes: NNNN                 # only if it replaced one

## Context
The forces: what makes this a decision, what it protects against, what is known and what is assumed.
A few paragraphs at most.

## Options
### A. <name>
What it makes easy. What it makes hard. What reversing it would cost.
### B. <name>
…

## Decision
<Option>, because <the deciding reasons, in terms of the options above>.

## Consequences
What becomes easier, what becomes harder, what is now constrained, and — as important — what this
decision deliberately does **not** constrain.

## Changes
- YYYY-MM-DD: <from → to>, because <one line>.     # proposed/provisional revisions only

## Evidence
Links only: investigations, benchmarks, probes that informed it.
```

## Changing an ADR

- **`proposed` / `provisional`**: edit freely. When the Decision itself changes, rewrite it and add one
  line under `Changes`. One line per change, not a narrative. Git keeps the rest.
- **`accepted`**:
  - Clarifications and corrections are edited in place.
  - Reversing the core decision is a new ADR with its own context (what was learned), `Supersedes:`
    the old one. Rare by construction, because only expensive decisions are `accepted`.
- **Superseded and rejected ADRs leave the main folder:** `git mv` them to `decisions/superseded/`
  and replace their status line with `Status: superseded by NNNN — do not follow`. An agent grepping
  `decisions/*.md` then only finds current decisions. One that greps recursively still meets the
  warning on line 3.
- **Sessions never change a Decision on their own**, whatever the status. They propose, and a human
  approves.

## Rules

- **One decision per ADR.** A bundle cannot be superseded in part, and its incidental details end up
  carrying the same authority as its core choice.
- **At least two real options.** An ADR with one option is an announcement.
- **Short.** Around a page. Longer means it contains design (→ design doc), implementation
  (→ `docs/modules`), or evidence (→ `docs/investigations`).
- **Not in an ADR:** "as implemented" notes, dated update logs, experiment results, review history,
  protocol reference, how-to steps.

## Authority

An ADR binds its **Decision**, not everything its text mentions. When work seems to conflict with one:

1. Check whether the conflict is with the decision itself or with a detail written nearby. Details carry
   no authority.
2. If it is the decision: say so, and propose a change (edit if `proposed`/`provisional`, superseding
   ADR if `accepted`). Don't silently work around it, and don't refuse the work because "the ADR says
   so".
3. A `proposed` decision is a working assumption. Expect to change it when the work shows it wrong.
