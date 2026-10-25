# Data model: the Infrahub reader reads the schema library's DCIM

**Feature**: `017-dcim-reader` · **Plan**: [plan.md](plan.md) · **Research**:
[research.md](research.md) · **Contracts**: [contracts/](contracts/)

The entities the feature adds, moves or retires, with their fields, rules and where each
lives. The mapping itself is [contracts/mapping.md](contracts/mapping.md); the formats
are [contracts/ctm.schema.json](contracts/ctm.schema.json) and
[contracts/formats.md](contracts/formats.md); the identifiers are
[contracts/scope-and-commands.md](contracts/scope-and-commands.md).

## 1. The scope

| Field | Type | Rule |
|---|---|---|
| value | string `tag:<name>` | `^tag:\S+$`; refused `scope.invalid` otherwise, before any connection |
| origin | the request's `scope` argument, or `server.Server.DefaultScope` from `FYLGJA_DEFAULT_SCOPE` | no default and no argument is `scope.unset` |

Lives in: `api.Request.args.scope` (five operations); `server.Server.DefaultScope`;
`findings.Subject.Scope`; `provision.ProvisionInput.Scope`, `ReadIntentInput.Scope`,
`ReconcileInput.Scope` (`omitempty`, so recorded histories replay); `ctm.Envelope.Scope`;
`compiler.Provenance.Scope`; `wire.Provenance.Scope` (`twin.json` 8). `twin step` and the
follow's checks take it from the record. The devices it selects are `DcimDevice`s carrying
the `BuiltinTag` of that name, whatever their status; a scope selecting none is
`scope.empty` (research R-03, R-04).

## 2. The CTM, version 2 (`internal/ctm`)

```go
type Envelope struct {
    Branch     string        `json:"branch"`
    At         string        `json:"at,omitempty"`
    ObservedAt string        `json:"observed_at"`
    SchemaHash string        `json:"schema_hash"`
    Scope      string        `json:"scope"`
    Mapping    Mapping       `json:"mapping"`
    Fidelity   []FidelityRow `json:"fidelity"`   // sorted by (disposition, object); [] never null
}
type Mapping struct {        // which reader, which model, which version of it
    Reader  string `json:"reader"`   // "infrahub-dcim"
    Model   string `json:"model"`    // "opsmill/schema-library"
    Version string `json:"version"`  // "26336e9"
}
type FidelityRow struct {
    Disposition string `json:"disposition"` // "approximated" | "omitted"
    Object      string `json:"object"`      // interface.mgmt_only | interface.enabled | platform.version | a cable's label or id
    Source      string `json:"source"`      // InterfacePhysical.role | InterfacePhysical.status | DcimPlatform | DcimCable
    Reason      string `json:"reason"`
}
type Platform struct {
    Package string `json:"package"`           // the package's platform.id
    Version string `json:"version,omitempty"` // never written by the Infrahub reader
}
type Interface struct {
    Name       string     `json:"name"`
    MgmtOnly   bool       `json:"mgmt_only"`
    Enabled    *bool      `json:"enabled,omitempty"`
    Link       string     `json:"link,omitempty"`
    Provenance Provenance `json:"provenance,omitzero"`
}
type Device struct {       // Name, Platform, Interfaces, Artifact, Provenance: role and site gone
type Link struct { ... }   // unchanged
const Version = "2"
```

Gone: `Iftype*` constants, `KnownIftypes`, `ImplementedIftypes`, `Address`,
`ContractVersion`, `ContractKind`, `RequiredGenerics`, `DeviceGeneric`,
`ArtifactTargetGeneric`; `Normalize` no longer fills `Family` or sorts addresses. New
constants: `ReaderInfrahubDCIM = "infrahub-dcim"`, `ModelSchemaLibrary =
"opsmill/schema-library"`, `ModelVersion = "26336e9"`. `Unmarshal` refuses any other
`ctm_version` naming both, as today.

