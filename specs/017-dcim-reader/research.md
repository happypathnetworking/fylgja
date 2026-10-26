# Research: the Infrahub reader reads the schema library's DCIM

**Feature**: `017-dcim-reader` · **Brief**: [brief.md](brief.md) · **Spec**:
[spec.md](spec.md) · **Written**: 2026-10-25, on the development host (Ubuntu 26.04.1,
Infrahub 1.11.2, `infrahub-sdk` 1.23.2 in `.venv`), by `plan`, after `specify` and
`clarify`.

§1 holds what the plan verified live, each fact with how it was verified and the wall time
(UTC) the answer carries; the raw exchanges are in the session's scratchpad and are not
committed. §2 holds the plan's decisions, R-01…R-22, each with what else was weighed. §3
holds the decision entry and the constitution amendment the spec says the plan writes,
drafted for the operator. §4 holds what is owed at implement. Every fact of §1 that holds
goes into [verified-facts.md](../../docs/verified-facts.md) at the close, with its date.

The brief's "[As read](brief.md#as-read)" was read from the library's files and one
validation-only schema check; every item of it the reader relies on is in §1, verified or
corrected.

---

<a id="1-verified"></a>
## 1. Verified at plan (2026-10-25, development host)

Everything was done on one throwaway branch, `fylgja-test-017-plan`, created at 18:59:37Z
from `main` and deleted at 19:19:51Z (the delete took 8.1 s), through `infrahubctl` for the
schema and raw GraphQL and REST for the rest. After it, Infrahub reads as it began: `main`'s
schema hash is `e43a1cde…`, it has no `Dcim*` kind, `BuiltinTag` counts 0 on it, `Branch`
lists `main`, `fylgja-test-demo` and `fylgja-fixture`, and the registration `fylgja`, the
group's members and the demo window's objects (§1.1) are as they were. No twin was booted,
no worker or server of the operator's was touched, and no token was printed.

### 1.1 The host's state, found (18:58Z)

