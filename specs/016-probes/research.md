# Research: Probes

**Feature**: `016-probes` · **Plan**: [plan.md](plan.md) · **Date**: 2026-10-28

§1 is what was verified on the running host and in the tree at this plan, §2 the decisions
the brief [left to the plan](brief.md#left-to-the-plan) and those the design raised
(R-01…R-30), §3 the decision entry D-064 and the constitution amendment drafted for the
operator, §4 what is owed at implement. Every claim about the tree was read on 2026-10-28
at `ec5d244`. This session booted no twin, pulled no image and wrote nothing to Infrahub
(`CLAUDE.md`: a headless session runs tier 2 at most); the live proofs are implement's,
listed in §4.

## 1. Verified at plan

### 1.1 The host's state

- `pgrep -x fylgja`: the worker (pid 919713) and the server (919804) run from `bin/fylgja`,
  neither `exe` deleted. `containerlab inspect --all`: no containers. Infrahub's eight
  containers up 24 hours, `/api/schema/summary` answers `200`. `free -m`: 19,119 MiB
  available. `docker images`: `ghcr.io/nokia/srlinux:24.7.1` and `ceos:4.32.0.2F` present;
  no `alpine` image. *(host, 2026-10-28)*

### 1.2 busybox `ping` and `ip`, the `ping` mechanism's tools

Run on the host's Docker in the Alpine-based image already present (`postgres:18-alpine`,
`/etc/alpine-release` 3.24.2, BusyBox 1.37.0), as root, without pulling anything:

- `ping` takes `-c CNT`, `-i SECS`, `-W SEC` (seconds to wait for the first response after
  all `-c` packets are sent), `-w SEC`, `-q`, `-I`, `-t`; `ip` has `address`, `route`,
  `link`. `pgrep`, `pkill` and a fractional `sleep` are busybox applets in the same image.
- `ping -c 3 -i 0.2 127.0.0.1` prints one line per reply, `64 bytes from 127.0.0.1: seq=0
  ttl=64 time=0.136 ms` (busybox writes `seq=`, iputils writes `icmp_seq=`), then `---
  127.0.0.1 ping statistics ---`, `3 packets transmitted, 3 packets received, 0% packet
  loss` and the round-trip line, exit 0.
- A background `ping -i 0.2` sent `SIGINT` after 1.1 s printed six replies and the same
  summary (`6 packets transmitted, 6 packets received, 0% packet loss`): an interrupt ends
  the flow and prints its counters, which is how `ReadFlows` reads a flow (R-14).
- `-i 0.2` is accepted as root with no minimum-interval refusal.

*(Docker 29.8.1, busybox 1.37.0 on Alpine 3.24.2, 2026-10-28)*

### 1.3 containerlab 0.79.0 and a `linux` node

A topology of one `nokia_srlinux` node and one `linux` node (`image: alpine:3.22.2`, not
present on the host) with two `exec` lines (`ip addr add 10.1.3.2/24 dev eth1`, `ip route
add 10.1.4.2/32 via 10.1.3.1 dev eth1`) and one link `["p1-a:eth1", "n1:e1-3"]`, under
`CLAB_LABDIR_BASE` at a scratch directory: `clab deploy --dry-run --format json` parsed
and checked it, exit 0, pulled nothing, created no lab directory and answered
`deployed-lab: true` with every list `null`, which is the answer for a lab none of whose
containers exist (`docs/verified-facts.md`, containerlab, 26.04 10-08). So the dry run the
server makes for every step accepts a `linux` node with `exec` beside SR Linux without the
image; whether the booted node runs the `exec` lines, and whether a privileged SR Linux
container and a plain one share a running lab, is owed (§4.1). *(2026-10-28)*

### 1.4 The tree

- **The compile's entry**: `compiler.Compile(c *ctm.CTM, reg *psp.Registry)` surveys every
  device through `SurveyDevice` and holds the links through `LinkTerminations`, both also
  validation's, then builds nodes, rows, links and the manifest; a device's package comes
  from `reg.LookupID(d.Platform.Package)` and a device with no artifact is refused. The
  CTM's `Normalize` defaults every provenance to `intent`, and `Marshal` writes
  `provenance` only when it is not (`TestProvenanceIsWrittenOnlyWhenItIsNotTheDefault`).
  `stage.Compile(c, reg)` wraps it; `stages.Pipeline.Compile(snapshot, reg)` calls it from
  a plan and a take. The purity test holds the compiler's imports.
- **The manifest** (`5`): `ManifestNode{Name, Platform, PSP, Image, ManagementPort,
  Artifact *, Bootstrap}`, `MappingRow`, `CabledLink{ID, A, B}`, `Fidelity{Basis,
  ProductionForwarding, Approximations, Omitted, Lossy, Read}`; `marshalManifest` sorts
  every list and writes every empty one `[]`.
- **The snapshot** (`1`): `Snapshot{Version, ID, ObservedAt, CTM, Probes []json.RawMessage}`;
  `Unmarshal` reads the version first and refuses any but `"1"`; `readProbes` refuses a
  non-empty list; `Hashed` hashes `{"ctm": …, "probes": […]}` with the inner `observed_at`
  left out, **and not the version**, so a `1` and a `2` with no probes hash to one id
  (R-05). The store never overwrites.
- **The stage kind's read**: `intent.StageReader` reads the default branch through the
  unnamed endpoints, `Check` holds the kind, its attributes and the extension against
  `GET /api/schema`, `ProposedChanges` and `OrphanStages` page by 100; the read-only test
  names `FylgjaStage` among six owned roots. The pattern for `FylgjaProbe` (R-06).
