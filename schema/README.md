# Schema

What the Infrahub reader reads, and Fylgja's two kinds of its own. The reader reads OpsMill's
[schema library](https://github.com/opsmill/schema-library)'s DCIM at commit `26336e9`,
vendored under `dcim/`, by one documented mapping onto the CTM, below; the stage kind and
the probe kind are the only schema Fylgja adds to anyone's Infrahub, and neither is intent.
See architecture [§4.1](../docs/architecture.md#41-intent-reader),
[D-057](../docs/decisions.md#d-057) and [D-064](../docs/decisions.md#d-064).

| File | Purpose |
|---|---|
| `dcim/dcim.yml` | The library's `base/dcim.yml` (`81df2eb8…`). |
| `dcim/ipam.yml` | The library's `base/ipam.yml` (`6d31dc03…`). |
| `dcim/location.yml` | The library's `base/location.yml` (`afef7a77…`). |
| `dcim/organization.yml` | The library's `base/organization.yml` (`082e8536…`). |
| `dcim/cable.yml` | The library's `extensions/cable/cable.yml` (`3196073c…`). |
| `dcim/location_minimal.yml` | The library's `extensions/location_minimal/location_minimal.yml` (`cf148227…`). |
| `dcim/LICENSE.txt` | The library's licence, Apache 2.0 (`71d4aed1…`). |
| `dcim/README.md` | [The note](dcim/README.md): the commit, each file's full SHA-256, the licence, and how the files are loaded. |
| `fylgja-stage.yaml` | The stage kind: a marked moment of a proposed change, which the operator writes and Fylgja only reads, and its extension of Infrahub's `CoreProposedChange` (`fylgja_stages`). Loaded on the default branch ([D-028](../docs/decisions.md#d-028)); needed only by `--stage`, `stage list` and `stage plan` ([D-045](../docs/decisions.md#d-045)). |
| `fylgja-probe.yaml` | The probe kind `FylgjaProbe`: a probe's declaration, two synthesized hosts on two uncabled ports, which the operator writes and Fylgja only reads ([below](#probes-declaring-one)). Branch-agnostic, loaded on the default branch beside the stage kind; read by every request that takes probes and sends no `--probes` file, so a request that reads intent is refused without it unless it sends one ([D-064](../docs/decisions.md#d-064)). |
| `infrahub.graphql` | The default branch's SDL, fetched from a running Infrahub by `make sdl` and committed, the typed client's input (`make generate`). Never edited by hand. |

The six files keep the library's names and bytes: nothing edits or formats them, not even
`infrahubctl schema format`, and a tier-1 test holds each embedded file's SHA-256 to the
note's table. Moving to another commit is a decision of its own, which moves the commit,
the note, the mapping's table and the CTM's `envelope.mapping.version` together; the library
calls itself experimental, so the commit is pinned.

**Loading them.** On the development host and CI's runner, `go run -tags fixture
./cmd/fylgja-fixture -prepare-main` (the bring-up script's `infrahub` part) loads the stage
and probe kinds in one request on `main`, wherever either is absent, then the six files in
one more, and only onto a `main` holding none of the library's kinds. A `main` holding any
is refused, with nothing of the library loaded: `main holds <n>
of the schema library's kinds (…): -prepare-main is the development host's and CI's tool,
which loads the library on an empty main alone; it is not an install path: a main that
already holds the library is yours, and fylgja schema check says whether it is the one the
reader reads`. A DCIM user who already runs the library loads nothing of Fylgja's but
`fylgja-stage.yaml` ([below](#the-kind-on-the-default-branch)), for the stage surface, and
`fylgja-probe.yaml` ([below](#the-probe-kind-on-the-default-branch)), which every read of
intent that sends no probe file asks for; `fylgja schema check` says whether their DCIM is
the one the reader reads.

## The mapping

The one rule by which the Infrahub reader, `infrahub-dcim`, turns the library's model into
the CTM: which kinds and fields it reads, what each becomes, with what fidelity, what it
refuses and what it omits. Every CTM it writes names it in its envelope (`mapping:
{reader: infrahub-dcim, model: opsmill/schema-library, version: 26336e9}`), and the
manifest's and the twin record's provenance carry the same block. It was drafted as
[017's mapping contract](../specs/017-dcim-reader/contracts/mapping.md).

| CTM | Read from | Rule | Fidelity |
|---|---|---|---|
| the scope | the request's `--scope tag:<name>`, or the server's `FYLGJA_DEFAULT_SCOPE` | every `DcimDevice` on the branch carrying the `BuiltinTag` of that name, whatever its `status`; everything else on the branch is outside the scope and not read | — |
| `devices[].name` | `DcimDevice.name` | the node's name | exact |
| `devices[].platform.package` | `DcimDevice.platform` → `DcimPlatform.name`, and its `manufacturer` → `OrganizationManufacturer.name` | the package whose `platform.matches` names the pair, both names exactly ([below](#a-match-is-exact)) | exact |
| `devices[].platform.version` | nothing | absent: the library's platform carries no version | **omitted**, one row per read |
| `devices[].artifact` | the device's `artifacts`, through `CoreArtifactTarget` | the one whose definition's `artifact_name` is the package's `config.artifact_name`, `Ready`, its bytes verified against Infrahub's checksum | exact |
| `devices[].interfaces[]` | `InterfacePhysical` whose `device` is among the devices read | one port per physical interface, by `name`; an `InterfaceVirtual` is never read | exact |
| `interfaces[].mgmt_only` | `InterfacePhysical.role` | `management` is the management port; a second such port on one device is omitted by the compiler (`omit.mgmt.extra`) | **approximated**, one row per read |
| `interfaces[].enabled` | `InterfacePhysical.status` | `disabled` is `false`; every other value, `null` included, is `true` | **approximated**, one row per read |
| `links[]` | the port's `connector`, a `DcimConnector` (the `DcimCable`), with its `connected_endpoints` | a link when the cable has exactly two ends and each is an `InterfacePhysical` of a device in the scope; its id is the two ends' `<device>:<port>` sorted and joined with `\|`, each port's `link` set to it | exact |
| nothing | any other cable, or connector that is not a `DcimCable`, reached from a port in the scope | omitted, never refusing the read, with one of four reasons (below) | **omitted**, one row per cable or connector |

**Not read**, since the mapping names everything read: the device's `description`,
`status`, `role`, `location`, `primary_address`, `serial_number` and `device_type`; the
port's `description`, `mtu`, `mac_address`, `l2_mode`, `ip_addresses` and
`sub_interfaces`; every `InterfaceVirtual`; every address, prefix, location, device type,
tag beyond the scope's and manufacturer beyond the platform's. The template reads the
device's `description` and each port's `ip_addresses` and renders them; the reader never
does, so an address moves a device's artifact and nothing else of the CTM. Every interface is a port:
there is no interface type to read, and wiring is derived by the compiler from
`mgmt_only` and the cables.

**The queries.** Two operations, paged by 100, every page at the read's `at` when one was
given: `Devices`, `DcimDevice(tags__name__value: $tag)` selecting the name, the platform's
name and its manufacturer's, and the artifacts; then `Ports`, `InterfacePhysical(device__ids:
$devices)` selecting each port's name, role, status, device and cable with the cable's label
and ends, once per page of devices. The read-only test holds every operation's roots to `DcimDevice`,
`InterfacePhysical`, Fylgja's `FylgjaStage` and `FylgjaProbe`, and Infrahub's own `CoreProposedChange`,
`CoreArtifactValidator`, `Branch`, `InfrahubEvent` and `CoreGraphQLQueryGroup`, and every
fragment target to `DcimDevice`, `DcimPlatform`, `InterfacePhysical`, `DcimCable`,
`CoreArtifactTarget` and `NodeMutatedEvent`. The scope's `BuiltinTag` is read by the filter
alone.

**Completeness, inside the scope.** After conformance and before any CTM, the read refuses
every device it cannot carry, all in one pass, with no CTM on any finding:

| Rule | Object | When |
|---|---|---|
| `scope.empty` | the scope | the device query answers 0: the tag absent from the branch, or on no `DcimDevice`; the message names the scope, the branch, and the `at` when the read is pinned ([research §5.16](../specs/017-dcim-reader/research.md#5-16)): `scope tag:fylgja selects no device on branch b`, `… on branch main at 2026-10-20T00:00:00Z` |
| `platform.missing` | the device | no `platform`, or a platform with no `manufacturer`; the message names what the device carries |
| `platform.unmatched` | the device | no package's `matches` names the manufacturer's and the platform's `name`, both exactly; the message names the device's pair beside every package's |
| `artifact.missing` and the other artifact rules | the device | no `Ready` artifact of the package's name, or one Fylgja cannot verify; a device refused for its platform is not also refused for its artifact |

**Omissions.** A cable never refuses the read, nor does a connector of the operator's own
kind inheriting `DcimConnector`, which is never a link. One reached from a port in the
scope that is not a link is omitted for the first reason that applies, judged once by its
id however many of its ends are in the scope; each omission is an `info` finding beside the read,
naming every end on a physical port as `<device>:<port>`, and a row of the CTM's fidelity
list. A device outside the scope is named by its id wherever an end names it: the read
never reads such a device, so it has only the id the port's `device` answers.

| Rule | Object | When | Reason |
|---|---|---|---|
| `omit.cable.kind` | the connector's id, since the read selects a `label` on a `DcimCable` alone | a connector whose kind is not `DcimCable` | `a connector that is not a DcimCable (<kind>)` |
| `omit.cable.ends` | the cable's `label`, or its id when it has none | `connected_endpoints` counts other than two, or counts two and lists fewer | `other than two ends (<n>)`, the count; `other than two ends (<listed> listed of <n>)` when Infrahub lists fewer ends than it counts |
| `omit.cable.endpoint` | the cable | an end whose kind is not `InterfacePhysical` | `an end not on a physical port (<kind>)` |
| `omit.cable.outside_scope` | the cable | an end whose device is not among the devices read | `an end outside the scope (<device id>:<port>)` |

A cable between two management-role ports, or with both ends on one device, is a link in
the CTM: the compiler omits the first (`omit.link.mgmt_only`) and validation refuses the
second (`link.endpoints.same_device`).

**The fidelity list.** Every CTM this reader writes carries three rows, `{approximated,
interface.mgmt_only, InterfacePhysical.role, "the management port is the port whose role is
management; the library has no management-only flag"}`, `{approximated,
interface.enabled, InterfacePhysical.status, "a port is enabled unless its status is
disabled; the library's status is not an admin state"}` and `{omitted, platform.version,
DcimPlatform, "the library's platform carries no version"}`, then one `{omitted, <cable>,
<kind>, <reason>}` per omitted cable, `<kind>` `DcimCable` or the omitted connector's own, sorted by the whole row: disposition, object,
source, then reason. The compiler
copies the list into the manifest's `fidelity.read` unchanged and holds no table of its own.

**Stamps, for stages.** A device's intent stamp is the latest node stamp among the device,
every one of its interfaces (virtual ones included), its platform, the platform's
manufacturer and every cable one of its physical ports is an end of. A node's stamp is its
`node_metadata.updated_at`, or its `created_at` when Infrahub's own account last wrote it,
as it does when a generation adds the node to its query's group
([D-058](../docs/decisions.md#d-058), [D-060](../docs/decisions.md#d-060)). An intent event
is a creation, a deletion or a change of any attribute or relationship but Infrahub's own
(`member_of_groups`, `subscriber_of_groups`, `artifacts`, `profiles`, `object_template`)
on an implementer of `DcimGenericDevice` (on the pinned library, `DcimDevice` alone), of
`DcimInterface` or of `DcimConnector`, a `DcimPlatform` or an `OrganizationManufacturer`; it counts for a device when its node or a peer is one of
those the device's stamp reads.

### A match is exact

A device's package is the one whose `platform.matches` names its manufacturer's `name` and
its platform's `name`, each compared exactly, letter case and spacing included. The shipped
packages match `Nokia` / `SR Linux` (`nokia_srlinux`) and `Arista` / `EOS` (`arista_eos`);
a device on `nokia` / `SR-Linux` matches neither and is refused `platform.unmatched`:
`device n1: manufacturer "nokia", platform "SR-Linux"; the packages match: arista_eos
[Arista / EOS], nokia_srlinux [Nokia / SR Linux]`. Nothing is added to the library's model
to key a package: rename the manufacturer or the platform, or give the package a pair of
that spelling ([psp/README.md](../psp/README.md#format-07)).

## What `schema check` reports

`fylgja schema check --branch <b>` runs the reader's conformance alone: it reads the
branch's schema (`GET /api/schema`) and compares it, kind by kind and field by field, with
what the pinned commit loads, issuing no object query and loading no package. Every read of
intent runs the same check first and is refused with the same findings, before any query.

| Kind | Attribute: kind, optional | Relationship: peer, kind, cardinality, optional |
|---|---|---|
| `DcimDevice` | `name`: Text, required | `tags`: `BuiltinTag`, Attribute, many, optional · `platform`: `DcimPlatform`, Attribute, one, optional · `interfaces`: `DcimInterface`, Component, many, optional · `artifacts`: `CoreArtifact`, Generic, many, optional (`CoreArtifactTarget`) |
| `DcimPlatform` | `name`: Text, required | `manufacturer`: `OrganizationManufacturer`, Attribute, one, optional |
| `OrganizationManufacturer` | `name`: Text, required | — |
| `InterfacePhysical` | `name`: Text, required · `role`: Dropdown, optional, choices including `management` · `status`: Dropdown, optional, choices including `disabled` | `device`: `DcimGenericDevice`, Parent, one, required · `connector`: `DcimConnector`, Attribute, one, optional |
| `DcimCable` | `label`: Text, optional | `connected_endpoints`: `DcimEndpoint`, Attribute, many, optional |
| `DcimConnector` (generic) | — | `connected_endpoints`: `DcimEndpoint`, Attribute, many, optional |

And `used_by`: `DcimGenericDevice` by `DcimDevice`, `DcimInterface` and `DcimEndpoint` by
`InterfacePhysical`, `DcimConnector` by `DcimCable`. `optional` is compared as Infrahub
reports it: a required attribute must read `optional: false`, and an optional one may read
either. The generic's row is there because `Ports` selects a port's cable's ends on the
connector outside the `DcimCable` fragment, so through `DcimConnector` itself: a branch
whose generic lacks them, `DcimCable` declaring them itself, is refused naming
`DcimConnector.connected_endpoints` rather than failing the query; the generic absent is
its one `schema.used_by.missing`.

| Rule | Object | When |
|---|---|---|
| `schema.kind.missing` | the kind | the branch's schema lacks a kind of the table |
| `schema.field.missing` | `<kind>.<field>` | the kind lacks a field of the table |
| `schema.field.mismatch` | `<kind>.<field>` | the field's kind, peer, cardinality or optionality is not the table's, naming each, expected first (`kind Text, found Number`) |
| `schema.choice.missing` | `<kind>.<field>` | the dropdown lacks `management` (`role`) or `disabled` (`status`) |
| `schema.used_by.missing` | the generic | the generic is not implemented by the kind the table expects |

Each is a rejection, exit 1, and names the commit (`the branch's schema has no kind
DcimCable; the mapping reads it as opsmill/schema-library@26336e9 has it`); every one is
reported in one pass, and nothing beyond the table is reported, so kinds, fields and
choices a branch adds fail nothing. On success it prints `conformant with
opsmill/schema-library@26336e9: DcimDevice, DcimPlatform, OrganizationManufacturer,
InterfacePhysical, DcimCable, DcimConnector`, the table's rows with the generic among them,
then the stages line, which reads the default branch
whatever branch was checked (`stages: FylgjaStage present on the default branch, with its
extension`); `--json`'s `verified` block is `{model, version, kinds: [{kind, fields}],
stages}`. It takes no `--at`: the schema endpoint answers for now.

## A diverged DCIM

A DCIM is conformant when its branch's schema holds every kind and field of the table as
the pinned commit has them: a later commit of the library, or a library with a user's own
kinds, fields and choices beside these, is conformant while that holds, and `schema check`
is how to find out. Fylgja never patches a schema that is not: nothing is inherited,
extended or loaded to adapt one, since the reader adds nothing to anyone's model. A DCIM
that differs where the mapping reads costs a **reader of its own**: a second mapping onto
the CTM, documented and checked as this one is, with its own name in every envelope. The
CTM is the contract, not this schema ([D-057](../docs/decisions.md#d-057)), and the
[production shape](../docs/roadmap.md#the-production-shape) makes the reader a seam;
Fylgja ships no reader for a diverged DCIM.

## The shipped template

`.infrahub.yml`, registered read-only on `main` as `fylgja`, gives Infrahub one query
(`device_config`, [`infrahub/queries/device_config.gql`](../infrahub/queries/device_config.gql)),
one Jinja2 transform (`srlinux_device_config`,
[`infrahub/templates/device_config.j2`](../infrahub/templates/device_config.j2)) and one
artifact definition (`srlinux_device_config`): the artifact `device-config`, `text/plain`,
for every device in the group `fylgja-devices`, by its name. The query reads one
`DcimDevice` with its description, its platform and the platform's manufacturer, and every
interface with its kind, name, status and role, and for a physical port its cable's ends
and its addresses (`ip_addresses`, the `IpamIPAddress` nodes the library's
`InterfaceLayer3` relates to the port, each by its `address` value). The template renders
both platforms: EOS's CLI when the platform's name is `EOS`, SR Linux's otherwise, a device
with no platform included, so that the pipeline never fails on one (the read refuses it).
Its header names the device, then `platform <Manufacturer> <Platform>; <description>`; each
physical port follows in name order, a management-role port as a comment left to the
platform and every other with its far end as its description (`to <device> <port>`), its
admin state, disabled when its `status` is `disabled`, and its addresses in value order:

| Platform | Per addressed port | Once per device |
|---|---|---|
| SR Linux | after the port's `subinterface 0 admin-state enable`: `set / interface <port> subinterface 0 ipv4 admin-state enable`, then `set / interface <port> subinterface 0 ipv4 address <a/l>` for each address | — |
| EOS | under the interface, after `no shutdown`: `no switchport`, then `ip address <a/l>`, a second and later address `ip address <a/l> secondary` (a plain second one replaces the first) | `ip routing`, after `hostname`, when any port is addressed: cEOS forwards nothing without it |

A device with no addressed port renders byte for byte what it did before 016. The render
was proved on live branches with `.venv/bin/infrahubctl render srlinux_device_config
device=<d> --branch <b> --out <file>`, which runs the tree's query and template against a
branch ([016's research §5](../specs/016-probes/research.md#5-verified-at-implement)).

**No routing.** It renders no virtual interface, no network instance beyond SR Linux's
`default` membership of each port's subinterface, no static route and no routing protocol,
and nothing above the ports. So two addressed ports of one device reach each other, by the
device's connected routes, and two devices do not: a [probe](#probes-declaring-one) whose
hosts sit on two devices finds no path through a twin of this template, and its burst
fails. The fixture gives each device two addressed spare ports for this reason,
`ethernet-1/10` with `10.<d>.10.1/24` and `ethernet-1/11` with `10.<d>.11.1/24` (`Ethernet10`
and `Ethernet11` on the mixed fixture's EOS devices), `d` the device's index, so that a probe
lies across one device: `testdata/probes/n1-loop.json` from `n1:ethernet-1/10` to
`n1:ethernet-1/11`. Routing between devices is the replacing transform's to render.

**It is a reference transform**, written to render the library's ports and their
addresses and nothing else, and meant to be replaced by the user's own transform rendering their layer 2 and 3 from
their own kinds. Fylgja reads the artifact, never the template: what a replacement owes is
an artifact on each device in the scope whose definition's `artifact_name` is its package's
`config.artifact_name` (`device-config` for both shipped packages), of a content type the
package accepts (`text/plain`), `Ready`. The push sends it after the bootstrap, so it never
has to carry management ([psp/README.md](../psp/README.md)).

**A tagged device outside `fylgja-devices` has no artifact, and is refused.** The tag puts
a device in the scope; the group is what the shipped definition renders. A device carrying
the scope's tag that is not a member of the group has no `device-config`, and every read of
its scope is refused `artifact.missing` naming it (`device n4 has no artifact named
device-config on branch b`). Join it to the group and generate its artifact: Infrahub
regenerates none on its own. A member without the tag renders and is outside the scope.

## Stages: marking one

A stage is a moment of a proposed change: its source branch at a point in time, named
`<branch>/<label>`, so a twin can be built from it (`fylgja twin create --stage
change-1/cabled`) and stepped to it (`fylgja twin step --stage change-1/cut-over`), and a
proposed change's stages listed and planned with no lab (`fylgja stage list`, `fylgja stage
plan --branch change-1`). Every proposed change has two stages of its own, derived and
never written: its **branch point** (`<branch>/branch-point`, the destination as it was
when the branch was made) and its **head** (`<branch>/head`, the branch as it is now). The
operator marks the moments between, each after that moment's writes and after its
artifacts are regenerated. Fylgja only reads stages, from the default branch. Every stage a
command resolves, reads or plans is read under one scope, its `--scope tag:<name>` or the
server's `FYLGJA_DEFAULT_SCOPE` (`twin step` takes its twin's), so the head and a mark's
staleness are judged on that scope's devices.

**Open the proposed change first**, as a draft while the change is built, from the branch
being built: the UI's "Create proposed change" with the draft toggle on, or
`CoreProposedChangeCreate` with `is_draft: true`. `main` cannot be a source, and a branch
has at most one open proposed change. Its creation runs its checks, which render the
branch's artifacts.

**When to mark**: after the moment's writes have landed and its artifacts have been
regenerated, by the proposed change's checks (its creation, or a retry, runs the artifact
validator) or by a generate. A regenerated artifact lands a few seconds after the generate
returns: wait for its checksum to move. A stage marked before that is refused as stale
(`stage.artifact.stale`), naming each device and both remedies; mark it again after
regenerating. Leave `as_of` out unless an instant is wanted: the mark's own write is always
after what it seals, while a read pinned at exactly a stamp sees the node and not the
value.

**The fields.**

| Field | Required | Meaning |
|---|---|---|
| `label` | yes | What this moment of the change is: a name with no `/` and no whitespace, unique within its proposed change. `branch-point` and `head` name the two derived stages, and a mark so labelled is refused (`stage.label.reserved`). |
| `proposed_change` | yes | The proposed change it belongs to, by id. The stage's branch is the proposed change's source. |
| `as_of` | no | The point in time on the branch, used verbatim (at most six fractional digits). One later than now is refused (`stage.at.unresolved`) until it has passed; one before the branch point is refused (`stage.at.before_branch_point`). Left out, it is the moment the stage was written. |
| `description` | no | What this moment of the change is, in a sentence. |

**The attribute is `as_of`; Fylgja says `at`.** Infrahub refuses attribute names shorter
than three characters, so the kind cannot call it `at`. Every command, report and record
calls it `at`, and says where it came from: `(given)` when `as_of` was written, `(written)`
when it is the stage's own write time, and `(branch point)` and `(head)` for the two
derived stages.

**Three ways to write one**, all Infrahub's own. Neither the stage kind nor Infrahub's
proposed change has a human-friendly id, so a stage names its proposed change by id;
`fylgja stage list --branch <b>` prints it beside the proposed change's name. An object
file, loaded with `infrahubctl object load stages.yml` on the default branch, which always
has the kind (the kind is branch-agnostic, so a stage lands in no branch's diff):

```yaml
---
apiVersion: infrahub.app/v1
kind: Object
spec:
  kind: FylgjaStage
  data:
    - label: cabled
      proposed_change: 18df3629-86a6-8afb-33bf-c518dfa7f7ce
      description: the new links cabled
    - label: cut-over
      proposed_change: 18df3629-86a6-8afb-33bf-c518dfa7f7ce
      as_of: "2026-10-17T04:19:35Z"
      description: traffic moved, at a chosen instant
```

Or the UI: **Stage**, an entry of its own in the sidebar's object menu
(`/objects/FylgjaStage`), with the fields above and the proposed change chosen from its
list. Or `infrahubctl object create FylgjaStage --set label=verified --set
proposed_change=<id> --set description="checked by hand"`. To delete one: the UI,
`infrahubctl object delete FylgjaStage <stage id> --yes`, or `FylgjaStageDelete`.

**Editing a stage.** Changing `description` changes nothing Fylgja reads: the stage keeps
its `at`. Changing `as_of` moves the stage's `at`. Changing `label` renames its reference,
and on a stage with no `as_of` it moves the `at` too: that `at` is the label's own write,
so a relabelled stage names the moment of the relabel. To keep its moment, write that `at`
(as `stage list` shows it) as its `as_of` first. None of this changes a twin already built
from the stage: the twin's record keeps what it was built from, and `stage list` warns
beside it (`stage.twin.moved`) when the stage now resolves elsewhere or is gone, as `twin
step` does beside its target; the step still goes from the bundle the twin was built from.

**Delete stages before their proposed change.** Infrahub refuses a proposed change's
delete while a stage names it (`It is linked to mandatory relationship proposed_change on
node FylgjaStage …`). A stage removed from its proposed change's `fylgja_stages` is left
naming none: `stage list` reports each such stage as `stage.orphaned` until it is deleted
by id, and `stage plan` plans none of them. A branch deleted under an open proposed change
cancels it, about 16 seconds later.

<a id="the-kind-on-the-default-branch"></a>
**The kind on the default branch.** Load it once, beside the library: `-prepare-main` does
on the development host before the library, and on an Infrahub that already holds the
library, `infrahubctl schema load schema/fylgja-stage.yaml` (check it first with
`infrahubctl schema check`); it is the one file of Fylgja's a DCIM user loads. `fylgja schema check --branch <b>` then says `stages: FylgjaStage present on the
default branch, with its extension`. An installation that never loads it loses only the
stage surface: `--stage`, `stage list` and `stage plan` are each refused naming this file
(`stage.kind.absent`).

[A stepping twin](../README.md#a-stepping-twin) walks a twin through a proposed change's
stages, forward and back.

## Probes: declaring one

A probe is a declaration outside intent ([D-064](../docs/decisions.md#d-064)): two hosts
the compiler synthesizes, `<name>-a` and `<name>-b`, each cabled by its `eth1` to an
uncabled port of the intent that is not `mgmt_only`, so that a step measures the loss
between them and `twin verify` sends a burst across the twin. It is never intent and never
in the CTM: the snapshot carries the probes beside it, and the probe package of the
probe's format says how its hosts run ([probes/README.md](../probes/README.md)). Since the
shipped template renders no routing ([above](#the-shipped-template)), a probe crosses one
device: both endpoints on one device's two addressed ports.

**Two sources, one list per request.** A `--probes <file>` declaration
([contracts/probes.schema.json](../contracts/probes.schema.json), version `1`) replaces the
probes declared here; it never adds to them. Without one, the server reads `FylgjaProbe` on
the default branch, unpinned, whatever `--at` or the stage says, once per request, after
its guards and before any read of intent, and hands the one list to every snapshot the
request takes: each stage of a `stage plan` or a rehearsal carries the same. With no object
of the kind the list is `[]`, with no warning. `twin create --snapshot` and `twin step
--snapshot` read neither: a snapshot carries its own. The checks `fylgja-step` and
`fylgja-twin` send no file, so a proposed change's checks carry the kind's probes.

**The kind is branch-agnostic**: a probe lands in no branch's diff, and once written every
branch's read with no file carries it, every proposed change's checks among them, until it
is deleted. Write one when it should travel with every request, and use a file for one
twin.

**The fields.** One object is one probe, its two endpoints flat attributes, so a read
yields the declaration's element by renaming alone: `a_*` is the file's first endpoint,
`b_*` its second.

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | `^[a-z0-9][a-z0-9-]{0,23}$`, unique; its hosts are `<name>-a` and `<name>-b`, their containers `clab-fylgja-<name>-a` and `-b`. |
| `format` | yes (`ping`) | The probe package that runs the hosts, a dropdown of the formats this kind knows: `ping` alone. |
| `a_device`, `b_device` | yes | The endpoint's device, by the intent's name. Not a relationship: the device may exist on one branch alone. |
| `a_interface`, `b_interface` | yes | The endpoint's interface on that device: uncabled and not `mgmt_only`, which the compile judges against the snapshot. |
| `a_address`, `b_address` | yes | The endpoint's host address with its prefix length, `10.1.10.2/24`. `Text`, not `IPHost`, which would normalise the value. |
| `a_gateway`, `b_gateway` | yes | The endpoint's gateway, an address with no prefix length, within the address's prefix: the device port's address. |
| `description` | no | What the probe watches, in a sentence. Fylgja does not read it. |

A probe read from the kind is held to the declaration's rules, at `resolve`, each finding
naming `FylgjaProbe on the default branch: …` where a file's names `probe file <path>: …`:
a name repeated or malformed, a format no loaded package declares, an address without a
prefix length, a gateway outside its prefix, a probe's four addresses of two families, and
two endpoints of the list sharing an address. Where its endpoints land is the compile's:
a device or interface the snapshot lacks, a cabled or `mgmt_only` port, a port an earlier
probe took, a host named as a device (`probe.*`, [contracts/cli.md](../contracts/cli.md)).
A stage that cables a probe's port is refused by the same rule; nothing drops a probe.

**Three ways to write one**, all Infrahub's own, on the default branch. An object file,
loaded with `infrahubctl object load probes.yml` (the kind is on the default branch, where
the loader writes when no `--branch` is given):

```yaml
---
apiVersion: infrahub.app/v1
kind: Object
spec:
  kind: FylgjaProbe
  data:
    - name: n1-loop
      format: ping
      a_device: n1
      a_interface: ethernet-1/10
      a_address: 10.1.10.2/24
      a_gateway: 10.1.10.1
      b_device: n1
      b_interface: ethernet-1/11
      b_address: 10.1.11.2/24
      b_gateway: 10.1.11.1
      description: the loop across n1's two spare ports
```

`format` takes the choice's name, `ping`. Or the UI: **Probe**, an entry of its own in the
sidebar's object menu (`/objects/FylgjaProbe`). Or `infrahubctl object create FylgjaProbe
--set name=n1-loop --set a_device=n1 --set a_interface=ethernet-1/10 --set
a_address=10.1.10.2/24 --set a_gateway=10.1.10.1 --set b_device=n1 --set
b_interface=ethernet-1/11 --set b_address=10.1.11.2/24 --set b_gateway=10.1.11.1`, which
reads back every attribute as written, `format` defaulting to `ping`. To delete one: the
UI, or `infrahubctl object delete FylgjaProbe <name>`, by its human-friendly id. On the
development host, `go run -tags fixture ./cmd/fylgja-fixture -probes <file>` writes each
probe of a declaration file, held first to the file's rules, and `-delete-probes` deletes
every one.

<a id="the-probe-kind-on-the-default-branch"></a>
**The kind on the default branch.** Load it once, beside the stage kind: `-prepare-main`
does on the development host, wherever it is absent, a `main` holding the library
included, and elsewhere `infrahubctl schema load
schema/fylgja-probe.yaml` (check it first with `infrahubctl schema check`), which moves
the default branch's schema hash. `fylgja schema check` does not report it. An
installation that never loads it is refused, at `resolve`, every request that takes probes
and sends no `--probes` file (`intent read`, `twin create --branch` and `--stage`, `twin
step` to a stage, `stage plan`, `twin rehearse`, and so the checks, which send none), as
`probe.kind.absent`, naming this file (`the default branch's schema has no kind
FylgjaProbe: load schema/fylgja-probe.yaml on it; only a request that sends no --probes
file reads it`); one that sends a file, an empty declaration
(`{"probes_version": "1", "probes": []}`) included, reads no kind and needs none.
