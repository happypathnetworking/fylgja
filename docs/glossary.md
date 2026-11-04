# Glossary

The terms Fylgja uses, alphabetically. A term marked *(orchestrator)* belongs to the
orchestrator, in the archived repository for now: the core never uses it, but a reader
meets it in a blueprint's `source` or in these documents. See also
[architecture.md](../design/architecture.md) and the formats in [`formats/`](../formats/README.md).

**Admission** — The check that a twin fits before anything is applied. `admit` reserves its
allocation, and the deployment's *demand* (runtime nodes, and the sums of the packages'
per-node CPU and memory) is compared with the driver's free capacity. A twin that does not
fit is refused with rule `admission.capacity` ([D-019](../design/decisions.md#d-019)).

**`admit`** — The driver call that reserves what a twin is bound to (a lab name and
management subnet, a namespace, a device reservation) and records it in the twin record by
*compare-and-set*, or refuses with the reason ([D-017](../design/decisions.md#d-017)).

**Allocation** — What `admit` reserved for one twin: `{lab, mgmt_subnet}` on containerlab,
`{namespace}` on clabernetes, `{reservation, devices}` on hardware. `plan` takes it as an
input, and `destroy` releases it.

**API 1** — The core's HTTP interface and the only way a client reaches it: resources under
`/v1/`, every long operation a *run*, verdicts as findings and refusals as problem
documents ([`api-1.openapi.yaml`](../formats/api-1.openapi.yaml),
[D-025](../design/decisions.md#d-025)). The frozen Go core's API is also version 1; they share
nothing else.

**Audit log** — The log lines, on the same stream as every other, that carry the principal and
the action of every write to a twin, so that every change is attributable
([Constitution X](../design/constitution.md#x-report-honestly)).

**Backoff** — The loop's growing delay before it retries a twin after a transient failure:
doubling from 1 s to a 60 s ceiling, reset by a pass that completes
([D-023](../design/decisions.md#d-023)).

**Blueprint** — The core's one input: the network (devices, interfaces, links, each
device's rendered configuration) and the probes declared beside it, with an opaque *source
envelope* ([`blueprint-1.schema.json`](../formats/blueprint-1.schema.json),
[D-006](../design/decisions.md#d-006), [D-006](../design/decisions.md#d-006)). A *producer* (the orchestrator, or
a hand-written file) writes it; the core files it by id, compiles it and returns it
unchanged. It was earlier called a *snapshot*.

**Blueprint id** — The lowercase-hex SHA-256 of the RFC 8785 (JCS) canonical JSON of
`{network, probes}` alone, so the same topology read from two branches has one id. Every
list must arrive sorted and unique; the core rejects one that is not
(`blueprint.unsorted`, `blueprint.duplicate`) and never sorts it.

**Bundle** — What the compiler makes of one blueprint and the loaded packages: a
`manifest.json` (nodes, *mapping rows*, links, placed probes, the blueprint id) and one
`configs/<node>.cfg` per node ([`bundle-1.schema.json`](../formats/bundle-1.schema.json)).
It is runtime-neutral and holds nothing that belongs to one twin, so one bundle can back
many twins on any driver ([D-011](../design/decisions.md#d-011)). Its id hashes its files.

**Burst** — A probe's verdict in *verify*: a fixed count of echoes from one probe host to
the other, held when every reply comes back ([D-008](../design/decisions.md#d-008)).

**`capabilities`** — The driver call that says what a driver can do: provision nodes or
claim them, change links on a running twin, forward in software or hardware, reach nodes
directly or by proxy, and keep twins apart by names alone or by the network. Code above the
*driver seam* may branch on a capability, never on a runtime.

**clabernetes** — containerlab on Kubernetes, one pod per node. The production *driver*,
with a namespace and a NetworkPolicy per twin and a LoadBalancer per node
([D-017](../design/decisions.md#d-017), [D-020](../design/decisions.md#d-020)). It is developed on *kind*, a
Kubernetes cluster in Docker ([D-022](../design/decisions.md#d-022)).

**Compare-and-set** — A write that succeeds only if the record's *revision*, its write
counter, is the one the writer read. Every change to a twin record is one, so two runs never
overwrite each other ([D-023](../design/decisions.md#d-023)).

**Compiler** — The pure function from a blueprint and packages to a bundle, with no I/O,
clock or environment ([Constitution V](../design/constitution.md#v-the-compiler-is-pure-identity-is-content)).
It answers the bundle id, the manifest, the compile's fidelity and its findings.

**Conformance suite** — The tests a *platform package* passes to count as supported. The
*driver conformance suite* is one set of scenarios run on each driver's own runtime.

**containerlab (local driver)** — containerlab runs network operating system containers as
a lab from a topology file. The local *driver* uses it for development and the live tier,
with one lab per twin, so neither needs Kubernetes.

**Core** — The deployable this repository builds: it turns a blueprint into a named twin,
and steps, verifies, shows and destroys it. It knows no source of truth.

**Credential provider** — The one source of node logins: the environment locally, Secrets
on a cluster. A platform package names its login by a `credentials` name, never a value.

**CTM (Canonical Topology Model)** — The archived repository's network body, version 2,
which snapshot 2 wrapped. Blueprint 1 replaces it.

**Deployment** — What a driver's `plan` returns: the rendered runtime files (for
containerlab, `topology.clab.yml` named for the twin), the allocation, the *demand* and the
fidelity of this twin on this runtime
([`deployment-1.schema.json`](../formats/deployment-1.schema.json)). The same plan always
gets the same id.

**Desired state** — What a twin should be. In the twin record it is the *spec*.

**Dry run** — A `PUT` of a twin's spec with `dry_run=true`: admission and the driver's
`plan` run and answer what would happen, and nothing is written
([D-025](../design/decisions.md#d-025)).

**Diverged** — A twin whose step failed or was cancelled after touching it, left part on its
old bundle and part on its new one. It can be shown, verified and destroyed
([D-029](../design/decisions.md#d-029)).

**Driver** — The code that runs twins on one runtime behind the *driver seam*: local
`containerlab`, `clabernetes`, and `hardware` later ([D-017](../design/decisions.md#d-017),
[Constitution XIII](../design/constitution.md#xiii-runtimes-are-drivers)).

**Driver registry** — `fylgja_core.drivers`, the one module above the *driver seam* that
names a runtime: it lists the drivers the core serves, makes one by name, and answers a
driver's capabilities ([D-046](../design/decisions.md#d-046)).

**Driver seam** — The seven calls every driver implements: `capabilities`, `admit`, `plan`,
`apply`, `inspect`, `destroy` and `endpoints`. Each is idempotent.

**`endpoints`** — The driver call that returns each node's management address. The push,
readiness, verify and flows dial it, whatever the runtime.

**Fidelity** — What a twin models exactly, approximates, synthesizes (probe hosts) or omits,
and why; asserted, never measured ([Constitution X](../design/constitution.md#x-report-honestly)). The
compile answers its runtime-independent part, and each deployment adds how nodes forward on
its runtime. An *approximation* is a package's own sentence; an *omission* is an interface
left out, with its reason.

**Finding** — One thing an operation found: a stable rule id, a severity and a message.
Findings make up a *verdict* or a problem document's `findings`.

**Flow** — Traffic a step runs between a probe's two hosts while it changes the twin. Its
*transient loss* (packets lost, the longest gap) is reported, never asserted.

**Frozen Go core** — The core as built in Go, kept as the reference implementation in the
*archived repository*, which also holds the orchestrator and the earlier formats
([D-005](../design/decisions.md#d-005)). It explains behaviour and supplies test scenarios, gets fixes
only, and is retired once the new core replaces it ([D-001](../design/decisions.md#d-001)).

**Generation** — A twin's counter of what was asked: it goes up by one with every change of
*spec* and with a deletion request. The loop copies it to `status.observed_generation`
once it has acted on it, so a client can tell whether the status is current
([D-025](../design/decisions.md#d-025)).

**Hardware driver** — A later release's driver: it claims devices from a pool rather than
creating nodes, cannot re-cable, and resets each device to a stored baseline. Its paper
shape checks the seam ([design/core.md](../design/core.md)).

**`hot_add_ports`** — A platform package's statement of whether a port added after boot
appears in the network operating system when a link to it is added live. cEOS: `false`.

**Incarnation** — A node's current instance: a container's start time locally, a pod's uid
on clabernetes. When it changes, the node lost its push, and the loop pushes it again
([D-023](../design/decisions.md#d-023)).

**Infrahub** *(orchestrator)* — OpsMill's source of truth, from which the orchestrator reads
devices, cables and each device's configuration rendered by a template.

**Isolation unit** — What a driver gives each twin so twins share nothing mutable: a lab
with its own management network, a namespace, or a device reservation
([Constitution VII](../design/constitution.md#vii-twins-are-named-and-isolated),
[D-019](../design/decisions.md#d-019)). A resource labelled as a twin's with no record behind it is an
*orphan*, found by a label sweep.

**Kind** — containerlab's built-in support for one network operating system
(`nokia_srlinux`, `ceos`): its interface aliases, default login and baseline. A platform
package states only what the kind does not ([D-015](../design/decisions.md#d-015)); for a kind with
no aliases (cEOS), that includes a *rename rule* from production names to the kind's ports.

**`link_apply_mode`** — How a link change reaches a running node of a kind: `live`,
re-cabled with no restart, or `restart`. Set by the platform package, written on each node
at create, and never changed on a running twin.

**Lossy** — A rename that drops a placeholder of its rule's match, so that two production
names can land on one runtime port. The plan counts lossy mappings and shared ports per
deployment, and omits an uncabled interface whose port a cabled one holds (`shared`).

**Mapping row** — One row of a bundle's mapping per blueprint interface: the device, the
production interface name, the rule that matched, the *disposition* (`cabled`, `uncabled`,
`management` or `omitted`), the node's own port name, and an omission's reason.

**Observed state** — The part of a twin record only the reconcile loop writes: the
generation it acted on, the phase, run, blueprint, bundle, deployment, nodes and last step,
and the *conditions* `Ready`, `Stepping` and `Diverged`, each with a stable reason.

**Orchestrator** *(orchestrator)* — The other deployable: it reads Infrahub, resolves
stages, rehearses proposed changes and reports on them. It lives in the archived repository
for now, and will write blueprint 1 and call API 1 ([D-003](../design/decisions.md#d-003)).

**Phase** — One ordered stage of the reconcile loop: `compiled`, `admitted`, `planned`,
`applied`, `ready`, `pushed`, `verified`, `flows`, and `destroyed` for a deletion. Each is
recorded before the next begins, so a restarted core resumes
([Constitution VIII](../design/constitution.md#viii-reconcile-to-desired-state)).

**`plan`** — The pure driver call that binds a bundle to a twin and a runtime, given its
allocation, and returns a *deployment*. It is the only binding step
([D-011](../design/decisions.md#d-011)). It refuses a runtime port two cabled interfaces
share (`interface.port.shared`, [D-045](../design/decisions.md#d-045)).

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

**Push** — Delivering each node the configuration the source rendered, by the mechanism its
package names: JSON-RPC for SR Linux, eAPI for EOS, once the node is ready (its push
transport answers). Every push is a *replace*; Fylgja renders no configuration
([D-007](../design/decisions.md#d-007)).

**Reconcile loop** — The core's own loop that drives each twin's observed state toward its
desired state through its driver, phase by phase ([D-023](../design/decisions.md#d-023)).

**Rehearsal** *(orchestrator)* — A twin created at a proposed change's first stage, stepped
to each later stage and verified after each, destroyed whatever happened, with the report
posted on the proposed change.

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
config, by deploying, then destroying ([D-023](../design/decisions.md#d-023)).

**Resync** — The loop's periodic re-queueing of every twin, so a missed runtime event is
only late, never lost ([D-023](../design/decisions.md#d-023)).

**Revision** — A twin record's write counter, bumped by every write, the client's or the
loop's. The API serves it as the ETag; a client sends it back as `If-Match`, and the write
fails `412` if the record has moved ([D-025](../design/decisions.md#d-025)).

**Run** — One long operation on a twin (create, step or destroy): a ULID, the principal, a
state and, once ended, a *verdict*. A write to the twin queues it, and the twin's status
names it while it runs; it is read by id, its events by cursor, and cancelled by id
(`202`). One run acts on a twin at a time.

**Run event** — One event of a run: a sequence number, a time, a phase and an outcome,
read after a cursor (`GET /v1/runs/{id}/events?after=N`). Timings are events.

**Snapshot** — The earlier name for a blueprint, still used by the archived repository's
formats (snapshot 2) ([D-006](../design/decisions.md#d-006)).

**Source envelope** — Where a blueprint came from (source, branch, point in time, scope,
mapping, when it was read), carried as the opaque `source` object. The core stores and
returns it, and never reads or hashes it
([Constitution VI](../design/constitution.md#vi-intent-is-addressed)).

**Source of truth** *(orchestrator)* — The system that holds a network's intent, today
Infrahub. Only the orchestrator reads one.

**Stage** *(orchestrator)* — A moment of a proposed change: its branch point, a mark the
operator records, or its head. The orchestrator resolves a stage to a blueprint.

**Spec** — The part of a twin record a client writes: the blueprint or bundle, the driver,
and whether the loop may restart nodes. Writing a new spec creates or steps the twin
([D-025](../design/decisions.md#d-025)).

**State store** — The one interface behind which twin records, runs and their events,
blueprints, bundles and deployments live: a directory locally, S3-compatible object storage
in production. No database
([Constitution IX](../design/constitution.md#ix-state-lives-behind-one-store-no-database)).
The local store's files are `lock`, `blueprints/<id>.json`, `bundles/<id>/manifest.json` and
`configs/<node>.cfg`, `deployments/<id>/deployment.json` with the rendered files beside it,
`twins/<name>.json`, and `runs/<ulid>.json` with `runs/<ulid>.events.ndjson`
([D-041](../design/decisions.md#d-041)).

**Status** — The part of a twin record only the reconcile loop writes: conditions, phase,
the running blueprint, bundle and deployment, the nodes, the last step and the observed
generation ([D-025](../design/decisions.md#d-025)).

**Step** — Taking a running twin to another blueprint or bundle without a rebuild, asked for
by writing a new *spec*: diff the two bundles (nodes, links, probes), re-cable where the
kind allows, replace each changed node, then wait for the twin to settle. A step that would
restart a node needs `allow_restart` in the spec.

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

**Verdict** — A findings document: what a compile, a package validation, a plan, a run or a
verification concluded, with a status and every finding behind it
([`findings-1.schema.json`](../formats/findings-1.schema.json)).

**Verified fact** — External behaviour checked on the running system, with its version
and date ([verified-facts.md](../design/verified-facts.md)).

**Verify** — Reading a running twin against its bundle: each node's host name, each linked
port's state, each link's LLDP neighbours, and each probe's *burst*. It changes nothing; a
waiting verify runs only inside a step.

**Watch** — A `GET` of one twin or every twin with `watch=true`, answered as server-sent
events: one per change, each carrying the whole record. A client that reconnects with the
last *revision* it saw misses nothing ([D-025](../design/decisions.md#d-025)).


**Work queue** — The loop's queue of twin names waiting to be reconciled. A name is never
queued twice, and each twin has at most one worker at a time ([D-023](../design/decisions.md#d-023)).
