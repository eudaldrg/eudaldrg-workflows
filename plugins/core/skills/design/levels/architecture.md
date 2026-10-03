# Level: architecture

Name the components, how data moves between them, the contracts between them, and every decision that
shapes them, with when each one gets settled.

## Work through

1. **Components**: one line of responsibility each, and the milestone that introduces it. If a
   responsibility needs "and", it is probably two components.
2. **Data flow**: a small diagram (ASCII is fine) from inputs to outputs. Name the one or two rules
   that hold the shape together (e.g. "sources write records, consumers read records").
3. **Contracts**: the interfaces other components depend on: record schemas, APIs, file formats,
   and the keys that join data from different places. These are the expensive things to change.
4. **Storage**: what is stored, where, for how long, who writes, who reads, and concurrency.
5. **Security and trust boundaries**: credentials, what is exposed, and to whom.
6. **Out of scope**: what the system will not do.

## The decision register

A table in `architecture.md`, one row per decision:

| # | Question | Status | Settled by | Depends on | ADR |
|---|---|---|---|---|---|

- `Status`: `open`, `proposed`, `provisional` or `accepted` (see `references/adr-format.md`), or
  `design doc` for a choice deliberately kept out of ADRs.
- `Settled by`: the milestone whose design session must decide it (the latest possible moment).
- `Depends on`: other decisions or milestone outcomes it needs first. This makes visible which decisions
  can be taken now and which must wait.

Take early decisions **provisionally** when a later milestone might change them, with the trigger
recorded in the ADR's *Revisit when*. Leaving them `open` means they get made implicitly by whoever
writes the code first.
