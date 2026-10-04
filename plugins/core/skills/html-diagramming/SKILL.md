---
name: html-diagramming
description: Diagramming guidance for local HTML — inline SVG diagrams that show the real mechanism, legible in both themes, in a .html file rather than an artifact. Reuses the built-in artifact-diagramming skill and overrides its hosted-artifact parts. Use when a local page, report or doc needs a diagram, or when asked to draw an architecture, flow or sequence diagram as HTML/SVG.
allowed-tools: Read, Write, Edit, Bash, Skill
---

# html-diagramming

Diagrams go into local `.html` files, not artifacts — same reason and same arrangement as the
`html-design` skill (`${CLAUDE_PLUGIN_ROOT}/references/lean-context.md`). The built-in
`artifact-diagramming` skill has the diagramming know-how; this skill reuses it.

## Procedure

1. **Load the built-in skills** with the Skill tool: `artifact-diagramming`, and `html-design` for
   the page around the diagram. Follow their guidance, with the overrides below taking precedence.

   If `artifact-diagramming` cannot be found, say so in one line and fall back to plain good
   practice: draw only when a picture shows something prose cannot, draw the real mechanism rather
   than boxes named after modules, keep labels inside their shapes, colour from CSS custom
   properties defined for both themes.

2. **Charts are not diagrams:** for anything plotting data, load `dataviz` instead.

3. **Write the file** where the project or the user says (ask if neither does), then check it
   with one local screenshot if a browser tool is available, otherwise none.

## Overrides of the built-in guidance

- The diagram lives in a complete local `.html` document — doctype, `<head>` with charset and
  viewport meta, `<title>` — or inside a page `html-design` is already producing.
- Inline SVG, inline styles; no external scripts or diagram libraries unless the user agrees, so
  the file stays self-contained and works offline.
- Ignore everything specific to a hosted artifact: the CDN allowlist, the hosted frame's
  restrictions, gallery icon/title rules, preview-then-publish, `ArtifactData`/capabilities and
  the hot-reload hook.
- Keep all of its diagramming rules: when a diagram earns its place, showing the real mechanism,
  legibility in both themes, and the SVG mechanics.

## Hard rules

- Never call the Artifact tool unless the user asks for a published artifact by name.
- Never publish, upload or share the file.
