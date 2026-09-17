---
name: generate-plan
description: Turn a piece of work into an executable plan file — context and decisions as prose, the task DAG as a json wf-plan fence that implement-plan consumes. Use before starting anything that is more than one or two commits, or when asked to plan, break down, or scope a change.
argument-hint: "[what to plan]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash
---

# generate-plan

Produce one plan file that a later session — or `/core:implement-plan` — can execute without you.

Read `${CLAUDE_PLUGIN_ROOT}/references/plan-format.md` first. It defines the artifact, the fence
schema and the git-trailer ledger. Do not invent fields.

This skill runs in the main session on purpose. A plan is mostly a distillation of the conversation
that led to it, and a fork would throw that away. If the work genuinely needs research first, run
`/core:investigate` and plan from its report.

## 1. Ground the plan before writing it

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_knowledge.py" query --what <module> --why <activity> --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_config.py"    checks --json
git log --oneline -15 && git status --porcelain && git rev-parse --short HEAD
```

**Read the docs the query names** and record them in `knowledgeRefs`. A plan written without reading
the module doc is a plan that re-derives what the project already decided. If a relevant doc comes back
`possibly-stale`, verify its claims against the code before building on them, and say so in the prose.

Then read the code the change actually touches. A plan whose `files` are guesses produces tasks that
cannot be verified.

## 2. Write the tasks

A good task is **one commit's worth of work with one way to prove it**. Concretely:

- It changes something a reader could review in one sitting.
- Its `verify` commands fail before it and pass after it. "Build succeeds" is a weak verify; a test
  naming the new behaviour is a strong one. If nothing can prove a task, either it is not a task or the
  plan is missing the task that makes it provable — usually "wire up the test target".
- Its `commit.subject` is the honest one-line summary, under 68 characters, no trailing period.
- Its `files` list the paths it expects to touch, globs allowed. Execution records what was *really*
  touched, so this list is for dependency analysis, not for enforcement.

Order by `dependsOn` and nothing else. **Never add a `parallel` field** — parallel safety is derived:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_plan.py" layers <plan.md>
```

If two tasks you thought were independent both touch `CMakeLists.txt`, the tool says so. Either accept
the serialization or split the shared edit into its own earlier task.

Put the reasoning in the prose sections, not in `notes`. `## Context` says why the work exists and what
it builds on; `## Decisions` is a table of the choices you made and what you rejected; `## Risks` names
what could go wrong and what the fallback is. Someone reviewing the plan should be able to disagree
with it from the prose alone.

## 3. Lint before you hand it over

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_plan.py" lint <plan.md>
```

Exit 5 means the plan is not executable. Fix it; do not describe the failure and move on.

Write to `plan.dir` (`docs/plans/` by default) as `{date}-{slug}.md`. That directory is gitignored —
if it is not, say so rather than adding entries to `.gitignore` yourself. It lives under `docs/`, not
`.claude/`, because this repo's plans and run cache must not assume a Claude-Code-specific location —
`AGENTS.md` best practice #1 is that agent-facing conventions here stay tool-agnostic.

## Hard rules

- **One task list.** It lives in the fence. Never also write a prose checklist of the tasks; two lists
  drift within a single session.
- Never start implementing. This skill produces a file and stops. Executing it is `/core:implement-plan`,
  and the user decides when.
- Never commit, push, or open a PR.
- Never invent a `baseCommit`. Read it from `git rev-parse HEAD`.
- If the tree is dirty, say what is uncommitted before writing the plan — a plan whose base is a dirty
  tree cannot be resumed cleanly.
- Do not pad the DAG. Three real tasks beat nine ceremonial ones, and every task is a commit someone
  has to review.
