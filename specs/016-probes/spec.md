# Feature Specification: Probes

**Feature Branch**: `016-probes`

**Created**: 2026-10-28

**Status**: Draft

**Input**: User description: "SPECIFY_FEATURE_DIRECTORY=specs/016-probes GIT_BRANCH_NAME=016-probes. 0.3, the fourth of its five specs: probes, ping only, as docs/roadmap.md's F-014 and Release 0.3 section define it. Read specs/016-probes/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. It names a new Infrahub kind, so load the infrahub-managing-schemas skill before naming it. Specify what the operator gets, not a new design."

Release 0.3 is exploratory coding toward the production refactor
([roadmap](../../docs/roadmap.md#release-03)), and this is its fourth spec
([F-014](../../docs/roadmap.md#f-014)). Since 018 the core's one input is the snapshot, a
document that wraps the CTM and carries `probes`, a list required and empty: "this intent,
with no probe declarations" ([D-061](../../docs/decisions.md#d-061)). Since 019 a twin is
frozen at its snapshot and changes only when the operator steps it
([D-062](../../docs/decisions.md#d-062)), so whatever is lost across a step is the step's
and nothing else's. This feature fills the slot. **A probe is the first input to the core
that is not intent**: a declaration the operator writes beside intent, carried in the
snapshot, compiled into synthesized hosts, and measured across a step. The headline demo is
loss during a change applied to a running twin, and the seam it proves for the
[production shape](../../docs/roadmap.md#the-production-shape) is an input the orchestrator
writes that no source of truth owns.

What the operator gets: a **probe declaration**, a file of their own, in which each probe
names itself, its format, `ping`, and two endpoints, each a device, one of its interfaces,
the address the probe's host takes with its prefix length, and its gateway, the device
interface's address; the same declaration kept in Infrahub as **`FylgjaProbe`**, one object
per probe on `main`, one source of the file and not the declaration; `--probes <file>` on
every command that takes a snapshot from intent, the kind's probes when the flag is left
out, and none when `main` holds none; a snapshot of version `2` that carries the list and
hashes it; a compile that turns each endpoint into a synthesized `linux` host on a
synthesized link to its device interface, all three in the manifest under provenance
`synthesized`, and refuses a probe it cannot place; a **`ping` probe package** beside the
platform packages, the first format of a second package kind; a step that starts every
probe's flow before its first change and reports, per probe, the packets sent, the packets
lost and the longest gap, labelled container timing and never asserted; a fourth kind of
verify assertion, a short burst after the wait that must get every reply, whose failure
fails the stage through 015's gate as any finding does; a `loss` column in the rehearsal's
report; and Infrahub's template rendering each interface's addresses, so that the device
side of a probe reaches the node by the only road Constitution IV allows. The brief's
[Decided](brief.md#decided) list is settled and restated here only where a requirement
needs the sentence. The decision entry (D-064), the kind's exact shape, the package's
mechanism and every exact name and wording the brief [leaves to the plan](brief.md#left-to-the-plan)
are the plan's to write.

Five actors appear below. **The operator** runs the lab host and Fylgja, models intent in
Infrahub, writes probe declarations in a file or in `FylgjaProbe`, marks stages and takes
snapshots with `intent read --out`. **The server**, `fylgja serve`, reads probes, takes and
files snapshots, compiles, starts workflows and runs `twin verify`'s burst; every refusal
is its. **The worker** runs the four workflows and, from this feature, the activities
that start and read a probe's flow. **The checks**, `fylgja-step` and `fylgja-twin`, are
clients inside Infrahub's task workers whose stage plan and rehearsal carry the probes and
whose gate does not change. **Infrahub** renders every device's configuration, from this
feature with each interface's addresses. Any second probe format, loss as a graph or an
export ([F-013](../../docs/roadmap.md#f-013)), any change to the CTM, the reader, the
mapping or the schema library's files, the NetBox reader (F-025), the orchestrator, and
any read of a node's running configuration are out of this feature.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A declared probe becomes a host on the twin (Priority: P1)

The operator writes a probe declaration file: one probe, `ping`, from an uncabled
interface of one device to an uncabled interface of another, each endpoint carrying the
address its host takes with its prefix length and its gateway, the device interface's
address, which intent holds and Infrahub renders. They run `fylgja twin create --branch
<b> --probes <file>`. The server reads the branch, reads the file, takes a snapshot of
version `2` whose `probes` list is the file's content, files it under an id that hashes
the probes with the CTM, compiles it and starts the provision workflow. The bundle holds
two synthesized `linux` hosts, one on each endpoint, each on a synthesized link to its
device interface, which takes the device's port as a cabled interface would; the manifest
names each host, each link and each port under provenance `synthesized`, and the bundle's
version is `6`. When the twin is ready, each host is up with its address and a route via
its gateway, and the first host reaches the second across the twin. The same branch taken
with no probes compiles to the bundle it did before this feature, but for the version.

**Why this priority**: nothing else in the feature exists until a declaration reaches a
running twin as a host. It is the seam the production shape names, an input no source of
truth owns, and it proves that the slot 018 reserved, the hash D-061 defined and the
synthesized provenance the CTM has carried since M1 all fit.

**Independent Test**: in tier 1, the three-node fixture's snapshot wrapped with a one-probe
declaration compiles to a bundle with the two hosts, their links and their ports under
provenance `synthesized`, all in the manifest, and the same snapshot with no probes
compiles to the former golden but for the version. In tier 3, a twin created from a
throwaway branch with `--probes` boots the hosts, and a ping from one host's container to
the far host's address is answered.

**Acceptance Scenarios**:

1. **Given** a branch whose devices hold an uncabled, addressed interface each and a
   declaration file naming one `ping` probe between two of them, **When** the operator
   runs `twin create --branch <b> --probes <file>`, **Then** the server files a snapshot of
   version `2` whose `probes` list equals the file's content, compiles it, and the twin
   boots with one host per endpoint, each addressed and routed via its gateway.
2. **Given** that bundle, **When** its manifest is read, **Then** each host, each
   synthesized link and the device port each link takes carry provenance `synthesized`,
   and every other node, link and port carries `intent`, as today.
3. **Given** two declaration files that differ in one probe, **When** each is taken with
   the same branch, **Then** the two snapshots have two ids, and the same file taken twice
   has one.
4. **Given** the ready twin, **When** a ping is sent from one host to the far host's
   address, **Then** it is answered through the two devices, and `twin show` names the
   snapshot as it does for any twin.
5. **Given** a snapshot of version `2` with an empty `probes` list, **When** it is
   compiled, **Then** the bundle equals the one the same intent compiled to under bundle
   `5`, in everything but the version.
6. **Given** `twin create --snapshot <id|file>` of a snapshot that carries probes, **When**
   the operator runs it, **Then** the twin builds with those hosts and no `--probes` is
   read; `--probes` beside `--snapshot` is refused before any connection.

---

### User Story 2 - Transient loss across a step, measured and reported (Priority: P1)

The operator holds a running twin with probes and steps it, to a stage or to a snapshot.
Before the step's first change, the worker starts every probe's flow: a steady ping from
each host to its far host, at the `ping` package's rate. The step runs as today. After the
wait, the worker reads each flow and records, per probe, the packets sent, the packets
lost and the longest gap between two answered packets, in the step record and in `twin
step`'s document, each figure labelled container timing. The figure is never asserted: a
step that loses every packet for a second still ends `stepped`. A step whose target
carries probes the twin's snapshot did not measures the flows the two snapshots share and
gives a host the step adds the verify burst alone.

**Why this priority**: this is the demo the roadmap names, loss during a change applied
to a running twin, and the one thing a probe exists to show. Without the measurement the
hosts are furniture.

**Independent Test**: in tier 1, a step record and a `twin step` document that carry loss
per probe validate under their contracts, with the label on each. In tier 3, a twin with
probes is stepped to a snapshot that disables and re-enables nothing on the probes' path,
and the step's document reports each probe's sent, lost and longest gap, labelled; then it
is stepped to one that restarts a device on the path, and the lost count is non-zero.

**Acceptance Scenarios**:

1. **Given** a running twin with two probes and a target that changes one device's
   artifact alone, **When** the operator runs `twin step --stage <s> --wait`, **Then** the
   flows start before the first push, the step runs and waits as today, and the document's
   step block carries, per probe, packets sent, packets lost and the longest gap, each
   labelled container timing.
2. **Given** a target that restarts a device on a probe's path, **When** the step runs,
   **Then** the probe's lost count is greater than zero, the step's outcome is what it
   would have been without probes, and no finding is raised for the loss.
3. **Given** a twin with no probes, **When** it steps, **Then** no flow starts and the
   step's document carries an empty loss list, as it carries every empty list.
4. **Given** a target whose snapshot carries a probe the twin's does not, **When** the
   step runs, **Then** the shared probes are measured across the step and the added host
   is built, routed and given the verify burst alone, with no transient figure.
5. **Given** a flow that cannot be started, **When** the step runs, **Then** the failure is
   recorded with a stable identifier, and the step's document says which probe was not
   measured and why; whether that is a phase or a finding under `record` is the plan's.
6. **Given** a step without `--wait`, **When** the operator reads the step's document,
   **Then** the loss figures are read at the wait's end as today's wait block is, and the
   dry run carries none.

---

### User Story 3 - Unrecovered loss fails the stage (Priority: P1)

The operator holds a proposed change rehearsed by `fylgja-twin`, whose stages the check
steps through on a twin with probes. At each stage's wait, verify derives from the staged
bundle a fourth kind of assertion beside `host_name`, `port_enabled` and `neighbor`: for
each probe, a short burst from its first host to its second gets N consecutive replies,
N the `ping` package's, read from the host. A burst that gets them holds; one that does
not fails, a finding like any other, so the stage's wait expires on it and the gate fails
the stage, with no change to the gate. The report the check posts on the proposed change
gains a `loss` column between `verify` and `new verification failures`, holding each
stepped stage's transient loss per probe, `—` for a created or refused stage, with the
container-timing caveat in the report's footer; the `rehearsal` document carries the same
per stage. A stage that disables a probe's device interface fails on the new kind. `twin
verify` runs the burst too, from the server, with and without `--wait`.

**Why this priority**: it is the feature's one exit criterion, "a flow that has not
recovered fails the stage", and the first thing a probe says that gates anything. The
measurement of Story 2 is advisory; this is the verdict.

**Independent Test**: tier 3's case 9. Its proposed change gains a stage that disables a
probe's device interface; `fylgja-twin` fails at that stage on the new assertion kind, the
earlier stages pass with their loss figures in the `loss` column, and the thread's table
carries the column. In tier 1, the derivation from a manifest with synthesized hosts, a
verify document with the new kind in its counts and by node, and the report's table with
the column rendered for a stepped, a created and a refused stage.

**Acceptance Scenarios**:

1. **Given** a staged bundle with two probes, **When** verify derives its assertions,
   **Then** it holds one assertion of the new kind per probe beside the three kinds it
   holds today, in a stable order, each naming the probe, the two hosts and the burst's
   expected count.
2. **Given** a ready twin whose probes' paths are up, **When** `twin verify` runs,
   **Then** each burst assertion is held, the counts by kind include the new kind, and the
   document's twin block is as 019 left it.
3. **Given** a stage that disables a probe's device interface, **When** `fylgja-twin`
   rehearses it, **Then** the stage's wait expires with the burst assertion failed, the
   gate marks the stage failed by the same rule that fails it on any finding, and the
   table's `verify` and `new verification failures` columns name it.
4. **Given** a rehearsal of three stages, the first created, the second stepped and the
   third refused at the compile, **When** the report renders, **Then** its table reads
   `| stage | at | snapshot | bundle | step | wait | verify | loss | new verification
   failures | verdict |`, the second row's `loss` holds its transient loss per probe, the
   first and third hold `—`, and the footer carries the container-timing caveat.
5. **Given** a twin with no probes, **When** `twin verify` or a rehearsal runs, **Then** no
   assertion of the new kind is derived, the `loss` column is present and reads `—` in
   every row, and the report is otherwise as 019 left it.
6. **Given** `twin verify --wait` on a twin whose probe path is down, **When** the wait's
   budget ends, **Then** the burst assertion is reported failed, the budget having held
   inside the wait's as the plan sizes it, and the command exits as a failed verify does
   today.

---

### User Story 4 - Probes kept in Infrahub, one list per request (Priority: P2)

The operator keeps their probes in Infrahub rather than in a file: `FylgjaProbe`, a
Fylgja-owned, branch-agnostic kind loaded on `main` beside the stage kind on
[D-045](../../docs/decisions.md#d-045)'s pattern, one object per probe, the file's shape as
attributes, written by object file, the UI or `infrahubctl object create` as
`schema/README.md` shows, and only read by Fylgja. A take with no `--probes` reads the
kind on `main`, unpinned, as stages are read, and a read of the kind yields exactly the
file's content. A `--probes <file>` replaces the kind's probes for that take, and a take
with neither has none, with no warning. A request reads its probes once, at its start, and
every snapshot it takes carries that list: a rehearsal's stages share one, `stage plan`'s
stages share one, and a later create or step reads them afresh.

**Why this priority**: the file is the declaration and works without this story, which
is why it is second; but the kind is how an operator who lives in Infrahub keeps probes
beside the intent they probe, and how the checks, which take no file, find them.

**Independent Test**: tier 2. `FylgjaProbe` loads on `main`; a test writes a probe there,
takes a snapshot of a `fylgja-test-*` branch with no `--probes` and reads the probe in the
snapshot's list; takes one with `--probes <file>` naming another probe and reads the
file's alone; deletes the probe on `main` and takes one with neither and reads an empty
list; and deletes everything it wrote, so that `FylgjaProbe` counts 0 after the tier. In
tier 1, a rehearsal plan of three stages carries one list in every stage's snapshot.

**Acceptance Scenarios**:

1. **Given** `FylgjaProbe` on `main` holding one probe and a take with no `--probes`,
   **When** `intent read --out`, `twin create --branch`, `twin create --stage`, `twin step
   --stage`, `stage plan` or a rehearsal takes a snapshot, **Then** its `probes` list holds
   that probe, read from `main` unpinned, whatever branch or `at` the intent was read at.
2. **Given** the same `main` and a `--probes <file>` naming another probe, **When** the
   take runs, **Then** the snapshot's list holds the file's probe alone.
3. **Given** `main` holding no probe and no `--probes`, **When** the take runs, **Then**
   the snapshot's list is empty, no warning is given, and the take is as it was before
   this feature.
4. **Given** a rehearsal of three stages, **When** its probes are edited on `main`
   between its second and third stage, **Then** all three stages' snapshots carry the list
   read at the rehearsal's start, and the next request reads the edit.
5. **Given** a probe on `main` whose device is not in the request's scope, or whose
   interface the device lacks, **When** the take compiles, **Then** it is refused at the
   compile as Story 5 says, and what a read of the kind yields for it is the plan's.
6. **Given** a twin created with probes from `main`, **When** the operator runs `twin
   step --snapshot <id|file>`, **Then** the step takes the snapshot's probes and reads
   neither a file nor the kind.
7. **Given** the contract tier's close, **When** Infrahub is read, **Then** `FylgjaProbe`
   counts 0, and `main`'s schema holds the kind beside `FylgjaStage`.

---

### User Story 5 - The compiler refuses a probe it cannot place (Priority: P2)

The compiler keeps one rule: a probe it cannot place is refused, at the compile and so at
`fylgja-step` for a stage. A probe is refused when its device is not in the snapshot, when
the device lacks the interface, when intent cables the interface, when the interface is
`mgmt_only`, when an endpoint's address or gateway is malformed, or when its format is one
no package declares. A stage that cables a probe's port, removes its device or deletes its
interface is therefore refused at that stage, and `fylgja-step` fails there: a probe never
vanishes from a stage, hiding the loss it was declared to show, and the remedy is the
declaration's, in the file or in `FylgjaProbe` on `main`. A probe whose port a lossy
package would have shared is recorded under `fidelity.lossy` as a shared port is today.
The refusal of a host address outside the interface's prefix is not made: the CTM holds no
address, and Fylgja asserts nothing of the device's.

**Why this priority**: the compile is pure and the refusals are its whole honesty; each is
a tier-1 case, and the stage rule is what makes a probe safe to keep on `main` beside a
proposed change that moves the topology under it.

**Independent Test**: tier 1, one case per refusal from a declaration against the
three-node fixture's snapshot, each naming the probe, the endpoint and the cause; a stage
plan with a stage that cables a probe's port, whose `fylgja-step` plan marks that stage
refused; and a lossy package's shared port recorded under `fidelity.lossy` for a probe.

**Acceptance Scenarios**:

1. **Given** a probe naming a device the snapshot lacks, **When** it is compiled, **Then**
   it is refused by a stable rule naming the probe, the endpoint and the device, before any
   bundle is written.
2. **Given** a probe naming an interface its device lacks, one intent cables, or one that
   is `mgmt_only`, **When** it is compiled, **Then** each is refused by its own rule,
   naming the probe, the endpoint, the interface and the cause.
3. **Given** a probe whose host address or gateway is not an address, or whose address
   carries no prefix length, **When** it is read or compiled, **Then** it is refused naming
   the field; an address outside the interface's prefix is not refused.
4. **Given** a probe whose format no package declares, **When** it is compiled, **Then** it
   is refused naming the format and the formats the packages declare.
5. **Given** a proposed change whose second stage cables a probe's port, **When**
   `fylgja-step` plans it, **Then** the first stage compiles and the second is refused at
   the compile, so the check fails at that stage as it fails a stage no package matches.
6. **Given** a proposed change whose stage removes a probe's device or deletes its
   interface, **When** it is planned, **Then** that stage is refused at the compile by the
   same rule, and the report's row reads refused.
7. **Given** a probe on a port a lossy package would have shared with another interface,
   **When** it is compiled, **Then** the bundle's `fidelity.lossy` records the port, its
   sharers and the probe, and the compile is not refused for it.

---

### User Story 6 - The `ping` package, the host, the template and the fixture (Priority: P2)

The `ping` probe package sits beside the platform packages, in their pattern and as a
second kind of package: a format value, the image and its acquisition, the mechanism (the
flow's command, how its counters are read, how the burst is run), its rate and its burst's
N, its resources and timeouts, validated by a schema at load, embedded, and overridable
host-wide through the package override directory as a platform package's timeouts are. The
host check refuses a run whose probe image is absent on the host as it refuses a platform's
whose image is absent. The device side of a probe is intent's: Infrahub's template renders
each physical interface's addresses on both platforms, so a probe's device interface comes
up addressed from the artifact, and the reader reads no address. The fixture's three
devices each gain one probe-ready interface, uncabled and addressed, beside the ports they
have, so the fixture's artifacts, its compiled id and its snapshot id move once the
template is imported.

**Why this priority**: the package is how `ping` is a mechanism keyed by a format value
and not a platform branch (D-031), and the template is the only road the device side can
take under Constitution IV; neither changes what the operator types, which is why they
sit below the stories that do.

**Independent Test**: in tier 1, the package schema rejects a package missing each required
field, the shipped `ping` package passes it, the host check refuses a bundle whose probe
image is absent naming the image and the remedy, and `TestCompilerNamesNoPlatform` passes
with a `linux` node in the compiler. In tier 2, once the template is imported, the fixture's
three artifacts carry each addressed interface's lines for its platform, and the fixture's
ids are the ones `CLAUDE.md` records. In tier 3, a mixed twin's EOS device interface comes
up addressed from its artifact, and the SR Linux one from its own.

**Acceptance Scenarios**:

1. **Given** the shipped `ping` package, **When** the server and the worker load their
   packages, **Then** each loads it beside the two platform packages, validated by the
   probe package's schema, and the start-up report names it.
2. **Given** a package file missing the format, the image, the mechanism or a timeout,
   **When** it is loaded from the override directory, **Then** it is refused at load naming
   the field, as a platform package is.
3. **Given** a bundle with probes and the `ping` image absent on the host, **When** a
   provision or a step is asked, **Then** the host check refuses it naming the image and how
   to get it, and nothing is deployed.
4. **Given** a device whose physical interface holds an address in Infrahub, **When** its
   artifact is generated, **Then** the artifact carries that interface's address lines
   for the device's platform, SR Linux's under its subinterface and EOS's as a routed
   port, and a device with no addressed interface renders what it did.
5. **Given** the fixture branch re-seeded, **When** it is read, **Then** each of its three
   devices holds one uncabled, addressed interface beside `ethernet-1/1`, `ethernet-1/2`
   and `mgmt0`, and its snapshot, compiled and artifact ids are the ones recorded.
6. **Given** the compiler with a `linux` host in a bundle, **When**
   `TestCompilerNamesNoPlatform` runs, **Then** it passes: the host is reached by the
   package's format value, never by a branch on what it is.

---

### User Story 7 - The formats, the decision and the documents (Priority: P3)

Snapshot `1` becomes `2` with `probes` defined; bundle `5` becomes `6`, a host node with
no package, no artifact and no bootstrap and the manifest saying what it is instead; the
step, verify and rehearsal documents carry loss and the new assertion kind; the twin record
moves only if it names the hosts; the probe declaration and the probe package each have a
contract with a version; every earlier format a test reads keeps a frozen copy, and every
recorded history replays. One decision entry, D-064, records that a probe is a declaration
outside intent, a file first and a kind second on D-045's pattern, carried by the snapshot,
compiled into synthesized hosts, with a probe package a mechanism keyed by a format value
beside the PSP and the declaration carrying its own gateway; it stands beside D-057, D-061
and D-062 and supersedes nothing. The contracts, the schema README, the package README,
the architecture, the C4 model, the glossary, the development notes, the README's
walk-through, the verified facts, the roadmap, `CLAUDE.md` and `docs/brief.md` say what is
now true.

**Why this priority**: none of it changes what a twin does, and all of it is how F-020 and
F-025 find what this feature built and how an operator of a 0.2 host reads a snapshot of
this build.

**Independent Test**: load each frozen copy and replay each recorded history; validate a
snapshot `2`, a bundle `6`, a step and a verify document with loss against their contracts;
read D-064 and the architecture's §4.2 and find no claim that every node is `intent`; grep
the tracked documents for "ping and iperf3" and find it only in the archive and the
decision log; `make linkcheck` clean.

**Acceptance Scenarios**:

1. **Given** a snapshot of version `1` on disk, **When** the server reads it, **Then** it is
   read as a `2` with no probes, or refused naming both versions as D-061 refuses another
   version; the plan chooses, and either way nothing converts a file in place.
2. **Given** a bundle of version `5`, **When** `twin provision` is asked for it, **Then** it
   is refused by `bundle.version.unsupported` naming both versions, as a `4` is today.
3. **Given** the three goldens, **When** they are re-baselined for bundle `6`, **Then** the
   re-baseline is a commit of its own, and each golden differs from its predecessor in the
   version alone until the fixture's new interface moves them again.
4. **Given** the decision log, **When** D-064 is read, **Then** it says what the brief's
   item 11 says, supersedes nothing, and D-010's "everything is `intent` today" is read as
   history by it.
5. **Given** the constitution, **When** the plan's Constitution Check runs, **Then** it
   says whether a probe package format is a fourth blessed layer by a MINOR amendment
   citing D-064, or falls under Principle II and the PSP's blessing with no amendment, and
   the tree matches its answer.
6. **Given** the glossary, **When** "probe" is looked up, **Then** the readiness probe and
   the probe of this feature are two entries that tell each other apart, and Probe
   declaration, Probe package, Flow, Transient loss and Synthesized node are defined.

---

### Edge Cases

- **A probe whose two endpoints are on the same device**: placed if both interfaces are
  uncabled and not `mgmt_only`; the two hosts ping through the device.
- **Two probes naming the same device interface**: the port is one host's; the second is
  refused at the compile as a cabled interface is, naming the first probe.
- **Two probes with one name**: refused when the declaration is read, naming the name; a
  probe's name is unique in its list, and `FylgjaProbe`'s uniqueness constraint says so.
- **Two hosts with one address**: refused when the declaration is read, naming both
  probes; an address inside no declared prefix of its interface is not refused, since the
  CTM holds no address.
- **A probe on a port a lossy package would have shared**: placed, and recorded under
  `fidelity.lossy` with the sharers; the port is the probe's.
- **A `--probes` file that is empty, or whose declaration lists no probe**: a take with an
  empty list, as a take with neither; a file that is not a declaration is refused naming
  the file and the field.
- **`--probes` on `twin create --snapshot`, `twin step --snapshot`, `twin compile` or `twin
  provision`**: refused before any connection as a conflict, since the snapshot or the
  bundle already says what it carries.
- **A snapshot `2` sent as a file whose probes list is not the contract's**: refused by
  `snapshot.invalid` naming the element, before any compile, as a sent snapshot's CTM is
  held to its own rules today.
- **A step whose target drops a probe the twin has**: the host is torn down with its link
  as a node intent removes is; whether its flow is read first is the plan's.
- **A step whose target adds a probe**: the host is built and routed by the step, gets the
  verify burst at the wait, and has no transient figure, since it had no flow before the
  first change.
- **A cancelled step**: its flows are stopped with the step; what the record says of them
  is the plan's.
- **A flow that cannot be started**: recorded with a stable identifier; whether it is a
  phase or a finding under `record` is the plan's; the step goes on.
- **A probe's host that does not boot**: the provision fails at readiness as a device that
  does not boot fails it, under the package's budget.
- **A diverged twin**: `step.twin.diverged` as today; its probes are whatever its record's
  snapshot carries.
- **A twin created before this feature, left up across the upgrade**: its record names a
  snapshot `1` or none; `twin step` reads its snapshot as Story 7 scenario 1 says, and a
  step to a snapshot with probes builds the hosts as a step that adds a probe does.
- **A probe edited on `main` mid-rehearsal**: the rehearsal's stages keep the list read at
  its start; the next request reads the edit.
- **`FylgjaProbe` absent on `main`**: a take with no `--probes` on an install whose `main`
  lacks the kind is refused naming the kind, as a stage command on an install without
  `FylgjaStage` is; the fixture tool's `-prepare-main` loads it where absent.
- **The template imported before the kind, or the kind loaded before the template**:
  independent; each tier's precheck names what it needs.
- **The rehearsal's check timeout**: `fylgja-twin`'s `timeout` of 4260 does not move; the
  burst's budget per stage fits inside the wait's as the plan sizes it.
- **A `linux` host beside a privileged SR Linux container**: the plan verifies on
  containerlab 0.79.0 that the two share a lab, how the host's address and route are set,
  and whether the image is pulled; none of it is in the verified facts yet.

## Requirements *(mandatory)*

### Functional Requirements

**The declaration**

- **FR-001**: A probe declaration MUST be a document of its own with a contract and a
  version, in which each probe has a name, unique in its list, a format, `ping` the one
  format this feature declares, and two endpoints, each naming a device, one of its
  interfaces, the address its host takes with its prefix length, and its gateway, the
  device interface's address; it MUST carry nothing else, no rate and no burst count.
- **FR-002**: The declaration MUST be readable from a file the operator writes and from
  `FylgjaProbe`, a Fylgja-owned, branch-agnostic kind loaded on `main` beside `FylgjaStage`
  on [D-045](../../docs/decisions.md#d-045)'s pattern, one object per probe with the file's
  shape as attributes, written by object file, the UI or `infrahubctl object create` and
  only read by Fylgja; a read of the kind MUST yield the file's content. The kind is one
  source of the declaration, not the declaration.
- **FR-003**: A malformed declaration MUST be refused when it is read, naming the file or
  the object, the probe and the field: a name repeated, a format no package declares, an
  address or gateway that is not one, an address with no prefix length, or two hosts with
  one address. An address outside its interface's prefix MUST NOT be refused.

**The snapshot and the takes**

- **FR-004**: The snapshot MUST move to version `2`: `probes` is the list of declarations,
  each element the contract's, empty when none were given, and hashed into the id as
  today. How a snapshot is taken, stored and handed to a workflow MUST NOT change; a
  non-contract element MUST be refused by `snapshot.invalid` before any compile.
- **FR-005**: `intent read --out`, `twin create --branch`, `twin create --stage`, `twin
  step --stage`, `stage plan` and the rehearsal's takes MUST accept `--probes <file>`,
  which the client reads and sends; with no file, the probes MUST be read from
  `FylgjaProbe` on `main`, unpinned, as stages are; with neither, the list MUST be empty,
  with no warning. A `--probes <file>` MUST replace the kind's probes, never add to them.
- **FR-006**: `twin create --snapshot` and `twin step --snapshot` MUST take whatever the
  snapshot carries and no flag; `--probes` beside `--snapshot`, on `twin compile` or on
  `twin provision` MUST be refused before any connection as a conflict.
- **FR-007**: A request MUST read its probe list once, at its start, and every snapshot it
  takes MUST carry that list: a rehearsal's stages and a stage plan's stages share one,
  and a later create or step reads afresh. The server MUST keep nothing between two
  requests, and the snapshot MUST stay the core's one input.

**The compile**

- **FR-008**: The compiler MUST turn each endpoint into a synthesized containerlab `linux`
  host, with the endpoint's address set and a route via its gateway, on a synthesized link
  to the device interface, which takes the device's port as a cabled interface would. The
  host, the link and the port MUST carry provenance `synthesized` and MUST be in the
  manifest; every other node, link and port MUST keep `intent`.
- **FR-009**: The compiler MUST refuse, at the compile and so at `fylgja-step` for a
  stage, a probe whose device is not in the snapshot, whose interface the device lacks or
  intent cables, whose interface is `mgmt_only`, whose port another probe already takes,
  or whose format no package declares, each by a stable rule naming the probe, the
  endpoint and the cause, writing no bundle. A stage that cables a probe's port, removes
  its device or deletes its interface MUST be refused at that stage by the same rule; a
  probe MUST NOT be dropped from a stage with a finding.
- **FR-010**: A probe on a port a lossy package would have shared MUST be recorded under
  `fidelity.lossy` as a shared port is, and MUST NOT be refused for it.
- **FR-011**: The bundle MUST move to version `6`: a host node has no package, no artifact
  and no bootstrap, and the manifest says what it is instead; a `5` MUST be refused by
  `twin provision` as `bundle.version.unsupported` naming both versions. A snapshot with
  no probes MUST compile to the bundle it did under `5` in everything but the version, and
  the compiler MUST stay pure, deterministic and free of any branch on what a node is
  (`TestCompilerNamesNoPlatform`).
- **FR-012**: Two declarations that differ in one probe MUST take two snapshot ids, and
  the same declaration taken twice one; the bundle id MUST move with the hosts and for
  nothing about the read.

**The probe package**

- **FR-013**: A probe package format MUST exist beside the PSP and in its pattern: a format
  value, the image and its acquisition, the mechanism (the flow's command, how its
  counters are read, how the burst is run), the flow's rate and the burst's N, its
  resources and timeouts, validated by a schema at load, embedded, and overridable
  host-wide through the package override directory. `ping` MUST be its one shipped
  format; iperf3 and Ixia-c MUST NOT be built.
- **FR-014**: The rate and the burst's N MUST be the package's alone; no probe, kind or
  snapshot field MUST carry them.
- **FR-015**: The host check MUST refuse a run whose probe image is absent on the host as
  it refuses a platform's, naming the image and how to get it, before anything is
  deployed; the image's acquisition MUST be the package's to say.

**The step's measurement**

- **FR-016**: A step MUST start every probe's flow before its first change and read each
  after the wait, recording per probe the packets sent, the packets lost and the longest
  gap, in the step record and in `twin step`'s document, each labelled container timing,
  and MUST assert nothing of them: the step's outcome MUST NOT change for any loss. The
  dry run MUST carry none.
- **FR-017**: The flows measured MUST be those of the probes both the twin's snapshot and
  the target's carry; a host the step adds MUST be built and routed by the step and given
  the verify burst alone; what the step does with a host the target drops, and with its
  flows on a cancellation or a flow that fails to start, is the plan's, each recorded with
  a stable identifier.
- **FR-018**: The worker MUST gain the activities that start and read a flow, and the
  count of activities D-062 records MUST move with them; the four workflows MUST stay four.

**Verify and the gate**

- **FR-019**: Verify's derivation MUST gain a fourth assertion kind beside `host_name`,
  `port_enabled` and `neighbor`: after the wait, a short burst from a probe's first host to
  its second gets N consecutive replies, N the package's, read from the host; one per
  probe, derived from the staged bundle's manifest in a stable order, with the probe, both
  hosts and the expected count named.
- **FR-020**: A burst that does not get its replies MUST be a failed assertion, a finding
  like any other: the step's wait MUST expire on it, 015's gate MUST fail the stage by the
  rule it fails a stage on any finding today, and the gate MUST NOT otherwise change. The
  verify document's counts by kind and by node MUST include the new kind.
- **FR-021**: `twin verify` MUST run the burst too, from the server, with and without
  `--wait`; the burst's budget MUST fit inside the wait's and inside `fylgja-twin`'s
  `timeout` of 4260, which MUST NOT move.

**The report**

- **FR-022**: The rehearsal's report MUST gain a `loss` column, its table reading `| stage
  | at | snapshot | bundle | step | wait | verify | loss | new verification failures |
  verdict |`: each stepped stage's transient loss per probe, `—` for a created or refused
  stage and for every row of a rehearsal with no probes, with the container-timing caveat
  in the report's footer; the `rehearsal` document MUST carry the same per stage. The
  column MUST be a number per probe, never a graph.

**The template and the fixture**

- **FR-023**: Infrahub's template query and template MUST render each physical
  interface's addresses, on both platforms, from `InterfaceLayer3.ip_addresses`, so that
  the device side of a probe reaches the node from its artifact; the reader, the mapping
  and CTM `2` MUST NOT change, and the reference transform's README MUST say what the
  template renders. The change MUST reach Infrahub only by the operator's push and import.
- **FR-024**: The fixture's three devices MUST each gain one probe-ready interface,
  uncabled and addressed, beside the ports they have, written by the seed; its snapshot
  id, compiled id and artifact checksums MUST be re-recorded, and
  `testdata/ctm/three-node.json` and the wrapped fixture under `testdata/snapshot/` MUST
  follow if they are to stay the fixture's; the fixture tool MUST gain what the tests and
  tier 3 need to write a probe.

**The formats, the decision and the documents**

- **FR-025**: `contracts/probes.schema.json` and the probe package's schema MUST be new;
  `snapshot.schema.json` (`2`), `manifest.schema.json` (`6`), `step.schema.json`,
  `verify.schema.json` and `rehearsal.schema.json` MUST move, `twin.schema.json` only if
  the record names the hosts; `cli.md` and `api.md` MUST gain their F-014 sections; every
  earlier format a test reads MUST keep a frozen copy under its package's
  `testdata/contracts/`, each still loading, and every recorded history MUST replay.
- **FR-026**: The three goldens MUST be re-baselined for bundle `6` on a commit of their
  own, reviewed, and again if the fixture's new interface moves them.
- **FR-027**: One decision entry, D-064, MUST record that a probe is a declaration outside
  intent, a file first and a kind second on D-045's pattern, carried by the snapshot and
  compiled into synthesized hosts; that a probe package is a mechanism keyed by a format
  value beside the PSP; and that the declaration carries its own gateway. It MUST stand
  beside D-057, D-061 and D-062 and supersede nothing; D-010's "everything is `intent`
  today" MUST be read as history. The Constitution Check MUST say whether a probe package
  format is a fourth blessed layer by a MINOR amendment citing D-064 or falls under
  Principle II with none, and the tree MUST match.
- **FR-028**: `schema/README.md` (the kind, how a probe is written, the template's
  addresses), `psp/README.md` or a README beside the probe packages, `docs/architecture.md`
  (§4.2, §4.3, §4.4, §4.6, §4.7, §6, and the C4 model redrawn with `make diagrams` run),
  `docs/glossary.md` (Probe told apart from the readiness probe; Probe declaration, Probe
  package, Flow, Transient loss; Synthesized node reworded), `docs/development.md`,
  `README.md`'s walk-through, `docs/verified-facts.md`, the roadmap (F-014's paragraph to
  `ping` only and D-045's pattern, and the entry built), `CLAUDE.md`'s Formats, State and
  fixture ids, and `docs/brief.md`'s Scope and Pipeline MUST say what is now true.

**Tier 3**

- **FR-029**: Tier 3 MUST show a twin with probes stepped and its step's document
  reporting transient loss per probe, and case 9's proposed change MUST gain a stage that
  disables a probe's device interface, at which `fylgja-twin` fails on the new assertion
  kind and the thread's table carries the `loss` column; nine cases, unless the plan adds
  a tenth for the probes alone.

### Key Entities

- **Probe**: one declared flow, `ping` by format, between two endpoints; the first input to
  the core that is not intent. Named, unique in its list.
- **Endpoint**: a device, one of its interfaces, the address the probe's host takes with
  its prefix length, and its gateway, the device interface's address. Nothing about the
  device side but the two names.
- **Probe declaration**: the list of probes, a document with a contract and a version; the
  file the operator writes, and what a read of `FylgjaProbe` yields.
- **`FylgjaProbe`**: the Fylgja-owned, branch-agnostic kind on `main`, one object per
  probe, the file's shape as attributes; one source of the declaration. Named by Infrahub's
  convention, namespace `Fylgja` and node `Probe`; its exact attributes, relationships and
  uniqueness constraint are the plan's.
- **Snapshot `2`**: the CTM unchanged beside the probe list, both hashed by the id
  ([D-061](../../docs/decisions.md#d-061)); still the core's one input.
- **Synthesized host**: a containerlab `linux` node the compiler makes for an endpoint,
  addressed and routed from the declaration, on a synthesized link to its device
  interface; provenance `synthesized`, in the manifest; no package, artifact or bootstrap.
- **Probe package**: a second package kind beside the PSP, keyed by a format value:
  image, acquisition, mechanism, rate, burst count, resources, timeouts; `ping` the one
  shipped.
- **Flow**: a probe's steady ping across a step, started before the first change and read
  after the wait.
- **Transient loss**: per probe across a step, packets sent, packets lost and the longest
  gap; container timing; reported, never asserted.
- **Unrecovered loss**: the fourth verify assertion kind, a burst after the wait that must
  get N consecutive replies; a failed one fails the stage through the gate.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A change applied to a running twin reports the loss it caused, per probe,
  labelled as the container's, in the step's document and in the rehearsal's `loss`
  column; shown live in tier 3, and in tier 1 by a step record and a report that validate
  with the figures and the label.
- **SC-002**: A flow that has not recovered after the wait fails its stage: in tier 3's
  case 9, the stage that disables a probe's interface fails on the new assertion kind and
  every earlier stage passes; in tier 1, 100% of burst-failed cases fail the stage by the
  unchanged gate.
- **SC-003**: A snapshot `2` with probes compiles to a bundle whose hosts, links and ports
  are all under provenance `synthesized` and all in the manifest; the same snapshot with no
  probes compiles to the former bundle but for the version; two declarations differing in
  one probe take two ids.
- **SC-004**: Every refusal in FR-003, FR-009 and FR-015 is a tier-1 case naming the probe,
  the endpoint and the cause, and a stage that cables, removes or deletes a probe's port
  fails `fylgja-step` at that stage in 100% of cases.
- **SC-005**: `FylgjaProbe` loads on `main`; a probe written there is read into a take on a
  `fylgja-test-*` branch, a `--probes` file replaces it, neither yields an empty list, and
  `FylgjaProbe` counts 0 after the tier.
- **SC-006**: `intent read --out --probes <file>` files a snapshot `2`, and `twin create
  --snapshot` of it compiles, in tier 2.
- **SC-007**: Once the template is imported, the fixture's three artifacts carry each
  addressed interface's lines and no other device's artifact changes; the fixture's ids
  are the ones `CLAUDE.md` records.
- **SC-008**: The shipped `ping` package passes its schema, a package missing any required
  field is refused at load, and `TestCompilerNamesNoPlatform` passes with a `linux` node.
- **SC-009**: The goldens are re-baselined on their own commit; every frozen copy loads and
  every recorded history replays; tier 1 stays under its 45 s budget uncached, or the plan
  raises it with the measurement.
- **SC-010**: Tier 2 passes whole with the kind on `main`, and tier 3 passes `E2E-OK` with
  the probe step and case 9's failing stage, in nine cases or ten.

## Assumptions

- The brief's [Decided](brief.md#decided) list, settled with the operator on 2026-10-25 and
  2026-10-28, is not reopened here: `ping` only and no other synthesized node type; the
  declaration a file first and the kind one source of it; the declaration carrying the
  host's address and its gateway; the probe set in the snapshot, hashed by its id; probes
  declared, never derived; the device side intent's; transient loss reported and never
  gated, unrecovered loss gating as a finding; container timing on every surface; the
  template rendering addresses and the reader not reading them; a probe that cannot be
  placed refused, a stage that cables, removes or deletes its port failing `fylgja-step`;
  one probe list per request; a file replacing the kind's probes and neither meaning none
  without a warning; the rate and the burst's N the package's; one decision entry, D-064.
  The brief's Open section is empty, so nothing is marked for clarification.
- The `infrahub-managing-schemas` skill was loaded before the kind was named:
  `FylgjaProbe` is namespace `Fylgja` and node `Probe` by Infrahub's naming rule, as
  `FylgjaStage` is; its attributes are snake_case; it is `branch: agnostic` and loaded on
  `main` on purpose, which `CLAUDE.md` decides over the skill's branch-first rule. The plan
  loads the skill again before `data-model.md` for the kind's shape (whether an endpoint
  is two attributes or a related kind, the uniqueness constraint, `human_friendly_id`,
  `display_label`, `order_weight`, and what a read yields when a device or interface it
  names is not in the scope), `-objects` for the README's object file and `-transforms`
  for the template.
- The plan decides what the brief [leaves to it](brief.md#left-to-the-plan): where the
  synthesized nodes enter the compile without the stored CTM moving; the `linux` image,
  its acquisition and how a host is configured, verified on containerlab 0.79.0; how a flow
  runs and how its counters are read, by the worker for the step and by the server for
  `twin verify`; the step's phases for a flow that fails to start and for a cancellation;
  whether a snapshot `1` on disk is read as a `2` or refused; the format versions that
  move and the frozen copies; the fixture's new interface, its name, address and prefix,
  and whether the test CTM and the wrapped fixture follow it; the template's lines on both
  platforms, verified on the images; the kind's shape; the Constitution Check's answer on
  a fourth blessed layer; the assertion kind's name and rule id; the burst's budget; and
  the estimate, since the roadmap's 5–7 hours predates snapshots and the template change.
  Each is verified against the running system before it is relied on, and recorded in
  `research.md`.
- Three steps are the operator's, each an `[operator]` task in the route with its reason:
  loading `FylgjaProbe` on `main` after the plan and before tier 2, a lasting write to an
  install that is not throwaway, which moves `main`'s hash; pushing the template and
  importing it, after which both task workers' checkouts are read, before tier 2's
  artifact proof, the fixture's re-seed and tier 3; and the review, the merge and the push
  at the close. The fixture's re-seed and the `linux` image's pull are a live session's.
- No credential, address of a management plane, token or login appears in a declaration,
  a snapshot's probe list, a finding or a log line; a probe's addresses are the twin's
  data-plane addresses and are not secret, and a snapshot holds configuration as it does
  today, crossing as a file.
- The API stays at version `1`: `probes` is a new optional argument on the operations that
  take a snapshot from intent, and a file beside a path as `snapshot` is, pre-1.0 as at
  014, 015, 017, 018 and 019.
- Every second format (iperf3, Ixia-c through [F-020](../../docs/roadmap.md#f-020)), loss
  as a graph or an export ([F-013](../../docs/roadmap.md#f-013)), any change to the CTM,
  the reader, the mapping or the schema library's files, the NetBox reader (F-025), the
  orchestrator, and any read of a node's running configuration or assertion of the
  device's address are out of this feature; F-025's reader takes the file alone, and F-020
  is a second format of the same declaration and package.
