---
name: investigate
description: Investigate a question about this codebase in depth, read-only, and return a cited findings report. Use when the user asks to investigate, dig into, research, or understand how something works, or asks a "why is it like this" question that needs evidence rather than a guess. Writes no code and makes no commits.
argument-hint: "<question to investigate>"
context: fork
agent: investigator
background: false
---

# investigate

Run the user's question as a read-only investigation in an isolated agent, then present what comes
back.

The point of the isolation is twofold: the agent has no `Edit`/`Write`, so it structurally cannot
change the repo while poking at it; and a long investigation's tool output stays out of the main
conversation, so only the findings land here.

## What to pass the agent

The user's question, as they asked it. Add the concrete context they would otherwise have to
re-derive:

- the repo root and current branch
- which files or areas they have been working on, if that came up earlier in the conversation
- anything already ruled out in this session, so it does not get re-investigated
- whether the question is about the current project or another one

Do not rewrite their question into something narrower. If it is genuinely ambiguous, ask them before
dispatching rather than guessing — a fork cannot come back for clarification.

## When the report comes back

Present the answer and its evidence. Do not re-run the investigation in the main session to
double-check it; if a claim looks wrong, say which one and why.

Then offer to save it, and only write the file if the user says yes:

```
docs/investigations/<YYYY-MM-DD>-<slug>.md
```

The agent never writes. Any file that gets written is written here, in the main session, after the
user asks for it.

If the report surfaced something actionable under "Worth knowing" — a bug, a stale doc, a
contradiction — surface that too rather than burying it. It is often the most valuable part.

## Hard rules

- Never commit, stage, push, or open a PR as part of an investigation. This skill produces knowledge,
  not changes. If the findings suggest work, that is a separate conversation.
- Never act on the findings in the same turn. Report first.
