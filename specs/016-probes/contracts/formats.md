# The formats: what moves, and the frozen copies

Each schema's change, in the shape implement writes it; the prose of each `description`
names 016 and the rule, as the 017–019 paragraphs do.

| Contract | Version | Change |
|---|---|---|
| `contracts/probes.schema.json` | `1`, new | `$id …/contracts/probes/v1`; `probes_version` const `"1"`; `probes[]` items `{name (pattern), format (enum ping), endpoints (2 items: device, interface, address (pattern a/l), gateway (pattern a))}`; `additionalProperties: false` throughout; the description: the file, the kind, the snapshot's element, the rules of data-model §1 |
| `probes/probe.schema.json` | `0.1`, new | `$id …/probes/v0.1`; `probe_version`, `format`, `image` (the PSP's image shape, `clab_kind`, `ref`, `acquisition` enum, `resources`, the two budgets), `host` (`interface`, `address[]`, `route[]`), `readiness` (`probe` enum `exec`, `command[]`, `expect`, `timeout_s`), `flow` (`interval_s`, `command[]`, `start_timeout_s`, `read_timeout_s`), `burst` (`count`, `wait_s`, `command[]`), `fidelity` (`forwarding` enum `software`, `timing` const `container`, `approximations[]`); every list required |
| `contracts/snapshot.schema.json` | `2` | `$id …/snapshot/v2`; `snapshot_version` const `"2"`; `probes` items `$ref` the declaration's probe, `maxItems` gone; the description: a `1` read as a `2`, the id unchanged, the elements hashed and held to the declaration's rules before filing |
| `contracts/manifest.schema.json` | `6` | `$id …/bundle-manifest/v6`; `bundle_version` const `"6"`; `nodes[]`: `provenance` (enum, default `intent`), `probe` object, `platform`, `psp`, `artifact`, `bootstrap` nullable with `if probe then …`; `mapping[]` and `links[]`: `provenance`; `probes[]` (required, `[]`); `fidelity.synthesized[]` (required, `[]`); the description: 016's paragraph |
| `contracts/step.schema.json` | — | `$defs/loss` (`basis` const `container`, `probes[]` `{probe, from, to, outcome enum, sent, lost, longest_gap_s, rule, message}`, `added[]`, `dropped[]`); `step.loss` (object or null); `step.phase` enum gains `flows`; `wait_counts.burst`; the description |
| `contracts/verify.schema.json` | — | `$defs/burst` `{probe, from, to, far_address, expected, outcome, read, error}`; `nodes[].psp` nullable, `nodes[].probe`, `nodes[].bursts[]`, `nodes[].host_name` optional on a host; `counts.burst`; `twin.diverged.phase` gains `flows`; the description |
| `contracts/rehearsal.schema.json` | — | `stages[].loss` (step's `$defs/loss` or null, required); `stages[].verify.burst`; `stages[].step.phase` gains `flows`; the description: the markdown's `loss` column and the caveat's sentence |
| `contracts/twin.schema.json` | `11` | `$id …/contracts/twin/v11`; `twin_version` const `"11"`; `step.loss`; `nodes[]` admits a host (`psp` and `artifact` nullable, `probe`); the description: 016's paragraph |
| `contracts/findings.schema.json` | `1` | the blocks above by `$ref`; no version move |
| `contracts/api.schema.json` | `1` | `probes` (string) on the five operations |

**Frozen copies**, each the 019 shape byte for byte, loading in
`TestFrozenContractCopiesAgree`:

| Copy | Where |
|---|---|
| `snapshot.schema.json` (`1`) | `internal/snapshot/testdata/contracts/019-following-removed/` |
| `manifest.schema.json` (`5`) | `internal/compiler/testdata/contracts/019-following-removed/`, and `internal/bundle`'s |
| `step.schema.json`, `verify.schema.json`, `rehearsal.schema.json`, `findings.schema.json` | `internal/findings/testdata/contracts/019-following-removed/`, and `internal/cli`'s and `internal/server`'s where each validates a document of the 019 shape |
| `twin.schema.json` (`10`) | `internal/lab/testdata/contracts/019-following-removed/` |

**The goldens** (`testdata/golden/`, at the repository root, with their ids in
`internal/compiler/golden_test.go`'s `golden*ID` constants): `three-node`, `lossy`, `mixed`
re-baselined for bundle `6` on a commit of their own; `three-node-probed` added from
`testdata/snapshot/three-node-probed.json`; `three-node`, `mixed` and `three-node-probed`
re-baselined again, on a second commit of their own, when the fixture's ports land
(`testdata/ctm/three-node.json`, `mixed.json` and their wrapped snapshots follow).
