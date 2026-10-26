# The mapping: the Infrahub reader of the schema library's DCIM

The one documented rule by which the Infrahub reader turns the schema library's model
into the CTM ([D-057](../research.md#3-1); Constitution III from 2.0.0): which kinds and
fields it reads, what each becomes, with what fidelity, what it refuses and what it
omits. The model is OpsMill's [schema library](https://github.com/opsmill/schema-library)
at commit `26336e9` (`26336e9026dff1907f2c58e81dd6ae7b5c3f763e`), its `base/dcim.yml`,
`base/ipam.yml`, `base/location.yml`, `base/organization.yml`,
`extensions/cable/cable.yml` and `extensions/location_minimal/location_minimal.yml`,
vendored under `schema/dcim/`. The reader's name in every envelope is `infrahub-dcim`,
its model `opsmill/schema-library`, its version `26336e9`. At the close this document is
the schema README's mapping section; until then it is the plan's.

## 1. What is read, and what it becomes

| CTM | Read from | Rule | Fidelity |
|---|---|---|---|
| the scope | the request's `--scope tag:<name>`, or the server's `FYLGJA_DEFAULT_SCOPE` | every `DcimDevice` carrying the tag, whatever its `status`; everything else on the branch is outside the scope and not read | — |
| `devices[].name` | `DcimDevice.name` | the node's name; every device read carries the tag | exact |
| `devices[].platform.package` | `DcimDevice.platform` → `DcimPlatform.name`, and its `manufacturer` → `OrganizationManufacturer.name` | the package whose `platform.matches` names the pair, both strings exactly | exact |
| `devices[].platform.version` | nothing | absent: the library's platform carries no version | **omitted**, one row per read |
| `devices[].artifact` | the device's `artifacts` through `CoreArtifactTarget` | as today: the one named by the package's `config.artifact_name`, `Ready`, bytes verified against Infrahub's checksum | exact |
| `devices[].interfaces[]` | `InterfacePhysical` with `device` among the devices read | one port per physical interface, by `name`; an `InterfaceVirtual` is never read | exact |
| `interfaces[].mgmt_only` | `InterfacePhysical.role` | `management` is the management port; a second such port on a device is omitted by the compiler as today (`omit.mgmt.extra`) | **approximated**, one row per read |
| `interfaces[].enabled` | `InterfacePhysical.status` | `disabled` is `false`; every other value, `null` included, is `true` | **approximated**, one row per read |
| `links[]` | the port's `connector`, a `DcimConnector` (the `DcimCable`), with its `connected_endpoints` | a link when the cable has exactly two ends and each is an `InterfacePhysical` of a device in the scope; the id is the two endpoints' `<device>:<port>` sorted and joined with `\|`, each port's `link` set to it | exact |
| nothing | any other cable reached from a port in the scope | omitted, never refusing the read, with one of three reasons (§4) | **omitted**, one row per cable |

Not read, by the rule that the mapping names everything read: the device's `description`,
`status`, `role`, `location`, `primary_address`, `serial_number`, `device_type`; the
port's `description`, `mtu`, `mac_address`, `l2_mode`, `ip_addresses`, `sub_interfaces`;
every `InterfaceVirtual`; every address, prefix, location, tag beyond the scope's,
device type and manufacturer beyond the platform's. The template reads the device's
`description` and renders it; the reader never does.

## 2. The queries

Two operations, paged by 100, every page at the read's `at` when one was given:

- **`Devices(tag, limit, offset)`**: `DcimDevice(tags__name__value: $tag, limit, offset)`
  selecting `id`, `name { value }`, `platform { node { name { value } manufacturer { node
  { name { value } } } } }` and the `ArtifactFields` fragment on `CoreArtifactTarget`
  (artifacts: name, status, content type, checksum, storage id, definition's artifact
  name), as today. No `interfaces`.
- **`Ports(devices: [ID], limit, offset)`**: `InterfacePhysical(device__ids: $devices,
  limit, offset)` selecting `id`, `name { value }`, `role { value }`, `status { value }`,
  `device { node { id } }` and `connector { node { id connected_endpoints { count edges {
  node { __typename id ... on InterfacePhysical { name { value } device { node { id } } }
  } } } } } }`, once per page of devices.

The read-only test holds every operation's roots to `DcimDevice`, `InterfacePhysical`,
`FylgjaStage`, `CoreProposedChange`, `CoreArtifactValidator`, `Branch`,
`InfrahubEvent` and `CoreGraphQLQueryGroup` (D-060), and every fragment target (`fragment … on`, `... on`) to `DcimDevice`,
`DcimPlatform`, `InterfacePhysical`, `DcimCable`, `CoreArtifactTarget` and
`NodeMutatedEvent`. The scope's tag, `BuiltinTag`, is read by the filter alone and is
the Infrahub-owned read FR-001 names.

## 3. Conformance: the table, per kind and per field

Read from `GET /api/schema?branch=` before any query, as the pinned commit loads (every
value is what Infrahub 1.11.2 reports for the six files; research §1.3). A kind absent is
`schema.kind.missing`; a field absent is `schema.field.missing`; a field present with
another `kind`, `cardinality`, `peer` or `optional` (where the table requires it) is
`schema.field.mismatch`; a dropdown without the choice the mapping reads is
`schema.choice.missing`; a generic the mapping relies on not implemented by the kind it
expects is `schema.used_by.missing`. Every finding names the commit (`as
opsmill/schema-library@26336e9 has it`), all are reported in one pass, and nothing beyond
the table is reported.

| Kind | Attribute: kind, optional | Relationship: peer, kind, cardinality, optional |
|---|---|---|
| `DcimDevice` | `name`: Text, required | `tags`: `BuiltinTag`, Attribute, many, optional · `platform`: `DcimPlatform`, Attribute, one, optional · `interfaces`: `DcimInterface`, Component, many, optional · `artifacts`: `CoreArtifact`, Generic, many, optional (`CoreArtifactTarget`) |
| `DcimPlatform` | `name`: Text, required | `manufacturer`: `OrganizationManufacturer`, Attribute, one, optional |
| `OrganizationManufacturer` | `name`: Text, required | — |
| `InterfacePhysical` | `name`: Text, required · `role`: Dropdown, optional, choices ⊇ {`management`} · `status`: Dropdown, optional, choices ⊇ {`disabled`} | `device`: `DcimGenericDevice`, Parent, one, required · `connector`: `DcimConnector`, Attribute, one, optional |
| `DcimCable` | — | `connected_endpoints`: `DcimEndpoint`, Attribute, many, optional |

`used_by`: `DcimGenericDevice` ⊇ {`DcimDevice`}, `DcimInterface` ⊇ {`InterfacePhysical`},
`DcimEndpoint` ⊇ {`InterfacePhysical`}, `DcimConnector` ⊇ {`DcimCable`}. `optional` is
compared as the endpoint reports it: a required attribute must read `optional: false`;
an optional one may read either (an attribute with a default reads `optional: true`
whatever its YAML says).

`fylgja schema check --branch <b>` runs this half alone and, on success, prints
`conformant with opsmill/schema-library@26336e9: DcimDevice, DcimPlatform,
OrganizationManufacturer, InterfacePhysical, DcimCable`, then the stages line as today.

## 4. Completeness, inside the scope

After conformance, before any CTM, every finding in one pass, no CTM on any:

| Rule | Object | When | Message names |
|---|---|---|---|
| `scope.empty` | the scope | the device query answers 0 (the tag absent from the branch, or on no `DcimDevice`) | the scope and the branch |
| `platform.missing` | the device | no `platform`, or a platform with no `manufacturer` | what the device carries |
| `platform.unmatched` | the device | no package's `matches` names the manufacturer's `name` and the platform's `name`, both exactly (letter case and spacing included) | the device's pair, and every package with its pairs |
| the artifact rules | the device | as today (FR-008); a device refused for its platform is not also refused for its artifact | as today |

A cable never refuses the read:

| Rule | Object | When (the first that applies) | Reason text |
|---|---|---|---|
| `omit.cable.ends` | the cable (`label`, or id when it has none) | `connected_endpoints.count` is not 2 | `other than two ends (<n>)` |
| `omit.cable.endpoint` | the cable | an end whose `__typename` is not `InterfacePhysical` | `an end not on a physical port (<kind>)` |
| `omit.cable.outside_scope` | the cable | an end whose device is not among the devices read | `an end outside the scope (<device>:<port>)` |

Each is an `info` finding beside the read, naming every end known as `<device>:<port>`,
and a row of the envelope's fidelity list. A cable is judged once, by its id, however many
of its ends are in the scope. A cable between two management-role ports, or with both ends
on one device, reaches the CTM: the compiler omits the first (`omit.link.mgmt_only`) and
validation refuses the second (`link.endpoints.same_device`), as today.

## 5. The fidelity list, as this reader writes it

Every read: `{approximated, interface.mgmt_only, InterfacePhysical.role, "the management
port is the port whose role is management; the library has no management-only flag"}`,
`{approximated, interface.enabled, InterfacePhysical.status, "a port is enabled unless
its status is disabled; the library's status is not an admin state"}`, `{omitted,
platform.version, DcimPlatform, "the library's platform carries no version"}`; then one
`{omitted, <cable>, DcimCable, <the finding's reason>}` per cable of §4. Sorted by
(disposition, object). The compiler copies the list into the manifest's `fidelity.read`.

## 6. The stamps and the events, for stages

A device's intent stamp (FR-023) is the latest node stamp among the device, every one of
its interfaces (virtual included), its platform, its platform's manufacturer and every
cable one of its physical ports is an end of, read as the two queries read them with
stamps and ids alone. A node's stamp is its `node_metadata.updated_at`, or its
`created_at` when its `updated_by` is Infrahub's own account (D-058): the `created_by` of
the internal `CoreGraphQLQueryGroup`s of the queries the scope's artifacts' definitions
render through, read by a third query (`QueryGroups`) at the stamps' branch and `at`, no
group leaving no stamp out (D-060). A generation adds what it reads for the first time to
its query's group as that account, seconds after the checksum, and that join is never
intent. The head's `at` is one microsecond after the latest of every device's intent stamp
and every artifact's `checksum.updated_at`, or after the latest intent event when later
(D-045, D-048, unchanged). An intent event is one whose primary
node's kind is `DcimDevice`, an implementer of `DcimInterface` or of `DcimConnector` on the
branch, `DcimPlatform` or `OrganizationManufacturer`, and that created or deleted the node
or changed any attribute, or any relationship but `member_of_groups`,
`subscriber_of_groups`, `artifacts`, `profiles` and `object_template`; it counts for a
device when its primary node or a peer is the device, one of its interfaces, its platform,
its manufacturer or one of its cables.
