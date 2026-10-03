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

The first two are `shared` scope (this plugin repo); the third is `local` scope, resolved to that
specific repo. See "Propose, then ask" below for what each scope means for applying.

**Check the target first.** `git.forbiddenBranchPrefixes` and the plan commit types already encode the
no-`chore` rule; proposing it again would be a duplicate that drifts. A promotion that is already done is the expected result, and
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

## Propose, then ask

Read `${CLAUDE_PLUGIN_ROOT}/references/propose-then-ask.md` for the full mechanics — scope tagging,
the ask/apply/commit flow, `autoLearn.mode`, and why this is safe for a skill (never a hook) to do.
This section only adds what is specific to a correction turning into a rule:

- **the evidence** is a session id, timestamp, and what the user actually wrote
- **the rule** is imperative and narrow enough to be checkable
- **why** is in the user's own terms, because a rule without its reason gets deleted by the next person
  who finds it inconvenient

The Stop hook (`autoLearn.hook.enabled`) only ever appends to `pending.jsonl`, detect-only, per
`AGENTS.md` rule #5. Only this skill, run interactively, turns a pending candidate into a proposal and,
on a yes, an applied change.

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

See `references/propose-then-ask.md` for the apply/commit/scope rules shared with `session-wrap`. Specific
to this skill:

- Never propose a rule you cannot quote the user saying.
- Never generalise a one-off preference. "Ask before opening a PR" is a rule; "the user dislikes PRs"
  is an overreach.
