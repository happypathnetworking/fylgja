# data-model.md

The section list `plan` writes `specs/NNN-slug/data-model.md` to: every type, document,
format and identifier the feature adds or moves, one numbered section per unit, each
heading naming the package or directory in parentheses.

## 1. <The first unit> (`internal/<package>`)

The fields, their types and rules; what reads and writes it; the format version it
carries and what moves it; the frozen copy an older test reads.

## 2. <The next unit> (`contracts/<file>.schema.json`)

…

## N-1. The identifiers (`internal/findings`)

Every rule id added or retired, `noun.noun.verb`, with the surface that emits it.

## N. The documents

Which documents the units above change, one line each, so the records run can be sized.
