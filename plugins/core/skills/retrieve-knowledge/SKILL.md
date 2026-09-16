---
name: retrieve-knowledge
description: Find the project documentation relevant to what you are about to do, by component and by activity. Use before working on an unfamiliar module, before running an unfamiliar procedure (deploy, replay, testing, profiling), or when asked what the project already documents about something. Also reaches other known projects on this machine.
argument-hint: "[module] [activity]"
allowed-tools: Read, Grep, Glob, Bash
---

# retrieve-knowledge

Knowledge lives on two axes — components (`docs/modules/`) and activities (`docs/tasks/`). Read
`${CLAUDE_PLUGIN_ROOT}/references/knowledge-format.md` for the full convention.

## Procedure

Work out which point on each axis the question implies. "How do I test the feed handler" is
module `feed-handler` + activity `testing`. Either may be absent — "how do we deploy" is activity only.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_knowledge.py" query \
  --what <module> --why <activity> [--where <project|path>] --json
```

Then **read the files it names**. The summaries in the output are routing hints, not evidence — never
answer from them. The `related` list contains ADRs that constrain the component; read those too when
the question is architectural.

`--where` defaults to the current project. Pass a registry name or a path to reach another project on
this machine; `wf_config.py projects` lists them. Use it when the question is explicitly about another
repo, or when this project's docs refer to one.

## When a lookup misses

The tool lists what *does* exist on that axis. Use it:

- **Close name** — the user said `feed` and the doc is `feed-handler`: resolution already tries aliases
  and normalization, so a miss here means it genuinely is not there.
- **Wrong axis** — "replay" might be a module in one project and an activity in another. Check both
  before concluding it is missing.
- **Genuinely absent** — say so plainly, then fall back to `rg` over `git ls-files` and answer from the
  code. Finish by noting that the answer was not documented, and offer `update-knowledge`. A question
  that the code answered and the docs did not is exactly the signal that a doc is missing — surface it,
  do not silently move on.

An `alias-conflict` or `ambiguous` result means two docs claim the same name. Report both and ask;
never pick one.

## Staleness

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_knowledge.py" stale [--where <project>] --json
```

If a doc you are about to rely on is `possibly-stale`, say so **before** using it, and name the source
files that moved. A confidently-cited stale doc is worse than no doc. Verify the claim against the code
before repeating it.

## Hard rules

- Never answer from a summary. Open the file.
- Never edit a doc from this skill — that is `update-knowledge`.
- Never invent a module or activity name that has no doc. If it does not exist, say it does not exist.
