# eudaldrg-workflows

A Claude Code plugin marketplace that holds the conventions, skills and tooling I use with LLM
coding agents across all my projects. It ships one plugin, `core`.

## Why it exists

I work in many repositories with coding agents. Without a shared layer, each repo grows its own
copy of the same instructions, lint rules and habits, and they drift apart. This repo keeps them
in one place, versioned and reviewable, and installs them into any project through Claude Code's
plugin system.

Design choices that run through it:

- **One source of truth for agent instructions.** Each repo has a single `AGENTS.md`; files such
  as `CLAUDE.md` are relative symlinks to it, so every agent tool reads the same text.
- **Plan, then execute from git.** Work is planned as a task graph in a plan file, then carried out
  one commit per task with trailers that let an interrupted run resume from git history alone.
- **Layered configuration in files.** Plugin defaults, then `~/.claude/workflows.json`, then
  `<repo>/.claude/workflows.json`. Project config is committed, so it is reviewable and works in CI.
- **Hooks detect and report, they never edit.** Any change to a working tree comes from an explicit
  skill invocation.
- **Generated files declare themselves.** Generated lint configs carry a provenance header and
  content hashes for drift detection, with no timestamp, so regenerating without changes produces
  no diff.
- **No Python dependencies.** Scripts use only the Python 3 standard library and run on plain
  Linux; platform-specific code is isolated in one module.

## Install

In Claude Code:

```
/plugin marketplace add eudaldrg/eudaldrg-workflows
/plugin install core@eudaldrg-workflows
```

Skills are then available as `/core:<skill-name>`. Prerequisites are `python3`, `git`, `rg` and
`jq` (plus `clang-format`, `clang-tidy` and `pre-commit` for the C++ lint skill). To check them:

```
python3 plugins/core/scripts/wf_config.py doctor
```

## What `core` contains

| Kind | Name | What it does |
| --- | --- | --- |
| Skill | `design` | Roadmap, MVP cut, architecture and ADRs for a project or feature, before any plan. |
| Skill | `simplify-design` | Reviews ADRs and design docs for rules that should be settings, or should not exist. |
| Skill | `generate-plan` | Turns a piece of work into a plan file: prose context plus a machine-readable task graph. |
| Skill | `implement-plan` | Executes a plan task by task, running checks and committing each task; resumable from git. |
| Skill | `investigate` | Read-only investigation of a codebase question, returning a cited findings report. |
| Skill | `retrieve-knowledge` | Finds the project docs relevant to the module or procedure about to be worked on. |
| Skill | `update-knowledge` | Writes or refreshes project docs, organised by component and by activity. |
| Skill | `session-wrap` | Reviews a session for corrections and gaps and updates the project docs or skills. |
| Skill | `auto-learn` | Moves rules recorded in one project's memory to where they belong. |
| Skill | `session-briefing` | Summarises recent sessions, commits, PRs and mail across projects as an HTML page. |
| Skill | `init-model-agnostic` | Converts a repo to `AGENTS.md` with tool-specific files as symlinks, using `git mv`. |
| Skill | `sync-lint-rules` | Generates a C++ project's `.clang-format` and `.clang-tidy` from shared rules plus overrides. |
| Skill | `setup-statusline` | Installs the shared status line into `~/.claude/settings.json`. |
| Skill | `setup-lean-context` | Applies, checks or reverts settings that shrink the startup context. |
| Skill | `setup-git-diff` | Installs difftastic and delta behind opt-in git aliases. |
| Skill | `html-design`, `html-diagramming` | Guidance for local HTML pages and inline SVG diagrams. |
| Agent | `investigator` | Read-only subagent that gathers and cites evidence for a question. |
| Hook | Stop: `wf_autolearn_hook.py` | Opt-in. Queues correction candidates when a session ends, for `auto-learn` to review. |
| Status line | `wf_statusline.py` | Host and directory, git branch, model, effort, context usage, cache state, cost and cost per hour. |

## Repository layout

```
.claude-plugin/marketplace.json   marketplace manifest
plugins/core/
  .claude-plugin/plugin.json      plugin manifest and version
  skills/<name>/SKILL.md          skills
  agents/                         subagents
  hooks/hooks.json                hook registration
  scripts/                        Python helpers shared by skills and hooks
  rules/cpp/                      shared C++ lint rules, authored as JSON
  references/                     docs several skills point at
  defaults/                       default configuration
tests/                            unit tests (python3 -m unittest)
AGENTS.md                         agent instructions; CLAUDE.md links to it
```

`AGENTS.md` documents the conventions in full, including the release process.

## Development

```
claude --plugin-dir ./plugins/core   # load the working copy; /reload-plugins after edits
python3 -m unittest discover tests
git config core.hooksPath .githooks  # blocks commits that name other local projects
```

## License

MIT. See [LICENSE](LICENSE).
