---
name: html-design
description: Design guidance for a local HTML page — a report, dashboard, briefing or explainer written to a .html file, not published as an artifact. Reuses the built-in artifact-design skill and overrides its hosted-artifact parts. Use before writing any standalone HTML page or report, or whenever artifact guidance would apply but the output stays local.
allowed-tools: Read, Write, Edit, Bash, Skill
---

# html-design

Pages are written as local `.html` files, not published as artifacts: the user keeps reports local
and views them with their own tooling, and the Artifact tool is usually denied
(`${CLAUDE_PLUGIN_ROOT}/references/lean-context.md`). The built-in `artifact-design` skill still
has the best design guidance, so this skill reuses it rather than copying it — Anthropic's updates
flow through.

## Procedure

1. **Load the built-in skill** with the Skill tool: `artifact-design`. Follow its guidance, with
   the overrides below taking precedence wherever they conflict.

   If it cannot be found, say so in one line and continue with plain good practice: the
   project's existing design system first, a restrained palette defined as CSS custom properties
   for both light and dark, a readable measure and type scale, real content in the copy.

2. **Charts:** if the page has any chart, plot, stat tile or KPI row, also load `dataviz` before
   drawing it.

3. **Write the file** — a complete local document (overrides below), saved where the project or
   the user says. If neither says, ask; do not invent a location in someone's repo.

4. **Check it:** if a browser tool is available, open the file once and take one screenshot to
   catch layout breaks. Otherwise skip it. Then give the user the path.

## Overrides of the built-in guidance

**Output is a complete, standalone `.html` document**, not a fragment for a host page:
`<!doctype html>`, `<html lang>`, `<head>` with `<meta charset="utf-8">`,
`<meta name="viewport" content="width=device-width, initial-scale=1">` and a `<title>`, then
`<body>`. Inline the CSS, scripts, SVG and small images so the file is self-contained and works
offline. An external dependency is a last resort and must be named to the user.

**Does not apply — ignore it:**

- the CDN allowlist and any other restriction of the hosted frame (sandboxing, blocked APIs,
  storage limits);
- the icon and title rules that exist for the artifact gallery;
- the preview-then-publish loop and anything about publishing, sharing or updating a published
  page;
- `ArtifactData`, `artifact-capabilities` and any runtime capability of a hosted page;
- the hot-reload hook.

**Still applies — keep it:** reuse the existing design system before inventing one; design tokens
for both themes; layout and hierarchy; charts drawn to scale; honest, specific copy; and the
design pass itself — a quick page is still designed.

## Hard rules

- Never call the Artifact tool, even if it is available, unless the user asks for a published
  artifact by name.
- Never publish, upload or share the file anywhere. It stays where it was written.
