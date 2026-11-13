# The mapping of NetBox's DCIM into a blueprint

The reader has one mapping, `netbox-dcim`: NetBox's own DCIM, whose version is NetBox's, into a
blueprint 1 ([`blueprint-1.schema.json`](../../formats/blueprint-1.schema.json),
[D-095](../../design/decisions.md#d-095)). No mapping is declared as data: what NetBox cannot
hold, the platform package of a pair of manufacturer and platform and the configuration context
that declares the probes, is the reader document's
([`netbox-reader-1.schema.json`](../../formats/netbox-reader-1.schema.json)). Each row below is a
member of the blueprint, where it comes from in NetBox, and its rule; each rule id is a row of
[rules.md](rules.md).

A blueprint's id addresses its `network` and `probes` alone
([D-006](../../design/decisions.md#d-006)), so the mapping sorts every list by code point and orders
each link's ends itself, and the same rows read in any order, a cable's sides swapped among them,
give one document but for `observed_at`, and one id. Every list is held to the `count` NetBox
answered for it before it is mapped (`read.incomplete`), and the platforms and the cables to the
ids they were asked by, so a device's platform is among the platforms read. A scoped device with no
interface is no fault.

| Member | In NetBox | Rule |
|---|---|---|
| The scope | `tag:<name>`: every `dcim.device` that carries the `extras.tag` of that name, whatever its status | A scope of another form is `scope.invalid`, and nothing is sent; a tag NetBox lists none of, or one no device carries, is `scope.empty` |
| `blueprint_version` | None | `"1"` |
| `network.devices` | Every scoped `dcim.device` | Sorted by `name`. A device that cannot be named, or has no package, is refused, and neither it nor a link it ends is built. A cable it ends is still judged for omission, so that every finding is filed in one pass ([Constitution III](../../design/constitution.md#iii-the-blueprint-is-the-contract)); one that would be a link is neither a link nor an omission, the device's refusal being the read's already. The reader never writes an unmanaged device: each has a `config`, or the read is refused |
| `name` (a device's) | `dcim.device`'s `name` | Lower-cased, each run of characters outside `[a-z0-9]` made one `-`, and `-` trimmed from both ends ([D-038](../../design/decisions.md#d-038)); a name so changed is `device.name.renamed` and a fidelity row naming both, whose source is `dcim.device.name`; no name, or a label that is empty or longer than 63 characters, is `device.name.unmappable`, a device with no name named `dcim.device <id>`; two devices of one label each `device.name.duplicate`. Links and probes name the device by its label |
| `platform` | `dcim.device`'s `platform`, a `dcim.platform`: its `name`, and its `manufacturer`'s `name` | The reader document's `package` of the row whose `manufacturer` and `platform` are the pair, compared exactly, letter case and spacing included. No platform, or a platform with no manufacturer, is `platform.missing`; a pair in no row `platform.unmatched` |
| `interfaces` | Every `dcim.interface` whose `device` is the device, whatever its type | Sorted by `name`: every interface whose `type` is not `virtual`, `bridge` or `lag` (`mapping.NOT_PORTS`), each a port. A virtual, bridge or LAG interface is the configuration's, and is left out with no finding |
| `name` (an interface's) | `dcim.interface`'s `name` | As NetBox spells it |
| `mgmt_only` | `dcim.interface`'s `mgmt_only` | NetBox's own, as it holds it: no fidelity row |
| `enabled` | `dcim.interface`'s `enabled` | NetBox's own, as it holds it: no fidelity row |
| `config` | What `render-config` answers for the device, `POST` under the branch's header with `Accept: text/plain` and no body, one request a device; NetBox stores no configuration, so it renders the device's template at the read ([verified-facts.md](../../design/verified-facts.md), "A device's configuration, rendered") | Judged for every scoped device, one the mapping refused by its platform or its name among them, in name order then id, so that every fault of every device is filed at once. 200 is the configuration, the text verbatim, its last byte the template's and a trailing newline kept, where NetBox calls it `text/plain` and it is UTF-8 text holding a character other than whitespace: none but whitespace is `render.empty`, and another content type, or bytes that are no UTF-8 text, `render.invalid`. 400 in NetBox's words for a device with no template is `render.template.missing`, and 500, a template that fails, `render.failed`, NetBox's words quoted; another 400, which NetBox answered a render under the header of a branch deleted, is `read.moved` where the bracket's close finds the read moved, and `render.unavailable`, its words quoted, where it does not; any other status is `render.unavailable`, 404 among them, which NetBox answers where the token's account lacks `view` or `render_config` on `dcim.device`; 401 and 403 are the transport's refused token. Nothing is defaulted, and a render's bytes are in no finding |
| `network.links` | Each `dcim.cable` a scoped interface's `cable` names, whatever the cable's status, with its `a_terminations` and `b_terminations` | Each cable judged once. It is omitted for the first of four reasons that applies, in this order, an `info` finding and a fidelity row `omitted` whose source is `dcim.cable`, named by its label or else `cable <id>`: a side of other than one termination (`omit.cable.ends`); an end that is no `dcim.interface`, a `dcim.frontport` say (`omit.cable.endpoint`); an end on no interface read of a scoped device, or on a virtual, bridge or LAG interface (`omit.cable.outside_scope`); an end `mgmt_only`, which blueprint 1 refuses a link on (`omit.cable.management`). Else it is a link, a cable with both ends on one device among them, where both its devices are in `network.devices`: a cable a refused device ends is judged for omission as any other, and only its link is held back. Sorted by `(a.device, a.interface, b.device, b.interface)` |
| `a`, `b` | The cable's two terminations, one a side | The two ends as `(device, interface)`, sorted, whichever side NetBox calls A: `a` the first |
| `device`, `interface` (an end's) | The termination's `dcim.interface`: its device's `name` and its own `name` | The device's label, and the interface's name |
| `probes` | The `data` of the `extras.configcontext` the reader document's `probes` names, listed by `?name=` under the branch's header inside the bracket, after the cables and before the renders, held to its `count`; a probe declaration ([`probes-1.schema.json`](../../formats/probes-1.schema.json)). Nothing is asked where the document names none, and the list is then `[]`. NetBox has no kind for a probe, so the context is inactive, which no device's rendered context takes, and is still listed by its name ([verified-facts.md](../../design/verified-facts.md), "NetBox 4.7.5 with netbox-branching 1.2.3") | None listed is `probe.context.absent`, and one active `probe.context.active`. A probe an end of which names no scoped device, by its name in NetBox compared exactly, is omitted (`omit.probe.outside_scope`), an `info` finding and a fidelity row `omitted` whose source is `extras.configcontext`, named by the probe's name. The rest, each end's `device` made that device's label, are held by the core's declaration loader (`fylgja_core.probes.validate`) to the declaration's schema and rules, with the formats they name, since whether a probe package runs a format is the compiler's to say: each problem is an error under the loader's rule, and then no probe is given. Data that is no mapping with a list `probes` of mappings, or states another `probes_version`, is given to the loader as it is. Sorted by `name`; each probe otherwise as the data holds it |
| `name`, `format`, `endpoints` (a probe's) | The members of one probe of the context's `data`, as the declaration holds them | As the data holds them, but each end's `device`, which names a device by its name in NetBox and is made that device's blueprint name, its label; held, with the rest of the declaration, by the core's declaration loader |
| `source` | The source envelope, which the core never reads or hashes | Exactly the seven members below, none hashed |
| `source.source` | None | `"netbox"` |
| `source.branch` | The branch read, by its name | As given, or null for `main` |
| `source.scope` | The scope | As given |
| `source.mapping` | `/api/status/`'s `netbox-version` | `{"reader": "netbox-dcim", "model": "netbox", "version": <NetBox's version>}` |
| `source.changelog` | The latest id of the changelog read from, `main`'s or the branch's | The id taken at the read's close, or null where the changelog holds none. Of a branch it is not the whole point in time: a sync changes what the branch reads and moves neither changelog, and the envelope does not carry the branch's `last_sync`, so two reads of one branch either side of a sync can carry one id for two states |
| `source.observed_at` | None: the reader's clock | UTC, `%Y-%m-%dT%H:%M:%S.%fZ`, taken before the first request; it pins nothing |
| `source.fidelity` | None | Rows `{"disposition", "object", "source", "reason"}`, sorted by those four in that order: on every read `platform.version` omitted, whose source is `dcim.platform`, NetBox's platform carrying none; and one for each device renamed, each cable omitted and each probe omitted |

**The bracket** keeps a read to one state, as far as the changelog read from shows it
([D-095](../../design/decisions.md#d-095)). NetBox reads no earlier time, so the read takes the
latest id of the changelog it reads from, `main`'s or the branch's, at its open, before its first
list, and again at its close, after its last render, and refuses a read between whose two ids the
changelog holds a row of a kind a read reads (`read.moved`): this guards an edit made during the
read. It also counts the rows at or below the open's id at the open and again at the close, and
refuses a read whose count moved: this guards a row of a lower id that commits after the open,
which moves no latest id. That count is of the rows below a fixed id; the changelog's ids are not
dense, so no count of the whole changelog is compared. A row pruned at or below the open's id
during the read takes one from that count as a late row adds one, so the two cancel and that pair
is not seen; nothing was read of NetBox's retention of its changelog. A journal entry's row,
`extras.journalentry`, and the branch object's own, `netbox_branching.branch`, refuse nothing
where they are above the open's id: the example writes both while a branch is rehearsed, and each
lands on `main`'s changelog alone. One committed late below the open's id refuses the read
whatever its kind, the count telling no kinds. So **a template that renders a device's own journal
entries is not guarded for them**: an entry written between two renders gives a configuration the
bracket does not refuse. A sync of a branch changes what it reads and adds no row to either changelog, so a
branch is read again at the close, and one no longer `ready`, or synced, its `last_sync` moved, is
`read.moved` too. The id taken at the close is `source.changelog`. What lives on `main` alone and is
not branched, the reader account's permissions among them, is not guarded by a branch's bracket,
which reads the branch's changelog and not `main`'s. Nor is a `view` grant of the reader's account
that carries constraints: by NetBox's design of its permissions, as its documentation describes
them and not as a reading shows them, a list is of the objects the account may view and its
`count` of that list, so a constrained grant shortens a list and its `count` alike, every check
the read makes holds, and the blueprint is of less than NetBox holds. Each `view` grant must carry
none ([README.md](README.md#what-it-sends-and-what-its-token-must-be-allowed)).

**What is never read**: virtual machines; modules; virtual device contexts; a path through a patch
panel, whose cable ends on a front port and is omitted; wireless links; addresses, which are the
template's to render; a platform's version, which NetBox does not carry; a device's status, its role,
its site and its other attributes; an interface's other attributes; and a cable's attributes but
its `label`, which names it in a finding, its status among them.