**Validation** (`internal/validate`): the envelope's `branch`, `observed_at`,
`schema_hash`, `scope`, `mapping.reader`, `mapping.model`, `mapping.version` required
(`data.required.missing`); `devices` non-empty; names unique; `platform.package` non-empty
and in the registry (`platform.unsupported`, naming the package and the registry's);
interfaces named; links with two ends on distinct devices, each naming an interface of a
device in the CTM. The iftype, parent and endpoint-kind rules go. The artifact rules are
unchanged.

## 3. The manifest, version 5, and the twin record, version 8

`compiler.Provenance{Branch, At, SchemaHash, Scope, Mapping}` from the envelope;
`compiler.Fidelity` gains `Read []ctm.FidelityRow` (`[]` never null), copied from the
envelope by `Compile`, which knows no row's meaning; `MappingRow` loses `Iftype`.
`wire.Provenance` mirrors `compiler.Provenance`; `lab.TwinVersion = "8"`; `findings.ShowRecord`
carries `Scope` and `Mapping` in place of `ContractVersion`; the verify document's `twin`
block and the step's sides never carried it and are unchanged; `findings.Subject` gains
`Scope`. Frozen copies: [contracts/formats.md](contracts/formats.md).

## 4. The support package, format 0.7 (`internal/psp`)

```go
type Identity struct {
    ID, Vendor, NOS string
    Versions        []string
    DeviceClass     string
    Matches         []Match `yaml:"matches" json:"matches"` // required, at least one
}
type Match struct {
    Manufacturer string `yaml:"manufacturer" json:"manufacturer"`
    Platform     string `yaml:"platform" json:"platform"`
}
func (r *Registry) Match(manufacturer, platform string) (*PSP, bool)  // exact on both
const FormatVersion = "0.7"
```

Rules `psp.matches.missing` and `psp.matches.duplicate` (`checkConsistency`,
`checkDuplicateMatch` over the set, and `Load` after shadowing); the suite's `matches`
check and `TestShippedPackagesShareNoMatch`. `Lookup(nos)` leaves product code
([contracts/package-matches.md](contracts/package-matches.md)).

## 5. The conformance table (`internal/intent/mapping.go`)

```go
type KindTable struct {
    Kind          string
    Attributes    []AttributeWant    // {Name, Kind, Required bool, Choices []string}
    Relationships []RelationshipWant // {Name, Peer, Kind, Cardinality, Required bool}
}
type UsedByWant struct{ Generic, Implementer string }
var LibraryTables = []KindTable{...}   // the five kinds of contracts/mapping.md §3
var LibraryUsedBy = []UsedByWant{...}  // the four implementer expectations
const LibraryModel, LibraryVersion = "opsmill/schema-library", "26336e9"
```

`SchemaInfo` gains the nodes' attributes and relationships as the endpoint reports them
(`Nodes map[string]NodeSchema`, each with `Attributes map[string]AttributeSchema{Kind,
Optional, Choices}` and `Relationships map[string]RelationshipSchema{Peer, Kind,
Cardinality, Optional}`), and keeps `Hash` and `UsedBy`. `CheckConformance` walks the
tables and files `schema.kind.missing`, `schema.field.missing`, `schema.field.mismatch`,
`schema.choice.missing` and `schema.used_by.missing`, each naming the commit; `Conformance`
becomes `{SchemaHash, Model, Version, Kinds []findings.KindFields}`; `Verified` becomes
`{Model, Version, Kinds, Stages}`.

## 6. The read (`internal/intent`)

- `Config` gains `Scope` (the tag's name, after `tag:`); `Fetch` runs `Devices` by tag,
  then `Ports` by the devices' ids per page, projects, judges cables (R-05), writes the
  envelope's fidelity list (R-06), fetches the artifacts as today, relinks and normalizes.
- `projectDevice` resolves the package through `reg.Match`; a device no package matches is
  the completeness pass's to refuse (`platform.missing`, `platform.unmatched`) before any
  artifact is fetched, so no CTM carries a device without a package.
- `cableJudgement{id, label, ends []end{deviceID, deviceName, port, kind}}` → a link, or an
  omission with its rule and reason; judged once per cable id.
- `Counts` gains `CablesOmitted`; `DevicesByPackage` reads `platform.package`.

## 7. The stamps and the events (`internal/intent/stamps.go`, `events.go`)

```go
type DeviceStamps struct {
    Match     psp.Match          // the manufacturer and platform pair, for reg.Match in Stale
    IDs       []string           // the device, every interface, the platform, the manufacturer, every cable
    Intent    string             // the latest node_metadata.updated_at among them
    Artifacts map[string]string  // as today
}
```

`IntentStamps` and `PortStamps` select edge `node_metadata { updated_at }` and ids
(research R-10); `Stamps.Latest` folds every device's and every artifact's. `intentKinds`
maps the branch schema's `used_by` of `DcimGenericDevice`, `DcimInterface` and
`DcimConnector` plus `DcimPlatform` and `OrganizationManufacturer` to "intent's";
`changesIntent` is true for a creation or deletion, any attribute, or any relationship not
in `churnRelationships = {member_of_groups, subscriber_of_groups, artifacts, profiles,
object_template}`; an event with no primary node is skipped. `Event.Names` is unchanged.

## 8. The findings (`internal/findings`)

Added, removed and kept identifiers: [contracts/scope-and-commands.md](contracts/scope-and-commands.md).
`OpSchemaCheck`'s success detail is `Verified{Model, Version, Kinds, Stages}`;
`KindFields{Kind string; Fields []string}`.

## 9. The server, the API and the client

- `server.Server.DefaultScope string`; `scopeOf(opts, given, givenAt bool) (string, error)`
  resolves a request's scope or refuses (`scope.invalid`, `scope.unset`) at `start`
  before the packages load; every handler that reads intent calls it: create, rehearse,
  read, stage plan, stage list; `twin step` and the follow use the record's.
- `operationArgs` gains `"scope": argString` on the five; `api.schema.json`'s `args` with
  it; `cmd/fylgja/serve.go` reads the variable, checks its syntax, reports the line.
- `internal/cli`: `--scope` on the five commands; `twin show` prints the record line.
- `stage.Read(ctx, branch, at, scope, reg, observedAt)`; `stages.Stamper.Stamps(ctx,
  branch, at, scope)`; `stages.Plan`/`List`/`Resolve` carry the scope through.

## 10. The template and the query (`infrahub/`)

`device_config.gql` is the template query of [contracts/mapping.md](contracts/mapping.md)
§2's shape by name; `device_config.j2` branches on `platform.node.name.value == 'EOS'`,
renders physical ports with their far end and admin state, comments management-role
ports, skips virtual interfaces, and writes `# platform <Manufacturer> <Platform>;
<description>` in its header (research R-11). `.infrahub.yml`'s description moves; the
definition is unchanged.

## 11. The schema directory and `-prepare-main`

`schema/dcim/{README.md, LICENSE.txt, dcim.yml, ipam.yml, location.yml, organization.yml,
cable.yml, location_minimal.yml}` byte-identical to the pinned commit (research R-12), the
README holding the commit, each file's SHA-256 and the licence; `schema/fylgja-stage.yaml`
stays; `fylgja-generics.yaml` and `reference.yaml` go; `embed.go` embeds `schema/dcim/*.yml`.
`testsupport.LoadSchema` loads the library in one request, then the stage kind, and waits
for `DcimDeviceCreate` and `FylgjaStageCreate`. `-prepare-main` loads the library only on a
`main` holding none of its kinds and refuses naming the kinds found (R-13); the bring-up
script reads that refusal as `present`.

## 12. The fixtures and the fixture tool (`internal/testsupport`, `cmd/fylgja-fixture`)

| Object | Three-node | Mixed |
|---|---|---|
| `BuiltinTag` | `fylgja` | `fylgja` |
| `OrganizationManufacturer` | `Nokia` | `Nokia`, `Arista` |
| `DcimPlatform` | `SR Linux` (Nokia) | `SR Linux`, `EOS` (Arista) |
| `LocationRegion` → `LocationCountry` → `LocationMetro` → `LocationSite` | `Lab region` → `Lab country` → `Lab metro` → `lab` | the same |
| `DcimDevice` | `n1`, `n2`, `n3`: `status active`, `location lab`, `platform SR Linux`, `tags [fylgja]`, `description FYLGJA-MARKER-<suffix>` | `s1` (SR Linux), `e1`, `e2` (EOS) |
| `InterfacePhysical` | `ethernet-1/1`, `ethernet-1/2`, `mgmt0` (`role management`) | `s1`: as n1; `e1`: `Ethernet1`, `Ethernet2/1`, `Management1` (management); `e2`: `Ethernet1`, `Ethernet3/1/1`, `Management1` |
| `DcimCable` | three, `connected_endpoints` the two ports, `label` the link's canonical id | three |
| the group join and the generate | as today | as today |

The marker: `MarkerDescription(branch)` = `FYLGJA-MARKER-<suffix>` with today's suffix
rule; greped as `FYLGJA-MARKER`. Flags: `-set-description <v>` (every device's
description) replaces `-set-role` and `-set-site`; `-add-link`, `-add-fourth-node`,
`-add-mixed-link`, `-disable-port` (`status: disabled`), `-add-interface`, `-seed-main`
and `-clear-main` write the library's kinds; `-prepare-main` as §11; `-sdl`, `-propose`,
`-stage`, `-ready`, `-run-check(s)`, `-close`, `-delete` unchanged. Test support gains
`SetDeviceSerial` (the identical-bytes case) and `SetDeviceDescription`; `SeedThreeNode`'s
idempotence reads `DcimDevice { count }`; `TagDevices`, `EnsureTag`, `EnsureManufacturer`,
`EnsurePlatform`, `EnsureSite` are the seed's helpers.

## 13. The migration (`specs/017-dcim-reader/migration/`)

Two documents, verified (research §1.9): `1-reference-kinds-absent.yaml` (the four
`Network*` kinds and `FylgjaContract`), then `2-generics-absent.yaml` (the four
generics), each loaded on `main` by hand with `infrahubctl`, about 50 s each; then
`-prepare-main`. The host's order and the operator's gate: research R-14,
[quickstart.md](quickstart.md) §2.
