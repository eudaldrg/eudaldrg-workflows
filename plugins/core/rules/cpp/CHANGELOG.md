# Shared C++ rules changelog

Bump `VERSION` and add an entry here in the same change. Projects that have fallen behind read this
to see what they are missing, so describe the *effect* on a codebase, not just the key that moved.

## cpp-rules/2026.09.2

`clang-format`'s `BasedOnStyle: Google` only ever controlled formatting, never identifier casing —
projects that assumed the Google base meant Google naming too were actually enforcing nothing on
names. Adds `readability-identifier-naming` options so the Google C++ Style Guide's naming rules are
now checked and auto-fixable, not just assumed:

- Types (class/struct/enum/union/type-alias/typedef) and functions/methods: `CamelCase`.
- Variables, parameters and public struct members: `lower_case`.
- Protected/private class members: `lower_case` with a trailing `_`.
- True constants — `constexpr` variables, enumerators, global/static/class constants — `kCamelCase`.
- Namespaces: `lower_case` (matches existing practice, no expected churn). Macros: `UPPER_CASE`.

Plain runtime `const` locals (not `constexpr`) are deliberately left under the generic `lower_case`
variable rule rather than forced to `kCamelCase`, since their value isn't fixed for the program's
lifetime — matching how the convention is actually applied in practice, not just the literal style
guide text. Any project regenerating onto this version should expect a large, mechanical rename diff
for classes/structs/functions if it wasn't already following Google naming; see
`skills/sync-lint-rules/SKILL.md` for the `run-clang-tidy -fix` workflow to apply it.

Also adds `MethodIgnoredRegexp`/`FunctionIgnoredRegexp` exempting `begin`/`end`/`cbegin`/`cend`/
`rbegin`/`rend`/`size`/`empty`/`data`/`swap`. Discovered the same rollout: `CamelCase`-ing a custom
range's `begin()`/`end()` compiles fine on its own but silently breaks every `for (auto& x : range)`
over it, since range-`for` and generic algorithms look up those names unqualified and require the
literal lowercase spelling — clang-tidy has no way to know a method is a customization point, so this
has to be an explicit exemption, not something the rest of the rules can catch.

Also adds `ExcludeHeaderFilterRegex: '/(build|_deps|third_party|external|vendor)/'`. Discovered while
rolling naming out to a project that vendors deps via `FetchContent`: the existing
`HeaderFilterRegex` (`^.*/(src|include)/.*`) matches *any* path with a `src` or `include` segment,
which includes `build/.../_deps/<dep>-src/include/...` — so every check, not just naming, had been
silently reporting (and would have auto-fixed) diagnostics inside vendored third-party headers.
Requires clang-tidy 19+ (`cpp.minClangTidyVersion`); introduced upstream in the 19.1.0 release.

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
