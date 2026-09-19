---
name: setup-git-diff
description: Install and configure difftastic (structural diffs) and delta (pager) for git on this machine, behind opt-in aliases — git dft, git ddiff, git dlog, git dshow. Use when asked to set up, deploy, update or remove difftastic/delta/better git diffs, on a new machine, or when `git dft` stops working.
argument-hint: "[--force | --upgrade | --no-install]"
allowed-tools: Read, Bash
---

# setup-git-diff

Makes git diffs readable for the human at the terminal without changing what scripts and agents
see. Global (`~/.gitconfig`), by design — the same viewers on every project. Gated by
`gitDiff.enabled` in `~/.claude/workflows.json`, so a machine only gets this when it opts in.

## What it deploys

| Command | What you get |
|---|---|
| `git dft [args]` | `git diff` through difftastic, side-by-side |
| `git ddiff [args]` | `git diff` through difftastic, inline (one column — use on a narrow terminal) |
| `git dlog [args]` | `git log -p` through difftastic |
| `git dshow [args]` | `git show` through difftastic |
| plain `git diff/log/show` | unchanged data; paged through **delta** when it is installed |

Deliberately **not** `diff.external`. That setting replaces the output of every `git diff` and
`git log -p` with difftastic's non-patch text, which breaks anything that parses a unified diff —
agents, `git apply` pipelines, and GUIs that shell out to `git diff` and render the result
themselves. Delta is a pager, so git starts it only for a terminal; piped output stays a plain
unified diff. The aliases override the pager to `less` for their own run, because delta expects
patch text.

Everything is written to one generated include file, `~/.config/git/wf-diff.gitconfig`, pulled in
by a single `include.path` line in `~/.gitconfig`. It carries a provenance header and no
timestamp, so re-running with no change produces no diff. `remove` undoes it cleanly.

Delta is only wired in if `delta` is already on `PATH`: a `core.pager = delta` with no delta
installed would break every paged git command.

## Procedure

1. See where the machine stands:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_gitdiff_setup.py" status
   ```

2. If it reports `enabled: False`, opt the machine in. Ask first when the user hasn't said to set
   this machine up; then add to `~/.claude/workflows.json` (create it if missing, keep other keys):

   ```json
   { "gitDiff": { "enabled": true } }
   ```

   Other knobs, all under `gitDiff` (defaults in `defaults/workflows.defaults.json`):
   `difftastic.enabled`, `difftastic.version` (`"latest"` or a pinned tag), `difftastic.installDir`
   (`~/.local/bin`), `delta.enabled`.

3. Preview, then apply:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_gitdiff_setup.py" show
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_gitdiff_setup.py" apply
   ```

   `apply` downloads the prebuilt `difft` release for this OS/arch into the install dir when it is
   not already on `PATH` (`--upgrade` re-downloads; `--no-install` never downloads). If
   `~/.gitconfig` already sets any key this would manage, it refuses and lists them — show the user
   and only re-run with `--force` on their say-so.

4. Delta needs a system package, and this skill must not run `sudo`. If `apply` says delta is
   missing, tell the user to run it themselves, then re-run `apply`:

   ```
   ! sudo apt install git-delta      # or: brew install git-delta
   ```

5. Verify in a repo with uncommitted changes:

   ```bash
   git dft | head -20
   git diff | head -5        # must still start with "diff --git"
   ```

   If `apply` warned that the install dir is not on `PATH`, the user needs to add it — the aliases
   call a bare `difft`.

## Using difftastic as an agent

Default to plain `git diff`. Models read `+`/`-` unified hunks best, difftastic output has no
patch markers, and structural diffing hides formatting-only changes — exactly what you need to see
when checking your own edit. The exception is reviewing a large refactor or reformat, where the
noise drowns the real change: run `git ddiff` (inline; without a terminal difftastic emits no
color) and say you did.

## Hard rules

- Never invoke this from a hook. Only run it when the user asks to set up, update, fix or remove
  it.
- Never hand-edit `~/.gitconfig` or the include file for this — always go through
  `wf_gitdiff_setup.py`, so drift detection and `remove` stay reliable.
- Never set `diff.external` globally, and never add `--no-ext-diff` workarounds: the whole design
  is that plain `git diff` stays untouched.
- Never run `sudo` on the user's behalf.