- **The activities**: fifteen, named in `wire` and registered by `Activities.Names()`;
  the step runs `InspectTwin`, `CheckHost`, `PlanReconcile`, `StageStep`, `ReconcileLab`,
  `AwaitReadiness`, `PushConfig`, `RecordStep` (disconnected), then `VerifyTwin` under
  `GetVersion(VerifyVersionID)`. The record's step block is `StepRecord{…, Phase *string,
  Wait *StepWait}`; `twin.json` is `10`.
- **Verify**: `verify.Derive(m)` yields `host_name`, then each cabled port's
  `port_enabled`, then each cabled port's `neighbor`, skipping a port intent disables and
  both ends of its link; `verify.Reader` is the gNMI reader the lab implements and tier 1
  fakes; `VerifyCounts` has four keys. `verifyPackages` refuses a node whose package has
  no conformance facet (`verify.package.unreadable`).
- **The rehearsal's deadline**: `rehearsal.Mechanism` and `Deadline` sum each rehearsed
  stage's `InspectTwin + 2 CheckHost + Stage + deploy + readiness + push + Record + Wait`
  with their margins; the markdown's table reads `| stage | at | snapshot | bundle | step |
  wait | verify | new verification failures | verdict |` and its `Caveat` is one sentence.
- **The host check**: `noteImage` verifies presence only for an acquisition other than
  `public_registry`, under `host.image.absent`, through `Images.Present` (`docker image
  inspect`); `NodePlans` builds each node's plan from its manifest `psp.id`.
- **The packages**: `psp.Registry` is loaded from the embedded `psp/*.yaml` and an
  override directory (`--psp-dir`, `FYLGJA_PSP_DIR`, a flag of the two roles alone);
  `conformance.PureChecks` has six checks.
- **The fixture**: `SeedThreeNode` writes `n1`–`n3`, each `mgmt0`, `ethernet-1/1`,
  `ethernet-1/2`, three cables; `SeedMixed` writes `s1`, `e1`, `e2` with `Ethernet1`,
  `Ethernet2/1`, `Ethernet3/1/1`; `SeedFourthNode`, `SeedThirdLink` and `SeedMixedLink`
  each create `ethernet-1/3` (and `Ethernet3`) and refuse a branch already holding it, so a
  probe-ready port cannot be named `ethernet-1/3` (R-19). `createPort` writes name, role
  and status; no seed writes an `IpamIPAddress`.
- **The library's address model**: `InterfacePhysical` inherits `InterfaceLayer3`, whose
  `ip_addresses` are `IpamIPAddress` (`Attribute`, many, optional, identifier
  `ip_address__interface`); `IpamIPAddress` inherits `BuiltinIPAddress`, with
  `human_friendly_id [ip_namespace__name__value, address__value]`, uniqueness
  `[address__value, ip_namespace]` and `interface` (one, optional). The template's query
  reads no `ip_addresses` today.
- **Tier 3**: nine cases; case 5 creates from a branch, freezes 330 s, disables
  `n1:ethernet-1/2` and steps to a snapshot by file and by id; case 8 is the mixed twin
  stepped to `mixed-link`, which restarts `e1`; case 9 rehearses a proposed change twice
  through `fylgja-twin`, the second with a stage `bad-port`.
- **The rule ids**: `host.image.absent`, `verify.host_name`, `verify.port.enabled`,
  `verify.neighbor`, `verify.package.unreadable`, `snapshot.invalid`,
  `snapshot.version.unsupported`, `snapshot.flags.conflict` and the step's phases
  `reconcile`, `readiness`, `push`, `record` are the ones this feature builds beside
  (data-model §12).

## 2. Decisions

- **R-01 Where the synthesized nodes enter.** `compiler.Compile` takes the snapshot's body:
  `Compile(c *ctm.CTM, decls []probe.Probe, reg *psp.Registry, probes *probe.Registry)`.
  Its first step, `PlaceProbes(c, decls, probes)`, is a pure function that returns a copy
  of the CTM with one device per endpoint (name R-02, `platform.package` the probe
  package's format, one interface `eth1`, provenance `synthesized`), one link per endpoint
  from the host's `eth1` to the device interface (provenance `synthesized`, the device
  interface's `link` set), and a host table (address, gateway, far address, probe,
  endpoint, package) that the topology and the manifest read; and every placement refusal
  (R-09). The stored CTM moves nothing; the snapshot keeps the declarations beside it.
  Validation calls the same function, so a refusal is worded alike from both, as
  `SurveyDevice` is. The compiler branches on a device's provenance to look its package
  up in the probe registry instead of the PSP's, never on what the format or the platform
  is; no `linux` literal enters the compiler, since the kind comes from the package.
  *Alternatives*: a CTM `3` carrying hosts and addresses, rejected (D-057, D-061, the brief:
  CTM `2` does not move); a separate compile stage after `Compile` that patches the
  topology, rejected (Constitution V: synthesized nodes are added before compilation, and
  the manifest's rows must see them). Serves FR-008, FR-011, SC-003.
- **R-02 The hosts' names and port.** A probe's hosts are `<name>-a` and `<name>-b`, its
  endpoints in the declaration's order; a probe's name is `^[a-z0-9][a-z0-9-]{0,23}$`, so a
  container name `clab-fylgja-<name>-a` stays short and valid. A host's one interface is
  `eth1`, the first data interface containerlab's `linux` kind names, and the link's host
  end is `<name>-a:eth1`. A host whose name equals a device's is refused
  (`probe.host.collision`). *Alternative*: a reserved prefix (`probe-<name>-a`), rejected
  as longer and no safer than a refusal. Serves FR-008.
- **R-03 A probe's two endpoints on one device** are placed when both interfaces are
  uncabled and not `mgmt_only`; the two hosts reach each other through the device's
  connected routes, which is what the reference fixture offers (R-19). Serves the edge
  case.
- **R-04 The declaration file.** JSON, as every document Fylgja reads: `{"probes_version":
  "1", "probes": [{"name", "format", "endpoints": [{"device", "interface", "address",
  "gateway"}, {…}]}]}` (`contracts/probes.schema.json`). `address` is an IP address with a
  prefix length (`10.1.10.2/24`), `gateway` an address with none; both families are
  accepted syntactically, but one probe's four addresses must be of one family and `ping`
  format `0.1` is IPv4 (R-08). The rules a read applies with no CTM: a name repeated or
  malformed, a format no package declares, an address or a gateway that is not one, an
  address with no prefix length, a gateway outside the address's prefix (the route could
  not be added), two endpoints with one address across the whole list (R-20), other than
  two endpoints, an unknown key, a version not `1`. The snapshot's element is the probe
  object without the file's wrapper. *Alternative*: YAML, rejected: the file crosses the
  API as a file and lands in a JSON snapshot. Serves FR-001, FR-003.
- **R-05 Snapshot `2`, and a `1` read as a `2`.** `snapshot.Version` is `"2"`; `Probes`
  becomes `[]probe.Probe`, each element held to R-04's rules before filing (a failure is
  `snapshot.invalid` at `probes[<i>].<field>`), and hashed as the raw list is today. A
  document declaring `"1"` is read wherever a snapshot is read, as a `2` with an empty
  list: its body hashes to the same id, since the version is not among the hashed bytes
  (§1.4), so nothing is converted and nothing moves; every document Fylgja writes is a
  `2`. D-061's "nothing converts one" holds: a `1` is not rewritten, and any other version
  stays `snapshot.version.unsupported`, naming `1` and `2` as the versions read. Serves
  FR-004, US7 scenario 1 and the upgrade edge case.
- **R-06 The takes and the kind's read.** `intent read --out`, `twin create --branch` and
  `--stage`, `twin step --stage`, `stage plan` and `twin rehearse` gain `--probes <file>`,
  sent as the argument `probes` (the path) beside one file, as `twin create --snapshot
  <file>` sends its file. The server reads the list once at the request's start, after the
  guards and before any read of intent: the file when given, else `FylgjaProbe` on the
  default branch through `intent.ProbeReader` (the `StageReader` pattern, unnamed
  endpoints, `Check` then a paged `Probes` query in name order), else an empty list; the
  list is handed to every take the request makes (`stages.Pipeline.Take` gains it), so a
  rehearsal's or a plan's stages share one. A kind absent on `main` is `probe.kind.absent`
  naming `schema/fylgja-probe.yaml`, only when the read is asked for. `--probes` beside
  `--snapshot` on create or step is `snapshot.flags.conflict` at the flag; `twin compile`
  and `twin provision` do not have the flag. Serves FR-005, FR-006, FR-007.
- **R-07 The kind's shape** (skill `infrahub-managing-schemas` loaded). `FylgjaProbe`:
  `branch: agnostic`, `include_in_menu: true`, `human_friendly_id: [name__value]`,
  `display_label: "{{ name__value }}"`, `order_by: [name__value]`,
  `uniqueness_constraints: [[name__value]]`, icon `mdi:radar`; attributes `name` (Text,
  required, R-02's regex, order 1000), `format` (Dropdown, choices `ping`, default `ping`,
  order 1100), then the two endpoints flat, `a_device`, `a_interface`, `a_address`,
  `a_gateway`, `b_device`, `b_interface`, `b_address`, `b_gateway` (Text, required,
  orders 1200–1530), `description` (Text, optional, 1600); no relationship. The endpoints
  are flat so that one `infrahubctl object create` writes a probe and a read yields the
  file's element by renaming alone; `a` and `b` are the names the manifest gives a link's
  ends. `Text` with a regex, not `IPHost`, for the addresses: `IPHost` normalises a value
  to a prefixed form, which would make a read of the gateway differ from the file's
  content. No relationship to `DcimDevice`: the device may exist on a branch alone, and
  the file names devices by name. *Alternative*: a component kind per endpoint, rejected
  (two writes per probe, a uniqueness scope, nothing gained). Serves FR-002; the load is
  the operator's (§4.2).
- **R-08 The probe package.** A second package kind in `probes/` (`README.md`,
  `probe.schema.json`, `ping.yaml`), embedded as `psp/` is and loaded into
  `probe.Registry` by the two roles, with overrides from `<psp-dir>/probes/*.yaml`, the
  one override directory's subdirectory, so no flag is added. Format `0.1`: `probe_version`;
  `format` (the value that keys the mechanism, D-031); `image` (`clab_kind`, `ref`,
  `acquisition`, `resources`, `deploy_timeout_s`, `destroy_timeout_s`, the PSP's shape);
  `host` (`interface`, the `address` and `route` command templates with `{address}`,
  `{gateway}`, `{far_address}`, `{interface}`); `readiness` (`probe: exec`, `command`,
  `expect`, `timeout_s`); `flow` (`interval_s`, `command`, `start_timeout_s`,
  `read_timeout_s`); `burst` (`count`, `wait_s`, `command`); `fidelity` (`forwarding:
  software`, `timing: container`, `approximations`). The shipped `ping`: `alpine:3.24.2`
  (public registry, about 8 MB, busybox 1.37.0; §1.2), `memory_mb: 32`, deploy 60 s,
  destroy 30 s, interval `0.2`, burst `5` with `wait_s: 2`, readiness `ip -4 -o addr show
  dev eth1` expecting the address. A package is validated by the schema at load and
  refused as `probe.package.schema` naming the field; two declaring one format are
  `probe.package.format.duplicate`. The conformance suite's pure half gains a check,
  `probes`, that every shipped probe package validates and renders its templates with
  nothing unrendered. Serves FR-013, FR-014, SC-008.
- **R-09 The placement refusals**, each at the compile and so at `fylgja-step` for a
  stage, naming the probe, the endpoint (`a` or `b`) and the cause, writing no bundle:
  the device not in the snapshot (`probe.device.unknown`), the interface the device lacks
  (`probe.interface.unknown`), one intent cables (`probe.interface.cabled`), one that is
  `mgmt_only` (`probe.interface.mgmt_only`), one another probe already took
  (`probe.port.taken`, naming the first), a format no package declares
  (`probe.format.unknown`, naming the formats loaded), a host name colliding with a
  device (`probe.host.collision`). A stage that cables, removes or deletes a probe's port
  is refused by the same rules; nothing drops a probe. A port a lossy package would have
  shared is recorded under `fidelity.lossy` by the existing survey, since the synthesized
  link makes the interface cabled. Serves FR-009, FR-010, SC-004.
- **R-10 The topology.** A host node is `kind: <package clab_kind>`, `image: <package
  ref>`, `exec:` the package's `address` and `route` templates rendered with the endpoint's
  values (`ip addr add 10.1.10.2/24 dev eth1`; `ip route add 10.1.11.2/32 via 10.1.10.1
  dev eth1`), no `startup-config`; the link is `["<name>-a:eth1", "<device>:<port>"]`. The
  route is a host route to the far endpoint's address: a default route would collide with
  containerlab's management default, and a prefix route would collide with the connected
  prefix when both endpoints share one. Serves FR-008.
- **R-11 Bundle `6`.** `nodes[]` gains `provenance` (omitted when `intent`, the CTM's own
  rule, so a probe-less bundle's bytes move the least) and, for a host, `probe: {name,
  endpoint, format, package: {id, source}}` with `platform`, `psp`, `artifact` and
  `bootstrap` written `null`; `mapping[]` and `links[]` gain `provenance` the same way; a
  host's own row is `eth1`, cabled, synthesized, and the device port's row is cabled with
  `provenance: synthesized`, since intent did not cable it; a top-level `probes[]` block
  records each probe as compiled (name, format, package, each host with its endpoint,
  device, interface, port, address, gateway), sorted by name; `fidelity.synthesized` lists
  every synthesized node. A probe-less snapshot compiles to its `5` bundle but for the
  version, `probes: []` and `fidelity.synthesized: []`, which the goldens' re-baseline
  shows and the spec's "in everything but the version" is read as. A fourth golden,
  `three-node-probed`, compiles the three-node snapshot wrapped with one probe. Serves
  FR-011, FR-012, SC-003.
- **R-12 The host check and the node plans.** A host node's plan comes from the probe
  registry by the manifest's `probe.package.id` (its image, budgets, resources and
  readiness); a package not on the worker is `host.probe_package.missing`. A probe image is
  verified present under exactly its reference whatever its acquisition and never pulled,
  under `host.image.absent`, the message's remedy from the acquisition (`docker pull
  <ref>` for `public_registry`): a host's deploy budget is sized for a container that
  starts in a second, and a pull inside a step's reconcile would be timed as the step's.
  Memory sums as a platform's does. Serves FR-015, US6 scenario 3.
- **R-13 The step's phases.** `StartFlows` runs after `StageStep` and before `ReconcileLab`,
  `ReadFlows` after `VerifyTwin`, both under `workflow.GetVersion("flows")`, so the seven
  histories replay. The phase `flows` is added to the step's enum for the one failure the
  activities can have as activities, an error of the runtime or a cancellation, which from
  the stage on is diverged as every failure after the stage is; a flow that cannot be
  started on one host is not a failure of the step but an entry in the loss list with
  `outcome: not_started` and the rule `flow.start.failed`, the step going on; a flow that
  cannot be read is `not_read` under `flow.read.failed`. A step cancelled or failed after
  the stage reads its flows on the record's disconnected context, as it records, with
  `outcome: interrupted` on each, so the record says what was lost until the cancel. A
  dry run starts nothing and carries `loss: null`. Serves FR-016, FR-017, FR-018, US2
  scenarios 5 and 6.
- **R-14 How a flow runs and is read.** `StartFlows` runs, in each host of a probe both
  snapshots carry, `docker exec -d <container> sh -c 'pkill -x ping; exec <flow.command>
  > /run/flow.log 2>&1'` with the far address and the interval rendered, idempotently
  (a stray flow is killed first). `ReadFlows` runs `docker exec <container> sh -c 'pkill
  -INT -x ping; <wait up to 5 s for it to exit>; cat /run/flow.log'` and the mechanism
  parses the summary's `transmitted` and `received` and every reply's `seq=` or
  `icmp_seq=` (`probe.ParsePing`, pure): `sent`, `lost = sent − received`, `longest_gap_s`
  the longest run of unanswered sequence numbers, from the start or to the end when the
  first or last were lost, times the interval, `0` when nothing was lost. Both are
  mechanisms keyed by the package's format, in `internal/lab`, through the `Runner` the
  lab drives Docker with, so tier 1 records them. The budgets are the package's
  `start_timeout_s` and `read_timeout_s`. Serves FR-016.
- **R-15 The burst, verify's fourth kind.** `verify.KindBurst = "burst"`, one assertion
  per probe of the staged manifest's `probes[]`, in name order after the three kinds, naming
  the probe, both hosts and the expected count; read by a `Burster` interface (`Burst(ctx,
  container, command) (sent, received int, err)`) that the lab implements with `docker
  exec <host-a> <burst.command>` and tier 1 fakes; held when `received == count`, failed
  otherwise (rule `verify.burst`, object the probe, exit 5), unread when the exec fails.
  The counts gain `burst`; the by-node view lists a host with its one burst and no gNMI
  read. A host node has no `host_name`, `port_enabled` or `neighbor` assertion; a
  synthesized link's `neighbor` assertions are skipped at both ends with the reason that
  the host speaks no discovery protocol, and the device port's `port_enabled` stands.
  `verifyPackages` reads a host's package from the probe registry and refuses nothing of
  it. `twin verify` and the step's wait run every burst on each read; a burst costs about
  `count × interval + wait_s` (3 s), inside the wait's budget. Serves FR-019, FR-020,
  FR-021, SC-002.
- **R-16 The budget.** A rehearsed stage's deadline gains the flows' two budgets (60 s for
  the shipped package) and the bursts ride inside the wait's unchanged default, so the
  fixture's three-stage rehearsal moves from 1,950 s to about 2,010 s, under the 3,600 s
  ceiling; `fylgja-twin`'s 4,260 covers the ceiling, the destroy and the allowance as
  before, and does not move (`TestTheTwinCheckOutlastsItsRehearsal`). Serves FR-021.
- **R-17 The report.** The table reads `| stage | at | snapshot | bundle | step | wait |
  verify | loss | new verification failures | verdict |`; a stepped stage's `loss` is one
  figure per probe, `<probe> <lost>/<sent>, gap <s>s`, `—` for a created, refused or
  not-reached stage and for every row with no probes; the footer's caveat gains a sentence
  on container timing. The `rehearsal` document's stage gains `loss`, the step document's
  block copied. The shortening rules keep the column, dropping its figures with the step's
  when the report is cut. Serves FR-022, SC-001.
- **R-18 The template.** `device_config.gql` selects, on an `InterfacePhysical`,
  `ip_addresses { edges { node { address { value } } } }`; the template renders each
  address in value order: SR Linux `set / interface <port> subinterface 0 ipv4 admin-state
  enable` and `set / interface <port> subinterface 0 ipv4 address <a/l>`; EOS `no
  switchport` and `ip address <a/l>` under the interface, and `ip routing` once, after the
  hostname, when any port is addressed, since cEOS forwards nothing without it. Nothing
  else is rendered: the reference transform renders ports and their addresses and **no
  routing**, so two addressed ports of one device reach each other by connected routes
  and two devices do not; `schema/README.md`'s template section says so. The reader and
  the mapping do not move. Serves FR-023, SC-007; the lines are owed live (§4.4).
- **R-19 The fixture.** Each device gains **two** probe-ready ports, `ethernet-1/10` and
  `ethernet-1/11` (SR Linux; `Ethernet10`, `Ethernet11` on the mixed fixture's EOS
  devices), uncabled, each with one `IpamIPAddress` in the default namespace:
  `10.<d>.10.1/24` and `10.<d>.11.1/24`, `d` the device's index (`n1` 1, `n2` 2, `n3` 3;
  `s1` 1, `e1` 2, `e2` 3). Two, not one, because the reference transform renders no
  routing (R-18), so the probe tier 3 shows must lie across one device: `n1-loop` from
  `n1:ethernet-1/10` (host `10.1.10.2/24`, gateway `10.1.10.1`) to `n1:ethernet-1/11`
  (`10.1.11.2/24`, `10.1.11.1`), and `e1-loop` on the mixed twin's `e1`. Not `ethernet-1/3`,
  which the fourth-node, third-link and mixed-link seeds create and refuse when present.
  `testdata/ctm/three-node.json`, `mixed.json` and the wrapped fixtures follow, so the
  goldens move a second time; `testdata/probes/` holds the declarations tier 1 reads.
  FR-024's "one" becomes two, recorded in the spec (R-30). The addresses are not read by
  the reader, so the fixture's CTM moves for the ports alone. Serves FR-024.
- **R-20 Two hosts with one address** are refused when the declaration is read
  (`probe.address.duplicate`, naming both probes): two hosts on one address cannot be told
  apart by a ping, and the check needs no CTM. An address outside its interface's prefix is
  not refused, as decided. Serves FR-003.
- **R-21 A host the target drops** is torn down with no flow: `StartFlows` starts the
  flows of the probes both snapshots carry, `ReadFlows` reads them after the wait, and a
  host only the twin's snapshot carries is a node the reconcile deletes, with no flow
  started and no figure, listed under the loss block's `dropped`. A host only the target
  carries is created by the reconcile, routed by its `exec`, given the burst at the wait,
  and has no transient figure (`added`). Serves FR-017, US2 scenario 4.
- **R-22 The record.** `twin.json` moves to `11`: `step.loss` (the block of R-13, `null`
  until `ReadFlows` wrote it) and `nodes[]` carrying a host with `probe` in place of `psp`
  and `artifact`, its `holds` the bundle whose topology configured it (a host containerlab
  created or recreated holds the staged bundle, since its configuration is the topology's,
  and no push reaches it). The `10` schema is frozen. Serves FR-025.
- **R-23 The formats that move and the frozen copies.** New: `contracts/probes.schema.json`
  (`1`), `probes/probe.schema.json` (`0.1`). Moved: snapshot `2`, manifest `6`,
  `step.schema.json` (the `loss` block, the phase `flows`, `wait_counts.burst`),
  `verify.schema.json` (`counts.burst`, the host node's shape, the burst assertion),
  `rehearsal.schema.json` (`stages[].loss`, `verify.burst`), `twin.schema.json` (`11`),
  `findings.schema.json` (the blocks), `api.schema.json` (the `probes` argument).
  Frozen under `testdata/contracts/019-following-removed/` in each package that reads
  the older shape: snapshot `1`, manifest `5`, step, verify, rehearsal, twin `10`,
  findings, each still loading in `TestFrozenContractCopiesAgree`. Serves FR-025.
- **R-24 Tier 3.** Nine cases. Case 5 creates with `--probes` (the `n1-loop` file), reads
  `twin verify`'s burst held, steps as today and reads the loss per probe in the step's
  document and the record; case 8 writes `e1-loop` into `FylgjaProbe` on `main` through
  the fixture tool, creates with no flag, steps to `mixed-link` (which restarts `e1`) and
  requires `lost > 0` and the burst held after the wait, then deletes the probe; case 9's
  proposed change gains a stage `probe-port-down` that disables `n1:ethernet-1/10` after
  `third-link`, at which `fylgja-twin` fails on `verify.burst`, the thread's table carrying
  `loss`. Each case checks the probe hosts are gone at destroy. Serves FR-029, SC-010.
- **R-25 Tier 3's time**: about 34 minutes, from 31.5: two extra hosts in three cases
  (about 2 s each to create and destroy), case 9's third stage (about 90 s), the flows'
  activities (under 2 s a step). Measured at the close.
- **R-26 The fixture tool** gains `-probes <file>`, which writes each probe of a
  declaration file into `FylgjaProbe` on the default branch, `-delete-probes`, which
  deletes every `FylgjaProbe` there, and `-prepare-main` loads `schema/fylgja-probe.yaml`
  when the kind is absent; `-stage` is unchanged, and `-disable-port` disables a probe's
  port as it disables any. `testsupport` gains `WriteProbes` and `DeleteProbes` for tier
  2. Serves FR-024, SC-005.
- **R-27 The identifiers** are listed in data-model §12; none retires. The glossary tells
  the readiness probe apart from this feature's probe by two entries, and the rule ids keep
  `probe.*` for the declaration's and `host.probe.login_unset` for the readiness probe's
  login, as today.
- **R-28 The C4 model**: `probe` as a component of the server (the declaration, the
  package, the parse) and of the worker (the package, the parse); the worker's `lab`
  component reaches Docker for the hosts' flows and the server's for the bursts; `probes/`
  as a second embedded set beside `psp/` in the containers' description; `make diagrams`.
- **R-29 The estimate**: 14–20 hours of sessions plus the tiers, against the roadmap's 5–7
  set before snapshots, the template change and the fixture's ports. The order of the
  work is the plan's.
- **R-30 Settled by the plan, recorded in the spec's Clarifications** (headless, no
  question asked): the demo probe lies across one device and each fixture device gains two
  probe-ready ports (R-18, R-19), which amends FR-024 and US1's scenarios 1 and 4; a
  snapshot `1` is read as a `2` (R-05); the kind is flat (R-07); the phase `flows` and the
  per-probe outcomes (R-13); a dropped host is torn down with no flow (R-21); two hosts with one
  address are refused (R-20); the kind `burst` and the rule `verify.burst` (R-15); a probe
  image is verified present whatever its acquisition (R-12). The operator may overturn any
  at `analyze`; the first is the one the plan flags as a choice the brief did not make.
  **At `analyze` (2026-10-28)** the operator answered "take your own recommendations":
  the first is confirmed and the spec's FR-024, US1 scenarios 1 and 4 and US6 scenario 5
  amended to two ports and a probe across one device or two; the rest stand as recorded;
  D-064 (§3.1, dated 2026-10-28) and the 2.3.0 amendment (§3.2) are to be appended as
  drafted by T002, since a chain stage writes inside the feature directory alone.

## 3. Drafted for the operator

### 3.1 D-064

```markdown
<a id="d-064"></a>
## D-064 — A probe is a declaration outside intent: a file first, an Infrahub kind second, carried by the snapshot and compiled into synthesized hosts by a probe package keyed by its format

**Status:** Accepted <date>, by the operator, at `016-probes`'s `analyze`. Beside
[D-010](#d-010) (the CTM, whose `synthesized` provenance it fills), [D-031](#d-031) (a
mechanism is code keyed by a format value, which the probe package is a second instance
of), [D-038](#d-038) (an assertion kind added as data), [D-045](#d-045) (the kind's pattern),
[D-057](#d-057), [D-061](#d-061) and [D-062](#d-062), which stand. Supersedes nothing.
D-010's "everything is `intent` today" is history from this entry. To be built by
`016-probes`.

### Context

Since 018 the snapshot carries `probes`, a list required and empty; since 019 a twin is
frozen at its snapshot, so loss across a step is the step's. The roadmap's F-014, re-shaped
on 2026-10-25, names the headline demo, loss during a change applied to a running twin,
and the production shape names a declaration outside intent as the third seam 0.3 proves.
The CTM carries no address (D-057), so a host's address must come from somewhere intent
does not own; the reader must not read addresses (D-057); and Infrahub renders every
device's configuration (D-028, Constitution IV).

### Options considered

- **The kind primary, the file `twin compile`'s input** (the 2026-10-16 brief). Rejected
  by the operator on 2026-10-25: F-025's NetBox reader takes a file alone, and the snapshot
  is the core's one input.
- **Probes derived from the topology.** Rejected: Fylgja guessing at intent.
- **The declaration a file first, the kind one source of it, carried by the snapshot,
  with the host's address and gateway in the declaration.** Chosen.
- **A generator type per probe, in code.** Rejected: D-031's branch on what a thing is.
- **The probe package a facet of the PSP.** Rejected: a host is of no platform.

### Decision

- A probe declaration is a document of its own (`contracts/probes.schema.json`, version
  `1`): each probe a name, a format and two endpoints, each a device, an interface, the
  address its host takes with its prefix length, and its gateway, the device interface's
  address. It carries nothing else; the rate and the burst count are the package's.
- The declaration lives in a file the operator writes, and in Infrahub as `FylgjaProbe`,
  one object per probe on the default branch, branch-agnostic, on D-045's pattern, written
  by the operator and only read by Fylgja. The kind is one source of the file, not the
  declaration: the NetBox reader takes the file alone.
- A request reads its probes once, from `--probes <file>`, else the kind, else none, with
  no warning, and every snapshot it takes carries that list. The snapshot, version `2`,
  carries the declarations beside the CTM and hashes them; a `1` reads as a `2` with none.
- The compile adds one synthesized `linux` host per endpoint to the CTM it compiles, on a
  synthesized link to the device interface, configured from the declaration alone, and
  refuses a probe it cannot place; the manifest marks every synthesized node, link and
  port. The device side is intent's: Infrahub's template renders the interface's address.
- A probe package is a mechanism keyed by a format value beside the PSP (`probes/`):
  image, acquisition, how a host is configured, how a flow runs and is read, how a burst
  runs, rate, count, resources, timeouts; `ping` is the first format.
- Transient loss across a step is measured and reported, labelled the container's, never
  asserted; unrecovered loss is a verify assertion kind, `burst`, under D-038, which fails
  a stage through D-052's gate unchanged.

### Consequences

- Bundle `6`, snapshot `2`, `twin.json` `11`; the step, verify and rehearsal documents
  carry loss and the burst; the goldens move twice. The worker serves four workflows and
  seventeen activities, which amends D-062's count.
- Constitution II is expanded and the Check's gate blesses the probe package (2.3.0).
- The reference transform renders addresses and no routing: a probe across two devices
  needs routing intent renders, which the user's own transform does; the fixture's probe
  lies across one device.
- A probe kept on `main` blocks a change that decommissions its device until it is
  deleted; the remedy is the declaration's.
- Revisit at F-020 (a second format and element shape), when the reference transform
  gains routing, or if a probe needs a rate of its own.

---
```

### 3.2 Constitution 2.2.0 → 2.3.0 (MINOR: Principle II materially expanded)

Principle II gains, after "Budgets, timeouts, readiness and the manufacturer and platform
pairs a package matches MUST come from the PSP, never from a global constant.": *"A probe
format is data in the same sense: a format MUST be added by writing a probe package
(`probes/`), keyed by its format value, and nothing else; its image, how a host is
configured, how a flow runs, is read and bursts, and its budgets MUST come from that
package, and no component MAY branch on what a format is."* Its rationale gains D-064. The
Gate Adjustments' blessed layers gain: *"**The probe package, a second package kind.**
Required by Principle II as amended; one mechanism per format, keyed by its format value.
*(D-031, D-064)*"*. The Sync Impact Report names 2.3.0 and the plan template's row II reads
the amended text. *Alternative*: no amendment, the layer passing under the PSP's blessing;
rejected by the plan since the gate names the layers it will not flag and a second package
kind is one, as the brief's author leaned.

## 4. Owed at implement

1. **The `linux` host, live** (the live session's): `docker pull alpine:3.24.2` and the
   image's digest recorded; a host boots beside a privileged SR Linux node in lab
   `fylgja`, runs its two `exec` lines (the address and the host route present inside the
   container), and reaches the far host through the device; whether containerlab fails a
   deploy when an `exec` line fails, or logs it (the exec readiness covers either);
   `docker exec -d` leaves the flow running and `pkill -INT` prints its summary inside a
   containerlab-run container as it did in §1.2. Each lands in `docs/verified-facts.md`
   under containerlab and a new heading, "The `ping` host".
2. **The kind on `main`** (the operator's, after the plan): `.venv/bin/infrahubctl schema
   check --branch main schema/fylgja-probe.yaml`, then `schema load`; the hash moves and is
   recorded; an `infrahubctl object create FylgjaProbe --set …` round-trips every field
   byte for byte, which R-07's `Text` choice assumes. The `infrahub-managing-objects`
   skill is read before `schema/README.md`'s object file is written.
3. **The PSP loader and a `probes/` subdirectory**: whether `psp.Load` reads the override
   directory's own entries alone or walks into subdirectories; it must skip `probes/`.
4. **The template's lines on both images** (the live session's, after the operator's push
   and import): SR Linux accepts `subinterface 0 ipv4 admin-state enable` and `… ipv4
   address <a/l>` in the replace; cEOS accepts `ip routing`, `no switchport` and `ip
   address` in a session; a device with no addressed port renders byte for byte what it
   did. The `infrahub-managing-transforms` skill is read before `device_config.gql` and
   `.j2` are edited, its union-fragment rule for the `InterfaceLayer3` selection among its
   rules. Then the fixture's artifact checksums, compiled id and snapshot id, recorded in
   `CLAUDE.md`.
5. **`IpamIPAddress`'s namespace**: whether a create with no `ip_namespace` lands in the
   default namespace on 1.11.2, which the seed assumes; the address's `interface` set to
   the port's id.
6. **The figures**: tier 1's time against 45 s; tier 2's and tier 3's against the
   estimates (R-25); the rehearsal's deadline for the fixture's three stages with probes
   (R-16); a burst's cost on the host.
7. **The roadmap's F-014 paragraph**: "ping and iperf3" to `ping` only and D-032 to D-045's
   pattern, and the entry marked built at the close; `CLAUDE.md`'s Formats, State and the
   fixture's ids; `docs/brief.md`'s Scope and Pipeline.
8. **The glossary**: Probe (this feature's) beside Readiness probe, Probe declaration,
   Probe package, Flow, Transient loss, Synthesized node reworded.

## 5. Verified at implement

Appended by the runs.

- **§4.3 The PSP loader and a `probes/` subdirectory** (Run 4, T006): `psp.Load` reads the
  override directory's own entries alone: it globs `filepath.Join(dir, "*.yaml")`
  (`internal/psp/load.go`, `Load` and `FromDir`), which never descends, so a directory
  holding `probes/ping.yaml` loads the same platforms as the embedded set and `probe.Load`
  of the same directory reads the probe package. Held in tier 1 by
  `TestThePSPLoaderSkipsTheProbesSubdirectory` (`internal/probe/package_test.go`).
  *(tree at `1506f79`, 2026-10-28)*
- **`schema/fylgja-probe.yaml` checks valid on `main`** (Run 4, T009): `.venv/bin/infrahubctl
  schema check --branch main schema/fylgja-probe.yaml` answers `Valid!` with a diff that adds
  `FylgjaProbe` and changes and removes nothing. A check only: nothing loaded, `main`'s hash
  unmoved; the load stays T017's. *(Infrahub 1.11.2, infrahub-sdk 1.23.2, 2026-10-28)*
- **`FylgjaProbe` loaded on `main`** (T017, the operator): `.venv/bin/infrahubctl schema
  load --branch main schema/fylgja-probe.yaml` loads it in about 24 s, and `main`'s hash moves
  from `7c413536d67ef86321c629c076a0d3a4` to `8a4f3bee8a72549e97450a414da18107`. An object
  written by `infrahubctl object create FylgjaProbe --set …` reads back with every `Text`
  attribute as written (addresses with their prefix length, gateways without), `format`
  defaulting to `ping`, and `object delete FylgjaProbe <name>` removes it by its
  human-friendly id. *(Infrahub 1.11.2, infrahub-sdk 1.23.2, 2026-10-29)*
- **§4.5 `IpamIPAddress`'s namespace** (Run 18, T033): an `IpamIPAddressCreate(data:
  {address: {value: "10.1.10.1/24"}, interface: {id: <port>}})` naming no `ip_namespace`
  lands in the default namespace: the address's `ip_namespace` reads the one
  `BuiltinIPNamespace`, an `IpamNamespace` named `default` with `default: true` (its
  `default` is a field of `IpamNamespace` alone, so a query of the generic reads it in an
  inline fragment). Its `interface` reads back the port, an `InterfacePhysical`, by its
  id, name and device (`InterfaceLayer3` has no `name`: the port's fields are read in a
  `... on InterfacePhysical` fragment). On two throwaway `fylgja-test-ns-*` branches,
  seeded by this tree's `SeedThreeNode` and `SeedMixed`: six addresses each, `10.<d>.10.1/24`
  and `10.<d>.11.1/24` on `n1`–`n3` (`s1`, `e1`, `e2`), 15 `InterfacePhysical` and 3
  `DcimCable`; the baseline's deletion (`clearBaseline`, `-clear-main`'s, run on the
  three-node branch) removed 6 addresses, 3 cables, 15 interfaces, 3 devices, 1 platform,
  1 manufacturer, 4 locations and 1 tag, its 3 artifacts gone with their devices, and
  `BuiltinIPAddress` then counts 0. Both branches deleted. *(Infrahub 1.11.2, 2026-10-29)*
- **R-18 The template rendered on live branches** (Run 19, T034): the command is
  `.venv/bin/infrahubctl render srlinux_device_config device=<name> --branch <b> --out
  <file>`, the transform's registered name and not the query's: `render` reads
  `.infrahub.yml`'s `jinja2_transforms` entry, runs the tree's `device_config.gql` against
  the branch and renders the tree's `.j2` locally (infrahub-sdk 1.23.2,
  `ctl/cli_commands.py`). `--out` writes the bytes; without it `rich` prints them. The
  query's `ip_addresses { edges { node { address { value } } } }` inside `... on
  InterfacePhysical` answers on 1.11.2 (`InterfaceLayer3`'s relationship, inherited, needs
  no further fragment: its peer `IpamIPAddress` is one node). On two throwaway
  `fylgja-test-t034-*` branches, seeded by this tree's `SeedThreeNode` and `SeedMixed`
  (whose artifacts the imported template rendered, so every stored artifact is the old
  template's), each render differs from its stored artifact by the address lines alone:
  `n1` (and `n2` with `10.2.…`, `s1` as `n1`) gains, after each probe-ready port's
  `subinterface 0 admin-state enable`, `set / interface ethernet-1/10 subinterface 0 ipv4
  admin-state enable`, `set / interface ethernet-1/10 subinterface 0 ipv4 address
  10.1.10.1/24`, and the same two for `ethernet-1/11` with `10.1.11.1/24`; `e1` gains `ip
  routing` after `hostname e1`, and `no switchport`, `ip address 10.2.10.1/24` under
  `Ethernet10` and `no switchport`, `ip address 10.2.11.1/24` under `Ethernet11`, after
  `no shutdown`. A second address written on `e1:Ethernet10` (`10.2.10.5/24`) and on
  `n1:ethernet-1/10` renders after the first, in value order, `ip address 10.2.10.5/24
  secondary` on EOS (a plain second `ip address` replaces the first there) and a plain
  `… ipv4 address 10.1.10.5/24` on SR Linux. EOS's interface lines render unindented, as
  they always have: each follows a `-%}` that strips the next line's leading spaces, and
  the stored artifacts read the same. On `fylgja-fixture` (seeded before 016, no address),
  the renders of `n1`, `n2` and `n3` equal their stored artifacts byte for byte, MD5
  `597f6263…`, `5ac21560…` and `e93df964…`, each its artifact's checksum. Both branches
  deleted; `Branch` then lists `main` and `fylgja-fixture`, `main`'s hash `8a4f3bee…`
  unmoved. The lines on the images stay §4.4's, the live session's. *(Infrahub 1.11.2,
  infrahub-sdk 1.23.2, 2026-10-29)*
- **R-19 The fixture's CTM follows the seed in its artifacts too** (Run 20, T035): R-19's
  "the fixture's CTM moves for the ports alone" does not hold. The reader reads no address,
  but the template renders every non-management physical port, cabled or not, so a seeded
  device's artifact gains each probe-ready port's lines under the imported template
  already, and its addresses once T034's template is imported. `TestMixedSeedReads`, run
  alone against a branch this tree's `SeedMixed` seeded, read `mixed.json`'s devices,
  interfaces (`ethernet-1/10`, `-1/11` on `s1`, `Ethernet10`, `Ethernet11` on `e1` and
  `e2`, uncabled, `mgmt_only` false, enabled) and links exactly, and differed in the three
  artifacts alone: `interface Ethernet10` / `no shutdown` and the same for `Ethernet11` on
  each EOS device, and `set / interface ethernet-1/10 admin-state enable`, its
  `subinterface 0 admin-state enable` and `network-instance default interface
  ethernet-1/10.0` (and `-1/11`) on `s1`. Since the goldens move only once more and the
  fixture is re-seeded after the import (T041, T042), the test CTMs carry the tree
  template's renders: `.venv/bin/infrahubctl render srlinux_device_config device=<d>
  --branch <b> --out <file>` on two throwaway branches seeded by the fixture tool
  (`fylgja-test-t035-3n`, `-mx`), each render's marker replaced by the fixture's
  (`FYLGJA-MARKER-fixture`, `FYLGJA-MARKER-mixed-fixture`) and its checksum the MD5 of the
  bytes. Each device gains ten lines (SR Linux: the two ports' five each, the `ipv4` pair
  among them) or nine (EOS: `ip routing` and the two ports' four each); `n1`–`n3` 1,327
  bytes each (`28881d3d…`, `092ca9f6…`, `95a3a917…`), `s1` 1,331 (`fdf83f15…`), `e1` 472
  (`b1431710…`), `e2` 476 (`e74b3db4…`); EOS's `Management1` comment moves from line 10
  to line 19, as the mixed compile's two warnings say. Both branches deleted; `Branch`
  then lists `main` and `fylgja-fixture`, `FylgjaProbe`, `FylgjaStage` and
  `CoreProposedChange` count 0. Until the import, `TestMixedSeedReads` fails on these
  lines, its seed's artifacts rendered by the imported template; until the re-seed,
  `TestFixtureReadsToTheThreeNodeCTM` fails on the interfaces and artifacts, as
  `TestReadCountsTheFixture` does on the count. *(Infrahub 1.11.2, infrahub-sdk 1.23.2,
  2026-10-29)*
- **The image** (Run 27, T042): `docker pull alpine:3.24.2` fetched it, and `docker image
  inspect --format '{{.Id}} {{.RepoDigests}}' alpine:3.24.2` reads
  `sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6
  [alpine@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6]`: on
  Docker 29.8.1 the image's id is its repository digest. Its busybox reads `v1.37.0`,
  `/etc/alpine-release` `3.24.2`. Both start-up reports then name it: `ping (embedded):
  image alpine:3.24.2 (public_registry, present on this host), flow ping every 0.2s, burst
  5`. *(Docker 29.8.1, 2026-10-29)*
- **§4.4 The fixture re-seeded under the imported template** (Run 27, T042): `make
  infrahub-clean && make infrahub-seed` (9 s and 43 s) seeds `fylgja-fixture` with the two
  addressed ports per device, and each `device-config` artifact, `Ready`, carries both
  ports' SR Linux lines, `subinterface 0 ipv4 admin-state enable` and `… ipv4 address
  10.<d>.10.1/24` (and `.11.1/24`), 1,327 bytes each, checksums `28881d3d…` (`n1`),
  `092ca9f6…` (`n2`) and `95a3a917…` (`n3`), each the MD5 of the stored bytes and equal to
  Run 20's renders. `intent read --branch fylgja-fixture --out` reads 3 devices, 15
  interfaces, 3 links and 3 artifacts, schema `8a4f3bee…`, `probes` `[]` with
  `FylgjaProbe` empty, and files snapshot
  **`0940db93e2ad1244a097824ececdaa6979500b1ddeeef15ca3cd612da68656ef`**, the same on a
  second read; its CTM's devices and links equal `testdata/ctm/three-node.json`'s; `twin
  compile --snapshot` writes bundle
  **`c3872f5c1cf8b79170a9bb0b902a3040ac34572e91c4ac089e5eb08306f0cf83`** (3 nodes, 3 links).
  *(Infrahub 1.11.2, 2026-10-29)*
- **§4.1 The `linux` host, live** (Run 27, T042, T043): on a throwaway branch's twin with
  `n1-loop`, containerlab deploys both hosts beside the three privileged SR Linux nodes in
  lab `fylgja` (deploy 46.7 s for 5 nodes; the whole create 52.5 s); a `linux` host is
  privileged too, as containerlab runs it. It runs each host's two `exec` lines after its
  links are made: inside `clab-fylgja-n1-loop-a`, `ip -4 -o addr show dev eth1` reads
  `inet 10.1.10.2/24`, and `ip route` holds `10.1.11.2 via 10.1.10.1 dev eth1` beside the
  connected route (`n1-loop-b` the mirror). The exec readiness held each host at its first
  attempt, 0.1–0.2 s after the deploy. `ping -c 3 10.1.11.2` from `a` is answered three
  times at TTL 63, and `traceroute` reads `10.1.10.1` then `10.1.11.2`: through `n1`. A
  host's container holds about 700 KiB. **A failed `exec` line is logged, not failed**: on
  a throwaway two-host topology under `CLAB_LABDIR_BASE` at a scratch directory, a route
  through an unreachable gateway is logged `ERRO Failed to execute command … rc=2` with its
  stderr (`ip: RTNETLINK answers: Network unreachable`), and the deploy exits 0 with the
  node `running`; the exec readiness is what catches it (destroyed after, with
  `--cleanup`). **`docker exec -d` and `pkill -INT` in a containerlab-run container**: `docker
  exec -d <host> sh -c 'pkill -x ping; exec ping -i 0.2 <far> > /run/flow.log 2>&1'` exits
  0 and leaves `ping` running; `pkill -INT -x ping` then makes it print its counters at
  once (`17 packets transmitted, 17 packets received, 0% packet loss`, the read 0.15 s), as
  §1.2 found outside containerlab. *(containerlab 0.79.0, Docker 29.8.1, alpine 3.24.2,
  SR Linux 24.7.1, 2026-10-29)*
- **§4.4 The template's lines on both images** (Run 27, T043): SR Linux accepts
  `subinterface 0 ipv4 admin-state enable` and `subinterface 0 ipv4 address 10.1.10.1/24`
  in the replace (each node's push 2.8–2.9 s), and `info from running /interface
  ethernet-1/10` reads `ipv4 { admin-state enable address 10.1.10.1/24 { } }`. On a
  throwaway mixed twin with `e1-loop` (`testdata/probes/e1-loop.json`; create 90.4 s,
  deploy 76.5 s), cEOS accepts `ip routing`, `no switchport` and `ip address` in the eAPI
  replace (pushes 2.3–2.5 s): `show running-config` on `e1` reads `ip routing`, and
  `no switchport`, `ip address 10.2.10.1/24` under `Ethernet10` (and `.11.1/24` under
  `Ethernet11`); the hosts ping through `e1` (first hop `10.2.10.1`), and `twin verify`
  reads `burst e1-loop 5 of 5 replies … held`. *(SR Linux 24.7.1, cEOS 4.32.0.2F,
  2026-10-29)*
- **§4.6 The flows' and the bursts' cost** (Run 27, T043): a burst, `ping -c 5 -i 0.2 -W 2`,
  takes 0.93–0.96 s by hand when every echo is answered; `twin verify` on the probed
  three-node twin 5.3 s (22 assertions over 5 nodes, 4 skipped), 6.0 s with the burst
  failing. Three steps on the probed twin, each pushing `n1` alone: to `n1:ethernet-1/2`
  disabled, 5.4 s and settled after 5.0 s, `loss n1-loop 0/45`; to `n1:ethernet-1/10`
  disabled with `--wait 30s`, `stepped` in 4.8 s and the wait expired after 34.4 s on
  `verify.burst n1-loop` (`0 of 5 replies`), `loss n1-loop 176/190`, longest gap 35.2 s,
  `twin verify` then exit 5 with `failed: 1 burst` alone; back, 5.0 s, settled after
  11.6 s, `loss n1-loop 41/77`, longest gap 8.2 s, the burst held. The flows add `step
  flows` (no measurable time) after the stage and `step loss` after the observe; the
  client's whole step 12.0, 40.8 and 18.3 s. Destroy 3.2 s, the hosts among its 5
  containers. *(2026-10-29)*
- **A step from a probed twin panicked the server** (Run 27, T043): `stepInput`
  (`internal/server/step.go`) read `n.PSP.ID` for every node of the twin's own manifest,
  and a host's `psp` is null, so the first step from a probed twin, a dry run's included,
  ended `twin.step outcome=panic` with no document (the client: `api.unreachable … unexpected
  EOF`). No tier-1 test stepped from a bundle carrying hosts. Fixed by skipping a node with
  no support package, as the target side's lookup already did, with
  `TestStepInputFromAProbedTwin` over the probed golden. `conformance.Boot` reads
  `n.PSP.ID` the same way, and its neighbour check would also expect a discovery neighbour
  on a probe's port; tier 3 runs the boot half on cases 1 and 6, whose twins carry no
  probe, so it is left for converge, named in T043's note. *(2026-10-29)*
- **Quickstart §3 and §4 corrected** (Run 27, T043): `intent read --probes` with a cabled
  endpoint files its snapshot, since placement is the compile's (FR-009, data-model §12),
  and `twin compile --snapshot` (or a create from it) refuses it,
  `probe.interface.cabled n1-loop/b`, exit 1; `--wait` takes a duration (`60s`), a bare
  `60` being `verify.wait.invalid`, exit 2; and `-generate` returns once the artifact
  count holds, before a rewrite lands (`GenerateArtifacts`' comment), so a read straight
  after it took `n1`'s old artifact once: the hand scenario waits for the checksum to
  move (about 10 s here). *(2026-10-29)*
- **§4.6 The tiers' times** (Run 28, T044, T045): tier 2 whole 2,017 s, against 019's
  2,009 s plus about a minute (Performance Goals), `internal/stages` 1,712.9 s, 87 s under
  its `-timeout 30m` (019: 109 s), then `internal/checks` 295.4 s; three artifact waits of
  1m30s lapsed under the tier's own load, each with one artifact `Pending`, and passed
  with their packages re-run alone (`internal/stage` 214.7 s, `internal/stages` 872.8 s),
  where 019's close lost one. Tier 3 `E2E-OK` at the first attempt in 2,236.6 s, about
  37.3 minutes against R-25's 34; case 9's rehearsals 82.7 s of 2,130 s and, failing at
  `probe-port-down` on the burst, 209.4 s of 2,850 s (R-16's deadlines hold with room);
  the losses measured on the container's basis, `n1-loop 0/45` and `0/52` across case 5's
  steps, `e1-loop 369/403` and `321/356` across case 8's restart of `e1` and back, `n1-loop
  641/656` across case 9's port down. *(Infrahub 1.11.2, containerlab 0.79.0, SR Linux
  24.7.1, cEOS 4.32.0.2F, alpine 3.24.2, 2026-10-29)*
- **The boot half on a probed twin, live** (convergence pass 1, T056, after T051): the
  worker and the server restarted from `086b07d`; `fylgja-test-t056-3187697` seeded (56.3
  s) and a twin created from it with `--probes testdata/probes/n1-loop.json` in 50.8 s,
  five nodes, snapshot `25794c5f…`, bundle `99830b6c…`, `n1-loop-a` and `n1-loop-b`
  ready in 0.1 s and 0.2 s. `FYLGJA_STATE_ROOT=$PWD/local go test -count=1 -tags e2e
  ./internal/conformance -run '^TestBootHalf$' -v` passed in 12.4 s wall (8.3 s the
  test's own): `boot half: 3 nodes [n1 n2 n3]`, then `2 probe hosts not read, having no
  package to read them by: [n1-loop-a n1-loop-b]`; `n1`'s two notes, `neighbor at
  /system/lldp/interface[name=ethernet-1/10]/neighbor: skipped: link
  n1-loop-a:eth1|n1:ethernet-1/10 is synthesized: n1-loop-a speaks no discovery protocol`
  and its `ethernet-1/11` twin naming `n1-loop-b`; `n1`'s line `4 cabled ports enabled and
  discovering; 2 neighbours as the bundle's links name them; 2 skipped on synthesized
  links`, the probe ports' state read as every cabled port's; `n2`'s and `n3`'s lines a
  three-node twin's (`2 cabled ports …; 2 neighbours …`); every check of the three devices
  held, none failed. Destroyed (5 containers) and the branch deleted. `scripts/e2e.sh`'s
  case 5 then runs it after its create, holding those three readings by `grep` (`c62d77d`),
  and tier 3 on that tree read **`E2E-OK`** at the first attempt, nine cases, exit 0, wall
  2,171.8 s (12:43:18–13:19:45Z; 016's Run 28 2,236.6 s): case 5's boot half 10.0 s
  (7.7 s the test's own), the same readings on its twin (bundle `d5a2c7aa…`, `n1` at
  172.20.20.3), beside case 1's 10.5 s and case 6's 5.9 s; case 5's verify 5.7 s, 18 held
  (1 burst), 4 skipped, its steps 12.1 s and 13.0 s, `n1-loop 0/45` and `0/53`; case 9's
  rehearsals 78.1 s of 2,130 s and 206.2 s of 2,850 s. The outputs are under
  `local/e2e-016-t056.outputs/`. *(SR Linux 24.7.1, cEOS 4.32.0.2F, containerlab 0.79.0,
  alpine 3.24.2, Infrahub 1.11.2, 2026-10-29)*
