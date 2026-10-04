---
name: setup-lean-context
description: Apply, check or revert the lean startup context settings in ~/.claude/settings.json — deny the Artifact tool, defer MCP tool schemas behind ToolSearch, turn off prompt suggestions. Use when asked to shrink the startup context or per-request token cost, to disable artifacts or prompt suggestions, on a new machine, or to check whether the Artifact deny can be lifted.
argument-hint: "[status | apply [--force] | revert]"
allowed-tools: Read, Bash
---

# setup-lean-context

Read `${CLAUDE_PLUGIN_ROOT}/references/lean-context.md` for the reasoning, the measurements, what
each setting costs, and when to lift the Artifact deny. In short, the first request of a session was
~121k tokens and every later request re-reads it; these three settings took it to ~39k:

| Key in `~/.claude/settings.json` | Value | Effect |
|---|---|---|
| `permissions.deny` | gains `"Artifact"` | drops the ~11.3k-token Artifact tool (and its companions) |
| `env.ENABLE_TOOL_SEARCH` | `"true"` | MCP tools sent by name only; schemas fetched on demand |
| `promptSuggestionEnabled` | `false` | no full-context suggestion request per turn |

A plugin manifest cannot contribute `permissions`, so this must be written by an explicit
invocation, never a hook. Global by design: the saving applies to every project.

## Procedure

1. See where the machine stands:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_lean_context_setup.py" status
   ```

   It prints each setting and what `apply` would change. Nothing is written.

2. Apply (preview first with `--dry-run` if the user wants to see it):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_lean_context_setup.py" apply
   ```

   The deny entry is merged into any existing list. If the file already sets
   `ENABLE_TOOL_SEARCH` or `promptSuggestionEnabled` to some other value explicitly, the script
   refuses and shows it: that was someone's choice. Confirm with the user before re-running with
   `--force`.

3. Tell the user it takes effect in the **next** session, and that pages and diagrams now go to
   local `.html` files through the `html-design` / `html-diagramming` skills instead of artifacts.

To undo, `revert` (also takes `--dry-run`) removes the three values and returns to Claude Code's
defaults. A value it did not set — say `ENABLE_TOOL_SEARCH="auto:5"` — is kept and reported.

To check whether the Artifact deny is still worth it, follow "When to re-enable Artifact" in the
reference: revert, run one plain interactive session, inspect the transcript's `prompt_snapshot`,
then re-apply or leave it off.

## Hard rules

- Never invoke this from a hook. Only run it when the user asks.
- Never hand-edit these keys for this purpose — go through `wf_lean_context_setup.py`, so the
  merge and the revert stay exact.
- Measure interactively. `claude -p` never includes the Artifact tool, so a headless comparison
  shows no difference and proves nothing.
