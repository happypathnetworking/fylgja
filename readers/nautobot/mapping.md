# The mapping of Nautobot's DCIM into a blueprint

The reader has one mapping, `nautobot-dcim`: Nautobot's own DCIM, whose version is Nautobot's, into a
blueprint 1 ([`blueprint-1.schema.json`](../../formats/blueprint-1.schema.json),
[D-118](../../design/decisions.md#d-118)). No mapping is declared as data: what Nautobot cannot
hold, the platform package of a pair of manufacturer and platform and the configuration context
that declares the probes, is the reader document's
([`nautobot-reader-1.schema.json`](../../formats/nautobot-reader-1.schema.json)). Each row below
is a member of the blueprint, where it comes from in Nautobot, and its rule; each rule id is a row
of [rules.md](rules.md). This table holds the members the mapping builds from the DCIM lists,
each device's `config`, the probes and the source envelope; the bracket, the groups and what is never read follow it.

A blueprint's id addresses its `network` and `probes` alone
([D-006](../../design/decisions.md#d-006)), so the mapping sorts every list by code point and orders
each link's ends itself, and the same rows read in any order, a cable's sides swapped among them,
give one document but for `observed_at`, and one id. Every list is held to the `count` Nautobot
answered for it before it is mapped (`read.incomplete`), and the platforms, the manufacturers and
the cables to the ids they were asked by, so a device's platform and a platform's manufacturer are
among those read. Ids are Nautobot's UUIDs, held as text. A scoped device with no interface is no
fault. The mapping names no branch: Nautobot has none, so no finding says where it was read.

| Member | In Nautobot | Rule |
|---|---|---|
| The scope | `tag:<name>`: every `dcim.device` listed by `?tags=<the tag's id>`, whatever its status | A scope of another form is `scope.invalid`, and nothing is sent; a tag Nautobot lists none of, or one no device carries, is `scope.empty` |
| `blueprint_version` | None | `"1"` |
| `network.devices` | Every scoped `dcim.device` | Sorted by `name`. A device that cannot be named, or has no package, is refused, and neither it nor a link it ends is built. A cable it ends is still judged for omission, so that every finding is filed in one pass ([Constitution III](../../design/constitution.md#iii-the-blueprint-is-the-contract)); one that would be a link is neither a link nor an omission, the device's refusal being the read's already |
| `name` (a device's) | `dcim.device`'s `name` | Lower-cased, each run of characters outside `[a-z0-9]` made one `-`, and `-` trimmed from both ends ([D-038](../../design/decisions.md#d-038)); a name so changed is `device.name.renamed` and a fidelity row naming both, whose source is `dcim.device.name`; no name, an empty name (Nautobot takes `""` as well as null), or a label that is empty or longer than 63 characters, is `device.name.unmappable`, a device with no name named `dcim.device <id>`; two devices of one label each `device.name.duplicate`. Links and probes name the device by its label |
| `platform` | `dcim.device`'s `platform`, a `dcim.platform`: its `name`, and its `manufacturer`'s `dcim.manufacturer` `name` | The reader document's `package` of the row whose `manufacturer` and `platform` are the pair, compared exactly, letter case and spacing included. No platform, or a platform with no manufacturer, is `platform.missing`; a pair in no row `platform.unmatched` |
| `interfaces` | Every `dcim.interface` whose `device` is the device, whatever its type, listed by `?device_id=` | Sorted by `name`: every interface whose `type` is not `virtual`, `bridge` or `lag` (`mapping.NOT_PORTS`), each a port. A virtual, bridge or LAG interface is the configuration's, and is left out with no finding |
| `name` (an interface's) | `dcim.interface`'s `name` | As Nautobot spells it |
| `mgmt_only` | `dcim.interface`'s `mgmt_only` | Nautobot's own, as it holds it: no fidelity row |
| `enabled` | `dcim.interface`'s `enabled` | Nautobot's own, as it holds it: no fidelity row |
| `network.links` | Each `dcim.cable` a scoped interface's `cable` names, whatever the cable's status, with its `terminations`, one member a connector of a side | Each cable judged once. It is omitted for the first of four reasons that applies, in this order, an `info` finding and a fidelity row `omitted` whose source is `dcim.cable`, named by its label or else `cable <id>`: a side of other than one termination (`omit.cable.ends`); an end that is no `dcim.interface`, a `dcim.frontport` say (`omit.cable.endpoint`); an end on no interface read of a scoped device, or on a virtual, bridge or LAG interface (`omit.cable.outside_scope`); an end `mgmt_only`, which blueprint 1 refuses a link on (`omit.cable.management`). Else it is a link, a cable with both ends on one device among them, where both its devices are in `network.devices`: a cable a refused device ends is judged for omission as any other, and only its link is held back. Sorted by `(a.device, a.interface, b.device, b.interface)`. A connector cabled to nothing, which a breakout cable leaves null in `terminations`, is no end: the cable is judged by the ends it has, so one interface a side is a link |
| `a`, `b` | The cable's two sides, one end each | The two ends as `(device, interface)`, sorted, whichever side Nautobot calls A: `a` the first |
| `device`, `interface` (an end's) | The termination's `dcim.interface`: its device's `name` and its own `name` | The device's label, and the interface's name |
| `probes` | The `data` of the `extras.configcontext` the reader document's `probes` names, listed by `?name=` inside the bracket, after the groups and before the renders, held to its `count`; a probe declaration ([`probes-1.schema.json`](../../formats/probes-1.schema.json)). Nothing is asked where the document names none, and the list is then `[]`. Nautobot has no kind for a probe, so the context is inactive, which no device's configuration context takes, and is still listed by its name ([verified-facts.md](../../design/verified-facts.md), "Nautobot 3.2.8 with Golden Config 3.0.8") | None listed is `probe.context.absent`, and one active `probe.context.active`. A probe an end of which names no scoped device, by its name in Nautobot compared exactly, is omitted (`omit.probe.outside_scope`), an `info` finding and a fidelity row `omitted` whose source is `extras.configcontext`, named by the probe's name. The rest, each end's `device` made that device's label, are held by the core's declaration loader (`fylgja_core.probes.validate`) to the declaration's schema and rules, with the formats they name, since whether a probe package runs a format is the compiler's to say: each problem is an error under the loader's rule, and then no probe is given. Data that is no mapping with a list `probes` of mappings, or states another `probes_version`, is given to the loader as it is. Sorted by `name`; each probe otherwise as the data holds it |
| `name`, `format`, `endpoints` (a probe's) | The members of one probe of the context's `data`, as the declaration holds them | As the data holds them, but each end's `device`, which names a device by its name in Nautobot and is made that device's blueprint name, its label; held, with the rest of the declaration, by the core's declaration loader |
| `config` (a device's) | Golden Config's render of the device at the read: one `GET` of `generate-intended-config` by `device_id` alone, never with Golden Config's `branch`, under the setting that applies to the device, its template repository and its query | The answer's `intended_config`, verbatim, its last newline as Golden Config answered it, and nothing else of the answer. Every scoped device is rendered once, in name order then id, a device with no name last and a device the mapping refused among them, so every fault of every device is filed in one pass. A device in no setting's group is `render.setting.absent`; a template the repository lacks `render.template.missing`; a template that raises `render.failed`; a render of whitespace alone `render.empty`; a 200 with no text `intended_config` `render.invalid`; a device Golden Config cannot find `render.device.unknown`; any other answer `render.unavailable`. Each is an error naming the device, its message holding no byte of a configuration, and nothing is defaulted. The render sees what the reader's account sees: Golden Config runs the setting's query under the account's grants, and answered 200 without what the account could not view ([verified-facts.md](../../design/verified-facts.md)), which the reader cannot check |
| `source.source` | None | `"nautobot"` |
| `source.scope` | The scope as given | `tag:<name>`, as given |
| `source.mapping` | `/api/status/`'s `nautobot-version` | `{"reader": "nautobot-dcim", "model": "nautobot", "version": <Nautobot's version>}` |
| `source.changelog` | The bracket's open: the changelog's newest row, `?limit=1` of `extras.objectchange` | `{"id", "time"}` of that row as Nautobot answered them, or null where the changelog held none |
| `source.templates` | The bracket's open: each template repository a Golden Config setting names, by its id | `{<repository name>: <current_head>}`, the commit Nautobot held for each at the open (empty for a repository never synced is a derivation: only a repository just made was read answering `""`); `{}` where no setting names one |
| `source.observed_at` | None: the reader's clock, before the first request | UTC, `%Y-%m-%dT%H:%M:%S.%fZ`; it pins nothing |
| `source.fidelity` | None | Rows `{"disposition", "object", "source", "reason"}`, sorted by those four in that order: on every read `platform.version` omitted, whose source is `dcim.platform`, Nautobot's platform carrying none; and one for each device renamed, each cable omitted and each probe omitted |

The envelope travels unhashed: a blueprint's id addresses its network and probes alone
([D-006](../../design/decisions.md#d-006)), so the same state read twice is one id whatever its
`observed_at`, and the changelog's row and the heads tell whoever reads a twin's provenance which
state of Nautobot, and which commit of the templates, it was read from
([Constitution VI](../../design/constitution.md#vi-intent-is-addressed)).

**The bracket** keeps a read to one state, as far as Nautobot's changelog and the template
repositories show it ([D-118](../../design/decisions.md#d-118)). The changelog's rows are keyed by
UUIDs, so no id orders them; Nautobot lists them newest first, and one `?limit=1` of
`extras.objectchange` answers the newest row and the total count. At its open, before anything
else is listed, the read takes both; inside the bracket it lists Golden Config's settings
(`nautobot_golden_config.goldenconfigsetting`) whole, and the template repositories they name, each
setting's `jinja_repository`, by their ids (`extras.gitrepository`), and takes each one's
`current_head`. Each list is held to its `count` and the repositories to the ids asked
(`read.incomplete`). At its close, after its last render, it takes the newest row and the count
again and lists the open's repositories again by their ids. It refuses the read (`read.moved`,
object `extras.objectchange`) where the newest row is another than the open's, by its id: a newer
row, or another of the same time; where the changelog held no row at the open and holds one now;
or where the count differs. The count guards a row of an earlier time seen late: a bulk edit of
120 interfaces in one request wrote 120 rows over about 35 s, none visible to a list of the
changelog until its transaction committed, when all 120 became visible at once, each with the time
it was written, and the edit itself with them, never before
([verified-facts.md](../../design/verified-facts.md), "Nautobot 3.2.8 with Golden Config 3.0.8").
It refuses the read too (`read.moved`, object the repository's name) where a repository's
`current_head` moved, or the repository is no longer listed. Every kind of row counts, since
nothing of Fylgja's writes to Nautobot: a render that fetches a head pushed since the last render
saves it, and writes a row of `extras.gitrepository` under the rendering account, so a read during
which a push is first fetched is refused once, and the next read finds the head already fetched.
A render with nothing to fetch writes nothing. Each finding gives both values, and the remedy:
read again; the reader does not read again by itself. The close is taken on every path past a
successful open ([D-098](../../design/decisions.md#d-098)): a read refused by `scope.empty` or
`read.incomplete` carries the close's findings beside its own. A list Nautobot answers 400 after
the open, as it does a list by an id no object has, is weighed there: where the close moved, the
read is refused by the close's findings alone; where the close cannot tell, its repositories not
listed whole, by its `read.incomplete`, carrying the 400's words; where nothing moved, the 400 is
raised. A render's `render.device.unknown`, and its `render.unavailable` of a 400, are weighed the
same way: where the close moved, the read is `read.moved` and the render files nothing; else the
render's error stands. **What the bracket does not see**: a row pruned from the changelog while
another becomes visible late, which cancel in the count; and a refresh of a dynamic group's stored
members by the job `RefreshDynamicGroupCaches`, which writes no row
([verified-facts.md](../../design/verified-facts.md)). A save of the group writes one, an update of
`extras.dynamicgroup`, and is seen. The read holds the stored members to the group's filter when
it lists them (the groups, below), so a membership stale then refuses the read; a refresh by the
job after that list and before the renders is not seen, and brings the stored members to the
filter, so the renders are of the membership the filter gives.

**The groups**, as read ([D-118](../../design/decisions.md#d-118);
[verified-facts.md](../../design/verified-facts.md), "Nautobot 3.2.8 with Golden Config 3.0.8",
"A group's stored members"). A Golden Config setting applies to the devices of its dynamic group,
and the group's members are stored: they are recomputed when the group is saved, or by
`RefreshDynamicGroupCaches`, and Golden Config renders a device under the setting its stored
membership gives, with no error. The reading had two outcomes
fixed before it: where the stored members are listed whole with a count and the filter can be
listed as devices to what a save stores, the two are held to each other; where not, stored
membership is the reader's known limit. It showed the first: a group's stored members are listed
by `extras/static-group-associations/` by `?dynamic_group=`, whole, with a count, and restricted by
`?associated_object_id=`; and the device list asked with a `dynamic-filter` group's filter as its
query answered what a save of the filter stored, for each filter read (a tag, a name of two
values, a related object's name, two keys together, booleans, a number, text where a list was, an
empty list, no key, a lookup and its negation). So, inside the bracket, after the cables and before
the renders, the read lists the groups of the settings the open listed, each once, by their ids
(`extras.dynamicgroup`), held to the ids asked; and for each group, in name order then id, its
stored members (`extras.staticgroupassociation`) and the devices its filter lists (`dcim.device`,
the filter's parameters beside `?id=`), each restricted to the scoped devices, batched as any list
by ids is, and held whole (`read.incomplete`). A scoped device in one and not the other is
`group.stale`, an error naming the group and the devices; a device outside the scope is not
judged. Its remedy, saving the group or running `RefreshDynamicGroupCaches`, is a change the
bracket does not see when it is the job's, so the message says to read again after it. A group of
another `group_type` than `dynamic-filter`, whose members are not its filter's, or whose filter
holds what cannot be sent as a query (a null, an object, a list within a list, or the key `id`, by
which the read restricts the list), is `group.unchecked`, a warning naming it, and nothing is
listed for it. The filter is sent as Nautobot holds it: each key's value, a list once a member,
text as it stands, a number as written and a boolean as `true` or `false`; an empty list sends
nothing. A filter Nautobot no longer takes, one naming a tag since deleted, which the group still
holds with its stored members, is answered 400 by the device list: it is weighed at the close as
any list's 400 is, and raised where nothing moved. The reader's account holds `view` on
`extras.staticgroupassociation` for the stored members' list.

**What is never read**: addresses, which are the template's to render and have no member in
blueprint 1; virtual machines; modules; virtual chassis; a path through a patch panel, whose cable
ends on a front port and is omitted; a platform's version, which Nautobot does not carry; a
device's status, its role, its location and its other attributes; an interface's other
attributes; and a cable's attributes but its `label`, which names it in a finding, its status
among them.
