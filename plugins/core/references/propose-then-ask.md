# Propose, then ask

Shared mechanics for any skill that finds a change worth making to a repo it did not open specifically
to edit — currently `auto-learn` and `session-wrap`. The rule this exists to keep is: **a proposal is
safe to apply the moment a human confirms the exact diff, in this conversation, this run** — nothing
more is needed, and nothing less is enough.

## Why this is safe, and where the line is

A skill invocation always has a human turn right there reading the output. That is different from a
hook, which runs unattended between turns — `AGENTS.md` rule #5 ("never mutate a user's repo from a
hook") exists for that unattended case and stays absolute. It does not extend to a skill a human is
watching: a confirmed diff *is* the audit trail, and queuing it to a file the user has to separately
remember to open buys no extra safety, only a proposal that quietly never gets reviewed.

So a hook that feeds one of these skills stays detect-only, appending candidates to a plain pending
file. Only the skill itself, run interactively, turns a candidate into a proposal and, on a yes, an
applied change.

## Scope

Every proposal is tagged with where it would land:

- **`shared`** — this plugin repo (`my_workflows`). Resolve the path from `${CLAUDE_PLUGIN_ROOT}`'s repo
  root, never the current project's working tree, even when the skill happens to be running from inside
  it.
- **`local`** — one specific project, named. If it is not the current repo, resolve its path via
  `wf_config.py projects --json`. Never guess a path.

## The proposal

Each one carries, at minimum:

- **the evidence** — what was actually observed (a session id and timestamp, a quote, a diff, whatever
  grounds the claim), because a rule nobody can trace back to something real gets deleted by the next
  person who finds it inconvenient
- **the rule or finding**, stated narrowly enough to be checkable
- **why**, in the terms of whoever it came from
- **scope** — `shared` or `local`, per above
- **the exact diff** — the lines to add and the file to add them to
- **what it would have changed**, concretely, in the situation that produced it

Append every candidate to `${CLAUDE_PLUGIN_DATA}/learnings/proposals.jsonl` first, unconditionally, with
a `"source"` field naming which skill produced it. That line is what survives a killed session and
stops a candidate from being proposed twice.

## Ask, then apply

In this conversation, ask about each candidate individually: apply, skip, or defer. This is `ask` mode,
and it is the default. Each skill exposes its own `<skillName>.mode` key (`ask` / `queue`) in
`workflows.defaults.json`; setting it to `queue` falls back to propose-and-stop — append the candidate
and present it, but never apply — which is the right choice for someone who wants more ceremony than
the skill's author does.

**On apply**, write only the specific file the confirmed diff named, only after that specific item was
confirmed, this run. Commit immediately — one commit per confirmed proposal, in the repo it actually
belongs to (per its scope), message naming the rule and citing where it came from. **Never `git push` or
open a PR** — that is the same ask-before boundary every other skill in this plugin uses for anything
that leaves the local repo.

Write the outcome (`applied`, `skipped`, `deferred`) back onto that proposal's line so a re-run does not
ask about it again. `deferred` may be re-asked next run; `skipped` may not, unless the user asks to
revisit rejects.

## Hard rules

- Never apply a proposal without the user confirming that specific item, in this conversation, this
  run. A prior yes to a different proposal does not carry over.
- Never write to a file the confirmed diff did not name.
- Never push or open a PR, applied proposal or not.
- Never propose something the target file already says.
