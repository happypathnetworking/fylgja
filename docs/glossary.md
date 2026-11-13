# Glossary

The terms Fylgja uses, alphabetically. A term marked *(orchestrator)* belongs to a reader under
`readers/` or to the example orchestrator under `orchestrator/`, beside the core in this
repository, and to the source of truth they join: the core never uses it, but it is met in a
blueprint's `source` or in these documents. See also
[architecture.md](../design/architecture.md) and the formats in [`formats/`](../formats/README.md).

**Acceptance run** — A phase's own gate, made once with the core on the local driver and once
with the core deployed on the cluster. Through Infrahub's check, phase 8's: the seeded branch's
proposed change, created by the maintainer in the development Infrahub, rehearsed through
Infrahub's own check `fylgja-twin`, the maintainer reading each report in its thread
([core.md](../design/core.md#phase-8-the-infrahub-reader-and-the-example-orchestrator-settled-2026-11-09)).
Through NetBox's tag, phase 9's: a branch built in the development NetBox in steps, each marked,
then given the tag `fylgja-rehearse`, by the script's last act or by hand, which starts the
rehearsal through NetBox's webhook and Prefect, the maintainer reading each report on the branch's
journal
([core.md](../design/core.md#phase-9-the-netbox-reader-and-the-examples-netbox-change-source-settled-2026-11-12)).
Each run's every command, and the blocks that say the maintainer can act, are in
[CONTRIBUTING.md](../CONTRIBUTING.md#the-acceptance-run).

**Admission** — The check that a twin fits before anything is applied. `admit` reserves its
allocation, and the deployment's *demand* (runtime nodes, and the sums of the packages'
per-node CPU and memory) is compared with the runtime's free room as the driver reads it at
`admit`, less the demand of twins admitted whose nodes are not yet up
([D-073](../design/decisions.md#d-073)). A twin that does not fit is refused with rule
`admission.capacity` ([D-019](../design/decisions.md#d-019)). The room is read by
`GET /v1/capacity` and `fylgja-core capacity show` ([D-076](../design/decisions.md#d-076)).

**`admit`** — The driver call that reserves what a twin is bound to (a lab name and
management subnet, a namespace, a device reservation) and records it in the twin record by
*compare-and-set*, or refuses with the reason ([D-017](../design/decisions.md#d-017)).

**Allocation** — What `admit` reserved for one twin: `{lab, mgmt_subnet, demand}` on
containerlab, `{namespace, core_namespace, controller_namespace, pod_cidr, registries, demand}`
on clabernetes, `{reservation, devices}` on hardware; clabernetes' `registries` maps a *pull
credential*'s key (its name as its variables write it) to its image prefix, and `demand`
(`{nodes, cpu, memory_mb}`) is the room the twin reserved, a step's refreshed to the target's
([D-073](../design/decisions.md#d-073)). `plan` takes it as an input, and `destroy` releases it.

**API 1** — The core's HTTP interface and the only way a client reaches it: resources under
`/v1/`, every long operation a *run*, verdicts as findings and refusals as problem
documents ([`api-1.openapi.yaml`](../formats/api-1.openapi.yaml),
[D-025](../design/decisions.md#d-025)). The frozen Go core's API is also version 1; they share
nothing else.

**Audit log** — The log lines, on the same stream as every other, that carry the principal and
the action of every write to a twin, so that every change is attributable
([Constitution X](../design/constitution.md#x-report-honestly)).

**Backoff** — The loop's growing delay before it retries a twin after a transient failure, or
after a pass that failed in a way the loop does not class: doubling from 1 s to a 60 s ceiling,
reset by a pass that completes ([D-023](../design/decisions.md#d-023)). A driver's event never shortens it, since a runtime's
own events follow every apply; a client's write does ([D-070](../design/decisions.md#d-070)).

**Base install** — `fylgja-core` installed with no extra: the model package, the client
library and the thin CLI, over httpx, jsonschema, referencing and PyYAML as ranges, which a
reader or an integrator's platform installs. The server's libraries are the extra
`fylgja-core[server]`, pinned exactly ([D-084](../design/decisions.md#d-084)), and
`fylgja-core-server` from a base install exits 2 saying so.

**Baseline stage** *(orchestrator)* — The first stage of a change that builds, which a
*rehearsal*'s twin is created at and whose failures are not the change's: what verify still
finds failing there once the *settle* has ended is recorded as failing before the change, and a
later stage is failed only for a failure of another rule or object
([D-086](../design/decisions.md#d-086)).

**Blueprint** — The core's one input: the network (devices, interfaces, links, each device's
rendered configuration, where it has one) and the probes declared beside it, with an opaque
*source envelope* ([`blueprint-1.schema.json`](../formats/blueprint-1.schema.json),
[D-006](../design/decisions.md#d-006), [D-006](../design/decisions.md#d-006)). A *producer*
(the orchestrator, or a hand-written file) writes it; the core files it by id, compiles it
and returns it unchanged. It was earlier called a *snapshot*.

**Blueprint id** — The lowercase-hex SHA-256 of the RFC 8785 (JCS) canonical JSON of
`{network, probes}` alone, so the same topology read from two branches has one id. Every
list must arrive sorted and unique; the core rejects one that is not
(`blueprint.unsorted`, `blueprint.duplicate`) and never sorts it.

**Bracket** — What keeps the NetBox reader's read to one state, NetBox reading no earlier time:
the latest id of the changelog read from, `main`'s or the branch's, and the count of its rows at
or below that id, taken at the read's open and again at its close, and for a branch the branch's
own row, read again at the close, whose `last_sync` a sync moves without a row in either
changelog. A row between the two ids of a kind a read reads, every kind but a journal entry's and
the branch object's own; a count that moved, a row of any kind written below the open's id; or a
branch gone, synced or no longer `ready`, refuses the read, `read.moved`, with the remedy: read
again ([D-095](../design/decisions.md#d-095),
[`readers/netbox/mapping.md`](../readers/netbox/mapping.md)).

**Branch point** *(orchestrator)* — The first *stage* of a proposed change: the default branch
as it stood when the change's branch was cut, read at the time Infrahub gives that cut
([D-088](../design/decisions.md#d-088)). A NetBox change has none, since NetBox reads no
earlier time: its first stage is `main` as it stands when the rehearsal reads it
([D-097](../design/decisions.md#d-097)).

**Build phase** — One item of the "Sequence" in [core.md](../design/core.md#sequence), such as
"phase 7", built in four stages: settle, plan, execute, land
([D-080](../design/decisions.md#d-080), [CONTRIBUTING.md](../CONTRIBUTING.md#how-a-phase-is-built)). Not the reconcile
loop's *phase*.

**Bundle** — What the compiler makes of one blueprint and the loaded packages: a
`manifest.json` (nodes, *mapping rows*, links, placed probes, the blueprint id) and one
`configs/<node>.cfg` per node that carries a configuration
([`bundle-1.schema.json`](../formats/bundle-1.schema.json)).
It is runtime-neutral and holds nothing that belongs to one twin, so one bundle can back
many twins on any driver ([D-011](../design/decisions.md#d-011)). Its id hashes its files.

**Burst** — A probe's verdict in *verify*: a fixed count of echoes from each probe host
toward the other's address, both ends in turn, run inside the host by the driver's `exec`;
each direction is held when every reply comes back ([D-008](../design/decisions.md#d-008),
[D-051](../design/decisions.md#d-051)).

**`capabilities`** — The driver call that says what a driver can do: provision nodes or
claim them, change links on a running twin, forward in software or hardware, reach nodes
directly or by proxy, keep twins apart by names alone or by the network, and finish an apply
cut short by applying again (`reapply`, [D-068](../design/decisions.md#d-068)). Code above the
*driver seam* may branch on a capability, never on a runtime.

**Change source** *(orchestrator)* — The example orchestrator's side of one source of
truth, behind a seam of four calls: the change a trigger names, its stages in order, a stage
read into a blueprint or the findings that refused it, and the report posted; with three
attributes, the bytes one part of a report may take there and the source's own sentences for
asking again and for checking the scope; and three more the *edge* alone asks: whether a change
is a draft, `claim`, the request that started the rehearsal taken so that it is used once, and
its connections closed ([integrating.md](integrating.md#the-seams)). Infrahub's,
`fylgja_orchestrator.infrahub`, finds the open proposed change of a branch, posts the report as
a thread of two comments, and claims nothing, since a proposed change's checks ask again only
when they run again ([D-085](../design/decisions.md#d-085)). NetBox's,
`fylgja_orchestrator.netbox`, finds a branch by its name, reads its *marks* from the branch's
journal and their blueprints from the core, takes the tag off the branch as its claim, and
files the report as one journal entry on the branch, its kind the verdict
([D-097](../design/decisions.md#d-097)).

**clabernetes** — containerlab on Kubernetes, one pod per node. The production *driver*,
with a namespace and a NetworkPolicy per twin and a LoadBalancer per node
([D-017](../design/decisions.md#d-017), [D-020](../design/decisions.md#d-020)). It is developed on *kind*, a
Kubernetes cluster in Docker ([D-022](../design/decisions.md#d-022)).

**Compare-and-set** — A write that succeeds only if the record's *revision*, its write
counter, is the one the writer read. Every change to a twin record is one, so two runs never
overwrite each other ([D-023](../design/decisions.md#d-023)). On the object store it is a
*conditional write*.

**Compiler** — The pure function from a blueprint and packages to a bundle, with no I/O,
clock or environment ([Constitution V](../design/constitution.md#v-the-compiler-is-pure-identity-is-content)).
It answers the bundle id, the manifest, the compile's fidelity and its findings.

**Conditional write** — An S3 write the endpoint makes only if the object is absent
(`If-None-Match: *`) or still the version read (`If-Match` at its ETag). It is the object
store's compare-and-set, and the store proves at start that its endpoint refuses what it
must ([D-061](../design/decisions.md#d-061)).

**Conformance suite** — The tests a *platform package* passes to count as supported. The
*driver conformance suite* is one set of scenarios run on each driver's own runtime.

**containerlab (local driver)** — containerlab runs network operating system containers as
a lab from a topology file. The local *driver* uses it for development and the live tier,
with one lab per twin, so neither needs Kubernetes.

**Core** — The deployable this repository builds: it turns a blueprint into a named twin,
and steps, verifies, shows and destroys it. It knows no source of truth.

**Credential provider** — The one source of node logins and *pull credentials*: the
environment locally, Secrets on a cluster. A platform package names its login by a
`credentials` name, and a gated image's pull credential by its `image.pull_secret`, never a
value.

**CTM (Canonical Topology Model)** — The archived repository's network body, version 2,
which snapshot 2 wrapped. Blueprint 1 replaces it.

**Deployment** — What a driver's `plan` returns: the rendered runtime files (for
containerlab `topology.clab.yml` named for the twin; for clabernetes a Namespace, a
NetworkPolicy and a `Topology`), the allocation, the *demand* and the fidelity of this twin
on this runtime
([`deployment-1.schema.json`](../formats/deployment-1.schema.json)). The same plan always
gets the same id.

**Desired state** — What a twin should be. In the twin record it is the *spec*.

**Dry run** — A `PUT` of a twin's spec with `dry_run=true`: admission and the driver's
`plan` run and answer what would happen, and nothing is written
([D-025](../design/decisions.md#d-025)). On a twin that runs it is a step's: admission keeps the
allocation the twin holds, the driver's `changes` say what the step would do to each node and
link, and the verdict is rejected where the step would be refused
([D-050](../design/decisions.md#d-050)).

**Diverged** — A twin whose step failed or was cancelled after its apply began, left as it
stands: part on its old bundle and part on its new one, so no bundle describes it. Its
`Diverged` condition is True, `last_step` says `diverged`, and the run's verdict is `diverged`,
its finding (`step.diverged`, or `step.node.silent` for a node silent on a resume) naming the
phase and what each node holds. Nothing is torn down or rolled back; it can be shown, verified
and destroyed, and accepts only deletion ([D-029](../design/decisions.md#d-029),
[D-050](../design/decisions.md#d-050)).

**Driver** — The code that runs twins on one runtime behind the *driver seam*: local
`containerlab`, `clabernetes`, and `hardware` later ([D-017](../design/decisions.md#d-017),
[Constitution XIII](../design/constitution.md#xiii-runtimes-are-drivers)).

**Driver registry** — `fylgja_core.drivers`, the one module above the *driver seam* that
names a runtime: it lists the drivers the core serves, makes one by name, and answers a
driver's capabilities and the `FYLGJA_*` variables it `needs`
([D-046](../design/decisions.md#d-046)). A driver the environment cannot make, the
clabernetes driver with no cluster to reach, is `Unmakeable`, naming the variable at fault.

**Driver seam** — The ten calls every driver implements: `capabilities`, `admit`, `plan`,
`changes`, `apply`, `inspect`, `destroy`, `endpoints`, `exec` and `events`. Each but `exec` is
idempotent.

**Edge** *(orchestrator)* — The example orchestrator's outer layer, above its rehearsal library
and its *change source*: the two Prefect flows Infrahub's checks start, `stage-plan` and
`twin-rehearse`, the second of which NetBox's webhook starts too, each a thin wrap of the
library that files its document as the run's artifact; the command line; and the two checks.
Only its flows and its *runner* import Prefect ([D-085](../design/decisions.md#d-085),
[D-097](../design/decisions.md#d-097)).

**`endpoints`** — The driver call that returns each node's management address. The push,
readiness, verify and flows dial it, whatever the runtime.

**`events`** — The driver call that names, for good, each twin whose runtime may have changed:
Docker's events for its labs' containers locally, one watch on its twins' pods on clabernetes.
A name is all it carries to the loop, since the loop reads what is true with `inspect`; the
loop's task queues each one, though never ahead of the twin's *backoff*, so a node the runtime
replaced is restored without waiting for the *resync*. The clabernetes driver also deletes a
pod whose container ended or restarted in it before it names the twin, so the cluster makes
the node anew ([D-070](../design/decisions.md#d-070)). It never fails: it starts its source
again after the *backoff*, then names every twin its source can name; on clabernetes a twin
whose every pod went is named by the *resync* alone ([D-058](../design/decisions.md#d-058)).

**Fidelity** — What a twin models exactly, approximates, synthesizes (probe hosts) or omits,
and why; asserted, never measured ([Constitution X](../design/constitution.md#x-report-honestly)). The
compile answers its runtime-independent part, and each deployment adds how nodes forward on
its runtime. An *approximation* is a package's own sentence; an *omission* is an interface
left out, with its reason.

**Finding** — One thing an operation found: a stable rule id, a severity and a message.
Findings make up a *verdict* or a problem document's `findings`.

**Flow** — Traffic a step runs between a probe's two hosts while it changes the twin. Its
*transient loss* (packets lost, the longest gap) is reported, never asserted.

**Frozen Go core** — The core as built in Go, in the *archived repository*, which also holds
the prototype orchestrator and the earlier formats ([D-005](../design/decisions.md#d-005)). It was
the reference implementation while the new core was built, explaining behaviour and supplying test
scenarios, and was retired at the cut-over ([D-001](../design/decisions.md#d-001),
[D-081](../design/decisions.md#d-081)): it gets no more fixes, and nothing tracked here needs it or
the archived repository to build, test or run.

**`FylgjaProbe`** — The Infrahub kind a *probe* is declared in, beside intent and not in it: one
object a probe, its two ends flat attributes. Its schema ships with the Infrahub *reader*, which
reads its objects into a blueprint's `probes` where the *reader document* asks for them
([D-082](../design/decisions.md#d-082)).

**Generation** — A twin's counter of what was asked: it goes up by one with every change of
*spec* and with a deletion request. The loop copies it to `status.observed_generation`
once it has acted on it, so a client can tell whether the status is current
([D-025](../design/decisions.md#d-025)).

**Hardware driver** — A later release's driver: it claims devices from a pool rather than
creating nodes, cannot re-cable, and resets each device to a stored baseline. Its paper
shape checks the seam ([design/core.md](../design/core.md)).

**Head** — The first instant after a branch's latest write, as the Infrahub *reader*'s `head`
answers it for a scope: a microsecond after the later of the newest stamp of the scope's devices,
their platforms, manufacturers, interfaces, addresses, cables and artifacts' checksums, of every
`FylgjaProbe` where the branch has the kind, and the newest event of the branch since it was made
and of `main` up to then, nothing discounted. A read pinned there meets every
write before it, where a read pinned at a write's own stamp meets only part of it
([D-082](../design/decisions.md#d-082)). *(orchestrator)* The last *stage* of a proposed change
is its branch read at its head, after the *branch point* and the *marks*
([D-088](../design/decisions.md#d-088)). A NetBox change's head is its branch as the rehearsal
reads it, at no instant, after `main` and the marks ([D-097](../design/decisions.md#d-097)).

**`hot_add_ports`** — A platform package's statement of whether a port added after boot
appears in the network operating system when a link to it is added live. cEOS: `false`.

**Incarnation** — A node's current instance: a container's start time locally, a pod's uid
and its container's restart count on clabernetes ([D-069](../design/decisions.md#d-069)).
When it changes, the node lost its push, and the loop pushes it again
([D-023](../design/decisions.md#d-023)): in a step's apply, or under a *restore* when a kick
finds it on a settled twin ([D-067](../design/decisions.md#d-067)). The loop compares
incarnations as the driver writes them, and never reads one.

**Infrahub** *(orchestrator)* — OpsMill's source of truth, from which the Infrahub *reader*
reads devices, cables and each device's configuration rendered by a template.

**Integration branch** — `phase-N-integration`, the branch a *build phase*'s plans are merged
into, cut from `main` with the phase's design merged in. It is squashed onto `main` at the
*landing*, and its history is kept under the tag `archive/phase-N-integration` ([D-080](../design/decisions.md#d-080)).

**Isolation unit** — What a driver gives each twin so twins share nothing mutable: a lab
with its own management network, a namespace, or a device reservation
([Constitution VII](../design/constitution.md#vii-twins-are-named-and-isolated),
[D-019](../design/decisions.md#d-019)). A resource labelled as a twin's with no record behind it is an
*orphan*, found by a label sweep.

**Kind** — containerlab's built-in support for one network operating system
(`nokia_srlinux`, `ceos`): its interface aliases, default login and baseline. A platform
package states only what the kind does not ([D-015](../design/decisions.md#d-015)); for a kind with
no aliases (cEOS), that includes a *rename rule* from production names to the kind's ports.

**Landing** — The end of a *build phase*, on the maintainer's word: the phase written as built,
the *integration branch* squashed onto `main` as one commit and its history tagged, and the
build's records copied to `local/sdd/phase-N/` ([D-080](../design/decisions.md#d-080)).

**Lease** — On a cluster, the `coordination.k8s.io/v1` object one core holds so that no second
core reconciles its store beside it ([D-062](../design/decisions.md#d-062)): held under the pod's
name for 15 s, and renewed every 5 s. A core waiting for it takes it once it has seen it
unchanged for 15 s by its own clock, never by the Lease's times; a core whose renewals have not
succeeded for 15 s stops (`lease.lost`). A release frees it for the next at once.

**Ledger** — The record of one plan's build, kept outside the tree by the session running the
phase: the tasks done with their commits, every *ruling*, and the findings deferred
([D-080](../design/decisions.md#d-080)).

**`link_apply_mode`** — How a link change reaches a running node of a kind: `live`,
re-cabled with no restart, or `restart`. Set by the platform package, written on each node
at create, and never changed on a running twin.

**Look** *(orchestrator)* — A dry run of each stage of a change as the twin it would make,
before a *rehearsal* creates anything: a stage the runtime has no room for, lacks an image
for or cannot build is refused there, and nothing is made
([D-086](../design/decisions.md#d-086)).

**Lossy** — A rename that drops a placeholder of its rule's match, so that two production
names can land on one runtime port. The plan counts lossy mappings and shared ports per
deployment, and omits an uncabled interface whose port a cabled one holds (`shared`).

**Mapping row** — One row of a bundle's mapping per blueprint interface: the device, the
production interface name, the rule that matched, the *disposition* (`cabled`, `uncabled`,
`management` or `omitted`), the node's own port name, and an omission's reason.

**Mark** *(orchestrator)* — A *stage* the operator records on a branch: a `FylgjaStage` in
Infrahub, branch-agnostic, naming its branch as text, with a label unique within that branch, an
optional `as_of`, the time it stands at, and an optional description. It has no relationship to
a proposed change, so it is written before one exists, and it outlives its branch. A change's
marks stand between its *branch point* and its *head*, in order of their time
([D-088](../design/decisions.md#d-088)). In NetBox, which reads no earlier time, a mark is a
journal entry on the branch naming a blueprint the core keeps: `stage mark` reads the branch as
it stands once a step exists, gives the blueprint to the core and writes the entry, naming the
label, the blueprint's id, the scope and the time read. A label is unique within its branch and
is never taken twice; the marks stand between `main` and the head in the order written, and a
mark's blueprint is read from the core the rehearsal runs through, which holds it where it was
given it ([D-097](../design/decisions.md#d-097), [D-100](../design/decisions.md#d-100)).

**NetBox** *(orchestrator)* — The source of truth from which the NetBox *reader* reads devices,
interfaces, cables and each device's configuration as NetBox renders it at the read from its
template, on a branch of the branching plugin or on `main`, as it stands
([D-095](../design/decisions.md#d-095)). A change in it is a branch, each step *marked* as it is
built, and rehearsed once the tag `fylgja-rehearse` is set on it
([D-097](../design/decisions.md#d-097)).

**Not rehearsed** *(orchestrator)* — The status of a *rehearsal* that could not be carried
through for a reason that is not the change's: no stage to build, no room on the runtime, an
image absent, the runtime's set-up, the core not answering or refusing, the source not
answering, or an earlier twin still there. Nothing is retried: a refusal for room is asked
again by running the checks again, or in NetBox by setting the tag again
([D-086](../design/decisions.md#d-086)).

**Observed state** — The part of a twin record only the reconcile loop writes: the
generation it acted on, the phase, run, blueprint, bundle, deployment, nodes and last step,
and the *conditions* `Ready`, `Stepping` and `Diverged`, each with a stable reason.

**Orchestrator** *(orchestrator)* — The example orchestrator: a worked example of joining
the core and a *reader* to a system that already exists. It resolves stages, rehearses
changes, an Infrahub proposed change or a NetBox branch, and reports on them, and is not
hardened ([D-081](../design/decisions.md#d-081), [D-085](../design/decisions.md#d-085)). It is
`fylgja-orchestrator`, under `orchestrator/`, in three layers, a rehearsal library, a *change
source* and an *edge*, written to be read once and replaced ([integrating.md](integrating.md));
its prototype, the orchestrator in the archived repository, was the reference it was written
against.

**Phase** — (For an item of the build's "Sequence", see *build phase*.) One ordered stage of the
reconcile loop: `compiled`, `admitted`, `planned`,
`applied`, `ready`, `pushed`, `verified`, `flows`, and `destroyed` for a deletion. Each is
recorded before the next begins, so a restarted core resumes
([Constitution VIII](../design/constitution.md#viii-reconcile-to-desired-state)).

**Pin** *(orchestrator)* — What fixes the moment a *stage* is read at, in a form only its
*change source* reads. For Infrahub it is the stage's kind, a branch, a time and the proposed
change's id. The *head*'s has no time until its read resolves one, once the proposed change's
artifact validation is waited for: the later of the reader's `head` and the validation's
completion, or the `head` alone where none completes ([D-085](../design/decisions.md#d-085),
[D-088](../design/decisions.md#d-088)). For NetBox it is the stage's kind, `main`, a mark or the
head, the branch, for a mark the mark as its journal entries give it, and the change's id, the
branch's `schema_id`, which the branch read again by its name is held to; it holds no time, since
NetBox reads no earlier time ([D-097](../design/decisions.md#d-097)).

**`plan`** — The pure driver call that binds a bundle to a twin and a runtime, given its
allocation, and returns a *deployment*. It is the only binding step
([D-011](../design/decisions.md#d-011)). It refuses a runtime port two cabled interfaces
share (`interface.port.shared`, [D-045](../design/decisions.md#d-045)).

**Plan 0** — The working document that holds a *build phase*'s branches, the order of its
plans, its rule for live runs, the names the plans share, and each place the build has bent
a decision's text. Plans live under `local/plans/`, outside the tree ([D-080](../design/decisions.md#d-080)).

**Platform package** — The data that makes one network operating system supported:
interface rules, push, readiness, gNMI paths, conformance, fidelity, and a section per
runtime ([`platform-package-1.schema.json`](../formats/platform-package-1.schema.json),
[Constitution II](../design/constitution.md#ii-platforms-are-data-never-code)). Adding a platform is
writing one. It replaces the *PSP*.

**Principal** — Who a request acts for, named by its bearer token. Every run records its
principal, and the audit log names one for every change to a twin.

**Probe** — Two synthesized *probe hosts* on two uncabled ports of the twin, which send
traffic across it. Declared outside intent and carried in the blueprint's `probes`; a
declaration file ([`probes-1.schema.json`](../formats/probes-1.schema.json)) is read by a
producer, never the core ([D-008](../design/decisions.md#d-008)).

**Probe host** — One of a probe's two synthesized nodes, `<probe>-a` and `<probe>-b`, each
cabled to its device's port with an IPv4 address and a gateway.

**Probe package** — The data for one probe format, such as `ping`: the host's image and
set-up commands, its readiness, and the flow and burst commands
([`probe-package-1.schema.json`](../formats/probe-package-1.schema.json)).

**Problem document** — An RFC 9457 answer for a request that is malformed, unauthorised,
refused or conflicting, and for a server fault
([`problem-1.schema.json`](../formats/problem-1.schema.json)). Its `rule` is the stable
id, and several faults ride in `findings`.

**Proposed change** *(orchestrator)* — Infrahub's unit of review: a branch's change toward
`main`, with its checks. The orchestrator rehearses its *stages*.

**PSP (Platform Support Package)** — The archived repository's platform package format,
`0.7`. Platform package 1 replaces it.

**Pull credential** — What a gated image is pulled with on clabernetes, named by its
package's `image.pull_secret`: the image prefix in `FYLGJA_CREDENTIAL_<NAME>_REGISTRY` (a
host, an optional port and an optional path, with no scheme), with the registry's login in
`_USERNAME` and `_PASSWORD`. A twin's allocation records every prefix the provider holds at
admission, and `apply` makes each one a Secret in the twin's namespace; none is ever a file
([D-057](../design/decisions.md#d-057)).

**Push** — Delivering each node the configuration the source rendered, by the mechanism its
package names: JSON-RPC for SR Linux, eAPI for EOS, once the node is ready (its push
transport answers). Every push is a *replace*; Fylgja renders no configuration
([D-007](../design/decisions.md#d-007)).

**Reader** — A library that turns one source of truth into blueprints, by one documented
mapping, reporting every fault in one pass and writing no blueprint on failure
([Constitution III](../design/constitution.md#iii-the-blueprint-is-the-contract)). Each source
of truth Fylgja reads has its own, and no reader imports another: the Infrahub reader,
`fylgja-infrahub` ([D-082](../design/decisions.md#d-082)), under
[`readers/infrahub/`](../readers/infrahub/README.md), and the NetBox reader, `fylgja-netbox`
([D-095](../design/decisions.md#d-095)), under [`readers/netbox/`](../readers/netbox/README.md),
each the library and a command of that name.

**Reader document** — The input a read takes beside its branch and scope, in each reader's
own format, holding what the source cannot. For the Infrahub reader, `infrahub-reader-1`, whose
read is given a time as well: which manufacturer and platform pair is which platform package,
the name of the artifact that holds a device's configuration, and whether probes are read
([D-082](../design/decisions.md#d-082)). For the NetBox reader, `netbox-reader-1`: which pair
is which platform package, and the name of the configuration context that declares the probes,
or none; NetBox renders each device's configuration itself
([D-095](../design/decisions.md#d-095)). Neither holds an address or a credential.

**Reconcile loop** — The core's own loop that drives each twin's observed state toward its
desired state through its driver, phase by phase ([D-023](../design/decisions.md#d-023)).

**Rehearsal** *(orchestrator)* — A twin created at a change's *baseline stage*, stepped to
each later stage and verified after each, destroyed whatever happened, with the report posted
on the change: one twin a rehearsal, named from the change and the run
([D-086](../design/decisions.md#d-086)). It ends `passed`; `failed`, where the change failed
at a stage; *not rehearsed*; or `stopped`, where it was stopped before anything could be said
of the change.

**Rejection fixture** — A document under `testdata/` that a loader or the compiler must
refuse, carrying one fault, named in its file name and its header comment or `source`
envelope; the test beside the code holds a row per fixture saying the rule and the JSON
pointer or object it must report, and nothing else.

**Replace** — The push that resets a node to its *baseline*, the configuration its kind
left at deploy (host name, linked ports, LLDP, gNMI), and applies the whole configuration in
one atomic commit ([D-027](../design/decisions.md#d-027)).

**Residue** — What a killed or hand-removed lab leaves on the host with no node left: its
block of `/etc/hosts` entries, its ssh config and its management network. It is an
`Inspection` state. Recovery rule 2 clears the root-owned part, the host entries and the ssh
config, by deploying, then destroying ([D-023](../design/decisions.md#d-023)). On
clabernetes it is the twin's namespace holding none of its pods.

**Restore** — A *run* of the loop's own, by the principal `core`, taken when a kick finds a
node of a settled twin at another *incarnation* than the record holds: the node was replaced
behind the core's back and lost its push, so it is readied and pushed again, and verify run,
which is advisory, as a step does for a node whose incarnation moved. Nothing is applied or
torn down, and `last_step` is not touched; on a twin that runs what its spec asks, `Ready` is
False for `twin.restoring` while it runs ([D-067](../design/decisions.md#d-067)). A node
missing or not running is never made: it is waited for through its boot window, then reported
(`twin.node.missing`), and once every node runs again a restore verifies the twin before it is
`Ready`.

**Resync** — The loop's periodic re-queueing of every twin, every `FYLGJA_RESYNC_S` (300 s
by default), so a missed runtime event is only late, never lost
([D-023](../design/decisions.md#d-023)).

**Revision** — A twin record's write counter, bumped by every write, the client's or the
loop's. The API serves it as the ETag; a client sends it back as `If-Match`, and the write
fails `412` if the record has moved ([D-025](../design/decisions.md#d-025)).

**Ruling** — A decision taken during a *build phase* on the maintainer's behalf, written in the
*ledger* as what was decided, why, and what it costs if wrong, and reported before the
*landing*. One that departs from a decision's text becomes a new entry then ([D-080](../design/decisions.md#d-080)).

**Run** — One long operation on a twin (create, step, restore or destroy): a ULID, the
principal, a state and, once ended, a *verdict*. A write to the twin queues it, or the loop
takes a *restore* of its own, and the twin's status names it while it runs; it is read by
id, its events by cursor, and cancelled by id (`202`). One run acts on a twin at a time.

**Run event** — One event of a run: a sequence number, a time, a phase and an outcome,
read after a cursor (`GET /v1/runs/{id}/events?after=N`). Timings are events.

**Runner** *(orchestrator)* — The process that serves the *edge*'s two flows to a Prefect
server, as the deployments `stage-plan/main` and `twin-rehearse/main`, each run a process of
its own beneath it. It holds the two tokens a rehearsal needs, the core's for the principal
`orchestrator` and one of the Infrahub account `fylgja-orchestrator`, or under NetBox one of the
NetBox account `fylgja-orchestrator`; a check holds neither
([D-085](../design/decisions.md#d-085), [D-097](../design/decisions.md#d-097)). A runner serves
one source, and a Prefect server one source's runner.

**Settle** *(orchestrator)* — Verify asked again after a *rehearsal*'s create, every 5 s,
until it holds or the settle budget passes, 180 s by default: verify does not wait outside a
step's run, and a twin's protocols take a moment to come up. What still fails then belongs to
the *baseline stage* ([D-086](../design/decisions.md#d-086)).

**Site overlay** — The kustomize overlay under `local/deploy/`, never committed, that deploys
the core on one cluster over the base under `deploy/`: the image's registry and tag, the Secrets
and the ConfigMap the base's pods name, made from files of mode `0600`, and the Service's
address. The base holds what is the same at every site, the overlay what a site decides
([D-062](../design/decisions.md#d-062), [deploy/README.md](../deploy/README.md)).

**Snapshot** — The earlier name for a blueprint, still used by the archived repository's
formats (snapshot 2) ([D-006](../design/decisions.md#d-006)).

**Source envelope** — Where a blueprint came from (source, branch, point in time, scope,
mapping, when it was read), carried as the opaque `source` object. The core stores and
returns it, and never reads or hashes it
([Constitution VI](../design/constitution.md#vi-intent-is-addressed)).

**Source of truth** *(orchestrator)* — The system that holds a network's intent, such as
*Infrahub* or *NetBox*. A *reader* reads its intent; a *change source* reads its changes and
posts the report to it.

**Stage** *(orchestrator)* — A moment of a change. Of a proposed change in Infrahub: its *branch
point*, a *mark* the operator records on the branch, or its *head*
([D-088](../design/decisions.md#d-088)). Of a branch in NetBox: `main` as it stands, a *mark*
taken as the branch is built, or its *head*, the branch as it stands
([D-097](../design/decisions.md#d-097)). The orchestrator resolves a stage to a blueprint
through the *reader*, and a NetBox mark from the core, which keeps its blueprint.

**Stage record** *(orchestrator)* — The example's file a twin, saying which change and *stage*
a twin made by `twin create` or `twin step` stands at, and the blueprint id that stage read as.
It is trusted only while that id is the twin's, and `twin step` with no stage named takes the
twin to the stage after it ([D-086](../design/decisions.md#d-086)).

**Spec** — The part of a twin record a client writes: the blueprint or bundle, the driver,
and whether the loop may restart nodes. Writing a new spec creates or steps the twin
([D-025](../design/decisions.md#d-025)).

**Stale configuration** — A device's configuration artifact generated before the latest write to
the intent it renders from: the device, the names of its platform and manufacturer, its
interfaces, their addresses, its cables and the names of their far ports and far devices, by their
stamps and the events of the branch and of `main` up to the branch's making, the task workers' own
writes not counting. The Infrahub *reader* refuses it by device, `artifact.stale`, since Infrahub
regenerates an artifact only when asked; a caller that knows a regeneration completed gives that
time as `generated_since` ([D-082](../design/decisions.md#d-082)).

**State store** — The one interface behind which twin records, runs and their events,
blueprints, bundles and deployments live: a directory locally, S3-compatible object storage
in production. No database
([Constitution IX](../design/constitution.md#ix-state-lives-behind-one-store-no-database)).
The local store's files are `lock`, `blueprints/<id>.json`, `bundles/<id>/manifest.json` and
`configs/<node>.cfg`, `deployments/<id>/deployment.json` with the rendered files beside it,
`twins/<name>.json`, and `runs/<ulid>.json` with `runs/<ulid>.events.ndjson`
([D-041](../design/decisions.md#d-041)). The object store keeps the same keys under its
prefix, with no `lock`, each event an object of its own, `events/<ulid>/<seq>.json`, and a
marker for each run of a twin, `twin-runs/<twin>/<ulid>` ([D-061](../design/decisions.md#d-061)).

**Status** — The part of a twin record only the reconcile loop writes: conditions, phase,
the running blueprint, bundle and deployment, the nodes, the last step and the observed
generation ([D-025](../design/decisions.md#d-025)).

**Step** — Taking a running twin to another blueprint or bundle without a rebuild, asked for
by writing a new *spec* (`fylgja-core twin step`, which waits for its run; with `--dry-run`, it
prints what the step would change). It is a run of the create's phases and two more
([D-050](../design/decisions.md#d-050)): the new bundle compiled, admitted over the allocation
the twin holds, planned, and the driver asked what changes; then, before anything is touched,
refused where it must be (a *diverged* twin, a change the driver cannot make, a node it would
restart or recreate without `allow_restart` in the spec); then applied over the running lab,
re-cabling where the kind allows and replacing each node that must be, each node that changed
readied and pushed, and verify waited for until it holds or `FYLGJA_STEP_WAIT_S` runs out
(`verified`), and each probe's flow recorded not started (`flows`). It ends stepped; or
unchanged when the bundle is the twin's, at `compiled` when every device node holds it, and
otherwise once it has readied, pushed and verified each one that holds nothing, as a *restore*
that failed or was cancelled leaves a node, with no plan or apply; refused, cancelled before its
apply began, or, unchanged, failed to ready or push such a node, with the twin running what it
ran; or *diverged*, when it fails or is cancelled from its apply on: a step is never rolled back
([D-029](../design/decisions.md#d-029)).

**Thin CLI** — `fylgja-core`, a client of API 1 like any other. It renders documents as
text and exits 0 for ok, 1 for a negative verdict, 2 for a problem, a transport failure or
a usage error, and 3 for a twin left dirty.

**Token file** — The server's file of client tokens, named by `FYLGJA_TOKENS`: one
`<sha256 hex of the token> <principal>` per line, so it never holds a token itself and several
are valid at once ([D-025](../design/decisions.md#d-025)). A client holds its token in
`FYLGJA_API_TOKEN` and sends it as a bearer token; the server hashes it, looks up the
*principal* and discards it.

**Twin** — A running copy of a network's intent: its operating system images, wired as the
blueprint says and configured as the source rendered, named and in its own isolation unit.

**Twin name** — A DNS-1123 label of at most 40 characters: the twin record's key, the API
path, and the name a driver gives the twin's lab or namespace.

**Twin record** — The core's record of one twin in the state store, the same on every
runtime, and the twin resource the API serves: its *spec* and *status*, its *generation*
and *revision*, changed only by compare-and-set
([`twin-record-1.schema.json`](../formats/twin-record-1.schema.json),
[D-025](../design/decisions.md#d-025)).

**ULID** — A 26-character, time-sortable id (48 bits of milliseconds, 80 random bits,
Crockford base32), made in the core, which every run carries
([D-040](../design/decisions.md#d-040)).

**Unmanaged** — A device node whose bundle gives it no configuration (the CLI prints the word).
The core pushes nothing to it and compares nothing of its configuration, and it runs its
kind's baseline ([D-048](../design/decisions.md#d-048)).

**Verdict** — A findings document: what a compile, a package validation, a plan, a run or a
verification concluded, with a status and every finding behind it
([`findings-1.schema.json`](../formats/findings-1.schema.json)).

**Verified fact** — External behaviour checked on the running system, with its version
and date ([verified-facts.md](../design/verified-facts.md)).

**Verify** — Reading a running twin against its bundle: each node's host name, asserted
against its device name for a node with no configuration and otherwise read and reported;
each linked port's state; each link's LLDP neighbour at both ends, judged against the far
node's read host name; the record's claim; and each probe's *burst*
([D-051](../design/decisions.md#d-051)). A node it cannot read ends the verdict `failed`,
never `nonconforming`. It changes nothing; a waiting verify runs only inside a step.

**Watch** — A `GET` of one twin or every twin with `watch=true`, answered as server-sent
events: one per change, each carrying the whole record. A client that reconnects with the
last *revision* it saw misses nothing ([D-025](../design/decisions.md#d-025)). The client
library does so itself when a stream ends early.


**Work queue** — The loop's queue of twin names waiting to be reconciled. A name is never
queued twice, and each twin has at most one worker at a time ([D-023](../design/decisions.md#d-023)).
