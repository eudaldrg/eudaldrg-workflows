# Level: roadmap

Turn a goal into ordered milestones, each independently useful, with the MVP cut marked.

## Ask first

- What is the outcome someone gets from this? Who is it for? One sentence each.
- What is the smallest thing that delivers that outcome, even crudely? That is the MVP candidate.
- What is explicitly not a goal? Write it down: out-of-scope lines stop scope creep later.

## Milestone rules

- Each milestone is **usable on its own**: a person can do something at its end they could not before.
  "Set up the database" is a task inside a milestone, not a milestone.
- Each has an **exit test**: a concrete check a human can run, with a number where one makes sense.
- Each lists the **design needed** before it can be planned: the questions, not the answers.
- Order by dependency, then by value. Mark the MVP; everything after it is optional by definition.
- Keep a **Later / backlog** list for ideas that are real but not scheduled.

## Artifact: `<docsDir>/roadmap.md`

Per milestone: `## Mn: <name>`, then goal, scope, exit test, depends on, design needed, and a
`Design status:` line (`not started` / `in progress` / `ready`) plus the tracking issue once it exists.

If the project uses GitHub issues, create one per milestone only after the human has confirmed the
roadmap, with the issue body linking to its section. The files stay the source of truth, and the
issue tracks progress.
