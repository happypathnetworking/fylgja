# The mapping of the DCIM library into a blueprint

The reader has one mapping, `infrahub-dcim`: the OpsMill schema library's DCIM, at the commit
`schema.COMMIT` names, into a blueprint 1
([`blueprint-1.schema.json`](../../formats/blueprint-1.schema.json),
[D-082](../../design/decisions.md#d-082)). No mapping is declared as data: what the schema cannot
hold, the platform package of a pair of manufacturer and platform and the artifact that holds a
device's configuration, is the reader document's
([`infrahub-reader-1.schema.json`](../../formats/infrahub-reader-1.schema.json)). Each row below is
a member of the blueprint, where it comes from in Infrahub, and its rule; each rule id is a row of
[rules.md](rules.md).

A blueprint's id addresses its `network` and `probes` alone
([D-006](../../design/decisions.md#d-006)), so the mapping sorts every list by code point and orders
each link's ends itself, and the same rows read in any order give one document but for
`observed_at`, and one id. A read pinned at a time reads every list at that time, sent to
Infrahub as given.

| Member | In Infrahub | Rule |
|---|---|---|
| The scope | `tag:<name>`: every `DcimDevice` whose `tags` hold the `BuiltinTag` of that name, whatever its status | A scope of another form is `scope.invalid`, and nothing is sent; one that selects no device is `scope.empty` |
| `blueprint_version` | None | `"1"` |
| `network.devices` | Every scoped `DcimDevice` | Sorted by `name`. A device that cannot be named, or has no package, is refused, and neither it nor a link it ends is built. The reader never writes an unmanaged device: each has a `config`, or the read is refused |
| `name` (a device's) | `DcimDevice.name` | Lower-cased, each run of characters outside `[a-z0-9]` made one `-`, and `-` trimmed from both ends ([D-038](../../design/decisions.md#d-038)); a name so changed is `device.name.renamed` and a fidelity row naming both; a label that is empty or longer than 63 characters is `device.name.unmappable`; two devices of one label each `device.name.duplicate`. Links and probes name the device by its label |
| `platform` | `DcimDevice.platform`, a `DcimPlatform`, its `name`, and its `manufacturer`'s, an `OrganizationManufacturer`'s `name` | The reader document's `package` of the row whose `manufacturer` and `platform` are the pair, compared exactly, letter case and spacing included. No platform, or a platform with no manufacturer, is `platform.missing`; a pair in no row `platform.unmatched` |
| `interfaces` | Every `InterfacePhysical` whose `device` is the device | Physical ports alone, sorted by `name`; an `InterfaceVirtual` is the configuration's, and is not read |
| `name` (an interface's) | `InterfacePhysical.name` | As Infrahub spells it |
| `mgmt_only` | `InterfacePhysical.role` | `role == "management"`, an approximation, the fidelity row `interface.mgmt_only`: the library has no management-only flag |
| `enabled` | `InterfacePhysical.status` | `status != "disabled"`, a status Infrahub holds none of included, an approximation, the fidelity row `interface.enabled`: the library's status is no admin state |
| `network.links` | Each connector a scoped port's `connector` names, a `DcimConnector`, with its `connected_endpoints` | Each connector judged once, however many of its ports were read. Its ends listed short of their `count`, or one twice, are `read.incomplete`. Else it is omitted for the first of five reasons that applies, in this order, an `info` finding and a fidelity row `omitted` whose source is its kind: no `DcimCable` (`omit.cable.kind`); other than two ends (`omit.cable.ends`); an end not on an `InterfacePhysical` (`omit.cable.endpoint`); an end on a device outside the scope, or on no port read (`omit.cable.outside_scope`); an end on a management port, which blueprint 1 refuses a link on (`omit.cable.management`). Else it is a link, a cable with both ends on one device among them, where both its devices are in `network.devices`. Sorted by `(a.device, a.interface, b.device, b.interface)` |
| `a`, `b` | The cable's two ends | The two ends as `(device, interface)`, sorted: `a` the first |
| `device`, `interface` (an end's) | The end's `InterfacePhysical`: its device's name and its own `name` | The device's label, and the port's name |
| `config` | The device's `artifacts`, each a `CoreArtifact`, by its `definition`'s `artifact_name`: its `status`, `checksum` and `storage_id`; and the bytes `GET /api/storage/object/<storage_id>` serves | Judged for every scoped device, one the mapping refused by its platform or its name among them, since the choice needs no package. The one artifact of the reader document's `artifact`, chosen from the listing alone: none is `artifact.missing`, several `artifact.ambiguous` and never a choice, a status but `Ready` (given verbatim), or no storage id or no checksum, `artifact.unready`, and no content is fetched for it. Then one request a device, in name order, for its content: a status but 200 is `artifact.content.unavailable`; bytes whose MD5 in hex is not the checksum `artifact.checksum.mismatch`; empty bytes or no UTF-8 text `artifact.content.invalid`. The text, verbatim. A read pinned at a past time lists the artifact as it stood then, whose storage id still serves those bytes, and never falls back to the present artifact ([verified-facts.md](../../design/verified-facts.md), "Infrahub 1.11.11") |
| `probes` | Every `FylgjaProbe`, where the reader document's `probes` is true, read through the branch's endpoint at the time read, as every other list ("The probes", below) | Read only where the document asks: the kind held to the branch's present schema, a kind or an attribute missing `probe.kind.absent`, and the list held whole. A probe an end of which names no scoped device is omitted, `omit.probe.outside_scope`, an `info` finding and a fidelity row `omitted` whose source is `FylgjaProbe`; the rest are held to the declaration's rules, each fault an error naming the probe (`probes.invalid`, `probe.name.duplicate`, `probe.gateway.outside`, `probe.address.duplicate`), and none is given where one is. Sorted by `name`. `[]` where the document asks for none, and an Infrahub without the kind is then no fault |
| `name`, `format` (a probe's) | `FylgjaProbe.name`, `FylgjaProbe.format` | As Infrahub holds them |
| `endpoints` | `FylgjaProbe`'s `a_device`, `a_interface`, `a_address`, `a_gateway`, then its `b_*` four | Two, a then b, each `{device, interface, address, gateway}`: the device a scoped device's name in Infrahub, compared exactly, written as its label, as links name it; the rest as Infrahub holds them |
| `source` | The source envelope, which the core never reads or hashes | Exactly the eight members below, none hashed |
| `source.source` | None | `"infrahub"` |
| `source.branch` | The branch read | As given |
| `source.at` | The time read at | As given, and sent as given: a read is always given its time, and the command, given no `--at`, reads at `head`'s answer |
| `source.scope` | The scope | As given |
| `source.mapping` | None | `{"reader": "infrahub-dcim", "model": "opsmill/schema-library", "version": <schema.COMMIT>}` |
| `source.schema_hash` | `GET /api/schema?branch=<branch>`'s `main` | The branch's present schema hash, as Infrahub answered it |
| `source.observed_at` | None: the reader's clock | UTC, `%Y-%m-%dT%H:%M:%S.%fZ`, taken before the first request; it pins nothing |
| `source.fidelity` | None | Rows `{"disposition", "object", "source", "reason"}`, sorted by those four in that order: on every read `interface.enabled` and `interface.mgmt_only` approximated, and `platform.version` omitted, `DcimPlatform` carrying none; and one for each device renamed and each connector and probe omitted |

**What is never read**: a platform's version, which the library does not carry; a device's
status, its role, its location and its other attributes; an `InterfaceVirtual`; a port's other
attributes; an address's attributes; a cable's attributes but its `label`, which names it in a
finding; an artifact's `content_type`, its name and its definition's other fields; and every kind
the schema check's table does not name, but the stale rule's below and `FylgjaProbe`. The stale
rule reads none of those values, but a stamp on each node it names, which a write to any of them
moves.

## The probes

A probe is declared beside intent and not in it, as the kind `FylgjaProbe`, which ships with the
reader in [`schema/fylgja-probe.yml`](schema/fylgja-probe.yml) and is the one schema of Fylgja's a
read may need ([D-082](../../design/decisions.md#d-082)). One object is one probe of blueprint 1:
ten Text attributes, all required, `name` and `format` under blueprint 1's patterns, and each end's
`device`, `interface`, `address` and `gateway` flat, a then b, each address and gateway under
blueprint 1's IPv4 patterns. `format` is no Dropdown, so a probe package is added with no schema
change, and an address is no `IPHost`. A probe names its devices by their names in Infrahub and has
no relationship to a device. The kind is branch-agnostic, unique and ordered by its name, and a
probe is read through any branch's endpoint; read through a branch's endpoint at a time, a probe
answers as it stood then, and one deleted since is still read there
([verified-facts.md](../../design/verified-facts.md), "Infrahub 1.11.11").

The kind is held to the schema the read has read already, by its name and its ten attributes'
names, so asking for probes costs no request where the kind is absent. Each probe omitted is left
out before the rest are judged, so its addresses are weighed against no other's. The rest are a
probe declaration ([`probes-1.schema.json`](../../formats/probes-1.schema.json)), each end's device
its blueprint name, held to its rules by the core's own loader with the formats the probes name:
whether a probe package runs a format is the compiler's to say (`probe.format.unknown`).

## The stale rule

A configuration older than its intent is refused by device, `artifact.stale`
([D-082](../../design/decisions.md#d-082)): Infrahub regenerates an artifact only when asked, so a
read after an edit would otherwise give a valid blueprint of a network that is not the one
intended. It is judged in the same pass as the rest, for each device whose artifact the read
selected, from lists read at the time read, each held whole (`read.incomplete`), and from the
branch's event log. Each row is one thing the rule reads, on what plan 2 read of Infrahub 1.11.11
([verified-facts.md](../../design/verified-facts.md), "Infrahub 1.11.11", "What a stale rule can be
built on").

| Read | In Infrahub | How it counts |
|---|---|---|
| A node's stamp | The `node_metadata` of the edge the node is read through: `updated_at`, `updated_by`, `created_at` | Its `updated_at`; its `created_at` where `updated_by` is a task workers' account, below, whose restamp after a generation is no intent. `__system__`, the id Infrahub answers on an operator's address create and edit, is never discounted, whatever made the query groups |
| The device, its platform, its manufacturer | Each scoped `DcimDevice`'s edge, its `platform`'s and the platform's `manufacturer`'s; and the platform's and the manufacturer's `name`'s own `updated_at` | The device's stamp; of the platform and the manufacturer, their `name` stamps alone, which are what the configuration renders of them. A device made on the platform moves the platform's node stamp, read on the `platform` edge of every device on it, and not its name's, so the two node stamps count for `head` alone (P3-44); a platform's or a manufacturer's other writes count through their own events, below |
| Its interfaces | Every interface of either kind under `interfaces` | A stamp each |
| Its addresses | Every `IpamIPAddress` under an interface's `ip_addresses`, selected on `InterfaceLayer3`, which a physical port and a virtual interface both inherit | A stamp each: an address's edit moves its own stamp alone, and one made moves its interface's and logs no event |
| Its cables | The `connector` of each `InterfacePhysical(device__ids:, connector__isnull: false)` of the scope, a row a port, by the port's id | The `connector` edge's stamp, the intent of each end's device |
| Its cables' far ends | Each end of each such connector, under `connected_endpoints`, on an interface: its `name`'s own `updated_at` and its device's `name`'s, whether or not the far device is in the scope | The far port's and the far device's names are what the configuration renders of the far end, and all of it the rule counts: their `name` stamps, and an event whose primary node is the far port or the far device and which names the attribute `name`. Nothing else of the far end counts, neither its node stamps, which an address made on it moves, nor an event naming the far device among its related nodes, as every one of its ports' does (P3-27) |
| When it was generated | The selected artifact's `checksum.updated_at`, the artifact the read chose found by its id, which moves only when the bytes stored differ | The later of it and `generated_since`, where one is given and no later than the time read; no checksum stamp is `artifact.unready`, whatever `generated_since` says |
| The task workers' accounts | The `created_by` of each internal `CoreGraphQLQueryGroup` of the queries the scope's artifacts render through (each artifact's definition's `transformation`'s `query`) | `agent` on the development Infrahub; nothing but an account's name tells it from an operator's |
| The branch's events | `InfrahubEvent(branches: [<branch>, "main"], since: <the floor>, order: DESC)`, 50 a page, on the branch's own endpoint, read down to the floor; for `main`, `branches: ["main"]` since its `branched_from`. The events read run from the floor, the oldest checksum stamp among the scoped devices judged, or `generated_since` where later, since no event before it can make one stale (P3-50), to the present, 50 a page: every event of the logs read in that time, whatever the scope | A branch is made from `main` holding what `main` held at its `branched_from`, a configuration gone stale there among it, so an event of `main`'s counts for a branch where it occurred no later than the branch's `branched_from`, and not after: a write on `main` after the branch was made is not the branch's, and a rebase is not read (P3-45). An event is intent's when it is a node's own write (a `NodeMutatedEvent`) on a `DcimPlatform`, an `OrganizationManufacturer`, an `IpamIPAddress` or a kind the branch's `used_by` lists for `DcimGenericDevice`, `DcimInterface` or `DcimConnector`, and it created or deleted the node, or names an attribute, or a relationship but `member_of_groups`, `subscriber_of_groups`, `artifacts`, `profiles` and `object_template`, and the reverse relationships the mapping never renders, a platform's `devices` and a manufacturer's `platforms`. It names a device when its primary node is one of the nodes above but a cable's far end, which counts by name alone, as the row before says, or when one of its related nodes is one of the device's own: the device, an interface, an address or a cable. The platform and the manufacturer are every device's on them, and a device made on the platform names it among its related nodes, so the two count through an event whose primary node they are alone (P3-42); a relationship's peer alone names none. One a task workers' account wrote, `__system__` never among them, or later than the time read, counts for none. The events show what no stamp does: an operator's write under the workers' restamp, and a removal, which can move a stamp back |

A device's intent was written at the latest of its stamps and of the intent events naming it. **It
is stale when that is strictly later than when its configuration was generated**, and the message
gives both times and the remedy: regenerate it, or read with a `generated_since` at which a
regeneration is known to have completed, since a regeneration that stores the same bytes moves no
checksum stamp. A stale configuration stays stale until someone asks.

**`head`** answers the first instant after the branch's latest write, for a caller that wants the
branch as it stands: `times.after` of the latest of every stamp above read with no time (the
devices', their platforms' and manufacturers' and their names', interfaces', addresses', cables',
their ends' names' and each checksum's), of every `FylgjaProbe`'s stamp, whatever devices it
names, where the branch's schema holds the kind, since a probe is the blueprint's too and `head`
has no reader document to ask, nothing discounted, and every event of the branch's history, its
own since it was made and `main`'s up to then, read as the row above reads them from the latest
stamp, intent's or not, in the layout Infrahub answered it in. A read pinned at exactly a write's
stamp answers its values with the earlier stamps; a microsecond after, the write. Infrahub logs a
write's events up to seconds after it, and its task workers' group writes follow a generation's
checksums by up to 7.9 s, so a `head` taken within about 10 s of a write may answer a time a write
falls after; the caller waits that out.

**What is not yet read**, so that the rule rests on no reading of it: an artifact reading `Error`; a
device's `platform` relationship changed; an address moved to another port; a manufacturer's edit; a
platform's attribute other than its name, which the rule counts by its event alone; a cable's
attribute edit; a cabled far port deleted, whose `node.deleted` names the far port, which is then
gone from the cable's `connected_endpoints`; whether a device re-platformed elsewhere logs a write
to its platform's `devices`, as one made on it does, or a platform to its manufacturer's
`platforms`, which the rule does not count; whether the task workers' restamp moves an attribute's
own stamp, which the far end's `name` stamps and the platform's and manufacturer's are, the seed's
stages read fresh being the check; a write on `main` before a branch was made that only an event
shows, read through the branch, which the contract tier never provokes, since it writes nothing on
`main`; an artifact a proposed change's validation regenerates with other bytes, plan 5 having
read the seeded branch's checksums and their stamps unmoved by one
([verified-facts.md](../../design/verified-facts.md), "Infrahub 1.11.11"); and two paths by which
the example's change source gives a read its `generated_since` or none, which its pure tier
alone holds: a mark read with the completion of an artifact validation in force at its time, and
a head read where no artifact validator appears. Not read either is the
direction the far end points to: an artifact's internal query group lists the nodes its query read,
which would tell the rule every node a configuration renders from, its template's own choice
included, in place of this table.
