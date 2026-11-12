# Rules of the Infrahub reader

Every finding the reader files has a stable dotted rule id, as the core's do (Constitution X),
and callers and tests match on the id, never on the wording. These rules are the reader's own,
never the core's ([`formats/README.md`](../../formats/README.md), note 11); the core's are in
[`docs/rules.md`](../../docs/rules.md). A finding is the core's `Finding`, of findings 1's form
([`findings-1.schema.json`](../../formats/findings-1.schema.json)): its severity, as its object
the name in Infrahub of what it is about, and a message of one sentence that names the branch
and the time read and never holds a byte of a configuration. A read whose findings hold an
error gives no blueprint ([D-082](../../design/decisions.md#d-082)). The code names each rule by
a module-level constant beginning `RULE`.

A **problem** is a reason the reader document
([`infrahub-reader-1.schema.json`](../../formats/infrahub-reader-1.schema.json)) is refused, so
that no read is made with it, under a rule id of the same kind: `document.load` raises the
core's `documents.Rejected` naming the file, with every problem found in one pass, each at a
JSON pointer and with a detail. The problems' rows come first, their severity `problem` and
their object the pointer.

The **schema check** (`schema.py`) holds the branch's schema to `TABLE`, every kind and field
the mapping reads, before `read` or `head` reads the network, since a query of what the branch
lacks fails naming nothing an operator can act on; each `schema.*` finding is an error, and
every one is filed in one pass. Infrahub records no commit of a loaded schema, and a kind's
hash is the instance's own, so the check compares names and properties and never a hash: the
commit each finding names after `opsmill/schema-library@`, the one `infrahub/schema/dcim/COMMIT`
holds, is the mapping's claim of the library's commit the table was written from, not a fact
read of the instance. `GET /api/schema` has no time axis, so the schema checked is the branch's
present one whatever time the read is pinned to, and a pinned query is checked against it too.
The table's properties are those Infrahub 1.11.11 answered on `main` for the library at that
commit, where `InterfacePhysical.status`, which has a default, reads optional though its file
declares it required ([verified-facts.md](../../design/verified-facts.md), "Infrahub 1.11.11").
Nothing the table does not name is reported: a branch may hold kinds, fields, choices and users
of its own.

The **read** (`read.py`, with `mapping.py` and `artifacts.py`; [mapping.md](mapping.md)) judges
the forms of the scope and the times before anything is sent, and ends at a schema that differs,
a scope that selects no device, or a list of the devices or the ports that is not whole, since the
rest would judge a partial list; past those, every rule is judged in one pass, every device at
fault filed. Every scoped device's artifact is judged, a device refused by its platform or its
name among them, since choosing the artifact needs the document's `artifact` and the listing
alone: a device with no platform and no artifact is `platform.missing` and `artifact.missing` in
the one result. A connector the mapping cannot make a link of is omitted, an `info` finding and a
fidelity row, and the read goes on: the first of the five `omit.cable.*` reasons that applies is
filed, in the order of their rows. Each problem of the blueprint built, which the read holds to
blueprint 1 (`blueprint.validate`), is an error under the core's own rule id
([`docs/rules.md`](../../docs/rules.md), the `blueprint.*` problems), its pointer the object, and
has no row here.

The **stale rule** (`stale.py`; [mapping.md](mapping.md), "The stale rule") judges each device
whose artifact the read selected, in the same pass, from lists of its own: the scope's stamps,
their cables', the internal query groups', all read at the time read, and the branch's events, with
`main`'s up to the branch's `branched_from`. A list of those that is not whole is
`read.incomplete`, and the rule is not judged, since a list in part could pass a stale device.
`head` (`read.py`) answers a time and has nowhere else to put a refusal, so it raises `Refused`
with the findings: `scope.invalid`; the schema check's `schema.*`, before anything else is read,
since its reads select the table's fields too; `scope.empty`; or `read.incomplete`, each naming
the branch as it stands.

The **probes** (`probes.py`; [mapping.md](mapping.md), "The probes") are read only where the
reader document asks for them, and then in the same pass: the kind `FylgjaProbe` held to the
schema already read, and each probe read at the time read, the list held whole
(`read.incomplete`). A probe an end of which names no scoped device is omitted, an `info` finding
and a fidelity row; the rest are a probe declaration, held to its rules by the core's own loader
(`fylgja_core.probes`), whose four rule ids the reader files as the loader names them
([`docs/rules.md`](../../docs/rules.md)), each an error whose object is the probe's name, every one
filed in one pass. A declaration refused gives no probe, and the read no blueprint.
`probe.format.unknown` is never filed: whether a probe package runs a format is the compiler's to
say. Where the document asks for no probe, the kind is not read and an Infrahub without it is no
fault.

The **command** (`cli.py`; [README.md](README.md), "The command") prints each finding as one line
on stderr, `<severity> <rule> <object>: <message>`, in a result's order, and exits 1 where one is
an error, writing no blueprint; a reader document refused exits 2, a line naming the file and one
for each problem beneath it, `<rule> at <pointer>: <detail>`. It files no rule of its own: what
stops it short of a finding (a variable not set or one the client's rules refuse, a reader
document not read, an `InfrahubError`, `--out` not written) is a line on stderr and exit 2,
under no rule id.

| Rule | Severity | Object | Means, and the remedy |
|---|---|---|---|
| `reader.version.unsupported` | problem | `/reader_version` | The document's `reader_version` is not `1`, and nothing else of it is checked. Write it in version 1's form |
| `reader.invalid` | problem | The member at fault (`/probes`); for a member missing or unknown, the object that lacks or holds it (`""` for the document, `/platforms/0` for a row), the member named in the detail; `""` for a file that is neither JSON nor YAML | The document violates its schema, or the file is no document at all. Correct what the detail names |
| `reader.platform.duplicate` | problem | The later row (`/platforms/1`) | Two rows hold one pair of manufacturer and platform, compared exactly, letter case and spacing included, so the pair would name two packages, or one package twice. Keep one row for the pair |
| `at.invalid` | error | The value given (`yesterday`) | `at` or `generated_since` is no RFC 3339 time with `T`, and `Z` or an offset; or it has more than six fractional digits, every one of which past the sixth Infrahub cuts, so a read at it would be pinned at another instant than the one given ([verified-facts.md](../../design/verified-facts.md), "Infrahub 1.11.11"); or `generated_since` is later than `at`, so it would stand for a regeneration the bytes read at `at` cannot carry, the object then the `generated_since` given. Nothing is sent. Give a time Infrahub answered, or one written to the microsecond or coarser, and a `generated_since` no later than `at` |
| `scope.invalid` | error | The scope given (`site:lab`) | The scope is not `tag:<name>`, its one form, which selects every `DcimDevice` that carries the tag `<name>`, whatever its status. Nothing is sent. Give the scope as `tag:<name>` |
| `infrahub.version.unverified` | warning | Infrahub's version (`1.12.0`) | The Infrahub read is of a version the reader was not verified on, none of `SUPPORTED` (`1.11.11`). Every result of that connection carries it, and it is logged once, at the connect; the read goes on. Verify the reader on that version, its contract tier against it, before relying on what it reads |
| `schema.kind.missing` | error | The kind, a node (`DcimCable`) or a generic (`DcimConnector`) | The branch's present schema lacks a kind the mapping reads. It is named once: none of its fields, and not its place among a generic's users, is named beside it. Load the library's file that declares it, at the commit named |
| `schema.field.missing` | error | The kind and the field (`DcimCable.label`) | A kind of the table lacks an attribute or a relationship the mapping reads. Give it the field as the library declares it at the commit named |
| `schema.field.mismatch` | error | The kind and the field (`DcimPlatform.name`) | A field the mapping reads differs from the table: an attribute's kind, a relationship's peer, kind or cardinality, or a field the mapping requires reading optional (one the table leaves optional may read either). One finding a field, each property that differs given with the table's value first (`kind Text, found Number; optional false, found true`). Make the field as the library declares it at the commit named |
| `schema.choice.missing` | error | The kind and the dropdown (`InterfacePhysical.role`) | A dropdown lacks a choice the mapping reads: `management` of `InterfacePhysical.role`, `disabled` of `InterfacePhysical.status`. Restore the choice |
| `schema.used_by.missing` | error | The generic (`DcimConnector`) | A generic's `used_by` does not name a kind the mapping reaches through it, both present, the table's five generics and their users: `DcimDevice` for `DcimGenericDevice`, `InterfacePhysical` for `DcimInterface`, `DcimEndpoint` and `InterfaceLayer3`, `DcimCable` for `DcimConnector`. A virtual interface is no user the table requires: its addresses are read where the branch has the kind. Let the kind inherit from the generic, as the library's does |
| `scope.empty` | error | The scope (`tag:fylgja`) | No `DcimDevice` on the branch at the time read, or as it stands for `head`, carries the tag, whether the tag is absent or on no device, which the read does not tell apart; the result's `empty` is true, and nothing more is read. Tag the devices to read, or name the tag they carry |
| `read.incomplete` | error | The list: `DcimDevice`, `InterfacePhysical`, a device's artifacts (`n1.artifacts`) or a cable's ends (`<cable>.connected_endpoints`, the cable by its label or else its id); and the stale rule's, a device's interfaces (`n1.interfaces`) and their addresses (`n1.ip_addresses`), the ports' connectors (`InterfacePhysical.connector`) and each one's ends (`<cable>.connected_endpoints`, once a cable), `CoreGraphQLQueryGroup` and `InfrahubEvent`; the probes, `FylgjaProbe`, read for the blueprint or, for `head`, for their stamps; or a device's name (`n1`), where the stale rule's stamps do not list a device the read listed | A list Infrahub answered, a nested one too, held other than the `count` Infrahub gave for it, or one object twice, so mapping it would give a blueprint of less than Infrahub holds, and judging the stale rule over it could pass a stale device; or the stale rule's stamps lack a device, or a device's artifact, that the read listed and selected, both read at one time under one filter. The message gives both numbers, or names what is missing, with the branch and the time read: a read is always given its time, which the command takes from `head` where it is given no `--at`, and `head`, which reads with no time, says it read the branch as it stands. A connector is listed once for each port it ends, so `InterfacePhysical.connector` names each row by its port, and two ends on one device are no object twice; an event the log answers again on its next page, as it grows while it is read, is kept once and is no fault. Read again; a list that is still not whole is a fault of Infrahub's answer, to report with the branch, the time and the list |
| `platform.missing` | error | The device's name in Infrahub (`n1`) | The device has no platform, or its platform no manufacturer, so the reader document cannot choose its platform package. Give the device its platform, and the platform its manufacturer |
| `platform.unmatched` | error | The device's name (`n1`) | The device's manufacturer and platform, compared exactly, letter case and spacing included, are a pair no row of the reader document holds. Add the pair's row to the document, or correct the names in Infrahub |
| `device.name.renamed` | info | The device's name in Infrahub (`N1`) | The device's name is no DNS-1123 label, so the blueprint names it by its label ([D-038](../../design/decisions.md#d-038)): lower-cased, each run of characters outside `[a-z0-9]` made one `-`, and `-` trimmed from both ends. A fidelity row names both, and each link and probe names the device by the label. Rename the device in Infrahub to read its name unchanged |
| `device.name.unmappable` | error | The device's name (`***`) | The device's name makes no DNS-1123 label: it holds no letter or digit, or its label is longer than 63 characters. Rename the device in Infrahub |
| `device.name.duplicate` | error | Each device's name (`N1`, and `n1`) | Two or more scoped devices make one label, so the blueprint could not tell them apart: each is filed, its message naming them all. Rename all but one of them in Infrahub |
| `omit.cable.kind` | info | The connector, by its label or else its id | A port is connected by a connector that is no `DcimCable`, and blueprint 1 makes a link of a cable alone. The connector is left out of the blueprint, a fidelity row `omitted` whose source is its kind, and the rest of the network is read. Connect the ports by a `DcimCable` to read the link |
| `omit.cable.ends` | info | The cable, by its label or else its id | The cable has other than two ends, every one listed (two listed of a `count` of three is `read.incomplete`), and a link has two. Left out, a fidelity row. Give the cable two ends |
| `omit.cable.endpoint` | info | The cable, by its label or else its id | An end of the cable is on no `InterfacePhysical` (an `InterfaceVirtual`, say), and a link ends on a physical port. Left out, a fidelity row. End the cable on physical ports |
| `omit.cable.outside_scope` | info | The cable, by its label or else its id | An end of the cable is on a device the scope does not hold, which is never read and is named by its id, or on no port the read holds. Left out, a fidelity row. Tag the far device to read the link |
| `omit.cable.management` | info | The cable, by its label or else its id | An end of the cable is on a management port, whose role is `management`, and blueprint 1 refuses a link on one. Left out, a fidelity row. Cable a port of another role |
| `artifact.missing` | error | The device's name (`n1`) | The device has no artifact whose definition's `artifact_name` is the reader document's `artifact` at the time read: none existed then, or it has another name; the message names the artifacts it has. Generate the device's configuration in Infrahub, or name in the document the artifact the installation uses |
| `artifact.ambiguous` | error | The device's name | The device has several artifacts of the document's name; the message gives each one's checksum, and the reader never chooses among them. Keep one |
| `artifact.unready` | error | The device's name | The device's artifact is not `Ready`, its status given verbatim (`Pending` while Infrahub generates it; an `Error` was not read), or it is `Ready` with no storage id or no checksum, so it holds no configuration rendered for the intent read, and no content is fetched for it; or, filed by the stale rule, its checksum has no stamp, so when it was generated is not known, whatever `generated_since` says. Regenerate it, and read again once it is `Ready` |
| `artifact.content.unavailable` | error | The device's name | Infrahub answered other than HTTP 200 for the artifact's stored content, `GET /api/storage/object/<storage_id>`, the status given. Read again; content still not served is a fault of Infrahub's storage, to report with the branch, the time and the storage id |
| `artifact.checksum.mismatch` | error | The device's name | The MD5 of the bytes Infrahub served is not the checksum the artifact lists, so they are not the configuration Infrahub describes; the message gives both digests and no byte. Regenerate the artifact, and report a mismatch that remains |
| `artifact.content.invalid` | error | The device's name | The content, its checksum's, is empty or is no UTF-8 text, so it is no configuration a blueprint can carry; the message names the first byte that is not, and quotes none. Correct the artifact's template |
| `artifact.stale` | error | The device's name (`n1`) | The device's intent was written later than its configuration was generated, so the configuration may not render the intent read: the latest write to the device, an interface of either kind, an address on an interface or a cable at one of its ports, by its stamp or by the branch's event log; to its platform or its manufacturer, by its `name` stamp, which is all of either the configuration renders, or by an event of its own (a device made on the platform moves the platform's node stamp and not its name's); or to the name of a cable's far port or far device, which is all of the far end counted, by its stamp or by its event naming `name` (an event names the device where its primary node is one of those, or where its related nodes name one of the device's own nodes, never its platform or manufacturer, which every device on them shares; and the events are the branch's own and, for a branch but `main`, `main`'s up to the branch's `branched_from`, which the branch was made holding), no later than the time read and Infrahub's task workers' own writes not counted, `__system__`'s always counted (told by the id Infrahub answers for it, `__system__` itself: [verified-facts.md](../../design/verified-facts.md), "Infrahub 1.11.11", "Which stamps each write moved"), is strictly later than its selected artifact's checksum stamp, or than the `generated_since` given where that is later ([mapping.md](mapping.md), "The stale rule"). The message gives both times, and the event where one is the latest write. Infrahub regenerates an artifact only when asked: regenerate it and read again; or, since a regeneration that stores the same bytes moves no checksum stamp, read with a `generated_since` at which a regeneration is known to have completed ([D-082](../../design/decisions.md#d-082)) |
| `probe.kind.absent` | error | The kind (`FylgjaProbe`) | The reader document asks for probes, and the branch's present schema has no kind `FylgjaProbe`, or the kind lacks one of the ten attributes the reader reads, each missing named; no probe is read, and the rest of the read is judged. Load the reader's `readers/infrahub/schema/fylgja-probe.yml` (`make infrahub-seed` loads it on the development Infrahub's `main`), or read with a document that asks for no probe |
| `omit.probe.outside_scope` | info | The probe's name (`n1-loop`) | An end of the probe names a device, by its name in Infrahub compared exactly, that is no device of the scope, so its host could be placed on no device of the blueprint. The probe is left out, a fidelity row `omitted` whose source is `FylgjaProbe`, and it is held to none of the declaration's rules, its addresses weighed against no other probe's. Name the device as Infrahub names it, or tag it to read the probe |
| `probes.invalid` | error | The probe's name, or its id where Infrahub answered its name null | A value of the probe breaks the declaration's schema ([`probes-1.schema.json`](../../formats/probes-1.schema.json)), blueprint 1's probe: an address with no prefix length, say, which a kind loaded from another file could hold, or an attribute Infrahub answered null (`format` reads optional, its default notwithstanding); the detail gives the member's pointer. A declaration refused gives no probe at all, so blueprint 1's own probe rules (`blueprint.probe.*`) are not filed for the others in the same pass, which the declaration's rules cover. Correct the probe in Infrahub, and load the kind from the reader's file, whose patterns are blueprint 1's |
| `probe.name.duplicate` | error | The probe's name | Two probes read hold one name, which the kind's uniqueness constraint keeps from happening where the kind is the reader's; each later one is filed. Rename one of them |
| `probe.gateway.outside` | error | The probe's name | An end's gateway is not within its address's prefix, so its host's route to the far host could not be added. Correct the gateway or the address |
| `probe.address.duplicate` | error | The probe's name, of the later host by name | Two hosts, of one probe or of two, hold one address, and a ping could not tell them apart; the later in the list sorted by name is filed. Give each host an address of its own |
