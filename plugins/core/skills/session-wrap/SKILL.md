---
name: session-wrap
description: Review one session — this one, or a past one by id — for corrections, mistakes, and workflow gaps, and decide whether this project's docs or this plugin's skills should change because of it. Use at the end of a working session, or when asked what should be documented from what just happened.
argument-hint: "[--session <id>]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash
---

# session-wrap

`auto-learn` is broad, cross-project and periodic: it promotes rules already stuck in memory, and
gap-fills projects whose sessions never recorded a correction at all. This skill is the opposite grain:
one session, reviewed close to the event, asking a narrower question — not "should this be a memory
rule" but **"does this deserve a project doc, or a fix to this plugin, instead of just a personal
memory entry that only this project's future sessions will ever see"**.

## Which session

Default: this conversation, right now. Reason directly over what already happened — no transcript
re-read needed, for the same reason `generate-plan` runs in the main session instead of a fork: you
already have the context, and reconstructing it from a transcript would throw information away.

With `--session <id>` — a session that already ended:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_sessions.py" show <id> --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_sessions.py" memory --json
```

Cross-check `memory --json` for the same project and skip anything already recorded as a memory rule.
That gap is `auto-learn`'s Job 2, not this skill's.

## Find what's worth keeping

Look for:

- **A correction you received** — not only a verbal "no, do it like X," but a live workflow correction:
  the user pointing out a branch was cut without fetching, a step skipped, an assumption that was wrong.
- **A mistake that cost real rework** — something no existing check, doc, or convention caught, because
  none existed.
- **A decision that took real discussion to reach** and would take just as much again next time,
  because nothing wrote it down. (A plan directory silently drifting back to a Claude-Code-specific path
  because the earlier decision to move it was never recorded anywhere is exactly this shape.)

A session with none of these is a real, boring, correct answer. Do not manufacture a finding to have
something to report.

## Classify each finding

- **Already covered** — an existing doc, `AGENTS.md` line, or memory rule already says this. Say so and
  propose nothing.
- **`local`** — true only of this project, or of how to work in it.
  - Doc-shaped (a component, a procedure, a decision) → the proposal is an `/core:update-knowledge`
    invocation, not a hand-authored diff. That skill owns axis-picking, frontmatter, and
    extend-before-create; duplicating its rules here is exactly the drift this skill exists to avoid
    elsewhere.
  - Not doc-shaped (an `AGENTS.md`-level convention) → propose a direct diff against that file.
- **`shared`** — about how any agent using this plugin should behave, in any project. Propose a direct
  diff against this plugin repo, same path as `auto-learn`'s `shared` proposals.

If a `local` finding is doc-shaped and the project has no `docs/modules`/`docs/tasks` at all:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_knowledge.py" list [--where <project>] --json
```

An empty list is not a blocker. `/core:update-knowledge` creates the first doc on an axis the same way
it extends an existing one — say plainly that this would be the project's first doc on that axis, and
propose it anyway.

## Propose, then ask

Read `${CLAUDE_PLUGIN_ROOT}/references/propose-then-ask.md` for the shared scope/ask/apply/commit
mechanics. This skill's proposals additionally carry:

- **what actually happened** — quoted from this conversation, or cited from the `--session` transcript
  (tool call, commit, or exact user text)
- for a `local`, doc-shaped finding: the exact `/core:update-knowledge` invocation to run on yes, not a
  diff this skill authored itself

`sessionWrap.mode` (`ask` default, `queue`) controls ask-vs-queue exactly like `autoLearn.mode`.

## Hard rules

- Never write doc content yourself for a `local`, doc-shaped finding. Invoke `/core:update-knowledge`.
  This skill decides *whether* something should be documented, not *how*.
- There is no Stop hook for this skill. Every candidate here came from a live, human-in-the-loop read
  of a transcript — never treat one as pre-reviewed the way a hook-produced candidate would be.
- Never fabricate a finding to avoid reporting "nothing to propose."
- Everything else — see `references/propose-then-ask.md`.
