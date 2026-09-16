---
name: session-briefing
description: Catch up on what happened since the previous working day — Claude sessions, commits across all known projects, open PRs and relevant mail — rendered as a page and opened in a browser. Use at the start of a day, after time away, or when asked what was done recently or which session something happened in.
argument-hint: "[since: previous-working-day | today | 7d | 2026-09-14]"
allowed-tools: Read, Write, Grep, Glob, Bash
---

# session-briefing

Answer one question: **what happened since I last worked, and what should I pick up?**

The scripts gather the facts and you write the narrative. Never hand-write HTML — `wf_render.py`
exists so no token is spent on markup.

## 1. Gather

```bash
SINCE="${1:-$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_config.py" get briefing.since)}"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_sessions.py" list --since "$SINCE" --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_config.py"   projects --json
```

For each project in the registry that still exists on disk:

```bash
git -C <path> log --all --since="<since date>" --author="$(git config user.email)" \
    --format='%h%x09%ad%x09%D%x09%s' --date=short
git -C <path> status --porcelain --branch | head -1
```

**Take commits from `git log`, not from the session JSON.** The transcript only records a commit
structurally when the command printed its usual `[branch sha] subject` line, so anything run with
`git commit -q` is invisible there. The session data is for *narrative* — what you were trying to do —
and git is for *facts*.

If `briefing.sources` includes `gmail`, search the connector for mail since the same date that
concerns these repos — review requests, CI failures, anything naming a project. Skip it silently if
the connector is not available; a missing integration is not a reason to fail a briefing. Calendar is
deliberately not a source.

## 2. Write

Lead with what actually matters. A briefing that opens with a table of session ids has buried the
point. Something like:

```markdown
# Wednesday 16 September

You spent yesterday on the workflows plugin and finished the plan pair. `widgets-api` has one
branch with uncommitted work.

## Picking up

- `feature/webhook-ingest` in widgets-api — 6 commits, tree dirty, PR #1 still open
- The clang-tidy pre-commit hook still points at `-p build`, which does not exist

## Yesterday

<two or three paragraphs, per project, saying what was done and why>

## Commits

| Project | Sha | Branch | Subject |
```

Rules for the narrative:

- **Say what was accomplished, not what was typed.** "Added the two-axis knowledge retrieval" beats
  "16 prompts, 33 files touched".
- **Name the loose ends.** A dirty tree, an open PR, a branch that never merged, a task that stopped
  after three failed attempts — those are the reason to read a briefing at all.
- Include counts and costs only where they inform a decision. Nobody needs a tool-use histogram.
- If a session ended mid-task, say so and say where it stopped.
- Do not invent continuity between unrelated sessions.

Keep to the subset `wf_render.py` supports — run it with `--supported` if unsure.

## 3. Render and open

```bash
OUT="$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_config.py" get briefing.outDir)/$(date +%F).html"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_render.py" briefing.md --subtitle "<range>" -o "$OUT"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_open.py" "$OUT"
```

`wf_open.py` exits 1 and prints the path when there is no browser — that is a complete outcome on a
headless box, not a failure. Honour `briefing.openBrowser: false` by skipping the last step. If
`briefing.format` is `markdown`, print the markdown and skip rendering entirely.

## Finding an old session

The reader covers all history, so it also answers "which session was it where I did X":

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_sessions.py" search "clang-tidy" --since all
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_sessions.py" show <id-prefix>
```

`search` matches human prompts only — what *you* asked, not what Claude replied. That is usually the
right index into a session, and it keeps the result set small enough to read.

## Hard rules

- Never write HTML by hand, and never add a CDN link or web font to the rendered page. It has to open
  from disk in five years.
- Never edit or delete anything under `~/.claude/projects/`. That directory is read-only to this skill
  — it is the only copy of that history.
- If `wf_sessions.py verify` reports unknown line types or unparseable lines, say so in the briefing.
  Silent drift is how a reader ends up trusting an incomplete picture.
- Sessions with no resolvable project are scratch runs and are excluded by default. Do not "fix" that
  by attributing them to the directory name — the directory is named after a stale path.
