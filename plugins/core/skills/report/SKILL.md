---
name: report
description: Publish a plan, investigation or work summary as a self-contained HTML report — written as Markdown, rendered by a script, then handed to the user's configured publish command or opened locally. Use when a session should leave a readable report behind, when asked to write up, report on, or summarise work, a plan or findings for a human to read.
argument-hint: "[plan | investigation | summary] [title]"
allowed-tools: Read, Write, Bash, Skill
---

# report

A report is the human-readable record of one plan, investigation or piece of finished work. You write
the content as Markdown; `wf_render.py` turns it into one standalone HTML page. **Never write HTML** —
the page shell and CSS are the same every time, so tokens go on content only.

## 1. Pick the kind and its skeleton

Use the kind the user named, else infer it. Each kind has a fixed section skeleton; use it as the
report's `##` headings, in this order, and drop a section only when it would be empty.

- **plan** — Goal · Approach · Steps · Risks · Open questions
- **investigation** — Question · Answer · Evidence · Open questions
- **summary** — What changed · Verification · Follow-ups

Lead with the answer: an investigation's Answer is the second section, not a conclusion at the end.
Cite code as `path:line` and commits by short sha. Keep it to what a reader needs to act on.

## 2. Write Markdown only

Stay inside the subset the renderer supports; anything outside it shows as plain text:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_render.py" --supported
```

Start the file with `# <title>`. Tables, lists and fenced code cover most needs.

A diagram goes in a ```` ```svg ```` fence holding one `<svg>…</svg>` element, drawn with
`currentColor` (and `fill="none"` where shapes should not be solid) so it reads in light and dark
themes. Load `/core:html-diagramming` for what to draw. The renderer only emits static SVG: a fence
with `<script>`, `on…=` handlers, `javascript:` URLs or `<foreignObject>` renders as code instead, so
draw only shapes, paths and text. Only draw when the picture shows something prose cannot.

## 3. Render

Both files go in the reports state directory, named `{date}-{slug}`:

```bash
DIR="$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_config.py" state-dir reports.dir --default reports)"
BASE="$DIR/$(date +%F)-<slug>"      # slug: lowercase title, words joined by '-'
```

Write the Markdown to `$BASE.md` with the Write tool, then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_render.py" "$BASE.md" \
    --title "<title>" --subtitle "<kind> · $(date +%F)" -o "$BASE.html"
```

## 4. Publish or open

```bash
CMD="$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_config.py" get reports.publishCmd)"
```

**`CMD` is empty** (the default): open the page locally. That is the whole outcome.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_open.py" "$BASE.html"
```

`wf_open.py` exits 1 and prints the path when there is no browser; that is a complete outcome on a
headless box, not a failure.

**`CMD` is set:** substitute `{file}` (the `.html` path), `{title}` and `{kind}`, each shell-quoted, in
one pass so a value containing a placeholder is never substituted twice, then run it:

```bash
python3 - "$CMD" "$BASE.html" "<title>" "<kind>" <<'PY'
import re, shlex, subprocess, sys
cmd, *values = sys.argv[1:]
fields = dict(zip(("file", "title", "kind"), values))
cmd = re.sub(r"\{(file|title|kind)\}", lambda m: shlex.quote(fields[m[1]]), cmd)
sys.exit(subprocess.run(cmd, shell=True).returncode)
PY
```

The command is the user's own setting; do not edit it, add flags to it, or guess what it talks to.
If it exits non-zero, report its error output and the local path, then open the file with
`wf_open.py` so the report is not lost.

## 5. Report back

Give the user the title, the kind and the `.html` path, plus whatever the publish command printed
when it ran. Do not paste the report's contents into the conversation; the page is the deliverable.

## Hard rules

- Markdown only. Never hand-write HTML outside a ```` ```svg ```` fence.
- One report per invocation, with one kind.
- Never name or assume a specific viewer. Publishing happens only through `reports.publishCmd`.
- Never commit the report into the project's repo; it lives in the state directory.
