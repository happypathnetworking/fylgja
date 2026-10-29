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

**Set with the operator on 2026-10-25: exploratory coding that informs the refactor of
Fylgja into a production system.** The production shape, discussed and tabled the same
day, is a core that builds, updates and destroys a twin from one input, under an
orchestrator that owns stages, rehearsals and whatever reads a report, and may call other
tools along the way. 0.3 does not build that split; it proves the seams the split will
cut along, in five specs, in this order:

1. **[F-011](#f-011)**, the Infrahub reader reading the schema library's DCIM directly,
   the CTM becoming the contract in place of the generics, as `017-dcim-reader`
   ([brief](../specs/017-dcim-reader/brief.md)): the reader seam against the model OpsMill
   publishes. **Built** on 2026-10-26, under [D-057](decisions.md#d-057) to
   [D-060](decisions.md#d-060) and Constitution 2.1.0.
2. **[F-024](#f-024)**, snapshots, as `018-snapshots`
   ([brief](../specs/018-snapshots/brief.md), written 2026-10-27): the CTM wrapped in one
   content-addressed document with a slot for the probe declarations, the core's one
   input, which the Infrahub reader produces and the server takes: the core and
   orchestrator seam itself. **Built** on 2026-10-27, under [D-061](decisions.md#d-061)
   and Constitution 2.2.0.
3. **[F-026](#f-026)**, following removed from the core, as
   `019-following-removed` ([brief](../specs/019-following-removed/brief.md), written
   2026-10-27): a twin is frozen at its snapshot and nothing rebuilds it but the operator;
   added on 2026-10-27 so that probes are specified against a twin that cannot rebuild
   itself. **Built** on 2026-10-28, under [D-062](decisions.md#d-062), with the
   constitution unamended at 2.2.0.
4. **[F-014](#f-014)**, probes, `ping` only, as `016-probes`
   ([brief](../specs/016-probes/brief.md), rewritten on 2026-10-28 against 017, 018 and
   019): a node declared outside intent, the explicit-instruction input to the core.
   **Built** on 2026-10-29, under [D-064](decisions.md#d-064) and Constitution 2.3.0.
5. **[F-027](#f-027)**, the split of the core and the orchestrator, **the next spec**,
   as `020-core-orchestrator-split` ([spec](../specs/020-core-orchestrator-split/spec.md),
   [brief](../specs/020-core-orchestrator-split/brief.md), written 2026-10-29), added on
   2026-10-29 and placed before F-025 by the operator: the production shape's two
   deployables, with the readers, the stages, the rehearsal and the reports on the
   orchestrator's side, a Python project on Prefect 3.9.0 whose first adapter is the
   Infrahub reader ported to Python, and the core narrowed to the snapshot; under
   [D-065](decisions.md#d-065) and [D-066](decisions.md#d-066).
6. **[F-025](#f-025)**, a reader of NetBox with its branching plugin, producing snapshots
   and taking a stage as a snapshot, after the split: the reader seam against a second
   source of truth, built as the orchestrator's second adapter, in Python. Probed live on
   2026-10-29 ([verified facts](verified-facts.md#netbox-474-with-netbox-branching-122)).

A contract bump defines a release: 0.2 moved the twin record, the API and the CLI for
stages while the contract stayed 0.2, and 0.3 retired the generics at F-011, after which
the CTM is the contract and nothing moves it again in the release. What F-011 changes is
under [Decisions the order needs](#decisions-the-order-needs). The release also takes one defect from 015, with
no spec: a client following a rehearsal that is terminated outside Fylgja answers only once
its abandoned children close, which with no worker is never
(`specs/015-proposed-change-rehearsal/research.md` §5.2), and a `fylgja-twin` check
following one waits out its timeout. Two features left the release on 2026-10-25:
[F-012](#f-012), the skill, which bolts on later and touches no core, and
[F-022](#f-022), the sync from NetBox, superseded by [F-025](#f-025).

**Upgrading a 0.2 host.** 0.3's release notes copy this list into
`.github/workflows/release.yml` when they are written at the release's close; a feature
whose upgrade needs a step adds it here:

1. Destroy a following twin before upgrading a host of an earlier build: a Schedule
   `fylgja-follow` left behind starts a workflow no worker of this build serves, and this
   build carries no code to clear it ([F-026](#f-026), [D-062](decisions.md#d-062)).
2. Destroy, then create again, any twin an earlier build left up: its bundle `5` and
   `twin.json` `10` are read and destroyed, but cannot be stepped from, and a bundle `5`
   is refused by `twin provision` ([F-014](#f-014)).
3. Load the probe kind on `main` before a request that sends no `--probes`:
   `.venv/bin/infrahubctl schema load --branch main schema/fylgja-probe.yaml`, or the
   fixture tool's `-prepare-main` from this build, which loads the stage and probe kinds
   where absent before it refuses a `main` already holding the schema library; import the
   template's commit on `main` so the probe-ready ports' addresses render; and `docker pull
   alpine:3.24.2`, since a run never pulls a probe image ([F-014](#f-014),
   `contracts/cli.md`'s 016 Upgrading).

<a id="the-production-shape"></a>
## The production shape

**A direction, not a decision.** Discussed with the operator on 2026-10-25 and tabled while
[Release 0.3](#release-03) proves the seams; nothing here binds a plan, and each part
becomes a decision entry when a feature takes it up. It is recorded so that 0.3's specs
know what they are exploring toward.

- **Two components.** A **core** that builds, updates and destroys a twin from one input,
  the snapshot ([F-024](#f-024)), and exposes it through the API: create from a snapshot,
  step to one, destroy, show, verify, and an explicit mutation of a node or a link. Nothing
  in the core knows a branch, a proposed change, a stage or a source of truth. An
  **orchestrator** that owns everything else: the readers that turn a source of truth into
  snapshots, stages and their resolution, the rehearsal, the follow, the checks and
  journal entries posted back to the source, and whatever a customer adds to a flow, a
  health check or a configuration tool among them. The orchestrator drives the core
  through the API alone, never by starting its workflows, so either side can be replaced.
- **Temporal stays in the core**, where mid-flight durability matters, and is not the
  orchestrator's integration surface.
- **Constitution I is kept for the core and freed for the orchestrator** by a decision
  entry: a core service and an orchestrator are two deployables, and the orchestrator will
  call tools written in anything.
- **The orchestrator's platform.** Go is not a requirement there. The intended direction
  is **Prefect**: the ecosystem's language (Infrahub's SDK, NetBox's client, Nornir,
  NAPALM), the technology Infrahub's own checks and generators run on, flows as code for an
  audience that writes transforms and playbooks, pause-for-input as a human gate,
  automations fired by a webhook, runs of hours, Apache 2, no Kubernetes. Its run resumes
  by rerun rather than mid-flight, which an idempotent core and a rehearsal that ends in a
  destroy tolerate. Two options are kept beside it: **Temporal**, already in the stack and
  the most durable, if the orchestrator turns out to be a product whose flows are Fylgja's
  code and nobody else's; and **Kestra**, declarative YAML with HTTP, shell and Docker
  tasks, if the orchestrator turns out to be a contract whose reference flows others
  edit. To verify before choosing: the open-source Prefect server's current feature
  boundary (events and automations) and whether Infrahub's embedded Prefect is a separate
  server to run beside, as assumed. Argo Workflows is noted for the case where
  [F-018](#f-018) lands on clabernetes and a cluster arrives anyway.
- **The API's shape for long operations** changes whichever platform is chosen: start,
  an operation id, then poll or a callback, beside the stream Fylgja's own clients hold
  open today. It is the orchestrator's first demand of the core and is independent of the
  platform.
- **Open**: whether the orchestrator is a product Fylgja ships, with its own flows and
  integrations, or a documented contract that a customer's own system drives, with Fylgja
  shipping reference flows. The platform choice above leans to the first while keeping the
  second possible, since every flow drives the core through the API anyone else would use.
- **What 0.3 proves of it**: [F-011](#f-011), a reader as an adapter; [F-024](#f-024),
  the snapshot as the core's input; [F-014](#f-014), a declaration outside intent as an
  input; [F-025](#f-025), a second adapter, for a source that cannot replay time.

## Backlog

[Release 0.3](#release-03) takes [F-011](#f-011), [F-024](#f-024), [F-026](#f-026),
[F-014](#f-014), [F-027](#f-027) and [F-025](#f-025), in that order; then observing, then object storage and remote hosts, a
third platform, Ixia-c and a WebUI. [Release 0.2](#release-02) built
[F-023](archive/v0.2-built.md#f-023), [F-007](archive/v0.2-built.md#f-007) and
[F-008](archive/v0.2-built.md#f-008) out of this order first ([the
archive](archive/v0.2-built.md)); the rest keep it. Read-only production data stays
[parked](decisions.md#parked). The features keep the numbers the order was set with; the
first six are built ([the archive](archive/v0.1-built.md)), F-009 is removed,
[F-010](#f-010) is folded into [F-011](#f-011), and [F-022](#f-022) is superseded by
[F-025](#f-025). [F-024](#f-024) and [F-025](#f-025) were added on 2026-10-25 and take
the next free numbers; [F-026](#f-026) was added on 2026-10-27 and takes the next;
[F-027](#f-027) was added on 2026-10-29 and takes the next.

[F-011](#f-011), [F-024](#f-024), [F-026](#f-026) and [F-014](#f-014) are built, as
`017-dcim-reader`, `018-snapshots`, `019-following-removed` and `016-probes`; none of the rest has a decision entry. [F-011](#f-011), [F-013](#f-013), [F-014](#f-014), [F-015](#f-015),
[F-017](#f-017) to [F-021](#f-021), [F-024](#f-024), [F-025](#f-025), [F-026](#f-026) and
[F-027](#f-027) are each one spec, with one contract boundary and one new kind of infrastructure. [F-012](#f-012) and
[F-016](#f-016) are chores or records, with no spec.

| # | Feature | What it bundles | Needs | Hours | Why here |
|---|---|---|---|---|---|
| F-010 | *Generic transform*, folded into [F-011](#f-011) | the shipped template queried `FylgjaDevice`, so a DCIM device rendered through it; what was left, the template documented as a reference transform, is a paragraph in [F-011](#f-011)'s README | — | — | Overtaken: Infrahub rendered from the generics already, and renders from the library's kinds since [F-011](#f-011). |
| F-011 | **The Infrahub reader reads the schema library's DCIM** | the generics retired and the CTM the contract; the library vendored at a pinned commit and loaded on `main`; the reader's mapping documented and its approximations in the manifest; packages matching platforms by name; the fixtures re-seeded in the library's kinds | nothing new | 6–10 | The strongest OpsMill signal, and the first reader written as an adapter. Probed live on 2026-10-16; its [brief](../specs/017-dcim-reader/brief.md) written 2026-10-25. Opens 0.3. Built as `017-dcim-reader` on 2026-10-26. |
| F-024 | **Snapshots** | the CTM, which carries each node's configuration, wrapped in one content-addressed document with a slot for the probe declarations; the core's one input, taken by the server and stored beside the bundles; `twin create` and `twin compile` from one | [F-011](#f-011) | 3–5 | The core and orchestrator seam, proved before anything is split. Its [brief](../specs/018-snapshots/brief.md) written 2026-10-27. Built as `018-snapshots` on 2026-10-27. |
| F-026 | **Following removed from the core** | D-012's following, D-026 and D-027 superseded; the reconcile workflow, its Schedule, `--interval` and `--no-follow` gone; a twin frozen at its snapshot; any twin with a snapshot stepping to a stage or a snapshot, `twin step --snapshot`; walking as stepping | [F-024](#f-024) | 3–5 | A snapshot-fed core does not read a branch on a timer; the production shape's orchestrator may bring following back as take, compare, step. Added 2026-10-27; its [brief](../specs/019-following-removed/brief.md) written the same day. Built as `019-following-removed` on 2026-10-28, in about 6.2 hours of sessions against R-25's 8–11. |
| F-022 | *`infrahub-sync` into the DCIM*, superseded by [F-025](#f-025) | a sync mapping from NetBox onto [F-011](#f-011)'s schema | — | — | The operator wants NetBox read directly, not synced into Infrahub. |
| F-027 | **The split: the core and the orchestrator** | the production shape's two deployables: a core narrowed to the snapshot, which builds, steps, destroys, shows and verifies a twin from one, and an orchestrator in Python on Prefect 3.9.0 owning the readers, the stages and their resolution, the rehearsal and the reports, driving the core through the API; the Infrahub reader ported to Python as its first adapter; Constitution I kept for the core and freed for the orchestrator | [F-014](#f-014) | 24–36 | Added 2026-10-29 and placed before F-025 by the operator, so the NetBox reader is built as the orchestrator's second adapter. Its [brief](../specs/020-core-orchestrator-split/brief.md) written 2026-10-29; specified as `020-core-orchestrator-split`, under [D-065](decisions.md#d-065) and [D-066](decisions.md#d-066), its estimate [R-22](../specs/020-core-orchestrator-split/research.md#2-decisions)'s. |
| F-025 | **The NetBox reader** | NetBox with its branching plugin on the development host; an adapter outside the core, in Python, producing snapshots from a branch, with `render-config` as the configuration; a stage taken as a snapshot the adapter holds; a twin of a NetBox branch | [F-027](#f-027), a NetBox instance (installed under `local/netbox/`, stopped) | 8–12 | The reader seam against a second source of truth, and the first that cannot replay time. Probed live on 2026-10-29. |
| F-012 | **Agent surface** | `fylgja-rehearsing-changes`, a skill in OpsMill's format over the CLI's JSON, with a findings catalogue generated from the code; an MCP server deferred | verify, the API, the rehearsal | 2–5 | Cheap once there is something to ask. Left 0.3 on 2026-10-25: it bolts on later and touches no core. |
| F-013 | **Observation** | markers with bundle id and stage; a `gnmic` targets export; a documented collector and Grafana dashboard; a per-capability definition of settled | stepping, the API | 4–6 | Convergence across a step becomes a graph. |
| F-014 | **Probes** | a probe declaration, in a file and in a Fylgja-owned kind; synthesized `ping` hosts and no other synthesized node; loss across a step; a probe package format | [F-024](#f-024), stepping, verify | 5–7 | The headline demo: loss during a change on a running twin. `ping` only, by the operator's choice on 2026-10-25. Built as `016-probes` on 2026-10-29, in about 9.1 hours of sessions against R-29's 14–20. |
| F-015 | **Operational state diff** | adjacencies and routes snapshotted at each stage's pause and diffed; posted on the proposed change | stepping, verify, the rehearsal | 4–6 | Builds on verify's readers and its observed facts. |
| F-016 | **Upgrade rehearsal** | the same intent on another NOS version through the package override, then verified | verify, a second image version | 2–4 | Cheap and operationally compelling. |
| F-017 | **Object storage and Temporal cluster** | as below | nothing new | 6–10 | Needed either way before [F-018](#f-018). |
| F-018 | **Remote hosts** | as below; parallel twins for A/B of two changes | [F-017](#f-017), lab hosts or a cluster | 12–20 | Gated, so it waits. |
| F-019 | **Third platform, Cisco IOL** | the parked platform order's next vendor, as data | the IOL image | 5–14 | Independent of everything. Filler whenever a gated feature blocks. |
| F-020 | **Ixia-c** | the OTG probe mechanism; flows, rates, loss and latency | [F-014](#f-014) | 8–12 | After ping probes have proven the kind and the manifest. |
| F-021 | **WebUI** | Go templates and htmx from the same binary, or a decision amending Constitution I | verify, the API, [F-013](#f-013) | 6–10 | Last, so it has verify, steps and observation to show. |

| Phase | Features | Hours |
|---|---|---|
| Release 0.3 | F-011, F-024, F-026, F-014, F-027, F-025 | 49–75 |
| Observing | F-012, F-013, F-015, F-016 | 12–21 |
| Scale and surface | F-017–F-021 | 37–66 |
| **All** | | **98–162** |

### The features

<a id="f-010"></a>
**F-010. The generic transform, folded into [F-011](#f-011).** It was to be a transform
written against the generics rather than the reference schema's kinds, so that any
implementing schema renders a baseline artifact. When it was folded, the shipped query
`device_config` already named `FylgjaDevice`, never a reference kind, so a DCIM-modelled
device rendered through the shipped template, and a baseline for a platform the template
has no branch for would serve nobody, since Fylgja refuses a platform without a support
package before any artifact is read. What was left, the template documented as a reference
transform that a DCIM user replaces with one reading the library's own fields, is a
paragraph in feature 11's README; 017 rewrote the query and the template over the
library's kinds. [D-009](decisions.md#d-009) holds: Infrahub renders.

<a id="f-011"></a>
**F-011. The Infrahub reader reads the schema library's DCIM; the CTM is the contract.**
Rewritten on 2026-10-25 from its [brief](../specs/017-dcim-reader/brief.md), which holds
the shape; this paragraph is the summary. The generics ([D-002](decisions.md#d-002)) were
the contract while Infrahub was the only source of truth: any schema could implement
Fylgja's four kinds and Infrahub resolved the query across them. Probed on 2026-10-16
against OpsMill's [schema library](https://github.com/opsmill/schema-library)
([Verified facts](verified-facts.md)), they could inherit into its DCIM only after
adaptation on one side or the other, and with NetBox read directly as the second source
([F-025](#f-025)) every reader is an adapter that maps a fixed, DCIM-shaped model onto the
CTM. So the generics go, the CTM is the contract, and the Infrahub reader reads the
library's own kinds at a pinned commit: a device is `DcimDevice`, a port is
`InterfacePhysical` and `InterfaceVirtual` is never read, `mgmt_only` is the port's
`role: management` and `enabled` its `status` not `disabled`, each recorded as
approximated, a link is a `DcimCable` with exactly two physical ends and any other cable
is omitted and recorded, the package is picked by a `matches` list the package itself
declares, by manufacturer and platform name, so nothing is added to anyone's model, and
the twin's scope is a tag on each device the request names, inside which an unmatched
platform refuses the read and at whose boundary a cable is omitted and recorded. Layer
1 only: nothing in the compiler, the bootstrap or verify ever consumed an address, a
loopback, a role or a site, and the configuration Infrahub renders carries them.
[D-002](decisions.md#d-002), [D-003](decisions.md#d-003) and [D-004](decisions.md#d-004)
are superseded whole and Constitution III is rewritten: the CTM is the contract, a reader
maps one source, documents the mapping, names the model version it reads and records every
approximation. The library is vendored verbatim under `schema/dcim/`, Apache 2.0, loaded
on `main` by `-prepare-main` where the generics were; the reference schema and
`FylgjaContract` go; `FylgjaStage` stays. The one fixture branch is re-seeded in the
library's kinds, the CTM thins and reshapes its platform, all three goldens move,
re-baselined on their own commit, and the PSP format moves for `matches`. The schema
README gains the paragraph feature 10 left: the shipped template as a reference transform
that renders ports, and a user's own transform rendering their layer 2 and 3 from their
own kinds. Needs nothing new. **Built** on 2026-10-26 as `017-dcim-reader`, under
[D-057](decisions.md#d-057), with Constitution 2.0.0; [D-058](decisions.md#d-058) and
[D-060](decisions.md#d-060), written at its tier-2 run, read a stamp Infrahub's own
account wrote on a node as the node's creation (Constitution 2.1.0). Its goldens are
`43d91715…`, `4213b3cf…` and `ecb665f5…`, and both tiers passed over the library's kinds
on the development host.

<a id="f-024"></a>
**F-024. Snapshots: the core's one input.** Added on 2026-10-25, the second spec of
[Release 0.3](#release-03), as `018-snapshots` ([brief](../specs/018-snapshots/brief.md),
2026-10-27). A snapshot is one document, version `1`, wrapping an unchanged CTM `2`, which
since M5 carries each node's rendered configuration, and a slot for the probe
declarations, empty until [F-014](#f-014) fills it; its id is the hash of that body minus
the read's `observed_at`, by the rule the manifest already uses for `bundle_id`. It is
stored by id in `snapshots/` beside the bundles, with a schema in `contracts/`, and it
retires the bundle's CTM sidecar. The core's workflows consume snapshots alone: the server
takes one for `twin create --branch` or `--stage`, as it already reads and compiles for
`step` and `rehearse`, and starts each workflow with the snapshot id and the bundle id;
`twin create --snapshot` and `twin compile --snapshot` take one directly, and `intent read
--out` writes one. Wherever a record names a bundle id it names the snapshot id beside it,
except in the bundle, so bundle `5` and the goldens do not move. How a snapshot comes to
exist is the reader's business. For Infrahub a stage is still the operator's mark
([D-045](decisions.md#d-045) unchanged), and resolving it reads the branch pinned at the
stage's `at` and takes the snapshot on demand, so taking it twice gives the same id while
the branch's history stands; a rebase moves it, a documented limit. Constitution VI gains
a sentence saying what addresses intent when the source of truth cannot replay time: the
snapshot's id. This is the core and orchestrator seam of the production shape, proved
before anything is split, and the feature that lets [F-025](#f-025) exist. Small, since
the pieces are all in the tree. Following is untouched by it and removed by
[F-026](#f-026). **Built** on 2026-10-27 as `018-snapshots`, under
[D-061](decisions.md#d-061), with Constitution 2.2.0: every create, plan, step, rehearsal
and `intent read --out` takes and files its snapshot on the server, and every workflow but
the reconcile starts with a snapshot id and a bundle id; `twin.json` `9` and five
documents name the snapshot; the sidecar and `twin compile --ctm` are retired; bundle
`5` and the three goldens did not move. The fixture branch's snapshot is `576933ec…`, and
both tiers passed on the development host.

<a id="f-026"></a>
**F-026. Following removed from the core.** Added on 2026-10-27, the third spec of
[Release 0.3](#release-03), as `019-following-removed`
([brief](../specs/019-following-removed/brief.md), 2026-10-27, which holds the shape;
this paragraph is the summary). It is placed before [F-014](#f-014) so that probes are
specified against a twin that cannot rebuild itself. A core fed snapshots does not read a
branch on a timer: [D-012](decisions.md#d-012) is superseded in the part that says an
unpinned twin follows its branch, [D-026](decisions.md#d-026) and
[D-027](decisions.md#d-027) whole, and [D-007](decisions.md#d-007) and
[D-014](decisions.md#d-014) in their Reconcile and Schedule. The reconcile workflow, the
Schedule `fylgja-follow` and the five control activities go, with `bundles/.reads/`, the
worker's last reader of a branch, so the worker serves four workflows and fifteen
activities; `--interval` and `--no-follow` go outright; `twin show`'s pinned, frozen or
following becomes `snapshot <id>` and what the snapshot holds. `step.twin.unsteppable` is
relaxed: any twin whose record names a snapshot steps, to a stage of any proposed change or
to `twin step --snapshot`'s snapshot of any branch, but never to another scope or mapping,
and a twin built from a bundle directory still does not step. A walking twin walks by
stepping, and the name is kept. Tier 3's case 5 becomes a step to a snapshot, showing the
exit criterion live and keeping its artifact-only and topology changes and verify 5a; the
Schedule assertions go. Following leaves the core, not Fylgja: the production shape's
orchestrator may bring it back as take, compare, step, and the push-based follow once
planned for [F-025](#f-025) is its to plan. One exit criterion: a twin is frozen at its
snapshot and nothing rebuilds it but the operator. The constitution does not mention
following, and is not amended. **Built** on 2026-10-28 as `019-following-removed`, under
[D-062](decisions.md#d-062), with Constitution 2.2.0 unamended: the worker serves four
workflows and fifteen activities and reads no source of truth, and nothing makes a
Schedule; `twin show` names the twin's snapshot, and `twin verify` the staged bundle's;
`twin step --snapshot <id|file>` and a step to a stage of any proposed change, the twin's
scope and mapping held; every rehearsal's deadline 30 s shorter; `twin.json` `10`; the
seven following rules, the step `follow` and `step.target.foreign` retired; bundle `5`
and the three goldens did not move. Tier 3's case 5 steps its twin to a snapshot by file
and by id after 330 s in which nothing rebuilt it, and both tiers passed on the
development host. Its measured effort, by its command log from specify through the live
tiers, is about 6.2 hours of sessions with the two tiers' 65 minutes among them, against
[R-25](../specs/019-following-removed/research.md#r-25-the-estimate)'s estimate of 8–11
hours of sessions plus the tiers and the 3–5 set before the inventory.

<a id="f-022"></a>
**F-022. `infrahub-sync` from NetBox into the DCIM, superseded by [F-025](#f-025) on
2026-10-25.** It was to keep the source of truth where branching lives and let OpsMill's
sync write NetBox into Infrahub. The operator wants NetBox read directly, as an alternative
source of truth that a NetBox-backed Fylgja need not make feature-identical to an
Infrahub-backed one, which is F-025. What the paragraph observed of the mapping holds
there: NetBox's interface carries `mgmt_only` and `enabled`, its interface types sort
ports from the virtual, a cable with two terminations is a link, and a multi-termination
cable, a LAG and a platform without a vendor and NOS are the refusals to expect.

<a id="f-025"></a>
**F-025. The NetBox reader.** Added on 2026-10-25, the last spec of
[Release 0.3](#release-03), placed after [F-027](#f-027) on 2026-10-29. NetBox Labs'
branching plugin is generally available, source-available and installable on the
community edition, so [D-001](decisions.md#d-001)'s premise that NetBox lacks branching no
longer holds; the entry is superseded in that part, and NetBox becomes a second source of
truth read directly, through a reader producing [F-024](#f-024)'s snapshots. The
change-request layer that gates a merge on approvals, NetBox Changes, is a Pro and Premium
feature; on the community edition the merge gate is the plugin's own `protect_main` and
permissions. **Its shape, settled by the operator on 2026-10-29**: an adapter outside the
core, in Python, the orchestrator's direction, which reads a branch by the plugin's
header, maps NetBox's model onto the CTM by one documented mapping, takes each device's
configuration from `render-config` and writes a snapshot file; the core takes it by `twin
create --snapshot` and `twin step --snapshot` and never learns NetBox exists; built after
the split as the orchestrator's second adapter, since built first it would invent the
orchestrator's toolchain, flow shape, stage store and rehearsal. What NetBox cannot do: a
pinned `at`, since it has no point-in-time read and a merged branch cannot be read again,
so a stage is the snapshot the adapter takes when the operator marks it, held by Fylgja
and not by NetBox, and the branch point is current `main`, the merge target, at the first
read; stored artifacts with checksums, since `render-config` renders on demand and stores
nothing, so there is no staleness rule; and checks inside its pipeline, so a check becomes
an event rule or custom script calling the API, its report a journal entry on the branch,
and a merge block the plugin's. What it adds: event rules and webhooks, which an
orchestrator bringing following back ([F-026](#f-026)) would follow by push; planned and
staged device status; the device-type library's real port inventories for the lossy
mapping; cable paths computed through patch panels; config contexts; and a plugin as the
natural UI. **Probed live on 2026-10-29** ([verified
facts](verified-facts.md#netbox-474-with-netbox-branching-122)), with a throwaway Python
adapter and NetBox 4.7.4 with the plugin 1.2.2 under netbox-docker on the development
host: `render-config` and GraphQL both honour the branch header, the adapter's snapshot
built a three-node twin and stepped it to the branch's, with the port it shut read
`disable` on the node, and the snapshot id reproduces outside Go. The install stays under
`local/netbox/`, stopped, about 1.3 GiB when running. The decision entries the order owed
before it are [F-027](#f-027)'s.

<a id="f-027"></a>
**F-027. The split: the core and the orchestrator.** Added on 2026-10-29 by the operator
as the next spec, before [F-025](#f-025). It takes [the production
shape](#the-production-shape) from a direction to a decision: a core that builds, steps,
destroys, shows and verifies a twin from a snapshot, and an orchestrator that owns the
readers, the stages and their resolution, the rehearsal and the reports posted back to the
source, driving the core through the API alone; Constitution I kept for the core and freed
for the orchestrator by a decision entry; and the API's shape for long operations, the
orchestrator's first demand. It is specified as `020-core-orchestrator-split`
([spec](../specs/020-core-orchestrator-split/spec.md),
[brief](../specs/020-core-orchestrator-split/brief.md), written 2026-10-29), under
[D-065](decisions.md#d-065) and [D-066](decisions.md#d-066): the orchestrator a Python
project on Prefect 3.9.0 under `orchestrator/`, chosen over Temporal and Kestra; the
Infrahub reader ported to Python as its first adapter; the core narrowed to the snapshot;
and 24–36 hours of sessions by
[R-22](../specs/020-core-orchestrator-split/research.md#2-decisions). Why before F-025: the NetBox reader is a Python adapter, so it is orchestrator
code, and built first it would invent what the split decides. What F-025's spike gives
it: a source that cannot replay time read as snapshot files, a stage as the snapshot the
orchestrator holds, the CTM envelope's three Infrahub-shaped places (`schema_hash`, `at`,
the artifact's stored checksum), the snapshot id reproducible outside Go, and a journal
entry on a NetBox branch as a report's home where the community edition has no change
request.

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

In a release's recording it is the demo's second act: the check posts its report on the
proposed change, and an agent explains the report in the thread. It moved from 0.2 to 0.3
on 2026-10-21 and left 0.3 on 2026-10-25, since it bolts on later and touches no core; it
waits for a release that has one to show. **Deferred**: the MCP
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
not belong in the operator's model the reader maps. The pattern that fits is
[D-045](decisions.md#d-045)'s, as it was [D-032](decisions.md#d-032)'s for the waypoint
before it: a Fylgja-owned, branch-agnostic kind in Infrahub, `FylgjaProbe`,
operator-written, naming two device ports, which the compiler turns into two synthesized
hosts, `<probe>-a` and `<probe>-b`, and their links, each host consuming a port on its
device and recorded in the manifest. A lossy package cares, since a port a probe takes is
one an interface cannot. The first and only generator is a containerlab `linux` host
running `ping`, which measures loss at low rates and costs almost nothing. A
generator is not a platform, so a small probe package format is the
[D-031](decisions.md#d-031) move: one mechanism per generator, keyed by a format value.
Containers forward in software, so the loss measured is the container's, never the
ASIC's, and the report says so. With stepping this is the headline demo: a graph of loss
across a change applied to a running twin. The hours include the kind and the manifest.

Re-shaped on 2026-10-25 for [Release 0.3](#release-03), the operator's choices: **`ping`
only, and no other synthesized node type** in this feature; iperf3, Ixia-c
([F-020](#f-020)) and an emulated boundary device are later formats of the same
declaration. **The declaration is a file first**, one input to [F-024](#f-024)'s snapshot,
and the Infrahub kind is one source of that file. **The declaration carries the host's
address and its gateway**, since the CTM carries no addresses: Fylgja configures the
host from the declaration alone, the device side stays intent's, and the brief's refusal
of a host address outside the interface's prefix is lost. [016's
brief](../specs/016-probes/brief.md) was rewritten on 2026-10-28 against these and 017's,
018's and 019's shape, and the feature taken as [D-064](decisions.md#d-064), with
Constitution 2.3.0: `--probes <file>` on the five commands that read intent, else the kind
on the default branch, else none; the snapshot `2` carrying the list; one `ping` probe
package, `probes/ping.yaml`, on `alpine:3.24.2`; and a step's flows and verify's burst
measuring and asserting each probe. **Built** on 2026-10-29 as `016-probes`, under
[D-064](decisions.md#d-064), with Constitution 2.3.0: a probe from `--probes <file>` or
`FylgjaProbe` on `main` (loaded there, `8a4f3bee…`), carried by snapshot `2` and compiled
into bundle `6`, its two hosts, their links and the ports they take under the manifest's
`fidelity.synthesized`; `probes/ping.yaml`, probe package `0.1`, its image verified present
and never pulled; `twin.json` `11`; a step's flows read as `loss`, reported and never
asserted, beside verify's burst, the assertion kind `burst` and the rule `verify.burst`;
the rehearsal's report a `loss` column. The worker serves four workflows and seventeen
activities. The fixture's devices each gained two addressed, uncabled ports and the
template their address lines on both platforms, so the goldens moved twice, to
`c70589c3…`, `10099944…` and `44ac283f…`, beside a fourth, three-node-probed
`5222063b…`; the fixture branch's snapshot is `0940db93…` and its bundle `c3872f5c…`, and
both tiers passed on the development host, tier 3 with probes in cases 5, 8 and 9. Its
measured effort, by its command log from specify through the live tiers, is about 9.1
hours of sessions with the two tiers' 71 minutes among them, against
[R-29](../specs/016-probes/research.md#2-decisions)'s estimate of 14–20 hours of sessions
plus the tiers and the 5–7 set before snapshots, the template change and the fixture's
ports.

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
exempting the UI. Its content is what the JSON already carries: `twin show`, stages and
plans, verify reports, steps and observation. Last, so it has something to show beyond a
status line. It is a second client of the same API.

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
- ~~At [F-011](#f-011) (017)~~: written on 2026-10-25 as [D-057](decisions.md#d-057) and
  built by 017, with Constitution 2.0.0; [D-058](decisions.md#d-058) to
  [D-060](decisions.md#d-060), written on 2026-10-26 at its tier-2 run, refine what a
  device's intent stamp is (2.1.0). As set: the CTM as the contract in place of the generics, the
  Infrahub reader an adapter for the schema library's DCIM at a pinned commit, with its
  mapping (a port is `InterfacePhysical`; `mgmt_only` from `role`, `enabled` from `status`,
  each approximated; a cable with other than two physical ends omitted and recorded; the
  package matched by the names it declares; the scope a tag the request names, strict
  inside it). The entry supersedes
  [D-002](decisions.md#d-002), [D-003](decisions.md#d-003) and
  [D-004](decisions.md#d-004) whole, rewrites Constitution III with a major version bump,
  and says in one line why the library's kinds and not a NetBox-shaped schema of Fylgja's
  own.
- At [F-024](#f-024) (018): the snapshot as the core's one input, content-addressed, with
  every stage resolving to one, the bundle's CTM sidecar retired by its store; and
  Constitution VI amended, a minor bump, with its sentence on what addresses intent when
  the source of truth cannot replay time. Its [brief](../specs/018-snapshots/brief.md)
  settles the shape. Taken as [D-061](decisions.md#d-061), with Constitution 2.2.0.
- At [F-026](#f-026) (019): [D-012](decisions.md#d-012) superseded in its following,
  [D-026](decisions.md#d-026) and [D-027](decisions.md#d-027) whole, and
  [D-007](decisions.md#d-007) and [D-014](decisions.md#d-014) in their Reconcile and
  Schedule; following leaves the core and the orchestrator may bring it back. Its
  [brief](../specs/019-following-removed/brief.md) settles the shape. Taken as
  [D-062](decisions.md#d-062), with the constitution unamended.
- At [F-014](#f-014) (016): the probe declaration as a file first and an Infrahub kind
  second, on [D-045](decisions.md#d-045)'s pattern for the kind; what a probe package is
  beside a platform package; and the declaration carrying its own gateway address.
  Taken as [D-064](decisions.md#d-064), with Constitution 2.3.0.
- At [F-027](#f-027), before [F-025](#f-025) (moved here from F-025 on 2026-10-29):
  Constitution I kept for the core and freed for the orchestrator, the production shape's
  entry; [D-001](decisions.md#d-001) superseded in the part that says NetBox lacks
  branching; and a stage as a snapshot Fylgja holds where the source of truth cannot
  replay time, beside D-045's mark where it can. (A push-based follow for the NetBox
  reader was planned here until [F-026](#f-026) took following out of the core.)
- Before [F-018](#f-018): the remote hosts' runtime, the decision log's [open
  question](decisions.md#open-questions).
- At [F-021](#f-021): whether the WebUI keeps Constitution I through server-rendered
  templates or amends it.