- **The demo window ([D-054](../../docs/decisions.md#d-054)) is open.** `main` holds
  `FylgjaDevice 3`, `FylgjaLink 3`, `FylgjaContract 1`, and `fylgja-devices` has three
  members; the branch `fylgja-test-demo` (`branched_from` 2026-10-23T13:41:27Z) holds four
  devices under one open proposed change (`18e12c5a…`, `is_draft: false`) with three stages.
  `CLAUDE.md`'s State says the host was left as the contract tier leaves it, `main` holding
  no network; it is not. Nothing here touched the window.
- **Consequences for this feature.** The migration ([R-14](#r-14)) removes the generics
  from `main` and `-clear-main` reads them, so **the window must be closed with the tree
  as it is today**, before the fixture tool is rewritten: `-delete fylgja-test-demo` (its
  stages, its proposed change, the branch), then `-clear-main`. Both are the operator's,
  since the branch is theirs ([plan.md](plan.md), "Owed before the work starts"). While it
  is open no tier 2 or tier 3 runs ([D-054](../../docs/decisions.md#d-054)).
- The worker (pid 3052935) and the server (pid 3052957, both `--listen`s) run from this
  tree's `bin/fylgja`; no twin, no tier and no converge loop was running; 15.9 GiB
  available.

### 1.2 The library on a branch (18:59Z–19:03Z)

- The clone of [opsmill/schema-library](https://github.com/opsmill/schema-library) at
  `26336e9026dff1907f2c58e81dd6ae7b5c3f763e` (merge of PR #98, 2026-10-09; `base/dcim.yml`
  last changed at `617c2b4f…`) holds the six files the spec vendors. Their SHA-256:
  `base/dcim.yml` `81df2eb8…`, `base/ipam.yml` `6d31dc03…`, `base/location.yml`
  `afef7a77…`, `base/organization.yml` `082e8536…`, `extensions/cable/cable.yml`
  `3196073c…`, `extensions/location_minimal/location_minimal.yml` `cf148227…`,
  `LICENSE.txt` (Apache 2.0) `71d4aed1…`. The library's own READMEs say only "refer to the
  reference page"; its root README calls it "a collection of examples … in an experimental
  phase".
- `.venv/bin/infrahubctl schema check --branch fylgja-test-017-plan <six files>` passed
  (every kind `added`, nothing refused), and `schema load --branch` loaded them in
  **27.5 s** (`6 schemas processed`); `DcimDevice` was on `GET /api/schema?branch=` one
  second later. The branch's hash moved to `908871c3…`; `main`'s stayed `e43a1cde…`. The
  order given was organization, location, ipam, dcim, cable, location_minimal, and one
  load took them together: `infrahubctl schema load` sends every file in one request.
- **`infrahubctl schema format` exists in 1.23.2** (`load`, `check`, `export`, `list`,
  `show`, `format`), as 014's §8.2 found; the vendored files are the library's bytes and
  are never formatted ([R-12](#r-12)).

### 1.3 What `GET /api/schema?branch=` says of the kinds the mapping reads (19:03Z)

The endpoint reports each node with its inherited attributes and relationships merged in,
each marked `inherited: true|false`, and each generic with its `used_by`. An attribute's
keys are `name`, `kind`, `optional`, `unique`, `default_value`, `choices` (each with
`name`, `label`, `description`, `color`), `inherited`, `regex`, `parameters`, … and a
relationship's `name`, `peer`, `kind`, `cardinality`, `optional`, `identifier`,
`min_count`, `max_count`, `on_delete`, `inherited`, …. **The conformance table
([R-02](#r-02)) is what the endpoint answered for the pinned commit**, not the YAML's text:
`DcimDevice.status` is written `optional: false` with a default in `base/dcim.yml` and
reported `optional: true`, as every attribute with a `default_value` is.

What the five kinds and the generics report, exactly:

| Kind | Attributes (name: kind, optional) | Relationships (name → peer, kind, cardinality, optional, identifier) |
|---|---|---|
| `DcimDevice` (inherits `CoreArtifactTarget`, `DcimGenericDevice`, `DcimPhysicalDevice`; `human_friendly_id: [name__value]`) | `name: Text, required, unique`; `description: Text, optional`; `status: Dropdown, optional` (default `active`; `active reserved provisioning maintenance deprecated`); `role: Dropdown, optional`; `serial_number`, `position`, `rack_face` | `tags → BuiltinTag, Attribute, many, optional, builtintag__dcimgenericdevice`; `platform → DcimPlatform, Attribute, one, optional, device__platform`; `interfaces → DcimInterface, Component, many, optional, device__interface`; `artifacts → CoreArtifact, Generic, many, optional, artifact__node` (inherited from `CoreArtifactTarget`); `location → LocationHosting, Attribute, one, required`; `primary_address`, `device_type`, `member_of_groups`, `subscriber_of_groups`, `profiles`, `object_template` |
| `DcimPlatform` | `name: Text, required, unique`; `description: Text, optional` | `manufacturer → OrganizationManufacturer, Attribute, one, optional, manufacturer__platform`; `devices → DcimGenericDevice, Generic, many` |
| `OrganizationManufacturer` (inherits `OrganizationGeneric`) | `name: Text, required, unique`; `description` | `platforms → DcimPlatform, Attribute, many, manufacturer__platform` |
| `InterfacePhysical` (inherits `DcimInterface`, `InterfaceLayer2`, `InterfaceLayer3`, `DcimEndpoint`, `InterfaceHasSubInterface`) | `name: Text, required`; `role: Dropdown, optional` (`upstream peering management customer core access`); `status: Dropdown, optional` (default `active`; `provisioning maintenance free disabled active`); `description`, `mtu`, `mac_address`, `l2_mode` | `device → DcimGenericDevice, Parent, one, required, device__interface`; `connector → DcimConnector, Attribute, one, optional, connector__endpoint`; `ip_addresses → IpamIPAddress, many`; `sub_interfaces → InterfaceVirtual, many` |
| `DcimCable` (inherits `DcimConnector`; `human_friendly_id: [label__value]`) | `label: Text, optional, unique`; `status: Dropdown, optional` (default `connected`); `cable_type`, `color`, `length` | `connected_endpoints → DcimEndpoint, Attribute, many, optional, connector__endpoint, min_count 0, max_count 0` |

`used_by`: `DcimGenericDevice → [DcimDevice]`, `DcimInterface → [InterfacePhysical,
InterfaceVirtual]`, `DcimEndpoint → [InterfacePhysical]`, `DcimConnector → [DcimCable]`.
`LocationSite.parent → LocationMetro` is `optional: false`.

### 1.4 The SDL's filters and stamps (19:03Z; `GET /schema.graphql?branch=`, 2.26 MB)

- **The device root takes the tag**: `DcimDevice(tags__name__value: String,
  tags__ids: [ID], tags__isnull, …)`, beside `ids`, `name__value`, `platform__name__value`,
  `platform__ids`, `status__value` and `node_metadata__updated_at__after`.
- **The physical root takes the device, one level down and no further**:
  `InterfacePhysical(device__ids: [ID], device__name__value, device__isnull, …,
  connector__ids, connector__isnull, role__value, status__value)`. There is **no
  `device__tags__*`**: asked for, `Unknown argument 'device__tags__name__value' on field
  'Query.InterfacePhysical'`.
- **The cable root takes its ends**: `DcimCable(connected_endpoints__ids: [ID],
  connected_endpoints__isnull)`.
- **The nested `interfaces` field takes attribute filters only** (`name__value`,
  `role__value`, `status__value`, `description__value`, `mtu__value`, `ids`): nothing
  narrows it to a kind. Read from the device, its edges carry both `__typename`s
  (`InterfacePhysical`, `InterfaceVirtual`).
- **Every `Edged*` wrapper carries `node_metadata { created_at updated_at updated_by
  created_by }`**, the nested relationship edges included (`interfaces { edges {
  node_metadata { updated_at } node { … } } }`, `connector { node_metadata { updated_at }
  node { … } }`, `platform { node_metadata { … } }`). The field is not on the node type
  itself: `Cannot query field 'node_metadata' on type 'DcimDevice'`. (The 09-28 fact "no
  node-level `_updated_at` is queryable" stands for the node type; the wrapper has it.)
- `NodeMutatedEvent` has `primary_node { id kind }`, `related_nodes`, `attributes { name }`,
  `relationships { name peer { id kind } }` and `level`; `RelatedNode` is `{id, kind}`.

### 1.5 The seed, and what the library demands (19:05Z–19:06Z)

Raw GraphQL creates, as the fixture tool's will be:

- **A site needs its whole hierarchy.** `LocationSiteCreate` with no parent is refused
  `parent is mandatory for LocationSite at parent`; a `LocationRegion` (no parent), a
  `LocationCountry` under it, a `LocationMetro` under that and the `LocationSite` under
  the metro load in four creates.
- **A device needs its location**: `location is mandatory for DcimDevice at location`.
  With it, a device loads with a platform, tags, a status and a description; without a
  platform (`n9`) and with a platform that has no manufacturer (`n8`, platform `Orphan
  OS`) as well.
- **`BuiltinTag` is branch-aware**: the two tags made on the branch read 2 there and 0
  on `main`, before and after the branch's deletion.
- **An `IpamIPAddress`** loads with `address` and `interface` alone (the default
  namespace is implied), attached to an `InterfaceVirtual`.
- **A cable's ends.** `DcimCableCreate` accepts two ends, three ends (`c-three`), one end
  (`c-one`) and no end (`c-none`): `connected_endpoints` has `min_count 0, max_count 0`.
  An end on an `InterfaceVirtual` is refused by Infrahub: `InterfaceVirtual - <id> cannot
  be added to relationship, must be of type: ['InterfacePhysical'] at
  connected_endpoints`, since `DcimEndpoint`'s one implementer is `InterfacePhysical`. A
  port already cabled refuses a second cable: `Node <id> has 2 peers for
  connector__endpoint, maximum of 1 allowed`. A cable between two management-role ports
  (`c-mgmt`) loads like any other.
- **The group.** `CoreStandardGroupUpdate` on the branch sets `fylgja-devices`'s members
  to the branch's four `DcimDevice`s (its three `NetworkDevice`s of `main`'s baseline
  dropped on the branch alone); each device then reads `member_of_groups 1` and
  `artifacts 0` through `... on CoreArtifactTarget`. `main`'s membership read 3
  throughout.

### 1.6 The reads, as the reader will make them (19:08Z)

- **Devices by tag.** `DcimDevice(tags__name__value: "fylgja")` answered `count 6`: `n1`,
  `n2` (status `maintenance`), `n3`, `e1`, `n8` and `n9`; the console server `cs1`
  (untagged) and `o1` (tagged `other`) are not among them; `tags__name__value: "other"`
  answered `o1` alone and `"nope"` answered 0. Each node's `platform { node { name
  manufacturer { node { name } } } }` gave `SR Linux`/`Nokia`, `EOS`/`Arista`, `Orphan
  OS`/`null` for `n8` and `null` for `n9`. `hfid` is `["n1"]`, `display_label` `n1`.
- **Ports by device.** `InterfacePhysical(device__ids: [the six])` answered `count 18`:
  every physical port of the six, none of `cs1`'s or `o1`'s, no `InterfaceVirtual`. Each
  carried `name`, `status`, `role`, `device { node { id name } }` and `connector {
  properties { updated_at } node { __typename id connected_endpoints { count edges { node
  { __typename id ... on DcimInterface { name device { node { id name } } } } } } ... on
  DcimCable { status label } } }`: the cable through the generic `DcimConnector`, and
  every end of it with its device's name. `n1:ethernet-1/3`'s cable `c-out` listed
  `n1:ethernet-1/3` and `cs1:port1`; `n1:ethernet-1/4`'s cable `c-three` listed its three
  ends; an uncabled port's `connector.node` is `null`.
- **Counts on the branch**: `DcimDevice 8`, `InterfacePhysical 20`, `InterfaceVirtual 2`,
  `DcimInterface 22`, `DcimCable 9`. `DcimCable(connected_endpoints__ids: [the 18
  ports])` answered 8, every cable but `c-none`.
- **The template's query** (`DcimDevice(name__value: "n1")` with `description`,
  `platform { node { name manufacturer { node { name } } } }` and `interfaces { edges {
  node { __typename name status role ... on InterfacePhysical { connector { node {
  connected_endpoints { edges { node { ... on DcimInterface { name device { node { name } }
  } } } } } } } } } }`) answered every physical port with its far end's device and port,
  and the loopback with `__typename InterfaceVirtual` and no `connector`.

### 1.7 Stamps (19:08Z–19:11Z)

- **An attribute's `updated_at` moves on a change of its own value alone** (a
  `description` edit moved `description.updated_at` and not `name`'s), as the 09-28 fact
  says. A second write of the same value moves nothing.
- **A relationship edge added carries its own stamp**: a second tag on `n1` read
  `properties.updated_at` of the write (`19:08:41.531237`) beside the first tag's creation
  stamp; **a removal leaves no stamp**: with the tag removed, the device's edges and
  attributes read as before the add ([D-048](../../docs/decisions.md#d-048) holds).
- **`node_metadata.updated_at` on the edge wrapper is the latest stamp among the node's
  current attributes and relationship edges.** On `n1` it read the creation stamp at
  first, `19:10:52.069260` after a description edit, `19:10:53.608380` after a tag was
  added, and **back to `19:10:52.069260` after that tag was removed**; a no-op write moved
  it nowhere; an interface's status edit moved the interface's (`19:10:56.550220`) and not
  its device's; a cable's status edit moved the cable's; a manufacturer's description edit
  moved the manufacturer's and not its platform's. The root filter
  `node_metadata__updated_at__after: T` answered the same way at every step (1, 1, 0 after
  the removal, …). So one field per node gives what the 014 stamps query folds by hand
  over a fixed field list, for every field the kind has, and a removal moves it no more
  than it moves a stamp.
- **Pinned**, as 014 found: read at exactly a write's stamp, the wrapper's `updated_at`
  reads the previous latest (`19:06:31.429999`, the group join) and the attribute's value
  reads the new one with its old stamp; one microsecond after, both read the write. Read at
  exactly the node's creation stamp the edge is absent; one microsecond after it is there
  with `updated_at == created_at`. The microsecond rule of D-045 stands unchanged.
- **The port's cable through the connector** reads the cable's own stamp: `connector {
  node_metadata { updated_at } }` on `n1:ethernet-1/1` moved to `19:08:51.094936` with the
  cable's status edit while the edge's `properties.updated_at` stayed at the cable's
  creation.
- **A cable re-ended** (`c12`'s `connected_endpoints` set to one end) leaves the former
  port with `connector { node: null, properties { updated_at: null } }` and the cable's
  remaining edge at its creation stamp: nothing stamped moves, and the events (§1.8) are
  how it is seen.

### 1.8 Events (19:12Z; `InfrahubEvent(branches: [b], since: branched_from, order: DESC)`)

130 events since the branch point, read in three pages of 50. Names seen:
`infrahub.node.created`, `infrahub.node.updated`, `infrahub.group.member_added`,
`infrahub.group.member_removed`, `infrahub.schema.updated` (whose `primary_node` is
`null`: a reader must guard it). Primary kinds seen: every kind the seed wrote
(`DcimDevice`, `InterfacePhysical`, `InterfaceVirtual`, `DcimCable`, `DcimPlatform`,
`OrganizationManufacturer`, `BuiltinTag`, the four location kinds), `CoreStandardGroup`,
and `NetworkDevice` for `main`'s baseline devices rewritten in the group on the branch.

- **A cable re-ended names its former port twice**: the cable's own event (level 0,
  `relationships: [connected_endpoints → n2:ethernet-1/1 (InterfacePhysical)]`) and the
  port's (level 1, `relationships: [connector → c12 (DcimCable)]`), 3 ms apart.
- **A tag removed** is `DcimDevice n1 updated, relationships: [tags → tag_other
  (BuiltinTag)]`, as its addition was.
- **An attribute edit** names the attribute (`attributes: [description]`,
  `[status]`), and **a creation names every attribute**, `human_friendly_id` and
  `display_label` among them, and every relationship set.
- **The group join** is Infrahub's own churn: `CoreStandardGroup updated, members → …` at
  level 0 and one `member_of_groups → <group>` update per device at level 1, exactly as
  014 found for the generics' kinds.
- A relationship's `peer` carries its `kind`, so an event's peers can be told by kind as
  well as by id.

### 1.9 The removal of the generics, rehearsed on the branch (19:12Z–19:17Z)

The branch held `main`'s baseline in the generics' kinds: `NetworkDevice 3`,
`NetworkInterface 12`, `NetworkLink 3`, `NetworkPlatform 1`, `FylgjaContract 1`, their
`CoreArtifact 3`, and `FylgjaStage 3` (branch-agnostic).

- **One document naming all nine kinds `state: absent` is refused**, by `schema check`
  and `schema load` alike: `Unable to load the schema: NetworkDevice: Relationship
  'interfaces' is referring an invalid peer 'FylgjaInterface'`. The implementers are
  validated against a schema the generics have already left.
- **Two documents work.** [`migration/1-reference-kinds-absent.yaml`](migration/1-reference-kinds-absent.yaml)
  (the four `Network*` kinds and `FylgjaContract`): `schema check` printed them under
  `removed`, the load took **50.6 s**, the five kinds left `GET /api/schema` and GraphQL
  (`Cannot query field 'NetworkDevice' on type 'Query'`), `CoreArtifact` still counted 3,
  `FylgjaStage` 3 and `DcimDevice` 8. Then
  [`migration/2-generics-absent.yaml`](migration/2-generics-absent.yaml): the load took
  **48.0 s**, the generics left (`Cannot query field 'FylgjaDevice' on type 'Query'. Did
  you mean 'FylgjaStage'?`), the branch's hash moved to `d7c4b720…`, and a second check
  printed `is Valid! No diff`. `main` read `NetworkDevice 3`, `FylgjaContract 1` and
  `e43a1cde…` throughout.
- The artifacts of the removed devices stay behind a kind removal; `-clear-main` deletes
  them with the devices, which is one reason the window closes first ([R-14](#r-14)).

### 1.10 What the probe did not verify (owed at implement, §4)

The new template rendering on a branch of the library's kinds, and what Infrahub's
pipeline does with a device whose transform's query errors; the registration's import of
the rewritten query against a `main` that holds the library (and whether it is refused
against one that does not); `-prepare-main`'s load of `schema/dcim/` beside the stage kind
on `main`, the hash it gives, and the fixture's compiled id; the conformance findings'
wording on a real branch missing a kind; a read pinned at a stage's `at` filtering by
tag (the scope as it was then); `BranchRebase` over the library's kinds; the tiers'
timings.

---

<a id="2-decisions"></a>
## 2. The plan's decisions

<a id="r-01"></a>
### R-01 Two queries read the scope: devices by tag, then physical ports by device ids, the cable through each port's connector

`Devices(tag, limit, offset)` is `DcimDevice(tags__name__value: $tag)` selecting `id`,
`name`, `platform { node { name manufacturer { node { name } } } }` and the
`ArtifactFields` fragment on `CoreArtifactTarget` as today; it selects no `interfaces`.
`Ports(devices: [ID], limit, offset)` is `InterfacePhysical(device__ids: $devices)`
selecting `name`, `role`, `status`, `device { node { id } }` and `connector { node { id
connected_endpoints { edges { node { __typename id ... on InterfacePhysical { name device
{ node { id } } } } } } } }`, one call per page of devices. Both are paged by 100 as
`Devices` is today.

- **Why two roots**: the device's `interfaces` edge cannot be narrowed to a kind (§1.4), so
  reading ports from the device would read every virtual interface's name, which FR-003
  forbids; the physical root with `device__ids` reads physical ports alone, and the root
  takes no `device__tags__*`, so the device ids come from the first query.
- **Why the cable needs no root of its own**: `connected_endpoints` is `DcimConnector`'s,
  and every end's device is reached through `... on InterfacePhysical`; an end whose
  `__typename` is not `InterfacePhysical` has no name and no device, which is exactly
  "an end not on a physical port" (R-05). An end's device outside the scope is told by its
  id's absence from the devices read, with no query of it (FR-002).
- **The read-only test** holds the operations' roots to `DcimDevice`, `InterfacePhysical`
  and `FylgjaStage`, and the Infrahub-owned four, and their fragment targets (`fragment …
  on`, `... on`) to the four kinds FR-001 names, `CoreArtifactTarget` and
  `NodeMutatedEvent`. `tags__name__value` is a filter and names no root: `BuiltinTag` is
  read by filtering on it, which the test's list records as the Infrahub-owned read FR-001
  calls it.
- Rejected: `DcimCable(connected_endpoints__ids:)` as a third query (a cable is reached from
  a port either way, and the root would list a cable twice per two in-scope ends); reading
  `interfaces` from the device and discarding the virtual ones (reads what the mapping says
  is never read).

<a id="r-02"></a>
### R-02 Conformance is a table from `GET /api/schema`, per kind and per field, choices included, naming the commit

The reader carries the table of §1.3 as data (`internal/intent/mapping.go`): for each kind
the mapping reads, the attributes it reads with their `kind` and `optional`, the
relationships with their `peer`, `kind` (Attribute, Component, Parent, Generic),
`cardinality` and `optional`, and for the two dropdowns the choices the mapping reads
(`role`: `management`; `status`: `disabled`); plus `used_by` expectations (`DcimEndpoint`
and `DcimInterface` implemented by `InterfacePhysical`, `DcimConnector` by `DcimCable`,
`DcimGenericDevice` by `DcimDevice`). The kinds: `DcimDevice` (`name`; `tags`,
`platform`, `interfaces`, `artifacts`), `DcimPlatform` (`name`; `manufacturer`),
`OrganizationManufacturer` (`name`), `InterfacePhysical` (`name`, `role`, `status`;
`device`, `connector`), `DcimCable` (`connected_endpoints`). Every finding names the
commit: `as opsmill/schema-library@26336e9 has it`.

- Identifiers: `schema.kind.missing` (object the kind), `schema.field.missing` (object
  `<kind>.<field>`), `schema.field.mismatch` (object `<kind>.<field>`; the property that
  differs, expected and found: `kind Text, found Number`; `cardinality one, found many`;
  `peer DcimPlatform, found NetPlatform`; `optional false, found true`),
  `schema.choice.missing` (object `<kind>.<field>`, the choice), `schema.used_by.missing`
  (object the generic, the implementer). All rejections, all in one pass, none naming a
  kind or field beyond the table (FR-012). `schema check` runs this half alone and, on
  success, says `conformant with opsmill/schema-library@26336e9: DcimDevice, DcimPlatform,
  OrganizationManufacturer, InterfacePhysical, DcimCable` and the stages line as today;
  its `verified` block becomes `{model, version, kinds: [{kind, fields: [...]}], stages}`.
- `optional` is compared as the endpoint reports it (§1.3): an attribute the table has
  `required` must read `optional: false`; one the table has optional may read either.
- Rejected: a schema hash compare (the hash is per install, §1.2); comparing the branch's
  SDL with a vendored SDL (2.26 MB, field order unstable); checking `DcimDevice.description`
  and `status` (the reader does not read them; FR-010).

<a id="r-03"></a>
### R-03 Completeness inside the scope: `platform.missing`, `platform.unmatched`, `scope.empty`; exact matching

After conformance, the read refuses, all in one pass and with no CTM:

- `scope.empty` (object the scope, `tag:fylgja`): the device query answered 0, whether the
  tag is absent from the branch or on no `DcimDevice` (both read 0, §1.6; the reader does
  not tell them apart, since telling them apart would query `BuiltinTag`).
- `platform.missing` (object the device): no platform, or a platform with no manufacturer,
  the message naming what the device carries (`platform "Orphan OS" with no manufacturer`;
  `no platform`).
- `platform.unmatched` (object the device): no package's `matches` names the pair exactly,
  the message naming the device's pair beside every package's: `manufacturer "nokia",
  platform "SR-Linux"; the packages match: nokia_srlinux [Nokia / SR Linux], arista_eos
  [Arista / EOS]`.

`platform.unsupported` stays as validation's and the compiler's CTM-side rule, for a CTM
whose `platform.package` names no package this build has (a hand-edited file, or a package
removed from the override directory). The artifact rules are unchanged (FR-008): a device
refused for its platform is not also refused for its artifact, as today a device without a
package is skipped by the artifact pass.

<a id="r-04"></a>
### R-04 The scope: `tag:<name>` on four commands and `stage list`, a server setting `FYLGJA_DEFAULT_SCOPE`, recorded everywhere the provenance goes

- **Syntax**: `tag:` followed by one shell word (`^[^\s]+$`). Anything else is
  `scope.invalid` at `start`, exit 2, before any connection, naming the accepted form.
  Present and empty (`--scope=`) is invalid too.
- **The setting**: `FYLGJA_DEFAULT_SCOPE`, read by the server at start and held on
  `server.Server.DefaultScope`, documented in `.env.example` under the server's variables,
  scaffolded by `scripts/bring-up.sh` as `tag:fylgja`, reported at start (`default scope:
  tag:fylgja`, or `default scope: unset (a request that names no scope is refused)`). The
  worker never reads it: every read inside a run carries its scope in its input. A request
  naming no scope with it unset is `scope.unset` at `start`, exit 2, naming the variable,
  before any connection.
- **Where it is carried**: `api.Request.args.scope` on `twin.create`, `twin.rehearse`,
  `intent.read`, `stage.plan` and `stage.list` (below); `provision.ProvisionInput.Scope`,
  `ReadIntentInput.Scope`, `ReconcileInput.Scope` (the follow's checks read under the
  twin's scope); `ctm.Envelope.Scope`; `compiler.Provenance.Scope` and
  `wire.Provenance.Scope` (so `twin.json`); `findings.Subject.Scope`; `twin show`'s record
  line. `twin step` and the following twin take the record's `provenance.scope` (FR-020).
- **`stage list`** is the one command the spec's FR-017 leaves out that reads stamps, and
  the head's `at` is the scope's (R-10), so with the setting unset it would be refused
  `scope.unset` with no way to say a scope. The plan gives it `--scope` too, as the API's
  `stage.list` gains the argument, and flags this for `analyze` to settle against FR-017.
- Rejected: a built-in fallback of `tag:fylgja` (clarify refused one); the scope on the
  record's `stage` block (it is provenance of the read, not of the stage).

<a id="r-05"></a>
### R-05 A cable reached from a port in the scope is a link only with exactly two physical ends inside it; otherwise an omission with one of three reasons

For each port in the scope with a connector, the cable's ends are judged once per cable
(a cable reached from both its ends is one cable, keyed by its id):

| Reason | Rule | When |
|---|---|---|
| other than two ends | `omit.cable.ends` | `connected_endpoints.count != 2` (one, none, three) |
| an end not on a physical port | `omit.cable.endpoint` | an end whose `__typename` is not `InterfacePhysical` (impossible with the pinned six files, §1.5, possible with a user's endpoint kind) |
| an end outside the scope | `omit.cable.outside_scope` | an end whose device id is not among the devices read |

Each is an `info` finding beside the read (object the cable's `label`, or its id when it
has none; message naming both ends as `<device>:<port>` where known) and a row of the
envelope's fidelity list (R-07). The first reason that applies is the one given, in the
order above. A cable with two physical ends in the scope becomes a CTM link with the
canonical id of today (`a:port|b:port`), both ends `link`ed; a cable between two
management-role ports reaches the CTM and the compiler omits it as `omit.link.mgmt_only`
as today (FR-007); a cable with both ends on one device reaches the CTM and validation
refuses it as today (`link.endpoints.same_device`).

<a id="r-06"></a>
### R-06 The CTM moves to `2`: the platform is a package, the interface is a port, the envelope carries the scope, the mapping and the fidelity list

```
ctm_version "2"
envelope { branch, at?, observed_at, schema_hash, scope,
           mapping { reader: "infrahub-dcim", model: "opsmill/schema-library", version: "26336e9" },
           fidelity: [ { disposition: approximated|omitted, object, source, reason } ] }
devices[] { name, platform { package, version? }, interfaces[] { name, mgmt_only, enabled, link?, provenance? }, artifact, provenance? }
links[]   { id, endpoints[2] { device, interface }, provenance? }
```

`iftype`, `parent`, `addresses`, `role` and `site` are gone; `platform.vendor/nos/model`
become `platform.package`, the package's `platform.id`, with `version` optional and never
written by this reader. `contract_version` is gone from the envelope: the CTM is the
contract and `ctm_version` names it; `mapping` says which reader produced it and which
model version it read, which is what Constitution VI's "contract version" becomes
(§3). `ctm.Unmarshal` already refuses another version naming both (`unsupported
ctm_version "1", expected "2"`), and `twin compile` reports it as `ctm.version.unsupported`
at the file, exit 1, in place of `contract.version.mismatch`; nothing converts a `1`
(FR-028). The schema is [contracts/ctm.schema.json](contracts/ctm.schema.json); the `1`
schema is frozen under `internal/ctm/testdata/contracts/017-dcim-reader/ctm.schema.json`
beside a `1` fixture the refusal test reads.

The envelope's fidelity list has, for every read, three fixed rows (`approximated
interface.mgmt_only from InterfacePhysical.role == management`; `approximated
interface.enabled from InterfacePhysical.status != disabled`; `omitted platform.version:
the library carries none`) and one `omitted` row per cable R-05 omitted (object the cable,
source `DcimCable`, reason the finding's). Rows are sorted by (disposition, object).

<a id="r-07"></a>
### R-07 The manifest moves to `5`, the twin record to `8`: provenance with `scope` and `mapping`, no `iftype` row, the reader's fidelity rows copied

- `bundle_version "5"`; `provenance { branch, at?, schema_hash, scope, mapping }`, the
  envelope minus `observed_at` and `fidelity` as `4`'s was minus `observed_at`; `mapping[]`
  rows lose `iftype`; `fidelity` gains `read: [...]`, the envelope's list copied verbatim
  by the compiler, which holds no table of any source's rows (FR-029), beside the
  packages' `approximations`, the compiler's `omitted` and `lossy`. `bundle.Verify` accepts
  `5` alone; `twin provision` refuses a `4` as `bundle.version.unsupported` naming both, as
  it refused a `3`. `4` is frozen under `internal/bundle/testdata/contracts/017-dcim-reader/manifest.schema.json`.
- `twin.json "8"`: `provenance` as the manifest's. A `7` record reads with no scope and
  `twin step` refuses it `step.twin.unsteppable` naming the version, as it refuses a `5`;
  `twin show` shows it with `scope unknown (record 7)`. `7` is frozen under
  `internal/lab/testdata/contracts/015-proposed-change-rehearsal/twin.schema.json`.
- `show.schema.json` carries the record's provenance (`contract_version` on `show.record`)
  and moves with it; `verify.schema.json`'s `twin` block and `step.schema.json`'s two sides
  name the bundle and the stage, never `contract_version`, and do not move;
  `findings.schema.json`'s `subject` gains `scope` and `verified` is R-02's. The CLI's
  `twin show` record line reads `record: …, bundle_id …, schema …, scope tag:fylgja,
  read by infrahub-dcim from opsmill/schema-library@26336e9`.
- The three goldens move (every manifest, every bootstrap of a node that lost `lo0`, every
  artifact) and are re-baselined by `go test ./internal/compiler -update` on a commit of
  their own (FR-032), after the compiler and the fixture CTMs under `testdata/ctm/` have
  moved and before anything reads the ids.

<a id="r-08"></a>
### R-08 The package declares `platform.matches`; format `0.7`; the registry matches exactly; the suite refuses no match and a shared match

```yaml
platform:
  id: nokia_srlinux
  vendor: nokia
  nos: srlinux
  matches:
    - manufacturer: Nokia
      platform: SR Linux
```

`psp_version "0.7"`; `platform.matches` required, `minItems 1`, each `{manufacturer,
platform}` non-empty strings; `nokia_srlinux` matches `Nokia` / `SR Linux`, `arista_eos`
matches `Arista` / `EOS` (the mixed fixture's names, R-15). `vendor` and `nos` stay: `nos`
keys the registry's shadowing and the manifest's `nodes[].platform`, `vendor` the report.

- `psp.Registry` gains `Match(manufacturer, platform string) (*PSP, bool)`, exact on both
  strings (FR-009), and the CTM's package is looked up by `LookupID`; `Lookup(nos)` goes
  from product code. `Load` indexes the matches after shadowing and refuses the registry
  when two packages share a pair (`psp.matches.duplicate`, naming both packages and the
  pair), as it refuses an invalid override.
- `psp validate`: `psp.matches.missing` (no match, or an entry with an empty name) and
  `psp.matches.duplicate` across the files given, beside `psp.identity.duplicate`.
- The conformance suite's pure half gains `matches` per package (at least one pair) and
  the set check `TestShippedPackagesShareNoMatch` over every package meant to load; a copy
  with no match and a third package sharing a pair are fixtures under
  `testdata/psp/defects/` (`matches-missing.yaml`, `matches-shared.yaml`).
- The `0.6` SR Linux package is frozen byte for byte as
  `testdata/psp/defects/version-0-6-m11.yaml`, as `version-0-5-m10.yaml` was, and
  `psp.version.unknown` names `0.7`. The mapping profile's schema names no `iftype`
  ([psp.schema.json](../../psp/psp.schema.json) mentions `mgmt_only` alone), so nothing
  else moves in it.

<a id="r-09"></a>
### R-09 The compiler treats every interface as a port; the iftype rules and their findings go

`ctm.Interface{Name, MgmtOnly, Enabled, Link, Provenance}`. `SurveyDevice` keeps two arms:
`mgmt_only` (the management rule, a second one omitted `omit.mgmt.extra`) and the data
rules (cabled when linked, else configured-not-cabled, unmappable as today); the loopback
arm and the `default` arm go, and `DeviceSurvey.Err` with them. `MappingRow` loses
`Iftype`. Validation loses `interface.iftype.unimplemented`, `interface.mgmt_only.iftype`,
`interface.parent.missing` and `link.endpoint.iftype`, and their fixtures under
`testdata/ctm/defects/` (`iftype-*.json`, `link-endpoint-loopback.json`,
`mgmt-only-loopback.json`, `parent-missing.json`); `ctm.KnownIftypes`,
`ImplementedIftypes` and the constants go. The breakout rule, sharing, collisions and
`ArtifactNames` are unchanged. The fixture CTMs under `testdata/ctm/` lose their `lo0`s
and `role`s and take `platform: {package: …}`; their artifacts are the new template's
(R-11), predicted by hand from the template's text, since the import gates every render
on this host (R-14), re-baselined once with the goldens, and checked against a real render
after the re-seed (SC-001); a difference costs a second golden commit of its own (FR-032).

<a id="r-10"></a>
### R-10 The stamps are each node's `node_metadata.updated_at`; the intent events are any write on those nodes but Infrahub's churn

`IntentStamps` becomes two queries shaped like the read's (R-01), selecting stamps and ids
and no value of intent but the names that key the package: per device `node_metadata {
updated_at }` on the device's edge, its `platform { node_metadata { updated_at } node { id
name { value } manufacturer { node_metadata { updated_at } node { id name { value } } } }
}`, its `interfaces { edges { node_metadata { updated_at } node { id } } }` (both kinds,
ids and stamps alone), and `ArtifactStamps`; per physical port `connector { node_metadata
{ updated_at } node { id } }`. A device's intent stamp is the latest of its own, its
interfaces', its platform's, its manufacturer's and its cables' (FR-023); `Latest` is the
latest of every device's and every artifact's checksum, as today. `DeviceStamps.IDs` is the
device, every interface, the platform, the manufacturer and every cable; `DeviceStamps.Match`
is the manufacturer and platform pair, which `Stale` resolves to the package through
`reg.Match`. §1.7 is why one field per node is enough: it is the latest over the node's
current attributes and edges, and a removal moves it no more than it moved a stamp.

`IntentEvents` keeps its query and changes its rule: an event is intent's when its primary
node's kind is one of the kinds the stamps read (`DcimDevice`, every implementer of
`DcimInterface` and of `DcimConnector` through the branch schema's `used_by`,
`DcimPlatform`, `OrganizationManufacturer`), and it is a creation or a deletion, or an
update naming any attribute or any relationship but Infrahub's own (`member_of_groups`,
`subscriber_of_groups`, `artifacts`, `profiles`, `object_template`). An event with no
primary node (`infrahub.schema.updated`, §1.8) is skipped. `Names(ids)` is unchanged, and
§1.8 shows why it reaches a re-ended cable from both sides. The staleness rule, the head's
`at`, `stage.main.moved` and the Infrahub-owned roots are untouched (FR-022).

Rejected: enumerating every attribute and edge of the library's kinds in the query (the
wrapper's stamp covers every field, a user's extra ones included, and the query stays
small); the `node_metadata__updated_at__after` filter (it answers "updated after", not the
stamp the head and the staleness rule compare).

<a id="r-11"></a>
### R-11 The template reads the device by name, branches on the platform's name, renders physical ports alone, and writes the manufacturer, the platform and the description into its header

`infrahub/queries/device_config.gql` becomes §1.6's template query (`DcimDevice(name__value:
$device)`). The template keeps one file for both platforms, selects the EOS dialect on
`platform.node.name.value == 'EOS'` and the SR Linux one otherwise, and for each interface
whose `__typename` is `InterfacePhysical`: a management-role port is the comment it is
today, any other port is configured with its far end's `<device> <port>` as its
description (from `connector.node.connected_endpoints`, the end whose device or name is
not this port's) and `shutdown`/`admin-state disable` when `status == disabled`. A virtual
interface is not rendered. The header's second line reads `# platform <Manufacturer>
<Platform>; <description>`. A device with no platform renders under the SR Linux dialect
with an empty platform, since the read refuses it anyway and a template must not fail the
pipeline. The `infrahub-managing-transforms` skill is loaded before the query and template
are written (CLAUDE.md), and `.infrahub.yml`'s description moves with them; the artifact
definition is unchanged (FR-034).

<a id="r-12"></a>
### R-12 `schema/dcim/` holds the six files byte for byte, under the library's names, with its licence and a note

```
schema/dcim/README.md            # the commit, the files' SHA-256, the licence, how -prepare-main loads them
schema/dcim/LICENSE.txt          # the library's, 71d4aed1…
schema/dcim/dcim.yml             # base/dcim.yml           81df2eb8…
schema/dcim/ipam.yml             # base/ipam.yml           6d31dc03…
schema/dcim/location.yml         # base/location.yml       afef7a77…
schema/dcim/organization.yml     # base/organization.yml   082e8536…
schema/dcim/cable.yml            # extensions/cable/cable.yml                       3196073c…
schema/dcim/location_minimal.yml # extensions/location_minimal/location_minimal.yml cf148227…
```

The files keep the library's `.yml` extension and bytes (SC-007: a tier-1 test holds each
file's SHA-256 to the README's table); nothing formats them. `fylgja-generics.yaml`,
`reference.yaml` and `schema/infrahub.graphql`'s generics go; `fylgja-stage.yaml` stays.
`testsupport.LoadSchema` loads `schema/dcim/*.yml` in one request, then `schema/*.yaml`
(the stage kind) in a second, since the library's kinds and the stage kind are independent
and the stage kind's extension of `CoreProposedChange` is already on `main`; `-schema-only`
on a throwaway branch loads both. `embed.go` embeds `schema/dcim/*.yml` beside
`schema/*.yaml`. `docs/diagrams/`'s schema entity diagram is redrawn from the six files.

<a id="r-13"></a>
### R-13 `-prepare-main` loads `schema/dcim/` only on a `main` holding none of the library's kinds, and refuses, loading nothing, when it holds any

Before any write, `-prepare-main` reads `GET /api/schema` and lists which of the library's
kinds (every node and generic the six files define) `main` holds. None: it loads the six
files (one request, about 30 s, §1.2), then the stage kind as today. Any: it refuses with
`main holds <n> of the schema library's kinds (DcimDevice, DcimPlatform, …): -prepare-main
is the development host's and CI's tool, which loads the library on an empty main alone;
a main that already holds the library is yours, and fylgja schema check says whether it is
the one the reader reads`, exit 1, before the group and the registration. The first run
after the migration (R-14) finds none and loads; a second run finds all and refuses, so
the bring-up script's part must take that refusal as `present`: it reads the tool's exit
and the sentence, and reports `main present (the library, the stage kind, the group, the
repository)` on it. CI's runner, whose `main` is empty, loads.

<a id="r-14"></a>
### R-14 The migration on this host, in order; the operator's gate; the SDL

0. **Before the work starts, the operator's**: close the demo window with today's tree:
   `go run -tags fixture ./cmd/fylgja-fixture -branch fylgja-test-demo -delete`, then
   `-clear-main` (§1.1). The plan's "Owed before the work starts" says so.
1. `schema check --branch main` then `schema load --branch main` of
   [`migration/1-reference-kinds-absent.yaml`](migration/1-reference-kinds-absent.yaml),
   then of [`migration/2-generics-absent.yaml`](migration/2-generics-absent.yaml), about
   50 s each (§1.9). `main` then holds the stage kind and Infrahub's own kinds.
2. `fylgja-fixture -prepare-main` from the new tree: the library loaded (R-13), the group
   and the registration found present. `main`'s new hash is read from
   `/api/schema/summary` and recorded in `CLAUDE.md` at the close.
3. **The operator's gate**: the commit carrying `infrahub/queries/device_config.gql`,
   `infrahub/templates/device_config.j2`, `.infrahub.yml` and the checks' one identifier
   (R-20) is pushed to `origin`'s `main`, and the session imports it
   (`InfrahubReadOnlyRepositoryImportLastCommit`) and waits for both task workers (about
   15 s), as 015's §6 did. The query names `DcimDevice`, which `main` holds from step 2; an
   import before step 2 is owed a verification (§4) and is not attempted. Until this step,
   no artifact renders on this host, so the fixture cannot be re-seeded and tier 2 cannot
   run; tier 1 can.
4. `make infrahub-clean` (deletes `fylgja-fixture`, whatever its schema) and `make
   infrahub-seed` (R-15), the fixture's compiled id recorded.
5. `make sdl` (from `main`, which now has the library and the stage kind and no generic)
   and `make generate`, committed, so CI's `go generate && git diff --exit-code` holds.
   Until step 5 the typed client is generated from an SDL fetched from a throwaway branch
   that has the library loaded (`fylgja-fixture -branch fylgja-test-017-sdl -schema-only`,
   then `-sdl schema/infrahub.graphql`), which carries the generics too, harmlessly: the
   reader's code can be written and tier 1 run before the host migrates.

The branch `fylgja-fixture` is never rebased; it is deleted and re-seeded (FR-039), and
keeps nothing. CI's path is the fresh one: `-prepare-main` loads the library and the stage
kind on an empty `main`, the registration imports the merged template, the seed renders.

Rejected: a throwaway registration served from the tree for the window (a second
registration of the same `.infrahub.yml` registers a second `device-config` definition,
which every read would refuse `artifact.ambiguous`); switching the registration's `ref` to
the feature branch (unverified that the import follows a rewritten `ref`, and a write to
D-044's registration).

<a id="r-15"></a>
### R-15 The fixtures in the library's kinds; the marker in `description`; the identical-bytes case

The three-node seed writes, on its branch: `BuiltinTag fylgja`; `OrganizationManufacturer
Nokia`; `DcimPlatform SR Linux` (manufacturer Nokia); `LocationRegion Lab region`,
`LocationCountry Lab country`, `LocationMetro Lab metro`, `LocationSite lab` (§1.5); the
devices `n1`, `n2`, `n3` (`status active`, `location lab`, `platform SR Linux`, `tags
[fylgja]`, `description` the marker); on each `InterfacePhysical` `ethernet-1/1`,
`ethernet-1/2` and `mgmt0` (`role management`), no loopback; the three cables `DcimCable`
with `connected_endpoints` the two ports and `label` the link's canonical id
(`n1:ethernet-1/1|n2:ethernet-1/1`, unique); then the group join and the generate as
today. The mixed seed writes `Arista` and `EOS` beside them, `s1` (SR Linux: `ethernet-1/1`,
`ethernet-1/2`, `mgmt0`), `e1` and `e2` (EOS: `Ethernet1`, `Ethernet2/1` or
`Ethernet3/1/1`, `Management1` as `role management`), and the three cables. The marker's
form is `FYLGJA-MARKER-<suffix>` with today's suffix rule (`fixture`, `main`, or the branch
name without `fylgja-`), written as the device's `description`, rendered by the template's
header (R-11), and greped for as `FYLGJA-MARKER` by every tier as today.

- `-set-description <v>` sets every device's description on a throwaway branch (the
  artifact-only change: the header moves, nothing else); `-set-role` and `-set-site` go.
  The identical-bytes case of `TestArtifactOnASeededBranch` and `TestStageRefusals` ("a
  site edit the template does not render") becomes a `serial_number` edit through test
  support's `SetDeviceSerial`, which needs no flag.
- `-add-link` adds `ethernet-1/3` on n1 and n3 and their cable; `-add-fourth-node` adds n4
  with `mgmt0` and `ethernet-1/1` and the peer's `ethernet-1/3`; `-add-mixed-link` adds
  `s1:ethernet-1/3`, `e1:Ethernet3` and their cable; `-disable-port` sets `status:
  disabled`; `-add-interface` adds a physical port; `-seed-main` and `-clear-main` write
  and clear the baseline in the library's kinds (the tag, the manufacturer, the platform,
  the four locations, the three devices, their ports and cables, the artifacts), refusing a
  `main` holding any of those. `SeedThreeNode`'s idempotence reads `DcimDevice { count }`.

<a id="r-16"></a>
### R-16 The API stays `1`; the CLI's `--scope`; the refusals before any connection

`scope` is a new optional string argument of `twin.create`, `twin.rehearse`,
`intent.read`, `stage.plan` and `stage.list` (R-04): a client of 015 never sends it and
is served under the default. `--scope tag:<name>` on the five commands; `twin step` takes
none (FR-020) and refuses one given (`unknown flag`, cobra's). `scope.invalid` and
`scope.unset` are made at `start` before any connection, after `--branch`'s and
`--stage`'s guards and before the packages are loaded. The checks' requests carry no
`scope` (FR-021). `api.md` and `cli.md` gain "017: the scope and the DCIM reader";
`api.schema.json`'s `args` definitions gain `scope`.

<a id="r-17"></a>
### R-17 What the read reports: the summary line, `twin show`, `schema check`

- `intent read`'s summary line: `wrote ctm.json: 3 devices (nokia_srlinux 3), 9
  interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports; 1 cable omitted
  (branch b, scope tag:fylgja, schema 908871c3…)`; the omitted count only when non-zero.
- `twin show`: the record line of R-07; the kind line unchanged.
- `schema check`: R-02's success line, the stages line; `--json`'s `verified` block.
- `stage plan`'s stage line names the scope once in the heading: `proposed change … on
  branch b → main, draft (4 stages), scope tag:fylgja`.

<a id="r-18"></a>
### R-18 The tiers

- **Tier 1** (`make test`, under 45 s): the compiler over the moved CTMs and goldens; the
  conformance table and every `schema.*` finding against an `httptest` schema document with
  a kind, a field, a choice or an implementer removed or changed; the read's projection and
  every `platform.*`, `scope.*` and `omit.cable.*` finding against an `httptest` Infrahub
  answering §1.6's shapes (a three-ended cable, a one-ended one, an outside end, an end of
  another `__typename`, a device with no platform, one with an orphan platform, one no
  package matches); the stamps and events rules against faked answers; `ctm.version.unsupported`
  from the frozen `1`; the package's `matches`, the two `psp.matches.*` rules, the suite's
  new checks; the API's `scope` on five operations and the two refusals through the
  harness; `twin.json` `8` and the frozen `7`; the manifest `5` and the frozen `4`; the
  vendored files' SHA-256; the read-only test's new lists; the nine histories replaying.
- **Tier 2** (`make test-contract`): the re-seeded fixture reads to `three-node.json` in
  everything but the envelope and compiles; the mixed seed reads and compiles; `schema
  check` passes on both naming the commit; on a throwaway branch `DcimCable` removed by a
  `state: absent` document (about 40 s) `schema check` and the read refuse
  `schema.kind.missing DcimCable` (the field-level findings are tier 1's); a throwaway
  branch with a three-ended cable and a cable to an untagged device reads with both omitted,
  each a finding and a row, and the untagged device absent from the CTM; a tagged device
  with no platform, and one on `nokia` / `SR-Linux`, refuse the read naming each; a read
  under `tag:nothing` is `scope.empty`; `internal/stages` and `internal/checks` pass with
  their assertions unchanged, with SC-009's edits (a virtual interface, the platform, the
  manufacturer, a cable) each making a mark stale and an untagged device's edit not. About
  two minutes more than today.
- **Tier 3** (`make test-e2e`): nine cases over the re-seeded fixtures, the marker in
  `description`, `twin show`'s scope line asserted in case 1, the `--scope` form in case 5;
  no new case.

<a id="r-19"></a>
### R-19 The records

The decision entry D-057 (§3.1) and Constitution 2.0.0 (§3.2) are the operator's to accept
at `analyze`, before the reader is built. The plan's own changes: `docs/architecture.md`
§2 (the pipeline's first step), §3 (core objects: the scope), §4.1 rewritten around the
mapping, §4.2, §4.3 (wiring derivation: every interface a port), §4.7 (`matches`, `0.7`),
§5 (the source of truth row), §6 ("The branch point needs a tagged device on `main`";
"Intent-conformant"), the open questions; `docs/c4/workspace.dsl` (the artifacts
repository's description, the schema as the vendored library and the stage kind, the
intent component's description) and `make diagrams`; `docs/glossary.md` (new: *mapping*,
*approximation*, *omission*, *scope*, *schema library*, *package match*, *node stamp*;
changed: *CTM*, *fidelity manifest*, *fixture branch*, *fixture tool*, *artifacts
template*, *intent*, *mixed twin*; retired, kept as "retired at 017" one-liners: *contract
version*, *generics*, *graduate, don't gate*, *reference schema*);
`docs/development.md` (layout, the fixture tool's paragraph, the tiers' rows, the
migration); `docs/verified-facts.md` (§1 whole, and the 09-28 line on `_updated_at`
amended); `README.md` (the walk-through's `contract 0.2` line and the five
`contract.node.missing` lines, which become `scope.empty`); `docs/brief.md` lines 51–53;
`docs/roadmap.md` (F-011 built); `CLAUDE.md` (Environment: `main`'s schema, the hashes, the
fixture, the writes to `main`; Formats; State; the reading list's schema sentence);
`.env.example`; `schema/README.md` rewritten (R-12's table, the mapping, what `schema
check` reports, what a diverged DCIM costs, the shipped template as a reference transform);
`psp/README.md` (0.7); `contracts/*`. `infrahub/checks/fylgja_api.py`'s one identifier
(R-20).

<a id="r-20"></a>
### R-20 The checks pass no scope and excuse `scope.empty` where they excused `contract.node.missing`

`fylgja_api.py`'s `branch_point_refusal` excuses the branch point's lone
`contract.node.missing`; it excuses `scope.empty` instead, and the server's `passedOver`
(`internal/server/rehearse.go`) does the same (FR-015). Nothing else in the three Python
files changes; the change rides the same push and import as the template (R-14 step 3).
Rejected: a check reading the server's default scope and sending it (it is the server's to
read, and the checks are clients that know no setting).

<a id="r-21"></a>
### R-21 The identifiers

Removed with the generics (FR-016): `contract.version.mismatch`, `contract.node.missing`,
`schema.generic.unimplemented`, `schema.artifact_target.missing`,
`interface.iftype.unimplemented`, `interface.mgmt_only.iftype`, `interface.parent.missing`,
`link.endpoint.iftype`. Added: `schema.kind.missing`, `schema.field.missing`,
`schema.field.mismatch`, `schema.choice.missing`, `schema.used_by.missing`,
`ctm.version.unsupported`, `scope.invalid`, `scope.unset`, `scope.empty`,
`platform.missing`, `platform.unmatched`, `omit.cable.outside_scope`, `omit.cable.ends`,
`omit.cable.endpoint`, `psp.matches.missing`, `psp.matches.duplicate`. Kept with their
meaning: `platform.unsupported` (CTM-side), `data.required.missing`, `device.name.duplicate`,
`link.endpoints.count`, `link.endpoints.same_device`, every artifact, mapping, stage, step,
verify, rehearsal and API rule. Severities, exits and steps are in
[contracts/scope-and-commands.md](contracts/scope-and-commands.md).

<a id="r-22"></a>
### R-22 The OpsMill skills

`infrahub-managing-schemas` was loaded at this plan, as the operator asked. Followed: the
schema is read from the running instance before it is relied on (§1.3); the library is
loaded on a branch first and the migration's documents are checked before they are loaded
(workflow-branch-first, for the probe; the load on `main` is D-028's and stays, CLAUDE.md);
`state: absent` for a removal, in two documents (migration-); the vendored files are the
marketplace's own, taken whole and unformatted with provenance recorded (reuse-, R-12).
Departed from, on purpose and as CLAUDE.md decides: nothing is `inherit_from`ed or
extended, since the reader adds nothing to anyone's model; `infrahubctl` is
`.venv/bin/infrahubctl`; `schema format` is never run on the vendored files. At implement,
`infrahub-managing-objects` is loaded before the seed is written (R-15) and
`infrahub-managing-transforms` before the query and template (R-11), per the brief.

---

<a id="3-drafted"></a>
## 3. The decision entry and the amendment, drafted for the operator

<a id="3-1"></a>
### 3.1 D-057 — The CTM is the contract; a reader maps one source's model onto it; the Infrahub reader reads the schema library's DCIM at a pinned commit

**Status:** Proposed 2026-10-25 by `017-dcim-reader`'s plan, for the operator to accept at
`analyze`. Supersedes [D-002](../../docs/decisions.md#d-002), [D-003](../../docs/decisions.md#d-003)
and [D-004](../../docs/decisions.md#d-004) whole. Beside [D-010](../../docs/decisions.md#d-010)
(the CTM, now the contract), [D-016](../../docs/decisions.md#d-016) and
[D-031](../../docs/decisions.md#d-031) (the package, which now also declares its platforms),
[D-028](../../docs/decisions.md#d-028) and [D-044](../../docs/decisions.md#d-044)
(unchanged), [D-045](../../docs/decisions.md#d-045) (the stage kind, untouched).

**Context.** D-002 made Fylgja's four generics the contract so that any Infrahub schema
could implement them and Infrahub would resolve one query across the implementers. They
met a model somebody else wrote on 2026-10-16, OpsMill's schema library, and could inherit
into its DCIM only after adaptation on one side or the other (verified-facts, "Inheriting
from two generics"). Release 0.3 adds NetBox as a second source of truth, read directly;
a reader of NetBox maps a fixed, DCIM-shaped model onto the CTM whatever the contract says,
and once one reader works that way the generics make the Infrahub reader the odd one out.
Nothing in the compiler, the bootstrap or verify ever consumed an address, a loopback, a
role or a site: the configuration Infrahub renders carries them.

**Options considered.** A layer-1 generics contract carried into the library by an overlay
schema (designed first; rejected by the operator on 2026-10-25: an overlay is still
something every user loads, and NetBox cannot load it). A mapping declared as data per
install (rejected: D-002's "mini-ETL language", now with two sources). **The CTM as the
contract and one documented mapping per source** (chosen).

**Decision.**

- The CTM is the contract, versioned by `ctm_version`. A reader maps one source's model
  onto it, by one documented mapping, names the model version it reads in every CTM's
  envelope, records every place the source's meaning is near the CTM's and not identical
  as an approximation and every object it leaves out as an omission, in the envelope's
  fidelity list, which the compiler copies into the manifest unchanged, and reads nothing
  the mapping does not name. The read-only test holds the list of kinds a reader queries.
- The Infrahub reader reads OpsMill's schema library's DCIM at commit `26336e9`, vendored
  under `schema/dcim/` with its licence, by the mapping in `specs/017-dcim-reader/contracts/mapping.md`:
  a device is a `DcimDevice` carrying the scope's tag, a port an `InterfacePhysical`,
  `mgmt_only` its `role: management` and `enabled` its `status != disabled` (approximated),
  a link a `DcimCable` with exactly two physical ends in the scope, any other cable omitted
  and recorded; the platform's version is absent. Conformance is per kind and per field
  against what the pinned commit loads, reported in one pass; completeness is strict inside
  the scope.
- A twin is of a scope, a tag on each device the request names (`--scope tag:<name>`) or
  the server's default (`FYLGJA_DEFAULT_SCOPE`), recorded in the CTM, the manifest and the
  record. A package declares the manufacturer and platform pairs it is (`platform.matches`),
  matched exactly; nothing is added to anyone's model to key a package or a scope.
- What survives of D-003 and D-004: wiring is derived by the compiler from what the reader
  mapped (`mgmt_only`, the cables), never declared in a schema; a reader never claims a
  meaning the source does not carry, and says so where it approximates.

**Consequences.** Constitution III is rewritten and VI reworded (2.0.0; §3.2); the generics
contract leaves the blessed layers and the mapping takes its place. `schema/`'s generics
and reference schema go; `FylgjaStage` stays. The CTM moves to `2`, the manifest to `5`,
`twin.json` to `8`, the package to `0.7`; the goldens move. The development host's `main`
is migrated by two removal documents and `-prepare-main`; a DCIM user loads nothing of
Fylgja's but the stage kind, and `fylgja schema check` says whether their DCIM is the one
the reader reads; a diverged DCIM needs a reader of its own, which the production shape
makes a seam. The library calls itself experimental: the commit is pinned, and moving it
is a change to the mapping's table, verified against the running Infrahub. Revisit when
the library publishes a release, when NetBox's reader (F-025) shows the CTM wants a field
this one cannot fill, or when the library's `DcimEndpoint` gains a second implementer.

<a id="3-2"></a>
### 3.2 Constitution 2.0.0: Principle III rewritten, VI reworded, the gate's blessed layer moved

Sync Impact Report: 1.3.0 → 2.0.0 (MAJOR: Principle III redefined). Source: D-057.
Templates: `.specify/templates/plan-template.md`'s Constitution Check names 2.0.0 and its
row III reads the new principle.

**III. The CTM Is the Contract; a Reader Maps One Source**
The CTM MUST be the one contract between a source of truth and the compiler. A reader
MUST read one source's model, as a named version of it, by one documented mapping, and
nothing the mapping does not name; it MUST read the least possible. Specifically:
- MUST name, in every CTM's envelope, the reader and the model version it reads.
- MUST record every approximation (a CTM field read from a source field whose meaning is
  near and not identical) and every omission (an object inside or touching the scope left
  out) in the envelope's fidelity list, which the compiler copies into the manifest
  unchanged; the compiler MUST hold no table of any source's approximations.
- MAY read an Infrahub-owned kind that a Fylgja kind relates to or depends on
  (`CoreProposedChange`, its validators, `Branch`, `BuiltinTag` as the scope's tag), each
  named in the read-only test with its reason, and the branch's event log
  (`InfrahubEvent`) for when intent last changed, removals included, an event's kind read
  only to be mapped through the schema's `used_by` and never queried (D-048); the
  read-only test MUST hold the list of kinds the reader queries.
- MUST NOT claim a meaning the source does not carry: where the mapping approximates, the
  manifest says so.
- Wiring behaviour MUST be derived by the compiler from what the reader mapped
  (`mgmt_only`, the links), never declared in a schema.
- MUST validate schema conformance (the kinds and fields the mapping reads, as the named
  model version has them) and data completeness (inside the scope) separately, report all
  findings in one pass, and produce no CTM on failure.
*Rationale: D-010, D-045, D-048, D-057.*

**VI**: "the schema hash Infrahub reports, and the contract version" becomes "the schema
hash Infrahub reports, the scope, and the mapping with the model version it read".

**II**: "Budgets, timeouts and readiness MUST come from the PSP" gains "and so MUST the
manufacturer and platform pairs a package matches".

**Constitution Check — Gate Adjustments**: "The generics contract. Required by Principle
III. (D-002)" becomes "The mapping, one per source, documented. Required by Principle
III. (D-057)". The plan template's row III: "The CTM is the contract; the reader names its
model version; approximations and omissions in the envelope's fidelity list, copied by the
compiler; nothing read the mapping does not name; the read-only test's list; wiring derived
from what was mapped; conformance and completeness checked separately".

**Constitution Check — Gate Adjustments, the CTM bullet**: "Synthesized nodes are not in
Infrahub and cannot live in types generated from Infrahub; something Infrahub does not own
must be the compiler's input. The CTM MUST stay a near-copy of the generated types until a
synthesized node needs more. *(D-010)*" becomes "The one contract between a source of
truth and the compiler: a reader maps its source onto it and a synthesized node is added
to it, so nothing any source owns is the compiler's input. It MUST carry only what the
compiler consumes and what provenance and fidelity require. *(D-010, D-057)*".

**Development Workflow — Three test tiers**: "Contract tests run against a real Infrahub
with the reference schema loaded" becomes "Contract tests run against a real Infrahub with
the vendored library and the stage kind loaded on `main`".

---

<a id="4-owed"></a>
## 4. Owed at implement

- §1.10's facts, each recorded here as §5 and then in `verified-facts.md`: the template's
  render on the library's kinds; the import of the rewritten query on a `main` holding the
  library; `-prepare-main`'s load and `main`'s new hash; the fixture's compiled id and the
  mixed fixture's; `schema.kind.missing` on a real branch; a pinned read filtering by tag;
  a rebase over the library's kinds; the tiers' timings (tier 1 under 45 s uncached).
- The operator's: the demo window closed before the fixture tool moves (R-14 step 0); D-057
  and Constitution 2.0.0 accepted at `analyze`, before the reader is built; the template
  commit pushed to `origin`'s `main` and imported before the fixture is re-seeded (R-14
  step 3).
- The goldens re-baselined on a commit of their own from the hand-predicted artifacts, and
  again on a second commit of their own if the real render after the re-seed differs (T060).
- `make diagrams` after the C4 and the schema entity diagram move.

---

<a id="5-verified"></a>
## 5. Verified at implement

What implement verified, each fact with how it was verified and the wall time (UTC) the
answer carries, as §1 is written; each that holds goes into
[verified-facts.md](../../docs/verified-facts.md) at the close (T067).

<a id="5-1"></a>
### 5.1 The template's renders, predicted (T016; 2026-10-25, 21:52Z–22:02Z)

**These bytes are predicted, to be checked at T060.** Infrahub's pipeline renders nothing
from the rewritten template until the operator's push of `origin`'s `main` (T057) and its
import (T058). The bytes were worked by hand from `infrahub/templates/device_config.j2`'s
text, over the fixtures of data-model §12 and [R-15](#r-15), and T019 takes them as
`testdata/ctm/three-node.json`'s and `mixed.json`'s artifacts. Each document below ends in
one newline and holds no other trailing whitespace. Its MD5 is the checksum the fixtures
record, as `CoreArtifact.checksum` is the MD5 of the stored bytes. The marker is the
device's `description`: `FYLGJA-MARKER-fixture` on the fixture branch's `n1`–`n3`, and
`FYLGJA-MARKER-mixed-fixture` on `s1`, `e1` and `e2`. That is the suffix rule applied to
`mixed.json`'s branch, `mixed-fixture`. A mixed seed on a throwaway branch carries that
branch's suffix, and its bytes differ from these in the header's second line alone.

The three-node fixture (links `n1:ethernet-1/1|n2:ethernet-1/1`,
`n1:ethernet-1/2|n3:ethernet-1/2`, `n2:ethernet-1/2|n3:ethernet-1/1`):

**`n1`** (SR Linux; 707 bytes, MD5 `597f6263eb7e0b539679b3956270876f`):

```text
# n1: production configuration rendered by Infrahub (fylgja-artifacts)
# platform Nokia SR Linux; FYLGJA-MARKER-fixture
set / system name host-name n1
set / network-instance default type default
set / interface ethernet-1/1 description "to n2 ethernet-1/1"
set / interface ethernet-1/1 admin-state enable
set / interface ethernet-1/1 subinterface 0 admin-state enable
set / network-instance default interface ethernet-1/1.0
set / interface ethernet-1/2 description "to n3 ethernet-1/2"
set / interface ethernet-1/2 admin-state enable
set / interface ethernet-1/2 subinterface 0 admin-state enable
set / network-instance default interface ethernet-1/2.0
# mgmt0: out-of-band management, left to the platform
```

**`n2`** (SR Linux; 707 bytes, MD5 `5ac21560015ad6bb1e881358115d0b7a`):

```text
# n2: production configuration rendered by Infrahub (fylgja-artifacts)
# platform Nokia SR Linux; FYLGJA-MARKER-fixture
set / system name host-name n2
set / network-instance default type default
set / interface ethernet-1/1 description "to n1 ethernet-1/1"
set / interface ethernet-1/1 admin-state enable
set / interface ethernet-1/1 subinterface 0 admin-state enable
set / network-instance default interface ethernet-1/1.0
set / interface ethernet-1/2 description "to n3 ethernet-1/1"
set / interface ethernet-1/2 admin-state enable
set / interface ethernet-1/2 subinterface 0 admin-state enable
set / network-instance default interface ethernet-1/2.0
# mgmt0: out-of-band management, left to the platform
```

**`n3`** (SR Linux; 707 bytes, MD5 `e93df96400ddbada7daa1a0777d9d3e3`):

```text
# n3: production configuration rendered by Infrahub (fylgja-artifacts)
# platform Nokia SR Linux; FYLGJA-MARKER-fixture
set / system name host-name n3
set / network-instance default type default
set / interface ethernet-1/1 description "to n2 ethernet-1/2"
set / interface ethernet-1/1 admin-state enable
set / interface ethernet-1/1 subinterface 0 admin-state enable
set / network-instance default interface ethernet-1/1.0
set / interface ethernet-1/2 description "to n1 ethernet-1/2"
set / interface ethernet-1/2 admin-state enable
set / interface ethernet-1/2 subinterface 0 admin-state enable
set / network-instance default interface ethernet-1/2.0
# mgmt0: out-of-band management, left to the platform
```

The mixed fixture (links `e1:Ethernet1|s1:ethernet-1/1`, `e1:Ethernet2/1|e2:Ethernet1`,
`e2:Ethernet3/1/1|s1:ethernet-1/2`):

**`s1`** (SR Linux; 711 bytes, MD5 `5e2a65f4dd4f5968c76e99f53fc3ff89`):

```text
# s1: production configuration rendered by Infrahub (fylgja-artifacts)
# platform Nokia SR Linux; FYLGJA-MARKER-mixed-fixture
set / system name host-name s1
set / network-instance default type default
set / interface ethernet-1/1 description "to e1 Ethernet1"
set / interface ethernet-1/1 admin-state enable
set / interface ethernet-1/1 subinterface 0 admin-state enable
set / network-instance default interface ethernet-1/1.0
set / interface ethernet-1/2 description "to e2 Ethernet3/1/1"
set / interface ethernet-1/2 admin-state enable
set / interface ethernet-1/2 subinterface 0 admin-state enable
set / network-instance default interface ethernet-1/2.0
# mgmt0: out-of-band management, left to the platform
```

**`e1`** (EOS; 319 bytes, MD5 `6b31a6de32516a4becb79002db56b1f7`):

```text
! e1: production configuration rendered by Infrahub (fylgja-artifacts)
! platform Arista EOS; FYLGJA-MARKER-mixed-fixture
hostname e1
interface Ethernet1
description to s1 ethernet-1/1
no shutdown
interface Ethernet2/1
description to e2 Ethernet1
no shutdown
! Management1: out-of-band management, left to the platform
```

**`e2`** (EOS; 323 bytes, MD5 `e6a46383814336980c408a48410105e3`):

```text
! e2: production configuration rendered by Infrahub (fylgja-artifacts)
! platform Arista EOS; FYLGJA-MARKER-mixed-fixture
hostname e2
interface Ethernet1
description to e1 Ethernet2/1
no shutdown
interface Ethernet3/1/1
description to s1 ethernet-1/2
no shutdown
! Management1: out-of-band management, left to the platform
```

Against today's artifacts, each document loses its loopback (`lo0`, `Loopback0`) and
moves its header's second line from `platform <vendor> <nos> <version>; role <role>` to
`platform <Manufacturer> <Platform>; <description>`. Every other line is as today's,
the EOS dialect's unindented `description` and `no shutdown` included: the template's
`-%}` strips the next line's indentation, as it always has, and tier 3 has proved those
bytes on cEOS.

How far the prediction was checked before the import:

- **The local render reproduces the pipeline's, for today's template.** `.venv/bin/infrahubctl
  render srlinux_device_config device=<d> --branch fylgja-fixture --out <file>` (SDK
  1.23.2; read-only) of the template at `9255232` gave, for `n1`, `n2` and `n3`, bytes
  whose MD5 equals each device's live `CoreArtifact.checksum` (`43e8fd0c…`, `ecb03029…`,
  `ae0c3a87…`) and `testdata/ctm/three-node.json`'s content. The SDK's file-based
  environment has `trim_blocks` and `lstrip_blocks` and the default `Undefined`, so an
  attribute read on a null node fails the render. This is why the template guards the
  platform and the manufacturer. Its filter allowlist (`infrahub_sdk/template/filters.py`)
  admits `sort` in the worker and local contexts, though not the core's, and the
  artifacts render in the worker, as today's template, which sorts, shows. The skill's
  `jinja2-template` rule lists `sort` as unavailable.
- **The rewritten query and template, rendered locally over the library's kinds, equal the
  prediction.** On the throwaway branch `fylgja-test-017-t016` (created from `main` at
  21:59:19Z; the six files of §1.2, fetched at `26336e9` into the scratchpad with their
  SHA-256 prefixes checked, loaded in one `infrahubctl schema load` in 24.1 s; the branch's
  hash `4161a1ab…`, not the plan's branch's `908871c3…`, since a branch's hash is its own),
  a seed made through the SDK by a session's script wrote the two fixtures together. The
  objects were the tag `fylgja`, `Nokia` and `Arista`, `SR Linux` and `EOS`, the four
  locations, the six devices and their 18 ports and six cables, labelled by the link's
  id. `infrahubctl render` of the tree's query and template rendered each of the six
  devices byte-identical to the prediction. That run is also the skill's dry-run
  (`deployment-gql-dry-run`): the query ran against the library's live schema with no
  GraphQL error. Its answer listed each interface's `__typename`. `n1`'s `lo0` and `e1`'s
  `Loopback0`, added as `InterfaceVirtual`s to prove the skip, answered `InterfaceVirtual`
  with no `connector`, and neither rendered.
- **Probes the fixtures do not hold rendered without failing.** On the same branch:
  - `x1`, with no platform and no description: the SR Linux dialect, the header's second
    line `# platform ` (empty), and a port of `status: disabled` as `admin-state disable`.
  - `x2`, whose platform `Orphan OS` has no manufacturer: `# platform Orphan OS; edge`.
  - `x3`, on EOS: a disabled port as `interface Ethernet1` then `shutdown`, with no
    description.
  - A three-ended cable (`x1`, `x2`, `x3`) gave each end the description of one of the
    other two, the last as the answer lists them, an order the template does not fix.
    The read omits such a cable (`omit.cable.ends`).
  - A one-ended cable gave its port no description.
- **The branch was deleted** at 22:01:59Z (the delete took 47 s). Afterwards `Branch` lists
  `main` and `fylgja-fixture` alone, `main`'s hash is `e43a1cde…` with no `Dcim*` kind, and
  `BuiltinTag` and `CoreProposedChange` count 0 on `main`.

What this does not prove, and T060 does: the render by Infrahub's pipeline in its task
workers, from the imported commit.

**Checked at T060 (2026-10-26, 13:22Z–13:24Z, Run 18 of the converge loop): the prediction
held, and the goldens did not move a second time.** After `c006bf9`'s import (§5.4), the
pipeline rendered each device in its task workers from the imported template.

- **The three-node fixture**, re-seeded on `fylgja-fixture` by `make infrahub-seed`: `bin/fylgja
  intent read --branch fylgja-fixture` read `n1`, `n2` and `n3` at 707 bytes each. Their
  checksums were `597f6263…`, `5ac21560…` and `e93df964…`, the MD5s above and
  `testdata/ctm/three-node.json`'s, and the MD5 of the content read equals the checksum.
  The read without its envelope equals that file's (§5.5).
- **The mixed fixture**, seeded by `fylgja-fixture -branch fylgja-test-017-mixed -mixed` (30.3
  s), carried the marker `FYLGJA-MARKER-test-017-mixed`. It read `s1` at 712 bytes, `e1` at
  320 and `e2` at 324, each one byte longer than above. With that marker replaced by
  `mixed.json`'s `FYLGJA-MARKER-mixed-fixture`, each device's bytes have the MD5 above
  (`5e2a65f4…`, `6b31a6de…`, `e6a46383…`) and equal `mixed.json`'s. The header's second line
  is the only one that differs, as predicted. The read gave the two warnings
  `artifact.interface.unrepresented e1:Management1` and `e2:Management1`, which
  `internal/compiler/mixed_test.go` pins. It compiled to `4fe3e26e…`, an id this branch's
  marker and provenance make its own. The branch was deleted (7.8 s).

So `testdata/ctm/three-node.json`'s and `mixed.json`'s artifacts are Infrahub's bytes, and
T024's goldens (three-node `43d91715…`, lossy `4213b3cf…`, mixed `ecb665f5…`) stand.

<a id="5-2"></a>
### 5.2 The interim SDL and client, the schema document, the query's dry run and `-prepare-main`'s gate (T031, T033; 2026-10-26, 00:50Z–00:53Z)

All on one throwaway branch, `fylgja-test-017-sdl`, which `fylgja-fixture -branch
fylgja-test-017-sdl -schema-only` created from `main` at 00:50:27Z. In one run of 39.5 s
wall, `go run`'s build included, it loaded `schema/dcim/`'s six files in one request and the
stage kind in a second. The branch's hash read `18e5f023…`; `main`'s stayed `e43a1cde…`.
Nothing was written to `main`, and no token was printed.

- **The gate, live.** A probe test that was not committed (`TestRun9Probe`, 4.6 s) ran
  test support's gate against the running Infrahub.
  - `LibraryKinds` computes 27 kinds from the six files, every node and generic they define
    (13 in `dcim.yml`, 4 in `ipam.yml`, 2 in `location.yml`, 3 in `organization.yml`, 1 in
    `cable.yml`, 4 in `location_minimal.yml`). quickstart §2's "21" was an estimate; the
    refusal on a migrated `main` names 27.
  - `KindsHeld` read `main` holding none of them.
  - `LoadLibrary` on the branch refused before any write, naming the 27 kinds in R-13's
    sentence with the branch's name in place of `main`.
  - `LoadOwnSchema` loaded the stage kind on the branch a second time and reported it
    present: the schema hash did not move. A raw `POST /api/schema/load` of the stage kind
    showed the answer's keys: `diff`, `hash`, `previous_hash`, `schema_updated` and
    `warnings`, with `hash` equal to `previous_hash` for an unchanged load. Test support
    compares the two hashes, as `infrahubctl` does.
- **The SDL.** `-sdl schema/infrahub.graphql` wrote 2,255,885 bytes, against `main`'s
  1,385,164. It holds `interface FylgjaDevice`, `type NetworkDevice`, `type FylgjaStage` and
  `type DcimDevice` together, so the old operations and the new can both generate. The
  file's header was written by hand to say it is the interim's.
- **The schema document.** `GET /api/schema?branch=fylgja-test-017-sdl` was trimmed with
  `jq` to the nodes `DcimDevice`, `DcimPlatform`, `OrganizationManufacturer`,
  `InterfacePhysical`, `InterfaceVirtual` and `DcimCable`, the generics `DcimGenericDevice`,
  `DcimInterface`, `DcimEndpoint`, `DcimConnector` and `CoreArtifactTarget`, and `main` (the
  branch's hash). It is `internal/intent/testdata/schema-26336e9.json`, 110,497 bytes. The
  generics' `used_by` read:
  - `DcimGenericDevice` [`DcimDevice`];
  - `DcimInterface` [`InterfacePhysical`, `InterfaceVirtual`];
  - `DcimEndpoint` [`InterfacePhysical`];
  - `DcimConnector` [`DcimCable`];
  - `CoreArtifactTarget` [`DcimDevice`, `NetworkDevice`]. The reference kind is there
    because the branch was made from a `main` that still holds it. On the migrated `main`
    it names `DcimDevice` alone. The document holds the token nowhere (`grep -F` of it, 0),
    nor any key named for a password, a secret or a token.
- **The query's dry run** (the skill's `deployment-gql-dry-run`).
  - `POST /graphql/fylgja-test-017-sdl` with `infrahub/queries/device_config.gql` and
    `{"device": "none"}` answered no `errors` and `{"DcimDevice": {"edges": []}}`.
  - The skill's own command, `.venv/bin/infrahubctl render srlinux_device_config
    device=none --branch fylgja-test-017-sdl`, ran the query and stopped in the template at
    line 8, `data.DcimDevice.edges[0]`, with `list object has no element 0`. That is a device
    the query does not find, which the pipeline never asks for, since it renders the
    group's members alone.
- **The client.** `make generate` (9.9 s) added 97 lines to `internal/intent/generated.go`
  and changed no operation. They are the library's implementers of the interfaces the old
  operations select: `ArtifactFieldsDcimDevice` and `ArtifactStampsDcimDevice` beside the
  `NetworkDevice` ones, and `IpamIPAddress` beside `InternalIPRangeAvailable` as a
  `BuiltinIPAddress`.
- **The branch was deleted** by `-branch fylgja-test-017-sdl -delete` at 00:52:58Z (`deleted 0
  stages, 0 proposed changes, branch fylgja-test-017-sdl`). Afterwards `Branch` lists `main`
  and `fylgja-fixture` alone, `CoreProposedChange` and `FylgjaStage` count 0, and `main`'s
  hash is `e43a1cde…`.

<a id="5-3"></a>
### 5.3 Conformance against the running Infrahub (T036; 2026-10-26, 01:25Z–01:27Z)

On one throwaway branch, `fylgja-test-017-conf`. `fylgja-fixture -branch fylgja-test-017-conf
-schema-only` made it from `main` at 01:25:34Z and loaded the library and the stage kind
in 37.9 s wall. A probe test that was not committed (`TestRun10Probe`, 2.5 s) then ran
`SchemaInfo` and `CheckConformance` from this tree against three branches. Nothing was
written to `main`, and no token was printed.

- **The library's branch conforms, read whole.** `GET /api/schema?branch=fylgja-test-017-conf`
  answered the untrimmed document: hash `5dbe3902…`, 76 nodes, 56 generics. The table gave
  0 findings in 1.3 s, schema read included.
  - `DcimDevice.artifacts` read `CoreArtifact`, Generic, many, optional: inherited from
    `CoreArtifactTarget` and merged into the node, as §1.3 found.
  - `InterfacePhysical.device` read `DcimGenericDevice`, Parent, one, `optional: false`.
  - `role`'s choices read `upstream peering management customer core access`.
  - `used_by`: `DcimEndpoint` [`InterfacePhysical`], `DcimConnector` [`DcimCable`],
    `DcimGenericDevice` [`DcimDevice`], `DcimInterface` [`InterfacePhysical`,
    `InterfaceVirtual`].
  - The `verified` block named `opsmill/schema-library@26336e9` and the five kinds with their
    fields in the table's order. So the trimmed document under `internal/intent/testdata/`
    answers as the whole one does.
- **`schema.kind.missing` on real branches.** `fylgja-fixture` (hash `0aba31a5…`, 62
  nodes, 35 generics) and `main` (`e43a1cde…`, the same counts) hold the generics, not the
  library. Each gave exactly five `schema.kind.missing`, one per kind in the table's order,
  each ending `as opsmill/schema-library@26336e9 has it`. Neither gave a field, choice or
  `used_by` finding, nor any naming a kind beyond the table. Until `main` migrates (T056)
  and the fixture is re-seeded (T060), `schema check` and every read refuse both, as
  conformance should.
- **The branch was deleted** by `-branch fylgja-test-017-conf -delete` at 01:26:44Z (`deleted 0
  stages, 0 proposed changes, branch fylgja-test-017-conf`). Afterwards `Branch` lists `main`
  and `fylgja-fixture` alone, `CoreProposedChange` and `FylgjaStage` count 0, and `main`'s
  hash is `e43a1cde…`.

<a id="5-4"></a>
### 5.4 The rewritten query imported on a `main` that holds the library (T058; 2026-10-26, 13:19Z–13:20Z)

Run 18 of the converge loop, from `d038c5a`, after the operator's push of `origin`'s `main` to
`c006bf9` (T057). The registration `fylgja` (`18dc77bb-…`) read `commit 3c3e79a`, `in-sync`,
`online`. Nothing but the import was written, and no token was printed.

- **No sync stuck, before and after.** The task manager's Prefect API, read inside its
  container (`POST /api/flow_runs/filter`), held no flow run `PENDING` or `RUNNING` and none
  `SCHEDULED` with its start in the past, at 13:19:08Z and again at 13:20:31Z.
  `git_repositories_sync` completed each minute. `InfrahubTask(state: [PENDING, RUNNING,
  SCHEDULED])` counted 0 as well.
- **The import.** `InfrahubReadOnlyRepositoryImportLastCommit(data: {id})` on `main` at
  13:19:17.3Z answered `ok: true` with a task. That task, `Import last commit from read only
  git repository`, ran until 13:19:45.7Z (28.4 s). Its end moved `commit` to
  **`c006bf9`**, `in-sync`, `active` / `online`.
- **The task workers.** Each holds the commit's tree under `/opt/infrahub/git/<repository
  id>/commits/c006bf9…`: `task-worker-1`, which ran the import, from 13:19:21Z, and
  `task-worker-2` from 13:19:50Z, 4.6 s after the flow ended. That is less than the 15 s
  `CLAUDE.md` allows. `refresh-git-fetch` ran twice at 13:20:01Z–13:20:02Z.
- **What `main` holds, read at 13:20:05Z.**
  - `CoreGraphQLQuery device_config`: its text is byte-identical to `c006bf9`'s
    `infrahub/queries/device_config.gql` (1,445 bytes). Its `models` read `DcimCable`,
    `DcimConnector`, `DcimDevice`, `DcimEndpoint`, `DcimGenericDevice`, `DcimInterface`,
    `DcimPlatform`, `InterfacePhysical`, `InterfaceVirtual` and `OrganizationManufacturer`,
    in place of the eight removed kinds §5.10 found. So **the rewritten query imports on a
    `main` that holds the library**, with no error, and Infrahub derives its models from
    the library's kinds. `fylgja_branch`'s `models` stay empty.
  - The transform `srlinux_device_config` (`infrahub/templates/device_config.j2`, query
    `device_config`) and the definition `srlinux_device_config` → `device-config`,
    `text/plain`, targeting `fylgja-devices`, are unchanged.
  - The two check definitions are still registered: `fylgja-step`
    (`infrahub/checks/fylgja_step.py`, `FylgjaStep`, timeout 300) and `fylgja-twin`
    (`fylgja_twin.py`, `FylgjaTwin`, timeout 4260). 4260 is the class's `timeout` at
    `3c3e79a` as at `c006bf9`; `CLAUDE.md` says 4200 (T071).

<a id="5-5"></a>
### 5.5 The hand scenarios (T061; quickstart §3–§6; 2026-10-26, 13:27Z–13:37Z)

Run 18, through the server from this tree (pid 292664, rebuilt at `5abdbd3` after the SDL's
commit, `default scope: tag:fylgja`), after the fixture's re-seed (T060). Three throwaway
branches, each deleted by the fixture tool at its end. Nothing was written to `main`, and no
token was printed.

**§3, the fixture read.**

- `bin/fylgja schema check --branch fylgja-fixture`, exit 0:

  ```
  conformant with opsmill/schema-library@26336e9: DcimDevice, DcimPlatform, OrganizationManufacturer, InterfacePhysical, DcimCable
  stages: FylgjaStage present on the default branch, with its extension
  ```

- `bin/fylgja intent read --branch fylgja-fixture --out local/fixture.ctm.json` took 2.1 s,
  exit 0. It wrote `local/fixture.ctm.json: 3 devices (nokia_srlinux 3), 9 interfaces, 3
  links, 3 artifacts, 0 lossy mappings, 0 shared ports (branch fylgja-fixture, scope
  tag:fylgja, schema 7c413536d67ef86321c629c076a0d3a4)`.
- **The read without its envelope equals `testdata/ctm/three-node.json`'s**: the `diff` said
  `same`.
- **The envelope**: branch `fylgja-fixture`, `observed_at`, `schema_hash` `7c413536…`, scope
  `tag:fylgja`, mapping `infrahub-dcim` / `opsmill/schema-library` / `26336e9`. Its fidelity
  rows are `approximated interface.enabled`, `approximated interface.mgmt_only` and
  `omitted platform.version`. The fixture branch's schema hash is now `main`'s, since the
  seed made it from the migrated `main`; it was `0aba31a5…`.
- `bin/fylgja twin compile` wrote three nodes and three links. **The fixture's compiled id is
  `f764e1fabdcd70b39a91cc2269ef0a3443c7ae6752af62bdf0936c4eda034147`** on this install
  (`47b2c449…` before the migration). The manifest's provenance is `{branch, schema_hash
  7c413536…, scope tag:fylgja, mapping}`, and `fidelity.read` holds the envelope's three rows,
  each with its source and reason. No test or script pins the fixture's id.

**§4, the scope.**

| Command | Answer | Exit |
|---|---|---|
| `intent read --branch fylgja-fixture --scope tag:fylgja` | the same read; the file equals the default's but `observed_at` | 0 |
| `… --scope tag:nothing` | `rejection scope.empty tag:nothing: scope tag:nothing selects no device on branch fylgja-fixture` | 1 |
| `… --scope fylgja` | `rejection scope.invalid [step start] fylgja: --scope "fylgja" is not a scope: the accepted form is tag:<name>, …` | 2 |
| `… --scope=` | `rejection scope.invalid [step start] : --scope "" is not a scope: …` | 2 |
| `twin step --scope tag:fylgja` | `rejection operation.failed twin.step: unknown flag: --scope`; the server logged no request | 2 |

- **Quickstart §4's `--out /dev/null` cannot be written.** The client writes through a
  temporary file beside its target: `rejection operation.failed intent.read: writing CTM: open
  /dev/.fylgja-ctm-749857017: permission denied`, exit 2, after the server's read had
  answered `ok`. The `tag:fylgja` read was run again to `local/scope.ctm.json`, and the
  quickstart's line now names that file. The refusals write nothing, so their `/dev/null`
  stands.
- The server logs each `scope.invalid` as `outcome=error duration=0s`: no read was made.
- **The scratch server**: `env -u FYLGJA_DEFAULT_SCOPE FYLGJA_STATE_ROOT=<scratch> bin/fylgja
  serve --listen 127.0.0.1:7659`, with no `FYLGJA_DEFAULT_SCOPE` in its environment.
  - It reported `default scope: unset (a request that names no scope is refused)`.
  - `FYLGJA_API_ADDRESS=127.0.0.1:7659 bin/fylgja intent read --branch fylgja-fixture` was
    refused, exit 2, with no file written: `rejection scope.unset [step start]
    FYLGJA_DEFAULT_SCOPE: no --scope was given and the server has no default: name one with
    --scope tag:<name>, or set FYLGJA_DEFAULT_SCOPE where fylgja serve starts`.
  - Its log holds one request line, `operation=intent.read outcome=error duration=6ms`, and
    no read.
  - It was stopped.

**§5, omissions and refusals**, on `fylgja-test-017-hand`, seeded by the fixture tool in 31.4 s.

- **The writes**, by GraphQL on the branch, took 2.5 s at 13:28:49Z:
  - `cs1`, with no tag and no platform, and its port `port1`;
  - the ports `n1:ethernet-1/3`, `n1:ethernet-1/4`, `n2:ethernet-1/3` and `n3:ethernet-1/3`;
  - the cable `c-out`, between `n1:ethernet-1/3` and `cs1:port1`;
  - the cable `c-three`, joining `n2:ethernet-1/3`, `n3:ethernet-1/3` and `n1:ethernet-1/4`.
- **The read**, exit 0: `3 devices (nokia_srlinux 3), 13 interfaces, 3 links, 3 artifacts, 0
  lossy mappings, 0 shared ports; 2 cables omitted (branch fylgja-test-017-hand, …)`, with
  two `info` findings:

  ```
  info omit.cable.ends c-three: cable c-three is omitted: other than two ends (3); its ends are n1:ethernet-1/4, n2:ethernet-1/3, n3:ethernet-1/3
  info omit.cable.outside_scope c-out: cable c-out is omitted: an end outside the scope (18e21766-2e61-eb2e-33b9-c513813241f7:port1); its ends are 18e21766-2e61-eb2e-33b9-c513813241f7:port1, n1:ethernet-1/3
  ```

  The end outside the scope is `cs1:port1`, named by `cs1`'s id, since the read never reads
  `cs1` (§5.6). The CTM holds `n1`, `n2` and `n3` and the fixture's three links, and no
  `cs1`. `.envelope.fidelity` holds five rows, sorted: the two `approximated`, then
  `omitted` `c-out`, `c-three` and `platform.version`.
- **The platforms.** The branch gained `OrganizationManufacturer nokia` and `DcimPlatform
  SR-Linux` under it. `n1` was moved onto that platform, and `n2`'s platform set to `null`.
  The read then exited 1 and wrote no file: `local/hand.ctm.json` kept its bytes and its
  time. It gave both rejections in one pass, beside the two omissions:

  ```
  rejection platform.missing n2: device n2 carries no platform; its support package is the one whose matches name its platform and manufacturer
  rejection platform.unmatched n1: device n1: manufacturer "nokia", platform "SR-Linux"; the packages match: arista_eos [Arista / EOS], nokia_srlinux [Nokia / SR Linux]
  ```

- `-branch fylgja-test-017-hand -delete`: `deleted 0 stages, 0 proposed changes, branch
  fylgja-test-017-hand` (6.3 s).

**§6, stages**, on `fylgja-test-017-stages`.

- **The setup.**
  - The branch was seeded in 23.0 s.
  - `cs1` was written before the proposed change, as `TestStagesSeeEveryWriteOfADevice`
    writes it, since its creation on the platform moves the platform's stamp (§5.8). It is
    untagged, on `Nokia` / `SR Linux`, with `mgmt0` (role `management`) and `ethernet-1/1`.
  - `-propose` printed `proposed change 18e21779-… opened on fylgja-test-017-stages, draft; 5
    validators concluded in 83s`. All five completed `success`: Data Integrity, Schema
    Integrity, the artifact validator, `fylgja-twin` and `fylgja-step`.
    - `fylgja-twin`'s message: `skipped: proposed change … is a draft; …`.
    - `fylgja-step`'s message is the plan, with `fylgja-test-017-stages/branch-point:
      refused (scope.empty)`.
- **The order.** The edits were made in the tier-2 test's order rather than the quickstart's.
  Each was marked after it and judged by `bin/fylgja stage plan --branch fylgja-test-017-stages`.
  After every edit but the last, `-run-check` regenerated the artifacts (31.8 s, 23.6 s,
  23.7 s), and a second mark was taken and read fresh, so that each mark is stale by its own
  edit alone. The virtual interface goes last, since the first generation to read a new node
  moves its stamp (§5.8).
- **What each mark read** (every plan exits 1, by the branch point's rejection):

  | Mark | Edit (UTC) | Verdict | Written at |
  |---|---|---|---|
  | `seeded` | none | fresh, bundle `ad1716a8…` | |
  | `untagged` | `cs1`'s `description`, 13:32:07.8 | fresh; the head moved to 13:32:07.988 | |
  | `platform` | `SR Linux`'s `description`, 13:32:24.7 | `stage.artifact.stale` `n1`, `n2`, `n3` | the platform's stamp, 13:32:24.850 |
  | `manufacturer` | `Nokia`'s `description`, 13:33:38.6 | stale `n1`, `n2`, `n3` | `infrahub.node.updated of a OrganizationManufacturer`, 13:33:38.712 |
  | `cable` | the cable on `n1:ethernet-1/1` re-ended to that port alone, 13:34:55.4 | stale `n1`, `n2`; not `n3` | `infrahub.node.updated of a InterfacePhysical`, 13:34:55.501 |
  | `virtual` | `InterfaceVirtual lo0` on `n1`, 13:36:12.2 | stale `n1` alone | `n1`'s stamp, 13:36:12.296 |

  - After each stale mark, the head was refused stale for the same devices.
  - The head had passed the re-ending at the first plan after it, 11.2 s on (the plan's own
    time included).
  - `platform-checked`, `manufacturer-checked` and `cable-checked` each read fresh.
  - `cable-checked` read two links and `info omit.cable.ends
    n1:ethernet-1/1|n2:ethernet-1/1 … other than two ends (1)`.
  - The `platform` mark was planned again a minute later. It then named the event, `written
    at 13:32:24.963472 (Infrahub's event log: infrahub.node.updated of a DcimPlatform; its
    latest stamp 13:32:24.850161)`, which had landed in the log since the first plan.
- **The branch point**: every plan read `fylgja-test-017-stages/branch-point: refused
  (scope.empty)`, `scope tag:fylgja selects no device on branch main at
  2026-10-26T13:29:45.838959Z`. The step from it read `not computed (… branch-point was
  refused)`, and the plan went on to every mark and the head.
  - `fylgja-step` passed over it at the proposed change's creation, as above.
  - The rehearsal's passing over it boots a twin, so it is §7's checks test (T062), not a
    hand step.
- **What §5.8 left owed**, partly seen here: in a proposed change's pipeline, a mark after a
  run-check was fresh each time. So the artifact validator's completion covered the query
  group's writes that follow a generation, for these edits. A new node's first generation
  (`lo0`) and a hand `-generate` were not exercised.
- `-branch fylgja-test-017-stages -delete`: `deleted 9 stages, 1 proposed change, branch
  fylgja-test-017-stages` (11.1 s).

**Afterwards**: `Branch` lists `main` and `fylgja-fixture` alone. `CoreProposedChange`,
`FylgjaStage`, `CoreChangeThread`, `CoreUserValidator`, `DcimDevice` and `BuiltinTag` count
0 on `main`, and `main`'s hash is `7c413536…`.

<a id="5-6"></a>
### 5.6 The read against the running Infrahub (T039–T041; 2026-10-26, 01:57Z–01:59Z)

Numbered after §5.4 and §5.5, which T058 and T061 hold. On one throwaway branch,
`fylgja-test-017-read`. `fylgja-fixture -branch fylgja-test-017-read -schema-only` made it
from `main` at 01:57:41Z and loaded the library and the stage kind in 42.3 s wall. A probe
test that was not committed (`TestRun11Probe`, 13.0 s) then wrote, with test support's own
writers, the three-node topology (no group join, no render), an untagged `cs1` with
`port1`, a cable `c-out` from a new `n1:ethernet-1/3` to `cs1:port1`, and a cable
`c-three` joining new `n1:ethernet-1/4`, `n2:ethernet-1/3` and `n3:ethernet-1/3`. The
writes took 8.7 s. It then ran this tree's `CheckConformance` and `Fetch` under two scopes.
Nothing was written to `main`, and no token was printed.

- **`tag:fylgja`**: conformance gave no finding, and the read took 3.8 s, schema included.
  Both new operations were accepted, and their answers decoded, the bound connector
  included.
  - **Devices**: `n1`, `n2` and `n3`, each `nokia_srlinux` by the pair `Nokia` / `SR Linux`;
    `cs1` was not read.
  - **Ports**: five on `n1`, four each on `n2` and `n3`, the management port by its role.
    Every port read enabled: its status is the library's default, `active`.
  - **Links**: the fixture's three, each port `link`ed to its canonical id.
  - **Omitted**: `omit.cable.outside_scope c-out`, reason `an end outside the scope
    (18e1f1c5-…:port1)`. The end outside the scope is named by its device's id, since the
    read never reads that device. Also `omit.cable.ends c-three`, reason `other than two
    ends (3)`. Each was an info finding and a fidelity row, beside the three fixed rows,
    sorted.
  - **Refused**: `artifact.missing` for each device, since nothing on this host renders
    the library's kinds until the template's import (T058). The envelope carried `scope
    tag:fylgja` and the mapping `infrahub-dcim`, `opsmill/schema-library`, `26336e9`.
- **`tag:nothing`**: one `scope.empty tag:nothing`, `scope tag:nothing selects no device on
  branch fylgja-test-017-read`, in 0.56 s, schema included. No port was asked for.
- **The branch was deleted** by `-branch fylgja-test-017-read -delete` at 01:59:31Z
  (`deleted 0 stages, 0 proposed changes, branch fylgja-test-017-read`). Afterwards
  `Branch` lists `main` and `fylgja-fixture` alone, `CoreProposedChange` and `FylgjaStage`
  count 0, and `main`'s hash is `e43a1cde…`.

<a id="5-7"></a>
### 5.7 The read's tier-2 cases before the render (T044; 2026-10-26, 02:28Z–02:34Z)

On two throwaway branches, each made from `main` by its test and deleted by its cleanup,
run side by side. Nothing renders the library's kinds on this host until the template's
import (T058), so a test that seeds cannot pass yet; these two need no render. Nothing was
written to `main`, and no token was printed.

- **`TestSchemaCheckNamesAMissingKind`, committed, passed** (258.6 s) on
  `fylgja-test-nocable-1792981732-6049`. It loaded the library and the stage kind, then
  `internal/intent/testdata/dcim-cable-absent.yaml`. `DcimCable` was gone in 1 m 48.8 s,
  counted until `DcimCableCreate` left the branch's GraphQL schema. That is more than R-18's
  "about 40 s", with a second branch loading the library at the same time. Conformance then
  gave one finding, `schema.kind.missing DcimCable`, naming `opsmill/schema-library@26336e9`.
  It named nothing beside it, though Infrahub's `DcimConnector` was left with no implementer.
  The read refused the branch with the same finding and no CTM.
- **A probe that was not committed** (`TestRun12Probe`, 287.5 s) ran on
  `fylgja-test-017-run12-1792981731-5632`, using test support's new writers.
  - **The seed**: the library loaded in 1 m 24.4 s. `SeedThreeNode` wrote the topology, and
    its render ended `Error` ×3 after its 90 s, as T029's note found.
  - **The writers**: `AddDevice` wrote `cs1` (no tag, no platform, `port1`) and `cs2`
    (`Nokia` / `SR Linux`, `mgmt0` its management port, no tag), and refused a second
    `cs1`. `AddInterface` wrote four ports. `AddCable` wrote `c-out` (two ends) and `c-three`
    (three ends), and refused a cable to a port that does not exist.
  - **The read under `tag:fylgja`**: `n1`–`n3`, 13 interfaces and 3 links. `c-out` was
    omitted `omit.cable.outside_scope`, its outside end named by `cs1`'s id
    (`18e1f394-…:port1`), and `c-three` `omit.cable.ends`, `other than two ends (3)`. The
    fidelity list held five rows, sorted. Each device was refused `artifact.not_ready`, its
    artifact `Error`, which is expected before T058.
  - **The tag after T**: T was taken 1.1 s after the writes, and `cs2` was tagged `fylgja`
    1.1 s after T. The read pinned at T read `n1`–`n3` alone. The unpinned read read `cs2`
    too, and refused it `artifact.missing`, since nothing was ever rendered for it. **So a
    pinned read filters by the tag as it stood at T** (§4's owed fact).
    `TestPinnedReadReproducesItsBundle` asserts it with a device rendered before T, at T062.
  - **The platforms**: `DcimDeviceUpdate` with `platform: null` took `n2`'s platform away,
    read back as a null node. `n1` moved onto `nokia` / `SR-Linux`, written with its
    manufacturer. The read then refused `platform.unmatched n1` (`device n1: manufacturer
    "nokia", platform "SR-Linux"; the packages match: arista_eos [Arista / EOS],
    nokia_srlinux [Nokia / SR Linux]`) and `platform.missing n2` (`device n2 carries no
    platform; …`) in one pass, with no CTM. The omissions and the other devices' artifact
    findings came beside them.
  - **`tag:nothing`**: one `scope.empty`, `scope tag:nothing selects no device on branch
    fylgja-test-017-run12-1792981731-5632`.
- **Afterwards** `Branch` lists `main` and `fylgja-fixture` alone, `CoreProposedChange` and
  `FylgjaStage` count 0, and `main`'s hash is `e43a1cde…`.

<a id="5-8"></a>
### 5.8 The stamps and the events against the running Infrahub (T047–T048; 2026-10-26, 03:02Z–03:05Z)

Two runs of a probe that was not committed (`TestRun13Probe`, in `internal/testsupport`
for its unexported writer), each on a throwaway branch `fylgja-test-017-run13-<unix>` made
from `main`, the library and the stage kind loaded (34.1 s, 46.8 s), the three-node topology
written with no group join and no render (2.5–3.5 s), and the branch deleted by its
cleanup. Then this tree's `Stamps` under `tag:fylgja` after each write below, and
`IntentEvents` since the branch point. Nothing was written to `main`, and no token was
printed.

- **An uncabled port refuses the whole page.** The first run's `PortStamps` selected every
  physical port: `Cannot return null for non-nullable field
  NestedEdgedDcimConnector.node_metadata`, once per uncabled port (`input:14:
  InterfacePhysical.edges[2].node.connector.node_metadata`). The SDL declares the wrapper's
  `node_metadata` non-null, and an uncabled port's is null. The query now asks for cabled
  ports alone, `InterfacePhysical(device__ids: …, connector__isnull: false)`, which the
  second run's every read accepted.
- **What moved which device** (the second run; a device "moved" when its `Intent` changed):
  - `InterfaceVirtual lo0` created on `n1`, then its `description` edited: `n1` alone, each
    time; `lo0`'s id joined `n1`'s `IDs`.
  - The platform's `description`: `n1`, `n2`, `n3`. The manufacturer's `description`: all
    three.
  - The cable `n1` — `n2`'s `status`: `n1` and `n2`, not `n3`.
  - **An untagged `cs1` created on the same platform (`Nokia` / `SR Linux`) with a port:
    `n1`, `n2`, `n3`**, every tagged device on it, at `cs1`'s creation stamp. The platform's
    `node_metadata` counts its reverse `devices` edge, as §1.7's rule says of every edge;
    and the log holds `DcimPlatform updated` naming `cs1`, whose primary node, the platform,
    is in every tagged device's `IDs`. Then `cs1`'s `description` edited: none.
  - `n1` joined to a `CoreStandardGroup`: `n1`. The same group upserted to the same member:
    none. This is Infrahub's `RelationshipManager.update`, which keeps a peer already
    there (`/source/backend/infrahub/core/relationship/model.py`, read in the image).
  - The cable `n1` — `n2` re-ended to `n1`'s port alone: no stamp moved, as §1.7 found. The
    log then held `DcimCable updated` naming the cable and `n2`'s former port, and
    `InterfacePhysical updated` naming that port and the cable, 1.4 ms apart, read 2 s after
    the write. Both name `n2` by its port's id.
- **The events' rule**: 49 intent events since the branch point, of `DcimDevice`,
  `InterfacePhysical`, `InterfaceVirtual`, `DcimCable`, `DcimPlatform` and
  `OrganizationManufacturer` alone. No `CoreStandardGroup`, `BuiltinTag` or location kind
  was kept, and the group join's `member_of_groups` update on `n1` was not.
- **Owed, for the operator** (T049's note):
  - US5 scenario 2 says a write to an untagged device makes no tagged device's mark stale.
    An untagged device created on, moved onto or moved off a platform that tagged devices
    share does, by the platform's stamp and its event alike. Editing one does not.
  - A node's first join of a group moves its stamp. Infrahub writes the query group of the
    template's query about three seconds after each generation's checksums
    (`docs/verified-facts.md`, 10-17), so a device, interface, cable, platform or manufacturer first read by a
    generation is stamped after its checksum. In a proposed change's pipeline the artifact
    validator's completion may come later and cover it; after a hand generate nothing does.
    Neither can be seen on this host until the template's import (T058). Owed at T061 and
    T062.
- **Afterwards** `Branch` lists `main` and `fylgja-fixture` alone, `CoreProposedChange` and
  `FylgjaStage` count 0, and `main`'s hash is `e43a1cde…`.

### 5.9 Test support's writers for the stages' tier-2 test (T051; 2026-10-26, 03:27Z–03:29Z)

An uncommitted probe (`TestRun14Probe`, in `internal/testsupport`) on a throwaway branch
`fylgja-test-017-run14-<unix>` made from `main`, the library and the stage kind loaded
(39.2 s), two tagged devices `n1` and `n2` on `Nokia` / `SR Linux` and the cable between
their `ethernet-1/1`, with no group join and no render; then the branch deleted by its
cleanup (64.6 s in all). Nothing was written to `main`, and no token was printed.

- `AddVirtualInterface(n1, lo0)` wrote one `InterfaceVirtual` on `n1`, found by
  `DcimInterface(device__name__value, name__value)` on the generic; a second of the name was
  refused before any write.
- `SetPlatformDescription` and `SetManufacturerDescription` each updated the one node of the
  name; an absent name was refused before any write.
- `ReEndCable(n1, ethernet-1/1, n1:ethernet-1/1)`: `DcimCableUpdate` with one peer in
  `connected_endpoints` replaced the set. The cable read one end, `n1:ethernet-1/1`, and
  `n2:ethernet-1/1`'s connector read `{"node": null}`.
- **Afterwards** `Branch` lists `main` and `fylgja-fixture` alone, `CoreProposedChange` and
  `FylgjaStage` count 0, and `main`'s hash is `e43a1cde…`.

What these writes do to the stamps and the events is §5.8's. Whether a run-check clears each
write before the next, as `TestStagesSeeEveryWriteOfADevice` asserts, needs the template's
import (T058). It is owed at T062.

<a id="5-10"></a>
### 5.10 `main` migrated (T056; 2026-10-26, 12:26Z–12:31Z)

The migration of [R-14](#r-14)'s steps 1 and 2, run on `main` by Run 16 of the converge loop
from `97856b3`, with `local/.env` loaded and the worker and the server restarted from this
tree. It was recorded here because §5.3 already holds T036's conformance. This is the
feature's one lasting write to `main`. No token was printed.

- **The precondition, read at 12:24Z.**
  - `main`'s hash was `e43a1cde…`: 62 nodes and 35 generics, no `Dcim*` kind.
  - `Branch` listed `main` and `fylgja-fixture` alone.
  - The nine kinds the documents remove each counted 0. So did `CoreArtifact`,
    `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread` and `CoreUserValidator`, and
    `fylgja-devices` had no member.
  - `fylgja` was the one registration, `ref main`, at `3c3e79a`, with its two checks.
  - There was no container, no `local/twin`, no Schedule and no running workflow.
- **The first document**, [`migration/1-reference-kinds-absent.yaml`](migration/1-reference-kinds-absent.yaml).
  - `schema check --branch main` (10.7 s): `Valid!`, with `removed:` naming `FylgjaContract`,
    `NetworkDevice`, `NetworkInterface`, `NetworkLink` and `NetworkPlatform`.
  - `schema load --branch main`: `1 schema processed in 47.162 seconds` (49.0 s wall),
    against the rehearsal's 50.6 s (§1.9).
  - Afterwards the hash read `6a17b5b8…`, with 57 nodes and 35 generics. `NetworkDevice`
    answered `Cannot query field 'NetworkDevice' on type 'Query'.`, and `FylgjaDevice` still
    counted 0.
- **The second document**, [`migration/2-generics-absent.yaml`](migration/2-generics-absent.yaml).
  - `schema check --branch main` (11.3 s): `Valid!`, with `removed:` naming `FylgjaDevice`,
    `FylgjaInterface`, `FylgjaLink` and `FylgjaPlatform`.
  - `schema load --branch main`: `1 schema processed in 42.228 seconds` (44.3 s wall),
    against the rehearsal's 48.0 s.
  - Afterwards the hash read `66edc133…`, with 57 nodes and 31 generics.
    - `GET /api/schema?branch=main` listed `FylgjaStage` alone of the `Fylgja*` and
      `Network*` kinds.
    - `FylgjaDevice` and `FylgjaContract` each answered `Cannot query field '<kind>' on
      type 'Query'. Did you mean 'FylgjaStage'?`.
    - `CoreArtifactTarget`'s `used_by` was empty.
  - `FylgjaStage` was untouched: branch-agnostic, with `label`, `as_of`, `description` and
    a required `proposed_change`. So was its extension, `CoreProposedChange.fylgja_stages`
    (many, peer `FylgjaStage`, identifier `proposed_change__fylgja_stages`).
  - Checked again after both loads, each document printed `is Valid! No diff`.
- **The library**: `go run -tags fixture ./cmd/fylgja-fixture -prepare-main` at 12:29:43Z,
  43.5 s wall with `go run`'s build, exit 0. It printed:

  ```
  schema library loaded on main (6 files, opsmill/schema-library@26336e9)
  stage kind present
  group fylgja-devices present
  repository fylgja present (location https://github.com/happypathnetworking/fylgja.git, ref main)
  import complete after 2s: query, transform and definition on main
  ```

  The import's wait returned at once, because `3c3e79a`'s import was already on `main` and
  the registration read `active` / `online`.
  - **`main`'s new hash**, from `/api/schema/summary`: **`7c413536…`**. The schema has 71
    nodes and 52 generics, nine of them `Dcim*`.
  - `CoreArtifactTarget`'s `used_by` names `DcimDevice` alone, as §5.2 expected of the
    migrated `main`.
  - The library added the same 14 nodes and 21 generics that it added on the rehearsal's
    branch, which held 76 and 56 (§5.3). That branch was made from a `main` that still
    held the five reference kinds and the four generics.
  - `DcimDevice` and `CoreArtifact` count 0, and `fylgja-devices` has no member.
  - The registration is unchanged: `commit 3c3e79a`, `active` / `online`, two checks.
- **The refusal.** Run again at 12:30:45Z, the tool exited 1 in 1.4 s and printed one
  line. It wrote nothing: the hash still read `7c413536…`. The line:

  ```
  fylgja-fixture: main holds 27 of the schema library's kinds (DcimCable, DcimConnector, DcimDevice, DcimDeviceType, DcimEndpoint, DcimGenericDevice, DcimInterface, DcimPhysicalDevice, DcimPlatform, InterfaceHasSubInterface, InterfaceLayer2, InterfaceLayer3, InterfacePhysical, InterfaceVirtual, IpamIPAddress, IpamPrefix, IpamPrefixScope, IpamVLANGroupScope, LocationCountry, LocationGeneric, LocationHosting, LocationMetro, LocationRegion, LocationSite, OrganizationGeneric, OrganizationManufacturer, OrganizationProvider): -prepare-main is the development host's and CI's tool, which loads the library on an empty main alone; a main that already holds the library is yours, and fylgja schema check says whether it is the one the reader reads
  ```

  The bring-up script's `library_held` reads this saved output as the library present, and
  does not read a load's output that way. It was run alone, outside the script.
- **Conformance on the migrated `main`**, read-only through the server from this tree:
  `fylgja schema check --branch main` answered the two lines below, exit 0.

  ```
  conformant with opsmill/schema-library@26336e9: DcimDevice, DcimPlatform, OrganizationManufacturer, InterfacePhysical, DcimCable
  stages: FylgjaStage present on the default branch, with its extension
  ```

  `fylgja-fixture` is untouched and still gives the five `schema.kind.missing` until T060
  re-seeds it.
- **What `3c3e79a`'s import leaves on `main` until T058.** The stored query
  `device_config`'s `models` still names the eight removed kinds (`FylgjaDevice`,
  `FylgjaInterface`, `FylgjaLink`, `FylgjaPlatform` and the four `Network*`).
  `fylgja_branch` names none. The transform `srlinux_device_config` and the definition,
  targeting `fylgja-devices`, are unchanged. The group has no member, so nothing renders
  through them. T058's import replaces the query.
- **Afterwards** `Branch` lists `main` and `fylgja-fixture` alone. `CoreProposedChange` and
  `FylgjaStage` count 0, and nothing else was written.

<a id="5-11"></a>
### 5.11 Tier 2 whole, and what a generation stamps (T062; 2026-10-26, 13:45Z–14:34Z)

Run 19 of the converge loop, at `1914556`, with `local/.env` loaded, the worker (pid
335153) and the server (pid 335155) rebuilt and restarted from this tree, and no twin.
T062 names §5.6 for this record, which T039–T041 already hold. Every branch below was a
throwaway, deleted by its test. Nothing was written to `main`, and no token was printed.

**A `DcimCable`'s delete stamps its two end ports.** This is what CI's contract job on
`c006bf9` found (run `40325771758`; T057), verified here three ways:

- `TestStagesSeeARemoval`, unchanged, at 13:47Z. The delete was sent at 13:47:33.880 and
  returned at 13:47:35.117. It moved the branch's latest stamp, and `n1`'s and `n2`'s
  intent stamps, from 13:46:27.669 to 13:47:34.064. It did not move `n3`'s. The test failed
  on its D-048 premise check alone, as on CI. The plan still refused `removed` and the head
  `stage.artifact.stale` for `n1` and `n2`, each naming the event, `infrahub.node.updated of
  a InterfacePhysical` at 13:47:35.12, later than the stamp.
- An uncommitted probe (`TestRun19Probe`) on a branch with three tagged devices and two
  cables, written with no render. The delete was sent at 13:49:27.543 and returned at
  13:49:27.822.
  - Each end port's `node_metadata.updated_at` moved to 13:49:27.754, read both as the
    device's `interfaces` edge and as the `InterfacePhysical` node.
  - Nothing else moved: neither device's own stamp, the platform's edge, `n3`, nor the
    other cable and its ports.
- `TestStagesSeeARemoval` rewritten to assert it (below), passed alone (209.2 s) and in the
  tier.

`NetworkLink`'s delete stamped nothing (014 research §8.17; `docs/verified-facts.md`,
10-17), and neither does a cable's re-ending (§5.8). D-048's event read stays, for the
re-ending, as the operator chose.

**Three fixes, each in its test (T057's note):**

- `internal/server`'s `TestRehearseRefusesBeforeAnyRun` and
  `TestRehearseComposedByTheFixtureTool` send `scope: tag:fylgja` (`fixtureScope`, from
  `testsupport.FixtureTag`) on `twin.rehearse` and `intent.read`. `handlerServer` has no
  default scope, as a server started without `FYLGJA_DEFAULT_SCOPE` has none, and the
  server's `scope.unset` is right. Both passed alone (317.2 s, side by side with the next)
  and in the tier.
- `TestStagesSeeARemoval` now asserts what Infrahub does, which the stage reader already
  handled:
  - the branch's latest stamp moves on the delete;
  - `n1`'s and `n2`'s intent stamps are that latest, and `n3`'s does not move;
  - the head passes the stamps' head by the delete's events, which land after its stamp.

  Its comment says why the premise check went. The plan's outcomes, the events named in the
  messages, and the regenerate's clearing of the head are as before.

**The tier**: `make test-contract 2>&1 | tee local/017-contract.out`, 13:56:42Z–14:25:15Z,
**1,712.5 s** wall, exit 2. `internal/checks` failed. Every other package passed:

| Package | Time |
|---|---|
| `internal/stages` | 1,426.6 s |
| `internal/stage` | 839.6 s |
| `internal/server` | 838.2 s |
| `internal/intent` | 652.3 s |
| `internal/cli` | 148.2 s |
| `internal/lab` | 11.5 s |
| `internal/provision` | 9.1 s |
| each of the other 15 | under 3.3 s |
| `internal/checks`, alone after them | 276.3 s, **FAIL** |

The owed facts held, each by its test's assertions; the tier runs without `-v`, so no
test's log was kept:

- **`schema.kind.missing` on a real branch**: `TestSchemaCheckNamesAMissingKind` (in
  `internal/intent`). One rejection on `DcimCable`, its message ending `as
  opsmill/schema-library@26336e9 has it`, and nothing else named.
- **A pinned read filters by the tag as it stood at T**: `TestPinnedReadReproducesItsBundle`
  (in `internal/stage`). `cs1`, rendered before T and tagged after it, is read by the
  unpinned read alone.
- **A rebase over the library's kinds**: `TestStageRefusals` (in `internal/stages`). Every
  mark is refused, naming the rebase at the new `branched_from` and the branch's
  `created_at`, which the rebase did not move.

**`TestChecksInsideInfrahub` failed: a new node's first generation stamps it after the
generation.** This is §5.8's owed fact (T049's open question 2), now seen live. The test
seeded its branch, opened a draft and marked `seeded`. It then added the third link with
`SeedThirdLink`, whose generate is a hand one (`POST /api/artifact/generate`), waited for
`n1`'s and `n3`'s checksums to move, and marked `third-link` at 14:23:05.456.

- The re-run's plan refused the head `stage.artifact.stale` for `n1` and `n3`. Their intent
  was written at 14:23:09.920, after their checksums (14:23:02.472, 14:23:04.294) and after
  the validator's last completion (14:22:31.181). No event was named.
- `fylgja-test-step` concluded `failure`, against the test's `success`. The test's other
  assertions held: the stale mark's failure, the ready proposed change's refused rehearsal
  and its two comments, and no twin.

An uncommitted probe (`TestRun19GroupJoinProbe`, run twice, 14:27Z–14:34Z) followed the
test's route, then tried both ways of regenerating:

- **The hand generate**: the third link was written at 14:32:15.53. The checksums moved to
  14:32:24.937 (`n1`) and 14:32:25.580 (`n3`). `n1`'s and `n3`'s intent stamps then moved to
  14:32:28.709, 3.1–3.8 s after the checksums.
  - The stamp is the new port's and the new cable's (`n1:ethernet-1/3`, `n3:ethernet-1/3`,
    the cable). It is their `member_of_groups` edges to the template query's groups
    (`device_config__<hash>`, one per artifact), written at 14:32:28.706 and 28.709.
  - `updated_by` on those nodes reads `agent`, Infrahub's own account. The devices'
    own stamps read `admin`.
  - A port is a member of its own device's group and of its peer's, since the template
    reads the far end.
- **The plan** then refused both `third-link`, marked after the stamp, and the head
  `stage.artifact.stale` for `n1` and `n3`.
- **A second hand generate** rendered identical bytes and wrote nothing. Every checksum and
  stamp stayed, and the plan was unchanged.
- **The proposed change's artifact check** (`CoreProposedChangeRunCheck`, `ARTIFACT`)
  completed its validator at 14:33:39.870, 25 s on. The head then compiled. `third-link`
  stayed stale, since the validator completed after its `at`.
- **The seed does it too.** After the seed's own render, every port's and cable's stamp is
  its group join, by `agent`, and `n2`'s intent stamp (14:31:07.130) is later than its
  checksum (14:31:06.375). The proposed change's creation covers it: its pipeline's
  validator completes later (14:31:58.353). So `seeded` and the head read fresh before the
  third link.

So with R-10's stamps, whatever a generation reads for the first time reads stale after a
hand generate, and no further hand generate clears it. That covers a new device, interface
or cable. Only the proposed change's artifact check clears it, and only for a stage marked
after that check. In 0.2 the same route left the head fresh, and FR-024 and US5's
Independent Test keep 0.2's behaviour.

`TestStagesListAndPlan` takes the same route and passed. Its list and plan most likely
read the head inside the 3–7 s before the groups' join; the tier keeps no test's log, so
this was not seen. It is a race the test can lose. The other tier-2 tests that add a node
judge no staleness after it. Tier 3's cases 7 and 9
take the same route (`-add-link`, then `third-link` and a plan expecting the head to
compile), so T063 would meet it too.

How to stop counting the query groups' joins is the operator's decision (T062's note). D-048
and R-10's event rule already call this churn and never intent.

**Afterwards**:

- `Branch` lists `main` and `fylgja-fixture` alone.
- `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread` and `CoreUserValidator` count 0.
- `main` holds no device, and its hash is `7c413536…`.
- The registration `fylgja` is the only one, at `c006bf9`.
- `clab inspect --all` is `{}`, there is no `local/twin`, and Temporal lists no Schedule.

<a id="5-12"></a>
### 5.12 Who writes a generation's group joins (T062, D-058; 2026-10-26, 14:45Z–14:56Z)

Run 19 again, at `78351aa`, before any code: D-058 has the build verify first how
Infrahub marks its own account on `updated_by`, and stop if that account can be told only
by a name an install may change. This was read two ways. First in Infrahub 1.11.2's source,
inside `fylgja-infrahub-infrahub-server-1` (`/source/backend/infrahub`). Then live, on the
throwaway branch `fylgja-test-017-run19-1793026272`, seeded by the fixture tool (28.3 s),
given the third link by `-add-link`, read by an uncommitted GraphQL probe, and deleted
(`deleted 0 stages, 0 proposed changes, branch …`). Nothing was written to `main`, the
worker and the server were not used, and no token was printed.

**Infrahub's own identity is `__system__`, and it writes none of the joins.**

- `SYSTEM_USER_ID = "__system__"` (`core/constants/__init__.py`) is the default `user_id` of
  every in-process save and delete. `node_metadata` resolves it to a synthetic account
  whose display label is `[Infrahub System]` (`graphql/loaders/account.py`). No install
  can change that id.
- It is the `created_by` and `updated_by` of both accounts on `main`, `admin` and `agent`
  (2026-10-08, the install's initialization).

**The joins are written by the task workers' account, on this install `agent`.**

- The template query's groups are written by the flow `graphql-query-group-update`
  (`groups/tasks.py`). It runs on a task worker and saves the `CoreGraphQLQueryGroup`
  through the SDK's client, `group.save(allow_upsert=True)`.
- That client is built from the worker's settings (`workers/dependencies.py`), and the
  SDK reads its token from `INFRAHUB_API_TOKEN`. Infrahub's published Compose file gives
  the task workers `INFRAHUB_INITIAL_AGENT_TOKEN` there. So the account is whichever one
  owns the token an install gives its task workers.
- Infrahub's initialization creates `agent` only when an agent token or password is set,
  under the hard-coded name `agent`, with `account_type` `User`, as it creates `admin`
  (`core/initialization.py`, `create_account`).
- Live, on `main`: `admin` (`18dc77a5-3850-…`, label `Admin`) and `agent`
  (`18dc77a5-c3c3-…`, label `Agent`), both `account_type` `User`, `active`, with no
  description.
- `GET /api/schema?branch=main`: `CoreGenericAccount.name` is unique, `read_only: false`.
  `account_type` is optional, defaults to `User`, and has the enum `User`, `Script`,
  `Bot`, `Git`.
- The branch's three `device_config__<hash>` groups (`group_type` `internal`, 12 members
  each) were created by `Agent` (2026-10-21, the demo window's renders on `main`) and
  updated by it at the seed's render.

**What the seed's render stamped.** The seed wrote every node as `Admin` between
14:51:27.6 and 14:51:30.7, and the checksums moved between 14:51:43.58 and 14:51:43.92.
Then, at 14:51:45.78–14:51:47.44, `Agent` restamped **every node the stamps read**: each
device, the platform, the manufacturer, every interface and every cable (`updated_by`
`Agent`). §5.11 named the ports' and the cables' joins after the seed. The devices, the
platform and the manufacturer join too, and only a first read joins. So, with R-10's
stamps, every device reads stale after the seed's own hand render. The proposed change's
creation covers that, as §5.11 found.

**The third link's hand generate** (`-add-link`, 14:53:16.44–14:53:18.36):

- Written as `Admin`: the two new ports at 14:53:17.107 and 14:53:17.251, which also moved
  `n1`'s and `n3`'s own stamps by `Admin`, and the cable at 14:53:17.716.
- The checksums moved at 14:53:24.591 (`n1`) and 14:53:25.682 (`n3`).
- At 14:53:28.761, `Agent` restamped the two new ports and the cable. No node that was
  already a member moved.
- Today's rule therefore reads `n1`'s and `n3`'s intent at 14:53:28.761, after their
  checksums: stale, as §5.11 found.
- D-058's rule (an `Agent` stamp counts as its node's `created_at`), applied by hand to the
  probe's output, reads `n1` 14:53:17.716 against 24.591 and `n3` 14:53:17.716 against
  25.682. `n2` reads 14:51:30.540 against 14:51:43.579. All three are fresh. After the
  seed, before the link, all three were fresh as well.

**So the account is told apart only by its name.** Nothing Infrahub records marks `agent`
as its own:

- its `account_type` is `admin`'s, and `__system__` created both;
- its token is the install's choice;
- its name is Infrahub's default, which an administrator may rename, and an install may
  run its task workers under another account, or with no `agent` at all.

This is D-058's stop condition. The rule is not built, and T062 stays open for the
operator (T062's note).

A route that names no account is visible here, for the operator: the writer of the
template query's own groups. Only Infrahub's flow writes a `CoreGraphQLQueryGroup` of
`group_type` `internal`, so whichever account last updated one is the account the task
workers run as, on any install. Reading it is a read of an Infrahub-owned kind the reader
does not make today (Constitution III's list, the read-only test).

<a id="5-13"></a>
### 5.13 Who else writes the template query's groups (T062, D-059; 2026-10-26, 15:15Z–15:25Z)

Run 19 a third time, at `2610a74`, before any code. D-059 names Infrahub's own account as
the `updated_by` of the template query's internal `CoreGraphQLQueryGroup`s, on the premise
that only Infrahub's flow writes them (§5.12's last paragraph). The groups' read was tried
first, read-only, on `fylgja-fixture` and `main`. Then the tier's removal was reproduced on
the throwaway `fylgja-test-017-run19c-1793028213`, seeded by the fixture tool (24.5 s, with
its render) and deleted (`deleted 0 stages, 0 proposed changes, branch …`). Nothing was
written to `main`, the worker and the server were not used, and no token was printed.

**The read D-059 asks for works as a query.** A device's artifact reaches its query by
`definition { node { transformation { node { query { node { id } } } } } }`. On
`fylgja-fixture` each `device-config` names `device_config` (`18dc77c3-196f-…`).
`CoreGraphQLQueryGroup(group_type__value: "internal", query__ids: [<that id>])` answers
the branch's three groups, with `node_metadata { updated_by { id } }` on each edge, with
or without `node` selected. On `fylgja-fixture` all three read `Agent`.

**A member's delete restamps the groups as the deleting account.**

- On `main`, the three groups read `created_by` `Agent` (2026-10-21, the demo window's
  renders) and `updated_by` **`Admin`**, all three at 2026-10-25T19:55:00.827234, with no
  member left.
- `main`'s event log at that instant: `infrahub.node.deleted` of a `NetworkPlatform` by
  `Admin`, whose `member_of_groups` named all three groups. Then `infrahub.node.updated`
  and `infrahub.group.member_removed` on each `CoreGraphQLQueryGroup`, each with
  `account_id` `Admin`'s.
- On the throwaway branch, after the seed's render, all three groups read `updated_by`
  `Agent` (15:24:03.38–03.44), with 12 members each.
- The n1 — n2 cable was then deleted as `Admin` (`DcimCableDelete`, sent 15:24:22.963,
  returned 15:24:23.346). The two groups the cable was a member of, n1's and n2's, then
  read `updated_by` **`Admin`** at 15:24:23.227218, with 11 members. n3's group stayed
  `Agent` at 15:24:03.436.
- Every group's `created_by` stayed `Agent`. So did each remaining member edge's
  `relationship_metadata.created_by`.

So the operator's account writes the groups too, whenever it deletes a node a generation
has read. That includes a cable, a port, a device, or the platform. The deleted node's
membership goes, and its group is stamped with the deleter's account.

**D-059 as written would leave out the operator's own stamps.** After that delete, the
groups' `updated_by` reads `{Admin, Agent}`. D-058's rule would then count every `Admin`
stamp as its node's `created_at`:

- `TestStagesSeeARemoval`'s assertion fails. It checks that the delete's port stamps are
  `n1`'s and `n2`'s intent (§5.11), and they would read as the ports' creation.
- On the source branch, an operator's later write is still caught by D-048's events,
  which `Stale` reads after the earliest checksum.
- The branch point reads `main`, and no events. `main`'s three groups read `Admin` today.
  So once `main` holds devices again, every `Admin` stamp there would be left out. A
  device on `main` edited after its render would then read fresh at the branch point,
  when it is stale.

D-059's own revisit names `__system__`, and not this case. So it is not built, and T062
stays open for the operator.

**What still tells the task workers' account apart, verified here:**

- **The groups' `created_by`.** The flow creates each group, and a member's delete does
  not move it: `Agent` on all three, before and after the delete. It is the same query
  as D-059's, with one field changed. It fails safe. If an install moves its workers to
  another account after the groups exist, that account's joins count again. That
  over-reports as stale, and never reads as a wrong fresh.
- **Each member edge's `relationship_metadata.created_by`.** Only the flow adds a member,
  and a delete removes the edge rather than restamping it. This is exact after a token
  change too. It is heavier: it reads every group's member edges, one group per rendered
  device.

<a id="5-14"></a>
### 5.14 D-058's rule under D-060's account, and tier 2 whole (T062; 2026-10-26, 16:05Z–16:46Z)

Run 19 a fourth time, at `118bdbd`, after [D-060](../../docs/decisions.md#d-060). The rule
was built in R-10's stamps (T047's and T049's code), its read tried live before the tier,
and the tier run whole. Every branch the tier made was a throwaway, deleted by its test.
Nothing was written to `main`, and no token was printed.

**What was built** (`internal/intent`):

- `IntentStamps` and `PortStamps` read each wrapper's `node_metadata { updated_at
  updated_by { id } created_at }`, bound as `stampMeta`. It is still one wrapper per node.
- The `ArtifactStamps` fragment also reads each artifact's `definition → transformation →
  query` id. The transformation's node is bound, so a transform of any kind decodes.
- A third query, `QueryGroups`, reads `CoreGraphQLQueryGroup(group_type__value:
  "internal", query__ids: …)` and selects only each group's `node_metadata.created_by {
  id }`. It runs on the stamps' branch, at their `at`, once the devices and ports are
  read. The read-only test names `CoreGraphQLQueryGroup` as the sixth owned root, with its
  reason.
- **The rule**: a node contributes its `updated_at`, or its `created_at` when its
  `updated_by` is one of the groups' creators. Nothing is folded until the groups are
  read.
  - No artifact means no query, so no groups request is made. No group leaves nothing
    out.
  - The rule applies wherever a node's stamp is folded: the device's intent, and the
    branch's latest, which sets the head's `at`. Checksums are folded as before.
  - So after a hand generate the head is one microsecond after the latest checksum, not
    after the join. `TestStagesListAndPlan` already asserted exactly that, and it held
    only when the test read before the join.
- **Tier 1**:
  - `TestStampsLeaveOutInfrahubsOwnAccount` runs over an account named as Infrahub names
    it and over a renamed one. In each, the joined port and cable count as their creation,
    and a stamp by an account that created no group is intent.
  - `TestStampsReadTheGroupsCreator` covers a group whose last writer is the operator's
    account: the operator's delete stamp stays intent. It also covers a scope with no
    internal group.
  - `TestStampsAskForGroupsWhereTheStampsAre`: with no artifact, no groups request is
    made, and a pinned read sends its `at` on the groups' request too.
  - With the rule switched off, the first two fail.
- **The mapping contract**: §2's roots and §6's stamp now say the same.

**Tried live first**, read-only, before the tier. The generated `IntentStamps` and
`QueryGroups` were sent as the client sends them to `fylgja-fixture`, and both were
accepted:

- Every device and interface read `updated_by` `Agent` at 13:22:46.04–.05. That is the
  seed's render's join, after the checksums at 13:22:44.63. Their `created_at` read
  13:22:14–18.
- Each artifact's transformation was a `CoreTransformJinja2` naming the query
  `18dc77c3-196f-…` (`device_config`).
- The three internal groups' `created_by` was `Agent`, a `CoreAccount`.

So under the rule the fixture's devices read their creation, before their checksums.

**`TestStagesListAndPlan` now meets the join instead of racing it.** After `SeedThirdLink`'s
artifacts move, `awaitJoined` polls `n1:ethernet-1/3`'s `node_metadata.updated_at` until
it is later than the branch's latest checksum, for at most a minute. Only then is
`third-link` marked. The list and the plan therefore always read after the join, which the
test used to read before. If the join is ever missing, the test fails naming D-058's
revisit.

**The tier**: `make test-contract 2>&1 | tee local/017-contract.out`, run from 16:17:29Z to
16:46:04Z, **1,714.7 s** wall, **exit 0**. Every package passed:

| Package | Time |
|---|---|
| `internal/stages` | 1,422.1 s |
| `internal/stage` | 829.2 s |
| `internal/server` | 768.3 s |
| `internal/intent` | 653.4 s |
| `internal/cli` | 207.7 s |
| `internal/lab` | 10.8 s |
| `internal/provision` | 8.1 s |
| each of the other 16 | under 3.9 s |
| `internal/checks`, alone after them | 278.8 s |

- **`TestChecksInsideInfrahub` passed** inside Infrahub's pipeline, through the server on
  the bridge from this tree (worker pid 668144, server pid 668165). Its checks' requests
  reached that server between 16:43:30Z and 16:45:48Z: `stage.plan`, the refused
  `twin.rehearse` and `twin.show`. So after `SeedThirdLink`'s hand generate and the
  `third-link` mark, `fylgja-test-step` concluded `success`, which §5.11's run did not.
- **That is every new test of T044 and T051, and every 014 and 015 test**, the three CI
  fixes of T057's first note among them.
- **The owed facts held**, each by its test's assertions as in §5.11. The tier runs
  without `-v`, so no test's log was kept:
  - `schema.kind.missing`'s wording on a real branch (`TestSchemaCheckNamesAMissingKind`);
  - the pinned read filtering by the tag as it stood at T
    (`TestPinnedReadReproducesItsBundle`);
  - `BranchRebase` over the library's kinds (`TestStageRefusals`).
- `TestStagesSeeARemoval` passed under the rule: the delete's port stamps are written by
  the operator's account, so they stay intent.

**Afterwards**:

- `Branch` lists `main` and `fylgja-fixture` alone.
- `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread` and `CoreUserValidator` count
  0.
- `main` holds no device, tagged or not, and its hash is `7c413536…`.
- `fylgja` is the only registration, at `c006bf9`, with `fylgja-step` and `fylgja-twin`.
- `fylgja-fixture`'s three devices each hold a `Ready` artifact.
- `clab inspect --all` is `{}`. There is no `local/twin`, and Temporal lists no Schedule
  and no running workflow.
