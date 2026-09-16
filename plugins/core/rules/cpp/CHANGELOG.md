# Shared C++ rules changelog

Bump `VERSION` and add an entry here in the same change. Projects that have fallen behind read this
to see what they are missing, so describe the *effect* on a codebase, not just the key that moved.

## cpp-rules/2026.09.1

Initial baseline, seeded from `widgets-api`'s hand-written configs so that project regenerates
byte-for-byte identically in effect (verified: all 334 resolved `clang-format` keys and the full
`clang-tidy` config match, 377 checks enabled either way).

- **clang-format**: Google base, 100-column limit, 4-space indent, access modifiers at -2, short
  functions collapsed only when empty, short `if` never collapsed, pointers bound left with
  `DerivePointerAlignment` off, includes sorted.
- **clang-tidy**: `bugprone-*`, `performance-*`, `modernize-*`, `readability-*`,
  `cppcoreguidelines-*` and `clang-analyzer-*` enabled, with six checks disabled that are noisy or
  contested in this codebase style: trailing return types, magic numbers (both spellings),
  non-private members in classes, C arrays, and `[[nodiscard]]` suggestions.
- Header filter limited to `src/` and `include/`; warnings are not errors by default.
