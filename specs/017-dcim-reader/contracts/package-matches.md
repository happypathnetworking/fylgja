# Platform Support Package format 0.7: `platform.matches`

What moves in [psp/psp.schema.json](../../../psp/psp.schema.json) and
[psp/README.md](../../../psp/README.md). Format 0.7 adds one required field and nothing
else; nothing of it reaches a bundle, so no `bundle_id` moves for it.

## The field

```yaml
psp_version: "0.7"
platform:
  id: nokia_srlinux
  vendor: nokia
  nos: srlinux
  versions: ["24.7"]
  device_class: router
  matches:
    - manufacturer: Nokia
      platform: SR Linux
```

| Field | Required | Meaning |
|---|---|---|
| `platform.matches` | **yes**, `minItems: 1` | The manufacturer and platform name pairs this package is, as a source of truth names them. A reader picks a device's package by comparing the source's manufacturer name and platform name with each pair, **both exactly**, letter case and spacing included: `nokia` / `SR-Linux` matches nothing. Each pair is `{manufacturer, platform}`, both non-empty strings. The Infrahub reader compares `OrganizationManufacturer.name` and `DcimPlatform.name`; the NetBox reader will compare NetBox's manufacturer and platform names the same way. Nothing is added to any source's model to key a package |

`vendor` and `nos` stay: `nos` keys the registry's shadowing of an embedded package by an
override and the manifest's `nodes[].platform`; `vendor` and `nos` name the package in
the reports. The shipped values: `nokia_srlinux` matches `Nokia` / `SR Linux`;
`arista_eos` matches `Arista` / `EOS`. A package may list several pairs (a renamed
manufacturer, a second spelling); two packages may not share one.

## The rules

| Rule | Where | When |
|---|---|---|
| `psp.schema` | `psp validate`, load | `matches` absent, empty, or a pair without both names (the schema's `required` and `minItems`) |
| `psp.matches.missing` | `psp validate`, load | the same, under the rule that says what the field is for |
| `psp.matches.duplicate` | `psp validate` over the files given; `psp.Load` over the embedded and override packages after shadowing, refusing the registry as an invalid override refuses it; `serve` and `worker run` at start | two packages name one pair; names both packages and the pair |
| `psp.identity.duplicate` | `psp validate` over the files given; `psp.Load` over the embedded and override packages after shadowing, as for a shared pair; `serve` and `worker run` at start | two packages declare one `platform.id`: an override copied from a shipped package under another `nos`, with a pair of its own, its `id` left. A device names its package by id (`platform.package`), so one matched to the override would be compiled with the embedded package. At the override's file, naming the id and the package that declared it first (`platform "nokia_srlinux" is already declared by psp/nokia_srlinux.yaml`) |
| `psp.version.unknown` | `psp validate`, load | a package declaring `0.6` or earlier: `declares format version "0.6", this build understands "0.7"` |

## The registry

`psp.Registry` gains `Match(manufacturer, platform string) (*PSP, bool)`, exact on both;
the CTM's `platform.package` is resolved by `LookupID`. `Lookup(nos)` leaves product code:
nothing in the CTM carries a `nos` any more. `Platforms()` keeps listing the `nos`
identifiers for the messages that name every package.

## The conformance suite

The pure half gains the check `matches`: the package names at least one pair with both
names non-empty (`package <id> (<path>): matches: declared <n> pairs, produced none`).
Beside the per-package checks, `TestShippedPackagesShareNoMatch` holds every package meant
to load (shipped and `testdata/psp/`'s) to pairwise distinct pairs. The boot half is
unchanged.

## The fixtures

- `testdata/psp/defects/matches-missing.yaml`: the SR Linux package with `matches: []`.
- `testdata/psp/defects/matches-shared.yaml`: a third package naming `Nokia` / `SR Linux`.
- `testdata/psp/defects/version-0-6-m11.yaml`: the SR Linux package at format 0.6, byte
  for byte, kept to prove `psp.version.unknown` names `0.7`, as `version-0-5-m10.yaml`
  proves `0.6`.
- `testdata/psp/heterogeneous/*.yaml` and `testdata/psp/lossy/chassisos.yaml` gain pairs
  of their own (`FastOS Inc` / `FastOS`, …).
