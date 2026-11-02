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

Stay inside the subset the renderer supports; anything outside it shows as plain text. Run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wf_render.py" --supported` if unsure.

Start the file with `# <title>`. Tables, lists and fenced code cover most needs.

A diagram goes in a ```` ```svg ```` fence holding one `<svg>…</svg>` element of plain shapes, paths
and text, drawn with `currentColor` (and `fill="none"` where shapes should not be solid) so it reads
in light and dark themes. Load `/core:html-diagramming` for what to draw, and draw only when the
picture shows something prose cannot. The renderer emits only static SVG; anything active in the
fence makes it render as code instead.

## 3. Render

Both files go in the reports state directory, named `{date}-{slug}`:

```bash
S="${CLAUDE_PLUGIN_ROOT}/scripts"
DATE="$(date +%F)"
DIR="$(python3 "$S/wf_config.py" state-dir reports.dir --default reports)"
BASE="$DIR/$DATE-<slug>"      # slug: lowercase title, words joined by '-'
```

Write the Markdown to `$BASE.md` with the Write tool, then:

```bash
python3 "$S/wf_render.py" "$BASE.md" --title "<title>" --subtitle "<kind> · $DATE" -o "$BASE.html"
```

## 4. Publish or open

`reports.publishCmd` is a command template with `{file}` (the `.html` path), `{title}` and `{kind}`
placeholders. `expand` fills them in, shell-quoted, and prints nothing when the setting is null:

```bash
CMD="$(python3 "$S/wf_config.py" expand reports.publishCmd \
    file="$BASE.html" title="<title>" kind="<kind>")"
if [ -n "$CMD" ]; then bash -c "$CMD"; else python3 "$S/wf_open.py" "$BASE.html"; fi
```

- **Null** (the default): the report is the local file, opened in a browser. `wf_open.py` exits 1 and
  prints the path when there is no browser; that is a complete outcome on a headless box.
- **Set:** the command is the user's own setting. Do not edit it, add flags, or guess what it talks to.
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
