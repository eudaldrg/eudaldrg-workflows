---
name: auto-learn
description: Promote rules that are stuck in one project's memory to where they actually belong, and fill in corrections no session ever recorded. Use periodically, after a project's conventions change, or when asked what Claude should have learned but did not.
argument-hint: "[--since <spec>]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash
---

# auto-learn

This skill does **not** compete with Claude Code's own memory. In-session capture is strictly better
at noticing a correction: it sees the prompt before it can be lost, has the full context, and knows
what it just did. `commit_attribution` proves the asymmetry — it reached memory, and its originating
prompt is not in any transcript on disk, so no retrospective sweep could ever have found it.

So this skill has the two jobs memory structurally cannot do.

## Job 1 — promotion

Memory is stored per project directory. There is no global memory. A rule learned in one repo is
invisible to every other repo, however universal it is.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_sessions.py" memory --json
```

For each `feedback` memory, ask: **is this rule really about that one repo?**

- *"Always ask before opening a PR in widgets-api"* — repo-specific unless the user says otherwise.
- *"Don't call things chores, use feature/"* — vocabulary, not a repo policy. Belongs everywhere.

A rule that belongs everywhere goes to one of:

| Kind of rule | Target |
|---|---|
| A setting with an existing key | `defaults/workflows.defaults.json` — e.g. `git.forbiddenBranchPrefixes` |
| How a workflow skill should behave | the relevant `skills/<name>/SKILL.md` |
| A convention for one other repo | that repo's `AGENTS.md` |

**Check the target first.** `git.forbiddenBranchPrefixes` already encodes the `chore/` rule; proposing
it again would be a duplicate that drifts. A promotion that is already done is the expected result, and
saying so is a real answer.

Also report `orphaned` slugs. Those hold rules for a project that no longer resolves — usually a
rename — so that project silently lost its memory and the rules need re-homing.

## Job 2 — gap-fill

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_sessions.py" memory --json      # the `gaps` array
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_sessions.py" corrections --since <spec> --json
```

A project with correction candidates and **no memory file** is a session that should have noticed and
did not. That is the only case where mining old transcripts beats having been there, and it is worth
the false positives.

**Candidates are narrowed, not classified.** The filter is lexical — it reads what the human wrote. It
deliberately does *not* select on tool errors, permission denials, `userModified` or interrupted turns:
measured across every transcript on this machine, **not one of those is ever followed by a human
prompt**. They mark trouble Claude resolved by itself, and they appear under `precededBy` as context
only. Expect roughly one false positive in four. The filter is tuned for recall because you are the
precision.

## Read each candidate in context

A prompt alone cannot tell you what rule to write. Open the transcript at that timestamp and read what
Claude did immediately before:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_sessions.py" show <session> --json
```

Then classify:

- **A correction** — Claude did something the user did not want. This becomes a rule.
- **A clarification** — the user is refining a request they made imprecisely. No rule; Claude was not
  wrong.
- **A question** — the user is asking Claude to justify something. A correction sometimes hides inside
  one ("Is this something I asked or something you proposed?" did), so read the answer Claude gave.
- **A change of mind** — the user wants something different now. No rule; nothing was wrong then.

Record the rejects too, with which class they fell into, so the next run does not re-litigate them.

## Propose, never apply

Each proposal carries:

- **the evidence** — session id, timestamp, and what the user actually wrote
- **the rule**, imperative and narrow enough to be checkable
- **why**, in the user's own terms, because a rule without its reason gets deleted by the next person
  who finds it inconvenient
- **the exact diff** — the lines to add and the file to add them to
- **what it would have changed** in the session it came from

Append to `${CLAUDE_PLUGIN_DATA}/learnings/proposals.jsonl` so they outlive the session, present them
in the conversation, and stop.

**Never edit `AGENTS.md`, a SKILL.md, a config file or a memory file from this skill.** Not even one
the user obviously wants. A system that rewrites its own instructions from inferred corrections is a
system nobody can audit.

## Checking the detector still works

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_sessions.py" corrections --since all --validate
```

Memory files quote what the user said, which makes them a free labelled set. Validation matches on the
longest shared *run* of words, not word overlap — overlap scored 0.75 against an unrelated prompt on
common English alone and reported a correction found whose prompt is not on disk.

- `found` — surfaced
- `no prompt` — not in any transcript, so it **cannot** be found. A fact about the corpus, not a failure
- `MISSED` — on disk and not surfaced. The real failure: add a case to `CORRECTION_CUES` in
  `wf_sessions.py`, do not lower the threshold

Non-zero exit means at least one `MISSED`.

## When to delete this skill

Its value is unproven: the cue table is tuned on 43 prompts from one user, and the first full sweep
produced no new proposals. **If three real sweeps in a row produce nothing actionable — no promotion,
no gap worth filling — delete the skill and keep `wf_sessions.py corrections` as a plain query.** This
is written down deliberately, so the decision is made on evidence rather than defended out of sunk cost.

## Hard rules

- Never apply a proposal.
- Never write outside `${CLAUDE_PLUGIN_DATA}`. The user's repos are read-only here.
- Never propose a rule you cannot quote the user saying.
- Never generalise a one-off preference. "Use `feature/` not `chore/`" is a rule; "the user dislikes the
  word chore" is an overreach.
- Never propose something the target file already says.
