# Feature Specification: The Infrahub reader reads the schema library's DCIM

**Feature Branch**: `017-dcim-reader`

**Created**: 2026-10-25

**Status**: Draft

**Input**: User description: "SPECIFY_FEATURE_DIRECTORY=specs/017-dcim-reader GIT_BRANCH_NAME=017-dcim-reader. 0.3, the first of its four specs: the Infrahub reader reads the schema library's DCIM directly, the CTM becoming the contract in place of the generics, as docs/roadmap.md's F-011 and Release 0.3 section define it. Read specs/017-dcim-reader/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design."

Release 0.3 is exploratory coding toward the production refactor
([roadmap](../../docs/roadmap.md#release-03)), and this feature opens it. Until now Fylgja
read only its own four generics, and an operator's model had to implement them
([D-002](../../docs/decisions.md#d-002)). Probed against OpsMill's
[schema library](https://github.com/opsmill/schema-library), the generics would not
inherit into its DCIM without adapting one side or the other, and with NetBox to be read
directly later in the release, every reader is an adapter onto a fixed model anyway. So
**the generics go and the CTM becomes the contract**: the Infrahub reader reads the
library's own kinds, as they are at a pinned commit, by one documented mapping, and
records in the fidelity manifest every place the library's meaning is near Fylgja's and
not identical. A twin is now **of a scope**, a tag the operator puts on each device the
twin is of; inside the scope the read is strict, and at its boundary a cable is omitted
and recorded. Each support package declares which of the source's platforms it is, by
manufacturer and platform name, so nothing is added to anyone's model.

What the operator gets: a branch modelled in the library's DCIM, the model OpsMill
publishes, becomes a twin with nothing of Fylgja's loaded beside it but the stage kind;
`fylgja schema check` says whether their DCIM is the one the reader reads; and every
command they used in 0.2, stages and rehearsals included, works over that model. The
brief's [Decided](brief.md#decided) list is settled and restated here only where a
requirement needs the sentence; its [mapping](brief.md#the-mapping) is the reader's rule
and is restated in the requirements below. The decision entry superseding D-002, D-003
and D-004, and the constitution's rewrite of Principle III, are the plan's to write.

Four actors appear below. **The operator** runs the lab host and Fylgja, models the
network in Infrahub, tags the devices a twin is of, and marks stages. **A DCIM user** is
an operator whose Infrahub already holds the schema library's DCIM, who loads nothing of
Fylgja's but the stage kind. **Infrahub** holds the model, renders each device's
configuration through the shipped template, and runs the checks. **Fylgja** reads the
branch by the mapping, compiles, and boots the twin, and writes nothing to the operator's
model (Constitution III). Snapshots, probes and the NetBox reader are the release's later
specs and are out of this one.

## Clarifications

### Session 2026-10-25

- Q: When a tagged device has no platform, or one no package matches, is it refused at the read or at compile? → A: At the read, as a completeness finding naming the device and what it carries, every such device in one pass, and no CTM produced. The CTM never carries a device without a package.
- Q: Does the CTM's version move to `2`, refusing the old shape, or stay `1`, accepting it? → A: `2`. A CTM of version `1` is refused, naming the version expected; nothing converts or maps an old platform to a package. Tests of the old format read a frozen copy.
- Q: How do the reader's approximations and omissions reach the manifest? → A: A fidelity list in the CTM's envelope, one entry per approximated or omitted field or object with its reason, written by the reader and copied into the manifest unchanged by the compiler, which holds no table of any source's approximations.
- Q: Does the server carry a default scope, or must every request name one? → A: A server setting, an environment name beside its others (the plan names it). A request without `--scope` reads under it; with it unset, such a request is refused before any read, naming the setting. No built-in fallback. The development host sets it to `tag:fylgja`.
- Q: Does a package's match compare manufacturer and platform names exactly, or ignore case and spacing? → A: Exactly, on both names. A miss refuses the read, naming the device's manufacturer and platform beside every package's declared matches.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A twin of a branch modelled in the library's DCIM (Priority: P1)

The operator's branch holds devices as the library models them: a `DcimDevice` with a
platform and its manufacturer, physical interfaces, and cables between them. They tag the
devices the twin should be of and run `fylgja twin create --branch <b> --scope tag:<name>`,
or leave the scope off and get the server's default. Fylgja reads every tagged device,
its physical ports with their management role and admin status, the cables between them,
and each device's rendered configuration; picks each device's support package by its
manufacturer and platform; compiles; and boots the twin. Nothing else on the branch is
read: a virtual interface, an address, a VLAN, a role, a location, an untagged device.
The twin pushes the configuration Infrahub rendered, as it always has. `twin show` says
which scope the twin is of.

**Why this priority**: this is the feature. Everything else here is how it is reported,
checked, kept working over stages, and installed.

**Independent Test**: on the re-seeded fixture branch, three devices tagged `fylgja` in
the library's kinds, `intent read --branch fylgja-fixture` produces the CTM
`testdata/ctm/three-node.json` holds, in everything but the envelope, and `twin create`
boots the three-node twin, pushes each device's rendered configuration, and `twin show`
names scope `tag:fylgja`.

**Acceptance Scenarios**:

1. **Given** a branch whose three `DcimDevice`s are tagged `fylgja`, each with a platform
   a package matches, physical interfaces and cables between them, and a `Ready`
   artifact, **When** the operator runs `twin create --branch <b> --scope tag:fylgja`,
   **Then** the twin boots with three nodes, one link per cable between two of their
   physical ports, each node's port admin state as its interface's status says, and each
   node's rendered configuration pushed.
2. **Given** the same branch, **When** the operator runs `twin create --branch <b>` with
   no scope, **Then** the read uses the server's default scope, and the twin record,
   `twin show` and the manifest's provenance name the scope that was read.
3. **Given** a branch that also holds an untagged console server and a tagged device's
   `InterfaceVirtual`s with addresses, **When** the operator creates the twin, **Then**
   neither the console server nor any virtual interface nor any address is read, and the
   read's counts name only the tagged devices and their physical ports.
4. **Given** a tagged device with one interface whose role is `management`, **When** the
   twin is created, **Then** that port is the device's management port and is not cabled
   in the twin.
5. **Given** a tagged device with an interface whose status is `disabled`, **When** the
   twin is created, **Then** that port is administratively down on the node; an interface
   with any other status is up.
6. **Given** two devices whose packages are `nokia_srlinux` and `arista_eos`, found by
   their platforms' manufacturer and name, **When** the operator creates the twin,
   **Then** a mixed twin boots exactly as 0.2's mixed fixture did.
7. **Given** `twin step --stage <s>` or the following twin's next read, **When** it reads
   the branch again, **Then** it reads under the scope the twin records, never the
   server's default.

---

### User Story 2 - The read says what it approximated and what it left out (Priority: P1)

The library's meanings are close to Fylgja's and not identical: a port's management role
is not a management-only flag, and a status of `disabled` is not exactly an admin state.
A real branch also holds cables Fylgja cannot place: one to a device outside the scope,
one with three ends, one on a console port. The operator wants a twin of what can be
twinned, and an honest account of the rest. Each approximation and each omission is a row
in the bundle's fidelity manifest, and each omitted cable is also a finding beside the
read, naming the cable and why. A cable never refuses the read. Inside the scope, though,
the read is strict: a tagged device with no platform, one no package matches, or one with
no ready artifact refuses the read, naming the device, and no CTM is produced, so a typo
in a platform name refuses the twin rather than silently thinning it.

**Why this priority**: Constitution X. A twin that silently differs from its source is
worse than no twin, and this reader is the first that maps rather than reads its own
kinds.

**Independent Test**: on a throwaway branch seeded from the fixture, add a cable with a
third end and a cable from a tagged device to an untagged one; the read succeeds, both
cables are absent from the CTM, each is a finding naming the cable and its reason and a
manifest row, and the untagged device is not read. Then change one tagged device's
platform to one no package matches; the read is refused naming the device and the
platform, and no CTM is filed.

**Acceptance Scenarios**:

1. **Given** any twin read by this reader, **When** its bundle is compiled, **Then** the
   manifest carries a row for the management flag read from the port's role and one for
   the admin state read from its status, each marked approximated, and one recording that
   the platform's version is absent from this source.
2. **Given** a cable with one end on a tagged device's physical port and the other on an
   untagged device, **When** the branch is read, **Then** the cable is omitted, a finding
   names it with the reason "an end outside the scope", the manifest has a row for it, the
   untagged device is not read, and the read succeeds.
3. **Given** a cable with other than two ends, or with an end on anything but a physical
   port, **When** the branch is read, **Then** it is omitted and recorded with its own
   reason, and the read succeeds.
4. **Given** a cable between two tagged devices with one end on a management port,
   **When** the branch is read, **Then** the cable reaches the CTM, and the compiler omits
   and records it as it does today.
5. **Given** a tagged device with no platform, or whose platform's manufacturer and name
   no package matches, **When** the branch is read, **Then** the read is refused with a
   finding naming the device and what it carries, every such device is reported in one
   pass, and no CTM is produced.
6. **Given** a scope whose tag is on no device of the branch, or is absent from it,
   **When** the branch is read, **Then** the read is refused with one stable finding
   saying the scope selects nothing, naming the scope.
7. **Given** a tagged device outside the group the artifact definition targets, **When**
   the branch is read, **Then** it is refused for want of an artifact, as today.

---

### User Story 3 - "Is my DCIM the one Fylgja reads?" (Priority: P2)

A DCIM user already runs the schema library, perhaps a later commit of it, perhaps with
their own changes. Before tagging anything they run `fylgja schema check --branch <b>`.
It reports, kind by kind and field by field, whether the branch's schema holds what the
mapping reads, as the pinned library commit has it, and names that commit, so they know
whether they are conformant, and if not, exactly what differs. A diverged schema is not
patched by Fylgja; the schema README says what it costs (a reader of their own) and what
the shipped template is (a reference transform that renders ports, to be replaced by
their own transform rendering their layer 2 and 3).

**Why this priority**: the reader's promise to a DCIM user is "nothing to load but the
stage kind", and this is how they find out whether it holds for them. It needs the reader
of Story 1 to mean anything.

**Independent Test**: `fylgja schema check` passes on the re-seeded fixture branch and on
the mixed fixture, naming the library commit; on a branch without the library's kinds it
fails, naming each missing kind and field in one report.

**Acceptance Scenarios**:

1. **Given** a branch whose schema holds the library's kinds at the pinned commit,
   **When** the operator runs `fylgja schema check`, **Then** it passes and names the
   library commit the reader was written against.
2. **Given** a branch missing a kind the mapping reads, or missing a field of one, or
   with a field of a different kind or cardinality, **When** the operator runs `schema
   check`, **Then** it fails with one finding per kind or field, every one in one pass,
   each naming the kind, the field and the library commit.
3. **Given** a branch with kinds and fields beyond those the mapping reads, **When** the
   operator runs `schema check`, **Then** the extra kinds and fields are not reported and
   do not fail it.
4. **Given** a non-conformant branch, **When** the operator runs any command that reads
   intent from it, **Then** the read is refused with the same conformance findings and no
   CTM is produced.

---

### User Story 4 - A support package says which platforms it is (Priority: P2)

The package author, adding or maintaining a platform as data (Constitution II), writes in
the package the manufacturer and platform names it matches, so `nokia_srlinux` names
`Nokia` and `SR Linux`. No field is added to the library or to anyone's model to key a
package, and the NetBox reader will match on NetBox's manufacturer and platform the same
way. The conformance suite refuses a package that names no match, or two packages that
share one.

**Why this priority**: the reader cannot pick a package without it, but it is a small,
self-contained change to the package format.

**Independent Test**: both shipped packages declare their matches and pass the suite's
pure half; a copy of one with its matches removed, or a third package sharing a match
with another, fails the suite naming the package and the match.

**Acceptance Scenarios**:

1. **Given** the shipped packages, **When** the conformance suite's pure half runs,
   **Then** each names at least one manufacturer and platform pair, no pair is named
   twice, and both pass.
2. **Given** a package with no match, or two packages naming the same pair, **When** the
   suite runs, **Then** it fails naming the package and the pair.
3. **Given** a package of the previous format, **When** the server loads it, **Then** it
   is refused naming the format it expected.

---

### User Story 5 - Stages and rehearsals work as they did, over the new model (Priority: P2)

The operator's 0.2 flow is unchanged: they open a proposed change, mark stages, run `stage
plan`, `twin create --stage`, `twin step` and `twin rehearse`, and Infrahub's checks
rehearse a ready proposed change. What moves is what counts as a change to a device: a
stage is stale when its device, any of its interfaces (virtual ones included, since a
transform may render them), its platform, its manufacturer, or any cable one of its ports
ends on was written after the stage's artifacts were. That is broader than 0.2's fixed
list, on purpose: over-reporting staleness costs a regenerate, and under-reporting costs a
wrong rehearsal. The checks pass no scope, so they rehearse under the server's default.
A branch point on a `main` that holds no network still falls through to the first stage,
as 015 settled.

**Why this priority**: 0.2's release story must survive the reader's rewrite, but it is
not new behaviour.

**Independent Test**: tier 2's stage and check packages pass unchanged in what they
assert but the branch point's identifier; on a throwaway branch, editing only a tagged
device's virtual interface after a mark makes that mark stale, and so does editing its
platform's manufacturer.

**Acceptance Scenarios**:

1. **Given** a mark made after the artifacts were regenerated, **When** a tagged device's
   virtual interface, platform, manufacturer, or a cable on one of its ports is then
   written, **Then** the mark reads stale for that device, naming it.
2. **Given** a write to an untagged device or to a cable between two untagged devices,
   **When** stages are resolved, **Then** no tagged device's mark is made stale by it,
   **except** an untagged device created on, moved onto or off, or deleted from, a
   platform the tagged devices share, or a platform or a device type created under, or
   moved onto or off, their manufacturer: that write moves the shared node's stamp or
   names it in an event, and the tagged devices' marks read stale, an over-report this
   story accepts.
3. **Given** `main` holds the library's kinds and no tagged device, **When** `stage plan`
   or a rehearsal resolves the branch point, **Then** it is refused with the
   scope-selects-nothing finding, and the rehearsal and `fylgja-step` treat it as they
   treated 0.2's "no network on `main`": the baseline falls to the first stage that
   resolves, and neither check fails for it.
4. **Given** `fylgja-twin` rehearses a ready proposed change, **When** it asks Fylgja,
   **Then** it names no scope, the rehearsal reads under the server's default, and the
   report names the scope read.
5. **Given** `stage plan`, `intent read`, `twin create` or `twin rehearse` with `--scope`,
   **When** it runs, **Then** every stage it resolves is read under that scope.

---

### User Story 6 - The install migrated, the fixtures re-seeded, the records true (Priority: P3)

The development host and CI move from the generics to the library. `main` loses the four
generics and the contract kind and gains the vendored library beside the stage kind, by
`fylgja-fixture -prepare-main`, which loads the library only on a `main` holding none of
its kinds and refuses one holding any, naming why, so it never migrates a user's later
library. The fixture branch and the mixed fixture are re-seeded in the library's kinds: a
site, a manufacturer per vendor, a platform per package, the same devices tagged
`fylgja`, their ports and cables, artifacts generated. The artifact query and template
read the library's kinds and lose their loopback branch, so every artifact moves. The
operator is told what they must do, in order, since a session never pushes: push the
template change to `origin`'s `main` and import it before the fixture is re-seeded and
tier 2 runs. The records say what is true afterwards.

**Why this priority**: the work cannot close without it, but it delivers nothing to an
operator beyond Stories 1 to 5.

**Independent Test**: after the migration, `main` lists the library's kinds and the stage
kind and none of the generics; `-prepare-main` run again refuses, naming the library's
kinds it found; the fixture reads to its CTM; the nine tier-3 cases pass with the marker
in `description`.

**Acceptance Scenarios**:

1. **Given** a `main` holding the generics and the stage kind, **When** the migration
   runs in its documented order, **Then** `main` holds the vendored library and the stage
   kind, the generics and the contract kind are gone, and the stage kind and every stage
   on it are untouched.
2. **Given** a `main` already holding any of the library's kinds, **When**
   `-prepare-main` runs, **Then** it loads nothing and refuses, naming the kinds it found
   and that it is the development host's tool, not an install path.
3. **Given** the vendored files under `schema/dcim/`, **When** they are compared with the
   library at the pinned commit, **Then** each is byte-identical, beside the library's
   licence and a note naming the commit.
4. **Given** the re-seeded fixture, **When** `-set-description` changes a device's
   description, **Then** the device's artifact changes and its CTM changes in the
   artifact alone: the artifact-only change, and the home of tier 3's marker.
5. **Given** the template change is on the tree but not yet imported by Infrahub,
   **When** a session reaches the tiers that need rendered artifacts, **Then** it follows
   the plan's documented route for that window and says what the operator must push and
   import, and never pushes itself.

---

### Edge Cases

- **A device with two management ports**: the first is the management port and the
  second is omitted, recorded as today.
- **A tagged device with no physical interface**: read as a device with no ports; the
  twin boots it uncabled.
- **A tagged device whose `status` is `deprecated`, `maintenance` or any other value**:
  read; `status` does not filter. A tagged device is the operator's intent.
- **A cable whose two ends are both on the same device**: carried if both are physical
  ports of a device in the scope, as a link today would be; the compiler's rules apply.
- **A cable with exactly one end**: omitted and recorded ("other than two ends").
- **A physical port with no cable**: an uncabled port, as today.
- **An interface that is `InterfaceVirtual` and carries a cable**: not read; a cable
  ending on it is omitted and recorded ("an end not on a physical port").
- **A platform with no manufacturer**: nothing to match on; the device is refused as
  incomplete, the finding naming what it carries (FR-014), not as unmatched.
- **Two packages could match one platform**: impossible, since the conformance suite
  refuses two packages sharing a pair.
- **A manufacturer or platform name matching a package in different letter case or
  spacing** (`nokia` / `SR-Linux` against `Nokia` / `SR Linux`): no match; the read is
  refused naming the device's names beside every package's matches (FR-009). The package
  README and the schema README say a match is exact.
- **The scope's syntax is wrong** (`--scope fylgja`, `--scope group:x`): refused before
  any read, naming the accepted form `tag:<name>`.
- **The server has no default scope configured and a request names none**: refused
  before any read, naming the setting (FR-018); a check run against such a server
  concludes failure with that finding.
- **A pinned `at` before the library was loaded on the branch**: the branch's schema at
  that time lacks the kinds. Conformance reads the branch's schema as it is now, since
  Infrahub's schema endpoint has no time axis, so a branch that conforms now passes it.
  The pinned read selects no device, and the read is refused with the
  scope-selects-nothing finding, naming the scope, the branch and the `at` (research
  §5.16).
- **The fixture branch made before the migration**: it carries the old schema and is
  never rebased; the migration deletes and re-seeds it.
- **A CTM file of the previous shape given to `twin compile`**: refused, naming CTM
  version `2` as the one expected (FR-028).
- **A twin record of the previous format on the host when the new server starts**:
  handled as every earlier `twin.json` move was; the plan says how.
- **A write to a cable that used to end on a tagged port and no longer does**: its event
  still makes the device's mark stale, since the event names a peer that was the
  device's.

## Requirements *(mandatory)*

### Functional Requirements

#### The reader and its mapping

- **FR-001**: The Infrahub reader MUST read the schema library's kinds as they are at the
  pinned commit `26336e9`, and its queries MUST name no kind of the operator's model other
  than `DcimDevice`, `DcimPlatform`, `InterfacePhysical` and `DcimCable`; the platform's
  manufacturer is read through the platform, and the scope's tag is Infrahub's own
  `BuiltinTag`, named in the read-only test as an Infrahub-owned read. The read-only test
  MUST hold that list.
- **FR-002**: A device MUST be every `DcimDevice` on the branch carrying the scope's tag,
  whatever its `status`; its name MUST be the node's `name`. Every other device MUST be
  outside the scope and not read.
- **FR-003**: A device's ports MUST be its interfaces that are `InterfacePhysical`, each
  by its `name`. An `InterfaceVirtual` MUST never be read.
- **FR-004**: A port MUST be the management port when its `role` is `management`; a
  second such port on one device MUST be omitted and recorded as today. This MUST be
  recorded in the manifest as approximated.
- **FR-005**: A port MUST be enabled unless its `status` is `disabled`. This MUST be
  recorded in the manifest as approximated.
- **FR-006**: A link MUST be a `DcimCable` with exactly two ends, each a physical port of
  a device in the scope. Any other cable or connector reached from a port in the scope MUST
  be omitted, never refusing the read, and MUST be recorded as a finding beside the read and
  a manifest row, each naming the cable and one of these reasons: an end outside the scope,
  other than two ends, an end not on a physical port, a connector that is not a `DcimCable`.
- **FR-007**: A cable on a management port between two devices in the scope MUST reach
  the CTM; the compiler MUST omit and record it as it does today.
- **FR-008**: A device's artifact MUST be read as today: the one its package names,
  `Ready`, its bytes verified against Infrahub's checksum.
- **FR-009**: A device's support package MUST be the one whose declared matches name its
  platform's manufacturer name and the platform's `name`, each compared exactly, letter
  case and spacing included; a device no package matches is refused as FR-014 says, the
  finding naming its manufacturer and platform beside every package's declared matches.
  The platform's version MUST be
  absent from this reader's CTM, and its absence MUST be a manifest row.
- **FR-010**: The reader MUST NOT read a device's `description`, `role`, `location`,
  addresses or any field the mapping does not name.

#### Strictness and findings

- **FR-011**: Conformance and completeness MUST be validated separately, every finding
  MUST be reported in one pass, and no CTM MUST be produced when either fails.
- **FR-012**: Conformance MUST check that the branch's schema holds each kind the mapping
  reads with each field it reads, with the kind of field and cardinality the pinned
  commit gives it, reported per kind and per field, each finding naming the library
  commit the reader was written against. Kinds and fields beyond those MUST NOT be
  reported.
- **FR-013**: `fylgja schema check` MUST run the conformance half alone and report it as
  FR-012 says.
- **FR-014**: A device in the scope with no platform, or with a platform that has no
  manufacturer, or whose platform no package matches, MUST be refused at the read as a
  completeness finding naming the device and what it carries, the first two as incomplete
  and the third as unmatched; no CTM MUST be produced, so a CTM never carries a device
  without a package.
- **FR-015**: A scope that selects no device, because its tag is absent from the branch or
  on no `DcimDevice`, MUST be refused with one stable finding naming the scope; the
  rehearsal and `fylgja-step` MUST treat that finding where they treated 0.2's refusal of
  a `main` holding no network.
- **FR-016**: `FylgjaContract`, its version compare, and every finding that existed only
  for the generics MUST be removed. Every finding the reader adds MUST have a stable
  identifier.

#### The scope

- **FR-017**: `twin create`, `twin rehearse`, `intent read`, `stage plan` and `stage list`
  MUST accept `--scope tag:<name>`, and the API's corresponding operations MUST carry it;
  `stage list` needs it because the head's point in time is read from the scope's devices.
  Any other form MUST be refused before any read, naming the accepted form.
- **FR-018**: The server MUST take a default scope from a setting in its environment,
  beside its other settings, documented in `.env.example`; a request that names no scope
  MUST be read under it. With the setting unset, such a request MUST be refused before any
  read, naming the setting; there MUST be no built-in fallback. The development host's
  environment MUST set it to `tag:fylgja`, and the server's start-up report MUST name it.
- **FR-019**: The scope read MUST be recorded in the twin record, in the manifest's
  provenance, and in the CTM's envelope, and `twin show` MUST print it.
- **FR-020**: `twin step` and the following twin's reads MUST read under the scope the
  twin records.
- **FR-021**: The checks MUST pass no scope.

#### Stages

- **FR-022**: The stage reader's Infrahub-owned reads (proposed changes, branches,
  artifact validators, the event log) MUST be unchanged, but for one that D-059 and D-060
  add: the template query's internal `CoreGraphQLQueryGroup`s, read for the account that
  created them, Infrahub's own.
- **FR-023**: A device's intent stamp MUST be the latest write on the device, on any of
  its interfaces (virtual ones included), on its platform, on its platform's
  manufacturer, and on any cable one of its ports is an end of, a write by Infrahub's own
  account (the one that created the template query's groups) counting as the node's
  creation instead (D-058, D-060). An event MUST count for a
  device when its node is one of those or a peer of one.
- **FR-024**: Every 0.2 stage and rehearsal behaviour not named here MUST hold unchanged
  over the library's kinds.

#### The packages

- **FR-025**: Each support package MUST declare a list of matches, each a manufacturer
  name and a platform name; the package format MUST move to `0.7`, and a package of
  another format MUST be refused.
- **FR-026**: The conformance suite's pure half MUST refuse a package with no match and
  two packages sharing a match, naming each.
- **FR-027**: `nokia_srlinux` MUST match `Nokia` / `SR Linux`; `arista_eos` MUST match
  `Arista` / `EOS`, the mixed fixture's manufacturer and platform.

#### The CTM and the compiler

- **FR-028**: The CTM MUST drop the device's `role` and `site` and the interface's
  `iftype`, `parent` and `addresses`; a device's platform MUST become its package and an
  optional version. The CTM's version MUST move to `2`, and a CTM of version `1` MUST be
  refused wherever one is read, `twin compile` included, naming the version expected;
  nothing MUST convert one or map its platform to a package.
- **FR-029**: The CTM's envelope MUST carry a fidelity list, one entry per approximated or
  omitted field or object with its reason, written by the reader; the compiler MUST copy
  it into the manifest unchanged and MUST hold no table of any source's approximations, so
  it never needs to know which source produced the CTM.
- **FR-030**: The compiler MUST treat every interface as a port, cabled unless it is the
  management port; the loopback case MUST be removed. The breakout rule, which derives
  parentage from port names, MUST be unchanged.
- **FR-031**: The manifest MUST lose `iftype` and gain the reader's approximation and
  omission rows.
- **FR-032**: The compiler MUST stay pure; the three goldens MUST move, re-baselined on a
  commit of their own.

#### Rendering

- **FR-033**: The artifact query and the template MUST read `DcimDevice` with its
  platform's manufacturer and name, its physical interfaces with their role, status and
  cable, and its `description`; they MUST lose the loopback branch and write the
  manufacturer, the platform and the description into the configuration's header comment.
  One template MUST still render both platforms.
- **FR-034**: The artifact definition MUST still target the group `fylgja-devices`, and
  the schema README MUST say that a tagged device outside it has no artifact and is
  refused.

#### The schema directory, `main` and the fixtures

- **FR-035**: `schema/` MUST lose the generics and the reference schema and gain
  `schema/dcim/`: the library's `base/dcim.yml`, `base/ipam.yml`, `base/location.yml`,
  `base/organization.yml`, `extensions/cable/cable.yml` and
  `extensions/location_minimal/location_minimal.yml`, byte-identical to the pinned
  commit, with the library's licence and a note naming the commit. The stage kind MUST
  stay.
- **FR-036**: `fylgja-fixture -prepare-main` MUST load `schema/dcim/` on `main` beside the
  stage kind only when `main` holds none of the library's kinds, and MUST refuse, loading
  nothing, when it holds any, naming the kinds found.
- **FR-037**: The fixture branch and the mixed fixture MUST be seeded in the library's
  kinds: a site, a manufacturer per vendor, a platform per package, the same devices
  tagged `fylgja`, their physical ports and cables, and generated artifacts. The fixture
  loses its loopbacks. Every fixture-tool action that writes the model (`-add-link`,
  `-add-fourth-node`, `-add-mixed-link`, `-disable-port`, `-add-interface`, `-seed-main`)
  MUST write the library's kinds.
- **FR-038**: `-set-role` and `-set-site` MUST be replaced by `-set-description`, the
  artifact-only change, and tier 3's marker MUST move to the device's `description`.
- **FR-039**: There MUST be one fixture branch; no second branch keeps the old model.

#### Records and migration

- **FR-040**: The install's migration MUST be documented in order: remove `main`'s
  generics and contract kind by two removal documents, the reference kinds first, since
  Infrahub refuses one document naming both; load the library on `main`; import the
  template from `origin`'s `main`, since no artifact renders until it is imported; then
  delete and re-seed the fixture branch. The operator MUST be told, before the work starts,
  that the template change needs their push and import before the fixture is re-seeded and
  before tier 2, that `main`'s schema is migrated, and that both fixtures are re-seeded.
  Tier 1 and the reader's code do not wait for the import.
- **FR-041**: The contract records MUST move with the change: the CTM's, the manifest's,
  the twin record's and the package's schemas, the API and CLI contracts, the decision
  entry superseding D-002, D-003 and D-004, Constitution III's rewrite with a major
  version bump, the architecture's reader, CTM, compiler and package sections, the C4
  model, the schema and package READMEs, the development guide, the verified facts, the
  glossary, the README's walk-through, and `CLAUDE.md`'s Environment, Formats and State.
- **FR-042**: Every fact the reader relies on about how Infrahub answers for the
  library's kinds MUST be verified live before it is relied on, and recorded in
  `research.md` and then in `docs/verified-facts.md`.

### Key Entities

- **The mapping**: the one documented rule by which a reader turns one source's model into
  the CTM: which kinds and fields it reads, what each becomes, and with what fidelity.
  This reader's is the brief's table.
- **The schema library**: OpsMill's published Infrahub schemas, Apache 2.0; its DCIM base
  and the cable and minimal-location extensions, vendored at commit `26336e9`, are the
  model this reader reads.
- **The scope**: a tag, named by the request or the server's default, that says which
  devices a twin is of. Ports and cables follow their devices. Recorded with every read.
- **An approximation**: a CTM field read from a source field whose meaning is near and not
  identical (the management flag from a role, the admin state from a status), recorded in
  the manifest.
- **An omission**: something on the branch inside or touching the scope that the read
  leaves out (a cable it cannot place, a platform version the source does not carry),
  recorded as a finding where it concerns the read and as a manifest row.
- **A package's matches**: the manufacturer and platform name pairs a support package
  declares it is; how a reader picks a device's package.
- **The CTM**: the contract, now; thinner (no role, site, interface type, parent or
  addresses), with the platform as a package and an optional version, and an envelope that
  carries the scope and the reader's fidelity list.
- **A device's intent stamp**: the latest write on a device and everything it owns or
  reaches by a cable, but Infrahub's own (D-058), against which a stage's artifacts are judged fresh or stale.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A branch modelled in the library's kinds becomes a running twin with nothing
  of Fylgja's loaded on it but the stage kind: the re-seeded fixture reads to the CTM
  `testdata/ctm/three-node.json` holds, in everything but the envelope, and the mixed
  fixture to its own.
- **SC-002**: The reader's queries name exactly the four kinds of the operator's model
  FR-001 lists, and the read-only test fails if a fifth is added.
- **SC-003**: 100% of approximations and omissions appear in the manifest: every bundle
  this reader produces carries the two approximation rows and the version row, and every
  omitted cable in the tier-2 cases (a third end, an end on an untagged device) appears as
  both a finding and a row.
- **SC-004**: A schema check on a branch without the library reports every missing kind
  and field in one run; the operator needs no second run to see the next problem.
- **SC-005**: A tagged device whose platform no package matches refuses the read in 100%
  of cases; no twin is ever booted with that device left out.
- **SC-006**: The nine tier-3 cases pass over the re-seeded fixtures with the marker in
  `description`, and tier 2's stage and check packages pass with no change to what they
  assert but the branch point's identifier (FR-015).
- **SC-007**: The vendored library files are byte-identical to the library at the pinned
  commit, and nothing is added to the library or to the operator's model to key a package
  or a scope.
- **SC-008**: Tier 1 stays under its 45 s budget, uncached.
- **SC-009**: Editing any one of a tagged device's interfaces (virtual included), its
  platform, its manufacturer, or a cable on one of its ports after a mark makes that mark
  stale in every case tested.

## Assumptions

- **The brief's four open questions** ([Open](brief.md#open)) were settled in clarify on
  2026-10-25 ([Clarifications](#clarifications)), each as the requirement it names:
  1. *(Settled in clarify, 2026-10-25: at the read; FR-014.)*
  2. *(Settled in clarify, 2026-10-25: version `2`, refusing `1`; FR-028.)*
  3. *(Settled in clarify, 2026-10-25: a fidelity list in the CTM's envelope; FR-029.)*
  4. *(Settled in clarify, 2026-10-25: a server setting, refusing an unscoped request when
     unset; FR-018.)*
- **The API's version stays `1`**: the scope is a member the operations gain, as 015's
  members were. The plan moves it only if it finds a change no `1` client survives.
- **Which other formats move is the plan's**: the brief names the CTM, the manifest,
  `twin.json` (for the scope), the package format (`0.7`), and the mapping profile's
  schema if it names `iftype`; the bundle's format moves if the manifest's change
  requires it. The contract version `0.2` retires with the generics.
- **The library's kinds are verified live** on a throwaway branch before the reader relies
  on them (FR-042); the brief's [As read](brief.md#as-read) section was read from files and
  one validation-only schema check, nothing more.
- **The mixed fixture's second manufacturer and platform names, and the marker's exact
  form in `description`**, were the plan's: `Arista` / `EOS`, and `FYLGJA-MARKER-<suffix>`
  by the fixture's suffix rule (research R-08, R-15).
- **The tag lives on the branch**, since tags are branch-aware; `main` holding no tagged
  device is the development host's normal state outside D-054's demo window, and reads as
  a scope that selects nothing (FR-015).
- **A session never pushes**: the template's import needs the operator's push of
  `origin`'s `main`, so tier 2 on this host either runs against a throwaway registration
  from the tree or waits for the operator's push and import, as the plan decides.
- **Out of scope**: snapshots (F-024), probes (F-014), the NetBox reader (F-025), any
  reading above layer 1, a reader for a diverged DCIM, the agent skill, and the production
  refactor itself.
