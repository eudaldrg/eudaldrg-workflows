# caveman output style: evaluation

Status: **on trial** since 2026-10-04, in two code projects, at project scope. This doc is not a
decision yet; it says what the plugin does, what it costs, what the evidence shows so far, and how
the trial is set up and undone.

[caveman](https://github.com/JuliusBrussee/caveman) is a third-party Claude Code plugin. Two parts
of it matter here, and they have different licenses:

- **The output-style plugin** (repo root plugin: `.claude-plugin/`, `src/hooks/`, `skills/`): MIT.
  This is what is being trialled.
- **The proxy / compression engine** (`engine/`, `proxy/`, `rewriter/`, `mcp/`, `shrink/`, …):
  BSL-1.1. It was measured separately and dropped: it compressed ~0.11% of request tokens, and its
  per-session id line, injected at the head of the conversation, stopped sessions sharing the prompt
  cache (~10k tokens rewritten per new process). Don't route sessions through it.

## What the style plugin does

The plugin works only through the prompt: there is no proxy, and requests are not rewritten. It
consists of two hooks and a skill.

- **SessionStart hook:** injects about 5.2k characters of rules. It runs on startup, resume, clear,
  compact and fork, so the rules come back after compaction. A continuation keeps the session's
  current mode instead of re-deriving the default.
- **UserPromptSubmit hook:** adds a 249-character reminder to every prompt
  ("CAVEMAN MODE ACTIVE (full). Enforce this reply: …"). It also catches `/caveman <level>`,
  "stop caveman" and "normal mode".
- **State:** the mode is stored per session in `~/.claude/.caveman-sessions/<id>.mode`, so an
  explicit "off" survives compaction. Files older than 14 days are removed.
- **Status line badge:** caveman ships `caveman-statusline.sh` for an orange `[CAVEMAN]` badge, but
  Claude Code runs only one `statusLine` command. `core`'s status line (`wf_statusline.py`) reads
  the same per-session state and shows `[CAVEMAN:<level>]` itself, so don't switch to caveman's
  script.

The rules at level `full`:

- **Wording:** drop articles, filler, pleasantries and hedging; fragments are fine. No invented
  abbreviations and no arrows, because they save no tokens.
- **Clarity:** mixed with ASD-STE100 Simplified Technical English. One idea per sentence, about 20
  words at most, active voice, one term per concept. When brevity and clarity conflict, clarity
  wins.
- **Tool calls:** no preamble or progress notes before or between them.
- **Auto-clarity:** switches to normal prose for security warnings, irreversible actions, multi-step
  instructions where order matters, and when the user asks for clarification.
- **What stays normal prose:** code, comments, commits, docs, PR and issue text, and memory files.

Other levels: `lite` keeps articles and full sentences and only cuts filler; `ultra` is terser; the
`wenyan-*` levels write classical Chinese.

## Controls

The default mode is resolved in this order, first match wins:

1. `CAVEMAN_DEFAULT_MODE` env var
2. `.caveman/config.json` or `.caveman.json` in the working directory or the nearest parent that has
   one, e.g. `{ "defaultMode": "off" }`
3. `~/.config/caveman/config.json`
4. `full`

A config file only picks the mode. The plugin itself has to be loaded for anything to happen. During
a session, `/caveman off` or "normal mode" turns it off and `/caveman lite|full|ultra` switches level.

## Cost

Measured with `claude -p "say ok"` with and without the plugin, on Opus 5.5:

| | First request (tokens) |
|---|---|
| Without | 20,791 |
| With | 24,706 (**+3,915**) |

Where the extra comes from, in characters:

| Source | Chars |
|---|---|
| Rules from the SessionStart hook | 5,205 |
| 20 extra skills in the skill listing | 4,232 |
| 3 extra agents (`cavecrew-*`) | 993 |
| Reminder, per prompt (stays in context) | 249 |

This text is identical in every session, so the next session reads it from cache. More than half of
it is the listing for task skills (`lean-build`, `surgical-patch`, `investigate-first`, …) and agents
that the output style doesn't need, and that overlap with `core`'s skills. Claude Code has no setting
to hide one plugin's skills.

## Evidence so far

One A/B on 2026-10-03, measured with [tokentee](https://github.com/eudaldrg/tokentee): 5 interleaved
`claude -p` runs per arm, the same read-only code question, Opus 5.5, read-only tools.

| Mean per run | Plain | caveman full |
|---|---|---|
| Cost | $0.209 | $0.139 (−34%) |
| Cost, warm-cache runs only | $0.146 | $0.096 (−35%) |
| Requests | 5.4 | 4.0 |
| Output tokens | 3,549 | 2,297 (−35%) |
| Final answer length | 4,248 chars | 3,590 chars (−15%) |

- Every answer in both arms was complete: all fields, key facts and file:line citations were present.
- The final answers still read as normal prose; their article rate was unchanged. Most of the saving
  came from fewer steps and less thinking. Thinking tokens were about 290-450 with the plugin against
  400-1,030 without.
- The plugin made runs very consistent: every run took the same number of requests and about the same
  output.

What this doesn't cover yet:

- **Scope:** one task, n=5, and no interactive, editing or long-session work.
- **Hard problems:** whether less thinking costs quality on them.
- **Progress notes:** the rule against them conflicts with Claude Code's own "say what you're doing"
  reminders. The effect is harmless, but expect fewer status lines.

## The trial (2026-10-04)

Two code projects, installed at **local** scope so nothing changes elsewhere:

```
claude plugin marketplace add <path to a caveman checkout>   # once, user scope; only declares it
cd <project> && claude plugin install caveman@caveman --scope local
```

- Plugin enable: `.claude/settings.local.json` gets `enabledPlugins: {"caveman@caveman": true}`.
- Mode pin: `.caveman/config.json` with `{ "defaultMode": "full" }`, in case a user-level default
  changes later.
- Git: both files are listed in that clone's `.git/info/exclude`, so the trial never shows in git.

A `enabledPlugins` entry alone does not load the plugin; it has to be installed for that scope.

In the trial projects, the style is active only in sessions started with plain `claude` (see "How
sessions are launched today" below). A session started through `claude-cave` there gets the proxy
and no style.

## How sessions are launched today

Sessions are opened from Bridge, the tmux-based session manager. Each agent tab has a `caveman`
flag, set at creation (`bridgectl tab create --launch --caveman|--no-caveman`; a fork or resume
inherits the source tab's flag) and changeable on restart (`bridgectl tab restart --caveman|--no-caveman`).
The flag only chooses the launcher binary:

| Flag | Launcher | What the session gets |
|---|---|---|
| off | `claude` | Plain Claude Code, plus Bridge's own `--settings` (status hooks) and `--append-system-prompt-file` (workspace prompt). |
| on | `claude-cave` (`~/.local/bin/claude-cave`, user-written) | Same, and also: requests routed through the caveman **proxy** (`ANTHROPIC_BASE_URL` set to the local proxy, which is started if down); `ENABLE_TOOL_SEARCH=true` by default; `--plugin-dir ~/.local/share/claude-cave/plugin`. That plugin is a generated copy of what `caveman enable claude` writes into settings: the proxy's `native-hook` on every hook event, a `shrink-hook` on PreToolUse, and the caveman MCP server. |

What the "on" launcher injects is the proxy's native core (the "Build simplest complete system…"
SessionStart text, a per-session `caveman-session-v1 sid=…` line, and a per-prompt "task contract"
naming a skill such as `investigate-first`). It does **not** inject the output-style rules this doc
evaluates. The measured −34% came from the style plugin loaded with `--plugin-dir <caveman
checkout>`, not from `claude-cave`.

`claude-cave`'s plugin is also named `caveman`. When both are present, the `--plugin-dir` copy wins
and the installed style plugin is not loaded at all. Checked 2026-10-04: in a trial project, a
session started with the `claude-cave` plugin listed only `caveman@inline` and got no style rules.

Ways to line the Bridge flag up with the style (not done yet):

- **Style only:** make `claude-cave` load the style plugin (`--plugin-dir <caveman checkout>`) and drop
  the proxy, its env and its plugin. This matches the measurements: the proxy saved ~0.11% and cost a
  cache rewrite per session.
- **Both:** rename the generated plugin (e.g. `caveman-proxy` in its `plugin.json`) so the two no
  longer collide, and add the style plugin's `--plugin-dir`.
- Either way, the project-scope installs above become redundant. The Bridge flag is then the only
  switch, and the `.caveman/config.json` files still choose the level.

**How to judge it.** Compare trial sessions with plain sessions of similar work, per session, from the
OpenTelemetry `api_request` events (tokentee's `otel_api_request` table):

- cost per turn
- output and thinking tokens per turn
- requests per turn
- cache read and write

Also note any answer that was hard to follow or missed something.

**Undo:**

```
cd <project> && claude plugin uninstall caveman@caveman --scope local && rm -r .caveman
```

Then remove the two lines from `.git/info/exclude`.

## If it is adopted

- Install at user scope and opt out where it doesn't fit: `{ "defaultMode": "off" }` in a
  directory tree, or `CAVEMAN_DEFAULT_MODE=off` in a launcher.
- Or keep it off by default (`~/.config/caveman/config.json`) and opt code projects in.
- Consider `lite` for sessions where the user reads long explanations.
- Plugins affect only Claude Code: claude.ai chats are unaffected either way.
