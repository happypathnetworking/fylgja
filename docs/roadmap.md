# Fylgja — Roadmap

What comes next, and the order of the work after it. Each feature is one spec or more, a
`specs/NNN-slug/` directory taken through the Spec Kit workflow, sized so that each spec
has one contract boundary and one kind of infrastructure in its tests. What `v0.1.0`
built, M1 to M14, is recorded in [its archive](archive/v0.1-built.md), and what `v0.2.0`
built, Release 0.2, in [its own](archive/v0.2-built.md). The architecture
is in
[architecture.md](architecture.md), and every decision the features rely on is in the
[decision log](decisions.md).

An estimate here is made before any research and is re-based when the feature gets a spec,
so the totals are a shape, not a commitment. A feature keeps the number the order was set
with; one added later takes the next free number and sits where the order puts it, and one
removed or folded into another leaves its number unused. A feature's id is `F-NNN`, written
as the decision log writes `D-NNN`, and each has an anchor here (`roadmap.md#f-011`). It is
not the number of the feature's spec directory, which Spec Kit assigns when the feature is
specified: `F-014`, probes, is specified as `016-probes`.

## Release 0.2

**Released as `v0.2.0`: a proposed change rehearsed on a twin before it merges.** Set with the
operator on 2026-10-16, for an audience outside the project, OpsMill first, who see it
in the README, a recording and the write-up. An engineer opens a proposed change in
Infrahub, and two checks from this repository report on it. `fylgja-step` answers in
seconds with the step from `main` to the source branch, stage by stage. `fylgja-twin`
answers in minutes. It boots a twin at the first stage it can build, the branch point
where `main` carries a network, steps it through the stages the operator marked on the
proposed change to the branch's head, verifies after every step, and tears it down. A
thread on the proposed change carries the report in markdown, and a stage that fails
blocks the merge. Nothing OpsMill publishes boots a twin per proposed change; their
containerlab demos deploy by hand, after the merge. On 2026-10-21 the operator moved
probes ([F-014](#f-014)) and the agent skill ([F-012](#f-012)) to
[Release 0.3](#release-03), so that 0.2 is ready to show sooner: the rehearsal
demonstrates without a loss column or an agent explaining its report, and the DCIM
([F-011](#f-011)) stays in 0.3 with its contract.

It built [F-023](archive/v0.2-built.md#f-023) as `014-proposed-change-stages`, then
[F-007](archive/v0.2-built.md#f-007) and [F-008](archive/v0.2-built.md#f-008) as
`015-proposed-change-rehearsal`, under [D-045](decisions.md#d-045) to
[D-053](decisions.md#d-053); and, for the release, the report made legible in Infrahub's
view, the recording and screenshots of a rehearsed proposed change on a baseline written
to `main` for a window ([D-054](decisions.md#d-054)), the write-up updated and the upstream
request for named points in time drafted. [The archive](archive/v0.2-built.md) records
each, as [v0.1's](archive/v0.1-built.md) does M1 to M14.

## Release 0.3

Not yet set with the operator. It opens with [F-011](#f-011), the schema library's DCIM
implementing the generics under contract 0.3, then [F-022](#f-022), the sync into it,
because a contract bump defines a release: 0.2 moves the twin record, the API and the CLI
for stages while the contract stays 0.2, and 0.3 moves the contract once, with nothing
added to the generics in between. It also takes two features moved from 0.2 on
2026-10-21: [F-014](#f-014), probes, as `016-probes`, whose
[brief](../specs/016-probes/brief.md) was written against 015 and is re-read against
0.2's close before it is specified; and [F-012](#f-012), the skill
`fylgja-rehearsing-changes`, as a chore. Their places in 0.3's order are set with the
rest. What contract 0.3 changes is listed under [Decisions the
order needs](#decisions-the-order-needs). The rest of the order below is untouched until
0.3 is set. It also takes one defect from 015, with no spec: a client following a rehearsal
that is terminated outside Fylgja answers only once its abandoned children close, which with
no worker is never (`specs/015-proposed-change-rehearsal/research.md` §5.2), and a
`fylgja-twin` check following one waits out its timeout.

## Backlog

The Infrahub-facing features come first, then observing, then object storage and remote
hosts, a third platform, Ixia-c and a WebUI. [Release 0.2](#release-02) built
[F-023](archive/v0.2-built.md#f-023), [F-007](archive/v0.2-built.md#f-007) and
[F-008](archive/v0.2-built.md#f-008) out of this order first ([the
archive](archive/v0.2-built.md)), and [Release 0.3](#release-03) opens with [F-011](#f-011) and [F-022](#f-022) and takes
[F-014](#f-014) and [F-012](#f-012); the rest keep it. Read-only production data stays
[parked](decisions.md#parked). The features keep the numbers the order was set with; the
first six are built ([the archive](archive/v0.1-built.md)), F-009 is removed and
[F-010](#f-010) is folded into [F-011](#f-011).

None of the features below has a spec or a decision entry, and only
[F-011](#f-011) has a probe behind its estimate. [F-011](#f-011),
[F-013](#f-013), [F-014](#f-014), [F-015](#f-015), [F-017](#f-017) to [F-021](#f-021) and
[F-022](#f-022) are each one spec, with one contract boundary and one new kind of
infrastructure.
[F-012](#f-012) and [F-016](#f-016) are chores or records, with no spec.

| # | Feature | What it bundles | Needs | Hours | Why here |
|---|---|---|---|---|---|
| F-010 | *Generic transform*, folded into [F-011](#f-011) | the shipped template already queries `FylgjaDevice`, so a DCIM device renders through it; what was left, the template documented as a reference transform, is a paragraph in [F-011](#f-011)'s README | — | — | Overtaken: Infrahub renders from the generics already. |
| F-011 | **Second schema: the schema library's DCIM** | contract 0.3; OpsMill's DCIM schema implementing the generics; a DCIM-modelled twin; the template documented as a reference transform | nothing new | 4–6 | The strongest OpsMill signal, and the first test of Constitution III. Probed live on 2026-10-16. Opens 0.3. |
| F-022 | **`infrahub-sync` into the DCIM** | a sync mapping from NetBox onto [F-011](#f-011)'s schema; a twin of a NetBox-sourced network | [F-011](#f-011), a NetBox instance | 3–5 | The source of truth stays where branching lives; the sync writes, not Fylgja. |
| F-012 | **Agent surface** | `fylgja-rehearsing-changes`, a skill in OpsMill's format over the CLI's JSON, with a findings catalogue generated from the code; an MCP server deferred | verify, the API, the rehearsal | 2–5 | Cheap once there is something to ask, and the demo's second act. |
| F-013 | **Observation** | markers with bundle id and stage; a `gnmic` targets export; a documented collector and Grafana dashboard; a per-capability definition of settled | stepping, the API | 4–6 | Convergence across a step becomes a graph. |
| F-014 | **Probes** | a Fylgja-owned probe kind; synthesized ping and iperf3 hosts; loss across a step; a probe package format | stepping, verify | 5–7 | The headline demo: loss during a change on a running twin. |
| F-015 | **Operational state diff** | adjacencies and routes snapshotted at each stage's pause and diffed; posted on the proposed change | stepping, verify, the rehearsal | 4–6 | Builds on verify's readers and its observed facts. |
| F-016 | **Upgrade rehearsal** | the same intent on another NOS version through the package override, then verified | verify, a second image version | 2–4 | Cheap and operationally compelling. |
| F-017 | **Object storage and Temporal cluster** | as below | nothing new | 6–10 | Needed either way before [F-018](#f-018). |
| F-018 | **Remote hosts** | as below; parallel twins for A/B of two changes | [F-017](#f-017), lab hosts or a cluster | 12–20 | Gated, so it waits. |
| F-019 | **Third platform, Cisco IOL** | the parked platform order's next vendor, as data | the IOL image | 5–14 | Independent of everything. Filler whenever a gated feature blocks. |
| F-020 | **Ixia-c** | the OTG probe mechanism; flows, rates, loss and latency | [F-014](#f-014) | 8–12 | After ping probes have proven the kind and the manifest. |
| F-021 | **WebUI** | Go templates and htmx from the same binary, or a decision amending Constitution I | verify, the API, [F-013](#f-013) | 6–10 | Last, so it has verify, steps and observation to show. |

| Phase | Features | Hours |
|---|---|---|
| Infrahub-facing | F-011, F-022, F-012 | 9–16 |
| Observing | F-013–F-016 | 15–23 |
| Scale and surface | F-017–F-021 | 37–66 |
| **All** | | **61–105** |

### The features

<a id="f-010"></a>
**F-010. The generic transform, folded into [F-011](#f-011).** It was to be a transform
written against the generics rather than the reference schema's kinds, so that any
implementing schema renders a baseline artifact. The shipped query `device_config` already
names `FylgjaDevice`, never a reference kind, so a DCIM-modelled device renders through
the shipped template today, and a baseline for a platform the template has no branch for
would serve nobody, since Fylgja refuses a platform without a support package before any
artifact is read. What was left, the template documented as a reference transform that a
DCIM user replaces with one reading the library's own fields, is a paragraph in feature
11's README. [D-009](decisions.md#d-009) holds: Infrahub renders.

<a id="f-011"></a>
**F-011. The second schema: the schema library's DCIM implements the generics, under
contract 0.3.** Only the reference schema has ever implemented the contract, so
Constitution III's "demand the least possible" is untested until a second one does. The
second is OpsMill's own:
[the schema library's](https://github.com/opsmill/schema-library) `base/dcim.yml`, with
its IPAM, location and organization bases. Probed on 2026-10-16 against
Infrahub 1.11.2 with validation-only schema checks ([Verified facts](verified-facts.md)):
the four base files load beside Fylgja's generics untouched, and the DCIM kinds inherit
them only after the DCIM side is adapted, because Infrahub's generics are nominal. A
same-named attribute or relationship inherited from two generics must match in every
normalized property, and the refusals came one at a time: `role` is Text in Fylgja and a
Dropdown in DCIM; `platform` differs in peer, identifier and `min_count`; `interfaces` in
`on_delete`. Two Parent relationships are refused even when identical, and `DcimInterface`
and `FylgjaInterface` both make `device` one. The adaptation that passed copies Fylgja's
`platform` and `interfaces` onto `DcimGenericDevice`, drops `DcimDevice`'s `role` and
`DcimInterface`'s `device`, with the per-device interface id and uniqueness that referenced
it, and adds a `DcimCable` inheriting `DcimConnector` and `FylgjaLink`. That is a fork of
the library's generics with double bookkeeping, `vendor` beside `manufacturer`, `enabled`
beside `status`, `endpoints` beside `connected_endpoints`, so the spec moves Fylgja's side
instead: contract 0.3 drops `role` and `site`, unused inputs and the operationally loaded
name Constitution III says not to claim; drops the interface's `device`, since the device
read nests its interfaces and the link read can take membership from the `link` field it
already selects; and makes `platform` optional, refused at compile time with a finding.
The CTM carries neither `role` nor `site`, so no golden moves; the fixture id does, as it
does per install. First research: whether Fylgja's relationships may ride the library's
identifiers under Fylgja's own names, since Infrahub matches edges by identifier. If they
may, the library stays as published; if not, the remaining adaptation is the library's
peers and the Parent, and the spec says so. The schema README gains the paragraph feature
10 left: the shipped template as a reference transform, and why a DCIM user writes their
own against the library's fields. Exit: a DCIM-modelled twin, the conformance suite's pure
half over the DCIM, a tier 3 case. Needs nothing new.

<a id="f-022"></a>
**F-022. `infrahub-sync` from NetBox into the DCIM.** [D-001](decisions.md#d-001) rejected
NetBox and Nautobot as the source of truth because they lack branching. It did not reject
them upstream. A one-way sync into Infrahub keeps the source of truth where branching
lives, and the sync writes, not Fylgja, so no decision changes. OpsMill ships
`infrahub-sync` with a config-driven mapping, so a sync inside Fylgja would duplicate
their product and add a runtime (Constitution I); its NetBox mapping lands in roughly the
library's shape, which is why [F-011](#f-011) targets it. The mapping looks tractable:
NetBox's interface carries `mgmt_only`, its interface types sort into physical and
loopback, and a cable with two terminations is a link. A multi-termination cable, a LAG
and a platform without a vendor and NOS are the refusals to expect, each a finding the
schema will word. Following works as it does now: the sync writes to a branch on a
schedule, and the twin follows that branch, so the latency is the sync cadence plus the
check interval. Needs a NetBox instance with demo data.

<a id="f-012"></a>
**F-012. The agent surface: `fylgja-rehearsing-changes`.** OpsMill ships Claude skills and
an MCP server for Infrahub, and their skills are interpretation over a tool's output:
`infrahub-analyzing-data` reads their MCP server and answers in prose, under TRIGGER and
DO NOT TRIGGER lines, in a forked context with `allowed-tools` of Bash and Read. Fylgja's
skill takes the same form over the JSON every command already prints with `--json`, so an
agent needs `FYLGJA_API_TOKEN` alone and the credentials stay in the server's and the
worker's environment as they do now. What an agent cannot do today is say what a findings
report means, so that is the skill's substance:

- **What it does.** Given a branch or a proposed change, it runs `stage plan`, then the
  rehearsal ([F-008](archive/v0.2-built.md#f-008)) or `twin create`, `step` and `verify` by hand, and gives a
  plain account of each stage: what changed, whether the twin converged, which assertion
  failed on which node, and the likely cause and remedy. It also answers the operating
  questions along the way: `twin show`, why the host refused, what an orphan is.
- **The catalogue.** A reference file lists every findings rule with its meaning and its
  remedy, so `stage.artifact.stale` reads "the stage was marked before its regenerate;
  regenerate, then re-mark" and a replace push's refusal names the line the NOS rejected.
  It is generated from `internal/findings`, and a tier 1 test fails when the file omits a
  rule, so the skill cannot drift from the code, which is the failure OpsMill's own skills
  warn about.
- **Advisory, as Fylgja is.** The skill reads and explains; it steps only when asked,
  destroys nothing unasked, and never composes an `at`, the act stages exist to remove. It
  repeats Constitution X in its own prose: convergence on a twin compares one change with
  another and predicts nothing absolute. Its rules forbid echoing the token, as this
  repository's do.
- **Where it points instead of acting.** Marking a stage is the operator writing to
  Infrahub by its own means, which OpsMill's `infrahub-managing-objects` skill covers; the
  skill gives the regenerate-first rule and the object file's shape, no more.

In a release's recording it is the demo's second act (0.3's, since it moved from 0.2 on
2026-10-21): the check posts its report on the
proposed change, and an agent explains the report in the thread. **Deferred**: the MCP
server, a client of the API, until a consumer that cannot run a binary appears, since
OpsMill's Infrahub MCP server already lets an agent holding both skills correlate
Infrahub's data with the twin's state; and a second skill,
`fylgja-authoring-platform-packages`, which belongs with [F-019](#f-019), where a third
vendor tests the claim that a package is data. Size: a few hours for the skill, plus the
generator and its test.

<a id="f-013"></a>
**F-013. Observation.** Stepping keeps a pause and recorded timings at each stage and
leaves telemetry out on purpose. The seeds exist: the package's `state` facet names the
transport and OpenConfig coverage, the conformance facet names the paths, and
[D-037](decisions.md#d-037)'s observed facts are the normalized vocabulary. Fylgja never
becomes a telemetry pipeline. It emits markers through the API, twin ready and step
applied, each with the bundle id, stage and timestamp, and it exports the twin's
targets, each node's management address, gNMI port, TLS and encoding, as a `gnmic` targets
file or Prometheus file discovery. A collector such as `gnmic` subscribes and exports to
Prometheus or InfluxDB, and Grafana computes convergence between the step marker and the
state settling. What "settled" means is defined per capability, for example route-table
counts unchanged for some seconds, or every BGP session established, and that is the
feature's research. The honesty constraint is already written: [architecture
§6](architecture.md#6-known-limitations) and each package's fidelity say convergence
timing differs in containers, so these measurements compare change A with change B on the
same twin and predict nothing absolute, and every surface that reports one says so
(Constitution X). [F-008](archive/v0.2-built.md#f-008) can then carry a convergence time as an advisory. The
markers and the export are the smaller part; the documented collector setup and dashboard
the larger.

<a id="f-014"></a>
**F-014. Probes.** [Architecture §4.2](architecture.md#42-canonical-topology-model-ctm)
justifies the CTM partly by synthesized nodes and names later traffic generators as one,
provenance `synthesized` is already in the model, and Constitution X demands every
synthesized node in the fidelity manifest. So the slot is reserved, and the questions are
where the declaration lives and which generator. Traffic is not network intent, so it does
not belong in the generics. The pattern that fits is [D-032](decisions.md#d-032)'s: a
Fylgja-owned, branch-agnostic kind in Infrahub, operator-written, naming two device ports
and a flow, which the compiler turns into synthesized host nodes and links, each consuming
a port on its device and recorded in the manifest. A lossy package cares, since a port a
probe takes is one an interface cannot. The first generator is a containerlab `linux` node
running ping and iperf3, which measures loss at low rates and costs almost nothing. A
generator is not a platform, so a small probe package format is the
[D-031](decisions.md#d-031) move: one mechanism per generator, keyed by a format value.
Containers forward in software, so the loss measured is the container's, never the
ASIC's, and the report says so. With stepping this is the headline demo: a graph of loss
across a change applied to a running twin. The hours include the kind and the manifest.

<a id="f-015"></a>
**F-015. Operational state diff.** With verify's readers, snapshot adjacencies and routes at
each stage's pause and diff them, so a proposed change carries what changed
operationally, not only what changed in the topology, through [F-008](archive/v0.2-built.md#f-008). Builds on
[D-037](decisions.md#d-037)'s observed facts.

<a id="f-016"></a>
**F-016. Upgrade rehearsal.** The same intent booted on another NOS version through the
package override directory and the package's `versions`, then verified. "Will this
configuration survive the next release" is a question every operator has. Mostly a
procedure and a package, gated on a second image version. Size: small.

<a id="f-017"></a>
**F-017. Object storage and a Temporal cluster.** Object storage replaces the bundle store's
directory behind its interface ([D-014](decisions.md#d-014)), and a self-hosted Temporal
cluster replaces `temporal server start-dev`. Both stay on the development host unless the
feature's spec moves Infrahub and the cluster to a host of their own; either way the
storage and orchestration seams are crossed before the host seam. The width is the bundle
store's seam, not the cluster: `bundle.Store`'s `Path` and the wire's `BundlePath` cross
the task queue as local paths, so this is the first change to what `internal/lab/wire`
means since it was written. Needed either way before [F-018](#f-018).

<a id="f-018"></a>
**F-018. Remote hosts.** Remote lab hosts, per-host task queues in place of the one queue
([D-015](decisions.md#d-015)), and a scheduler that places each twin on a host. Excluding
the hosts' provisioning. The API already gives an operator access to a twin from another
machine. It does not reach a host it does not run on: `fylgja serve` runs on the lab host
and reads the host in its own process ([D-041](decisions.md#d-041)), so how the server
reaches a remote host, and whether the task queue is the answer, are this feature's. Two
twins at once, one per host or namespace, are what make A/B of two changes possible, which
[F-013](#f-013) and [F-014](#f-014) make worth having.

**The remote hosts' runtime is open** ([the decision log's open
questions](decisions.md#open-questions)). If [F-018](#f-018) targets clabernetes, as
recommended, the cluster schedules the twin and pulls its images, so the per-host queues,
the scheduler and the image shipping largely give way to a second lab driver, and the
feature also waits for clabernetes 0.9's release and a cluster. It is re-scoped and
re-sized when the question closes, before it is specified.

<a id="f-019"></a>
**F-019. A third platform as data: Cisco IOL.** The strongest proof of
[D-031](decisions.md#d-031) is a vendor nobody designed for. The parked platform order
names IOL next, then PAN-OS ([Parked](decisions.md#parked)). IOL needs no KVM, so it boots
on a host that does not nest, and its image is account-gated, so the `docker import`
acquisition path and `host.image.absent` carry over. Research first: readiness is
gNMI-only and push is JSON-RPC or eAPI, and whether IOL serves either is unverified, so
the package may need a new readiness or delivery mechanism. That is a format change under
D-031, never a platform branch, and the write-up must say so: a third vendor is "just
YAML" only where the existing mechanisms fit. Supported means both halves of the
conformance suite pass ([psp/README.md](../psp/README.md)). It depends on nothing above,
so it is the filler whenever a gated feature blocks. The upper hours are a new
mechanism's.

<a id="f-020"></a>
**F-020. Ixia-c.** Keysight's community edition is a container with a containerlab kind, and
the Open Traffic Generator client has a Go implementation, so it stays Go end to end and
gives flows, rates, loss and latency where ping gives loss alone. It is a second mechanism
under [F-014](#f-014)'s probe package format. TRex needs hugepages and DPDK and is too heavy
for the development host.

<a id="f-021"></a>
**F-021. The WebUI.** Constitution I is where a UI bites: a JavaScript front end is a second
runtime. Either serve Go templates with htmx from the same static binary, with the assets
embedded as the packages are, which keeps the principle, or write a decision entry
exempting the UI. Its content is what the JSON already carries: `twin show`, following,
stages and plans, verify reports, steps and observation. Last, so it has something to
show beyond a status line. It is a second client of the same API.

## Decisions the order needs

- ~~At [F-023](archive/v0.2-built.md#f-023) (014)~~: written on 2026-10-16 as [D-045](decisions.md#d-045),
  stages superseding [D-032](decisions.md#d-032). A stage is a moment of a proposed
  change, the ends are derived (the branch point read on `main` at `branched_from`, the
  head pinned one microsecond after the branch's latest stamp), and M10's kind is removed;
  built by 014, with [D-046](decisions.md#d-046) refining its staleness rule,
  [D-047](decisions.md#d-047) its orphan's cause, and [D-048](decisions.md#d-048) its head
  and its staleness rule again, both reading the branch's intent events. With it,
  Constitution VI amended (1.2.0), citing that entry: "MUST NOT send an `at` of its own"
  became "MUST NOT send an `at` it composed from a clock of its own; an `at` read from
  Infrahub — a stamp it returned, or the first instant after one — MAY be passed as the
  operator's would be".
- ~~At 015~~: written on 2026-10-19 as [D-049](decisions.md#d-049) to
  [D-052](decisions.md#d-052) and built by 015: the check as the writer of a comment,
  beside [D-026](decisions.md#d-026), made a thread by [D-053](decisions.md#d-053) on
  2026-10-20; the server listening on the Docker bridge, superseding
  [D-042](decisions.md#d-042)'s loopback default for this deployment; `twin rehearse` as a
  fifth short workflow; and the check concluding from the report's status, Fylgja's
  verdicts staying advisory ([D-039](decisions.md#d-039)).
- At 016: probes as an input to a compile beside intent, hashed into the bundle; and
  [F-014](#f-014)'s own entries below.
- At [F-011](#f-011), contract 0.3 ([Release 0.3](#release-03)): `role` and `site` dropped
  from `FylgjaDevice`; `device` dropped from `FylgjaInterface`, with the link read taking
  membership from the interface side; `platform` optional, a compile-time finding when
  absent; and whether Fylgja's relationships ride the schema library's identifiers under
  their own names, or the library adapts its peers and its Parent. The entry supersedes
  the parts of [D-003](decisions.md#d-003) and [D-004](decisions.md#d-004) that named
  those members, and says in one line why the schema library and not a NetBox-shaped
  schema of Fylgja's own.
- At [F-014](#f-014): a second Fylgja-owned kind on [D-032](decisions.md#d-032)'s pattern,
  and what a probe package is beside a platform package.
- Before [F-018](#f-018): the remote hosts' runtime, the decision log's [open
  question](decisions.md#open-questions).
- At [F-021](#f-021): whether the WebUI keeps Constitution I through server-rendered
  templates or amends it.
