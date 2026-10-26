# The formats that move: bundle 5, twin.json 8, the findings blocks, the frozen copies

| Format | From | To | Why |
|---|---|---|---|
| CTM | `1` | `2` | [ctm.schema.json](ctm.schema.json): the platform is a package, every interface a port, the envelope carries `scope`, `mapping` and `fidelity` and no `contract_version` |
| bundle manifest | `4` | `5` | the provenance block's shape, a mapping row's lost `iftype`, `fidelity.read` |
| `twin.json` | `7` | `8` | the provenance block's shape |
| PSP | `0.6` | `0.7` | `platform.matches` ([package-matches.md](package-matches.md)) |
| findings | `1` | `1` | `subject.scope` is an addition a `1` reader ignores. `verified` loses `contract_version` and `generics`, and `show.record` loses `contract_version`: removals, accepted because both blocks are read by this build's `twin show` and `schema check` alone, by no check and by no recorded history; a `1` document carrying them is not produced by this build and is not re-read |
| the API | `1` | `1` | `scope` is an optional argument |
| contract | `0.2` | retired | the CTM's version is the contract's |

Three things are called *mapping*, on purpose and kept apart by where each sits: **the
mapping** is the documented rule of [mapping.md](mapping.md), one per reader; the CTM
envelope's `mapping` block and the manifest's and record's `provenance.mapping` name
which reader produced the CTM and which model version it read (`{reader, model,
version}`); and the manifest's top-level `mapping[]` is the compiler's port mapping, one
row per interface, as it was in `4`. The glossary's *mapping* entry says the same (T065).

## Bundle manifest 5 (`contracts/manifest.schema.json`)

- `bundle_version`: `"5"`.
- `provenance`: `{branch, at?, schema_hash, scope, mapping{reader, model, version}}`, the
  CTM's envelope minus `observed_at` and `fidelity`. `contract_version` is gone.
- `mapping[]`: `{device, interface, mgmt_only, enabled, port, node_name, disposition}`;
  `iftype` is gone; `disposition` keeps its four values (`configured-not-cabled` is an
  uncabled port).
- `fidelity`: `{basis, production_forwarding, approximations, omitted, lossy, read}`.
  `read` is the CTM envelope's fidelity list, copied unchanged, `[]` only for a reader that
  wrote none; `approximations` stays the packages' strings; `omitted` and `omissions` stay
  the compiler's.
- `twin provision` refuses a `4` as `bundle.version.unsupported` naming both, as it refused
  a `3`; `bundle.Verify` accepts `5` alone. The three goldens move and are re-baselined on
  a commit of their own.

## `twin.json` 8 (`contracts/twin.schema.json`)

- `twin_version`: `"8"`; `provenance` as the manifest's. Nothing else is new.
- A `7` record reads with no scope: `twin show` shows it (`scope unknown (record 7)`),
  `twin step` refuses it `step.twin.unsteppable` naming the version, `twin destroy` clears
  it, `twin rehearse` reclaims it when it names a dead rehearsal. An `8` whose scope is not
  `tag:<name>`, which no build writes, is read as naming none: `twin show` shows its scope
  unknown and `twin step` refuses it, naming the value (T097). An `8` whose mapping is not
  one `twin.json` 8 holds (a reader's name not of its form, or a model or version left
  empty), which no build writes either, is shown naming its reader unknown and each field
  it fails, its JSON record carrying neither `scope` nor `mapping` (T106); `twin step`
  refuses it `step.twin.unsteppable`, naming each field it fails, since a step that diverges
  keeps the record's mapping in the record it writes, which `twin.json` 8 cannot hold
  (T113).

## The findings blocks (`contracts/findings.schema.json`, `show`, `verify`, `step`)

- `subject` gains `scope` (optional string): present whenever a read was made under one.
- `verified` becomes `{model, version, kinds: [{kind, fields: [string]}], stages}`;
  `contract_version` and `generics` go.
- `show.record` carries the record's provenance: `contract_version` goes, `scope` and
  `mapping` come. `verify.twin` and `step`'s two sides name the bundle and the stage and
  never carried `contract_version`; they do not move, and a step's or a verify's scope is
  the document's `subject.scope`.

## The frozen copies

| Format | Frozen under | Read by |
|---|---|---|
| CTM `1` | `internal/ctm/testdata/contracts/017-dcim-reader/ctm.schema.json`, beside `testdata/ctm/defects/version-1.json` (a `1` fixture) | the refusal test, `ctm.version.unsupported` |
| manifest `4` | `internal/bundle/testdata/contracts/017-dcim-reader/manifest.schema.json` | the `bundle.version.unsupported` test |
| `twin.json` `7` | `internal/lab/testdata/contracts/015-proposed-change-rehearsal/twin.schema.json` | `TestFrozenContractCopiesAgree`; the `7` record read with no scope |
| PSP `0.6` | `testdata/psp/defects/version-0-6-m11.yaml` | `psp.version.unknown` |
| findings `1`, the API `1` | unchanged | — |
