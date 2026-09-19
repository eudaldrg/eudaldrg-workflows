---
name: setup-statusline
description: Install or refresh the shared Claude Code status line (host:wd, git branch, model, effort, context usage, cost) into ~/.claude/settings.json, pointed at this plugin's script. Use when asked to set up, enable, update, or fix the status line/status bar, or after the plugin moves/updates and the status line stops working.
argument-hint: "[--force]"
allowed-tools: Read, Bash
---

# setup-statusline

Claude Code's `statusLine` setting cannot be contributed by a plugin manifest — only `agent` and
`subagentStatusLine` are pluggable — so this must be written into `~/.claude/settings.json` by an
explicit invocation, never a hook. This skill exists to do that write safely: it touches only the
top-level `statusLine` key and leaves the rest of the file alone.

## What it deploys

`${CLAUDE_PLUGIN_ROOT}/scripts/wf_statusline.py` renders:

```
<host>:<wd> (<branch><dirty>) <model> [<effort>] <used>/<cap> (<pct>%) $<cost> ($<rate>/hr)
```

On a narrow terminal (e.g. a phone) the segments wrap onto extra rows instead of being
cut off. The width is read from the tmux pane, then `$COLUMNS`, then `statusLine.maxWidth` in the
layered config (default `0` = never wrap, one row).

Every segment after `<host>:<wd>` drops out independently when its data isn't available (no git
repo, model without an effort parameter, session too short for a burn rate). Thresholds for the
color-coded context percentage and cost live in the layered config under `statusLine.*` — see
`${CLAUDE_PLUGIN_ROOT}/defaults/workflows.defaults.json` for the defaults and
[[wf_config]] docs for how to override them per-machine (`~/.claude/workflows.json`) or per-project
(`.claude/workflows.json`).

## Procedure

1. Preview what would be written:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_statusline_setup.py" show
   ```

2. Apply it:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_statusline_setup.py" apply
   ```

   This is global (`~/.claude/settings.json`), by design — the status line is meant to be the same
   across every project. If `~/.claude/settings.json` already has a `statusLine` block that this
   script didn't write (no `wf_statusline.py` in its command), it refuses and shows the existing
   block rather than clobbering someone's hand-written config. Confirm with the user before
   re-running with `--force` to overwrite it.

3. Sanity-check the script actually runs, using the sample payload from Claude Code's docs:

   ```bash
   echo '{"model":{"display_name":"Sonnet 5"},"workspace":{"current_dir":"'"$PWD"'"},"cwd":"'"$PWD"'","cost":{"total_cost_usd":0.42,"total_duration_ms":120000},"context_window":{"total_input_tokens":42000,"context_window_size":200000,"used_percentage":21.0}}' \
     | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_statusline.py"
   ```

   A blank line or a traceback means something is wrong before the user ever sees it live — the
   real status line only shows blank on failure, with no error surfaced in the UI.

4. Tell the user it takes effect on the next status line refresh (next assistant turn) — no
   restart needed.

## Hard rules

- Never invoke this from a hook. Only run it when the user explicitly asks to set up, update, or
  fix the status line.
- Never hand-edit `~/.claude/settings.json` yourself for this — always go through
  `wf_statusline_setup.py`, so the "did this plugin write it" check stays reliable for next time.
- If the user asks for a per-project status line instead of global, that's a deliberate deviation
  from this skill's default — write the same block into that project's `.claude/settings.json`
  instead, and say so explicitly, since it means other repos won't get it.
