# Lenses

A lens is topical design knowledge that the `design` skill loads only when it applies. Lenses keep the
skill small while its knowledge grows: a new book on database design becomes a lens, not a longer
SKILL.md.

## Format

```markdown
---
when: the design stores structured data, chooses a database, or defines a schema
source: "Author, Title (year), chapters 3-5", or "project experience", or both
---

# Database design

Short, checkable rules, each with its reason. Questions to ask. Common failure modes and how to spot
them in a design. No summaries of the book: only what changes a decision.
```

- `when` decides loading. Make it specific enough that the lens does not load for everything.
- `source` keeps it honest. Knowledge nobody can trace gets deleted by the next person who dislikes it.
- One topic per lens. If a lens needs sections for unrelated situations, split it.

## Where lenses live

- Shared lenses: this directory. Only general knowledge, nothing about a specific project.
- Project lenses: `<docsDir>/design/lenses/` in that project, for its own conventions (a house style
  for C++ ownership, the latency budget every component must respect…).

## When a lens should become a skill

If one level of design (say, API design) grows its own procedure, artifacts and resume logic, and
not just knowledge, split it into its own skill and have `design` point to it. Until then, a lens is
enough.
