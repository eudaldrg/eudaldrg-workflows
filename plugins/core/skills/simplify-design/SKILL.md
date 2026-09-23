---
name: simplify-design
description: Review ADRs and design docs for rules that should not be rules — decisions that are cheap to reverse, constraints with no stated reason, values that should be settings, bundled or stale ADRs — and propose moving, downgrading, splitting or dropping them. Use after a design session, before a milestone is marked ready, when ADRs feel like they block ordinary changes, or when asked whether something should be an ADR.
argument-hint: "[path to decisions/ or a design doc, default: this repo's]"
allowed-tools: Read, Grep, Glob, Bash, Write, Edit
---

# simplify-design

The design equivalent of simplifying code: every rule in a design must pay for itself. A rule that
constrains without protecting anything makes every later change fight it.

Read `${CLAUDE_PLUGIN_ROOT}/references/adr-format.md` first. Its "Is it an ADR at all?" test is the
standard this skill applies.

## Review from the files, not the conversation

Judge only what is written. If a reason exists only in the author's head (or in the conversation that
produced the design), the design does not have it, and the next session will not either. That is a
finding, not something to fill in charitably.

## For every decision found

That means each ADR, and each rule-shaped statement in a design doc ("X must", "always", "never", "only").
Answer:

1. **What does it protect against?** Quote the text that says so. None → it is a preference.
2. **What would reversing it cost today?** Concretely: users, stored data, dependent components,
   lines of code. Cheap → it is not an ADR (yet).
3. **Could it be a setting?** If the right value depends on the machine or the load, decide
   "configurable", not the value.
4. **Is there a change policy hiding in it?** "Use format X" is often better written as "formats may
   change if stored data is migrated".
5. **Is it one decision?** A bundle should be split, and the incidental parts moved out.
6. **Are there real options?** Only one option means it was an announcement.
7. **Is the status honest?** `accepted` in a project with no users and no data to keep usually means
   `proposed`.

## Verdicts

One per item, with a one-line reason:

| Verdict | Meaning |
|---|---|
| keep | a real, expensive-to-reverse decision with its trade-off shown |
| fix | a real decision, but missing options, the "because otherwise", or an honest status |
| split | several decisions bundled: name the parts |
| make tunable | the decision becomes "configurable"; the value moves to config |
| rewrite as policy | replace the frozen choice with the rule for changing it |
| move to design doc | a real choice, but cheap to reverse |
| move to modules / investigations / tasks | not a decision: implementation facts, evidence, procedure |
| drop | constrains nothing anyone would miss |
| supersede | contradicted by what the code does now: the design lost, and the record should say so |

## Output

A table: item, verdict, reason, and the exact destination for anything that moves. Then the proposed
edits, grouped per destination file.

Apply nothing until the human confirms, per `${CLAUDE_PLUGIN_ROOT}/references/propose-then-ask.md`
(this skill's scope is always `local`). Moves use `git mv` where a whole file moves. Content moved
out of an ADR is **moved**, not copied: the ADR loses it.
