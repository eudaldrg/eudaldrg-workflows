# my_workflows

Personal coordination layer for how I use LLM coding agents (Claude Code today, others later)
across all my projects. This repo is a Claude Code **plugin marketplace**: it packages reusable
skills, agents and shared rules, and documents the conventions I want followed everywhere —
including in other, unrelated project repos.

This file is the single source of truth. `CLAUDE.md` is a symlink to it — edit `AGENTS.md`.

## Repo layout

```
my_workflows/
  .claude-plugin/marketplace.json     # marketplace manifest ("eudaldrg-workflows")
  plugins/core/
    .claude-plugin/plugin.json
    defaults/workflows.defaults.json  # layer 0 of the config system
    scripts/                          # python3 stdlib; shared by skills and hooks
    rules/cpp/                        # canonical shared lint rules, authored as JSON
    references/                       # shared docs several skills point at
    skills/<name>/SKILL.md
    agents/<name>.md
    hooks/hooks.json
  AGENTS.md
  CLAUDE.md -> AGENTS.md
```

## Prerequisites

`python3`, `git`, `rg` (ripgrep), `jq`. For the C++ path: `clang-format`, `clang-tidy`,
`pre-commit`. Run `scripts/wf_config.py doctor` to check them and get install commands.

Nothing here may assume WSL. Anything platform-specific is isolated in `scripts/wf_open.py`;
everything else must run unchanged on plain Ubuntu.

## Repo hygiene

This repo is public and shared across every project on the machine, so nothing project-specific
belongs here — examples in skills/references/changelogs must stay generic, and anything a project
indexer or scan writes (e.g. `wf_config.py projects --scan` output) must never be committed as
project-specific data, only as the empty `projects: {}` shape in defaults.

`.githooks/` enforces this: `pre-commit` and `commit-msg` block a commit that names another
project on this machine (by directory name or by an entry in `~/.claude/workflows.json`'s
`projects` registry). Enable it once per clone:

```
git config core.hooksPath .githooks
```

## Best practices

These apply to work in this repo and to how agents should set up *other* project repos.

### 1. AGENTS.md is the source of truth, tool-specific files are symlinks

- Every project has one `AGENTS.md` at its root with all agent-facing instructions.
- Tool-specific filenames (`CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`) are
  **relative symlinks** to it — `ln -s AGENTS.md CLAUDE.md` — never copies. Relative so they
  survive being cloned or moved.
- AGENTS.md is read natively by Codex, Cursor, Copilot, Aider, Windsurf, Zed, Amp, Jules and
  ~20 other tools. Claude Code and Gemini CLI are the holdouts that still need their own
  filename, which is exactly what the symlink solves.
- `.cursorrules` and `.windsurfrules` are **not** symlink targets: both are deprecated and use a
  different format. Report them, don't convert them.
- Converting an existing repo is the `init-model-agnostic` skill's job — it uses `git mv` so
  history follows the file, and never merges divergent files without asking.
- Inside a *plugin* directory, `CLAUDE.md`/`AGENTS.md` are developer docs only — Claude Code's
  plugin loader does not read them. Plugins contribute instructions via skills, agents and hooks.

### 2. Develop plugins in place — never keep a second copy

The loop is `claude --plugin-dir ./plugins/core`, edit files, then `/reload-plugins`. Edits are
picked up live. Do **not** keep an editable copy outside `plugins/` and sync it in; that is not a
documented practice and only creates drift. Bump `version` in `plugin.json` when publishing, and
run `claude plugin validate` before doing so.

The bump is its own commit, never folded into a feature or fix, and its message is the changelog
entry: `build(core): release 0.6.0 Since 0.5.3: <what changed, user-visible first>`. Do not use
`chore` anywhere, as a commit type or as a branch prefix; older history has it, but new commits must not.

A plugin *installed* from the marketplace is a cache and does not track source edits — that needs
`/plugin marketplace update`. Use `--plugin-dir` while iterating.

### 3. Configuration is layered, and lives in files

Three layers, deep-merged, later wins: plugin defaults → `~/.claude/workflows.json` →
`<repo>/.claude/workflows.json`. Read it with `scripts/wf_config.py`; never hand-parse it.
Project config is committed, so it is reviewable and works in CI where no plugin is installed.
Plugin `userConfig` is deliberately unused — it is per-installation scope and cannot express
per-project settings.

### 4. Generated files declare themselves

Anything this tooling generates into another repo (lint configs, vendored check scripts) carries a
provenance header naming its source and the command to regenerate it, plus content hashes for
drift detection — and deliberately **no timestamp**, so regenerating with no changes produces no
diff.

### 5. Never mutate a user's repo from a hook

Hooks detect and report. Regeneration, staging and any file change are always an explicit skill
invocation, so nothing ever shows up unexplained in a working tree.

## Plugins

### `core` (`plugins/core/`)

Local development:

```
claude --plugin-dir ./plugins/core      # then /reload-plugins after edits
```

Install through the marketplace:

```
/plugin marketplace add eudaldrg/eudaldrg-workflows
/plugin install core@eudaldrg-workflows
```

Skills are namespaced by plugin name, so they appear as `/core:<skill-name>`.
