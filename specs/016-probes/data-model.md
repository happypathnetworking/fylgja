# Data model: Probes

**Feature**: `016-probes` · **Plan**: [plan.md](plan.md) · **Research**:
[research.md](research.md)

Every type, document, format and identifier the feature adds or moves, and where in the
tree each changes. The tree is read at `ec5d244`. Two documents are new (the declaration,
the probe package), six move (snapshot `2`, bundle `6`, step, verify, rehearsal, `twin.json`
`11`), one Infrahub kind is added, and the worker gains two activities.

## 1. The probe declaration (`internal/probe`, `contracts/probes.schema.json`)

```text
Declaration { Version "1"; Probes []Probe }                 // the file; the snapshot carries Probes alone
Probe       { Name string; Format string; Endpoints [2]Endpoint }
Endpoint    { Device, Interface string; Address string /* a/l */; Gateway string /* a */ }
```

Rules a read applies with no CTM (`probe.Validate`, research R-04, R-20), each a
rejection naming the file or the object, the probe and the field: `probes.version.unsupported`
(not `1`, or none), `probes.invalid` (not an object, an unknown key, a missing field, other
than two endpoints), `probe.name.invalid` (not `^[a-z0-9][a-z0-9-]{0,23}$`),
`probe.name.duplicate`, `probe.format.unknown` (no loaded package declares it; applied
where a registry is at hand, the server's and the compile's), `probe.address.invalid` (not
an address with a prefix length), `probe.gateway.invalid` (not an address, or carrying a
prefix length), `probe.gateway.outside` (not within the address's prefix),
`probe.family.mixed` (the four addresses of one probe not of one family),
`probe.address.duplicate` (two endpoints of the list with one host address). Read by the
server (`--probes <file>`, the kind's objects mapped to elements, a sent snapshot's
elements) and by the snapshot's `Unmarshal` before filing. Written by the operator; by
`intent read --out` inside the snapshot. The file's version `1`; nothing older.

## 2. `FylgjaProbe` (`schema/fylgja-probe.yaml`)

Namespace `Fylgja`, node `Probe`, `branch: agnostic`, loaded on the default branch beside
`FylgjaStage`, written by the operator and only read by Fylgja (research R-07):

| Attribute | Kind | Required | Rule |
|---|---|---|---|
| `name` | Text | yes | §1's regex; `uniqueness_constraints: [[name__value]]`, `human_friendly_id: [name__value]`, `display_label`, `order_by` |
| `format` | Dropdown | yes | choices `ping`; default `ping` |
| `a_device`, `a_interface`, `b_device`, `b_interface` | Text | yes | non-empty |
| `a_address`, `b_address` | Text | yes | an address with a prefix length (regex) |
| `a_gateway`, `b_gateway` | Text | yes | an address with none (regex) |
| `description` | Text | no | not read |

A read yields the file's element: `{name, format, endpoints: [{a_*}, {b_*}]}`, in name
order, paged by 100 through `intent.ProbeReader` (`Check` holds the kind and its ten
attributes against `GET /api/schema`; `Probes` is the query `Probes` in `queries.graphql`;
the read-only test's owned roots gain `FylgjaProbe` with its reason). The kind absent is
`probe.kind.absent`. No relationship, no extension. The schema's `$id` is this
repository's. Loaded by the operator and by `-prepare-main` when absent.

## 3. The snapshot `2` (`internal/snapshot`, `contracts/snapshot.schema.json`)

`Version = "2"`; `Snapshot.Probes []probe.Probe`, written `[]` and never null; `Hashed`
unchanged in shape (`{"ctm": …, "probes": […]}`), the elements in the declaration's order;
`readProbes` decodes each element strictly and holds it to §1 (`snapshot.invalid` at
`probes[<i>].<field>`); `readVersion` accepts `"1"` and `"2"`, a `1` read as a `2` with
no probes (research R-05) and any other `snapshot.version.unsupported` naming both; `check`
holds a written document to `2`. `Take(c, probes)` wraps a CTM with a list; every take the
server makes passes the request's list (`stages.Pipeline.Take`, `takeSnapshot`). The `1`
schema is frozen as `internal/snapshot/testdata/contracts/019-following-removed/snapshot.schema.json`.
`twin create --snapshot` and `twin step --snapshot` take the stored or sent document's
list; the store is unchanged.

## 4. The synthesis (`internal/compiler/synthesize.go`)

```text
PlaceProbes(c *ctm.CTM, decls []probe.Probe, probes *probe.Registry) (placed *ctm.CTM, hosts map[string]Host, findings.List)
Host { Node, Probe, Endpoint ("a"|"b"), Device, Interface, Port string; Address, Gateway, FarAddress string; Package *probe.Package }
```

Pure. For each probe in name order and each endpoint in order: the device looked up by
name (`probe.device.unknown`), the interface by name (`probe.interface.unknown`), its
`link` empty (`probe.interface.cabled`, naming the link), not `mgmt_only`
(`probe.interface.mgmt_only`), not taken by an earlier probe (`probe.port.taken`, naming
it), the format in the registry (`probe.format.unknown`), the host name free
(`probe.host.collision`); then a device `{Name: <probe>-<end>, Platform: {Package:
<format>}, Interfaces: [{Name: eth1, Link: <id>, Provenance: synthesized}], Provenance:
synthesized}` and a link `{ID: CanonicalLinkID(host:eth1, device:interface), Provenance:
synthesized}` appended, and the device interface's `Link` set. Every refusal in one pass,
then nothing placed. Called by `validate` (`validate.Intent` and the server's sent-snapshot
rules) and by `Compile`, which then surveys the placed CTM as today: a host device's
package is read from the probe registry by its provenance, and it has no artifact to
refuse. The compiler's grep (`TestCompilerNamesNoPlatform`) sees no `linux`, `alpine` or
`ping` literal: each comes from a package.

## 5. The bundle `6` (`internal/compiler`, `contracts/manifest.schema.json`)

- `BundleVersion = "6"`; `bundle.Verify` accepts it alone, refusing a `5`
  (`bundle.version.unsupported`, naming both).
- `topology.clab.yml`: a host node `kind`, `image` and `exec` (the package's `host.address`
  and `host.route` templates rendered: `{address}`, `{gateway}`, `{far_address}`,
  `{interface}`), no `startup-config`; its link as any cabled link.
- `ManifestNode` gains `Provenance string` (`json:"provenance,omitempty"`, written only
  when `synthesized`) and `Probe *ManifestProbe{Name, Endpoint, Format, Package
  ManifestPSP}`; for a host `Platform`, `PSP`, `Artifact` and `Bootstrap` are written
  `null` (the two value fields become pointers), `Image` the package's, `ManagementPort`
  `eth0`. The schema: `platform`, `psp`, `artifact`, `bootstrap` nullable, `probe` present
  exactly when they are null (`if`/`then`).
- `MappingRow` and `CabledLink` gain `Provenance` (`omitempty`): the host's `eth1` row
  (`port eth1`, `node_name eth1`, cabled, `enabled true`) and the device port's row (cabled,
  since the synthesized link cables it) carry `synthesized`; links from `PlaceProbes` carry
  it.
- `Manifest.Probes []ManifestProbeEntry{Name, Format, Package ManifestPSP, Hosts
  [2]{Endpoint, Node, Device, Interface, Port, Address, Gateway}}`, sorted by name, `[]`
  when none; `Fidelity.Synthesized []string`, the host names sorted, `[]` when none.
- No configs file for a host. `fidelity.production_forwarding` is per platform package
  and gains no entry for a host; the package's `fidelity.forwarding: software` and `timing:
  container` are the `probes[]` entry's `fidelity {forwarding, timing}`.
- Goldens: the three re-baselined for the version, `probes: []` and `fidelity.synthesized:
  []`; a fourth, `three-node-probed`, from `testdata/snapshot/three-node-probed.json`
  (the three-node fixture wrapped with `n1-loop`); all four again when the fixture's ports
  land (research R-19). The `5` schema frozen under
  `internal/compiler/testdata/contracts/019-following-removed/`.

## 6. The probe package (`probes/`, `internal/probe`)

```yaml
probe_version: "0.1"
format: ping                                   # the mechanism's key (D-031)
image: { clab_kind: linux, ref: alpine:3.24.2, acquisition: public_registry,
         resources: { cpu: 0.1, memory_mb: 32 }, deploy_timeout_s: 60, destroy_timeout_s: 30 }
host:
  interface: eth1
  address: ["ip", "addr", "add", "{address}", "dev", "{interface}"]
  route:   ["ip", "route", "add", "{far_address}/32", "via", "{gateway}", "dev", "{interface}"]
readiness: { probe: exec, command: ["ip", "-4", "-o", "addr", "show", "dev", "{interface}"], expect: "{address}", timeout_s: 30 }
flow:  { interval_s: 0.2, command: ["ping", "-i", "{interval}", "{far_address}"], start_timeout_s: 30, read_timeout_s: 30 }
burst: { count: 5, wait_s: 2, command: ["ping", "-c", "{count}", "-i", "{interval}", "-W", "{wait}", "{far_address}"] }
fidelity: { forwarding: software, timing: container, approximations: [...] }
```

`probe.Package` decoded strictly; `probe.Registry{byFormat}` loaded from the embedded
`probes/*.yaml` and `<psp-dir>/probes/*.yaml`, an override shadowing by format;
`Validate` under `probes/probe.schema.json` (`probe.package.schema`, `probe.package.version.unknown`,
`probe.package.format.duplicate`, `probe.package.template` for a placeholder no field
renders); every budget, template and count read from it by the lab, the host check, the
compiler and verify, never from a constant. `Origin` embedded or override, as a PSP's. The
conformance pure half gains `CheckProbes`. The two roles' start-up report names the probe
packages beside the platform packages. Nothing of the package but its format and `clab_kind`,
image and templates enters a bundle, so a budget change moves no `bundle_id`.

## 7. The node plans and the host check (`internal/lab/hostcheck.go`, `wire`)

`wire.NodePlan` gains `Probe *ProbePlan{Format, Package PSPRef, Readiness ExecProbe{Command,
Expect, TimeoutS}, Flow FlowSpec{IntervalS, Command, StartTimeoutS, ReadTimeoutS}, Burst
BurstSpec{Count, WaitS, Command}}` and keeps `DeployTimeoutS`, `DestroyTimeoutS`,
`MemoryMB` from the package. `NodePlans` reads a host's package by `probe.package.id`
(`host.probe_package.missing` when absent). `noteImage` verifies a probe image whatever
its acquisition (`host.image.absent`, the remedy by acquisition: `docker pull <ref>` for
`public_registry`, research R-12). `AwaitReadiness` keyed by `readiness.probe: exec`: the
command through the Runner, ready when its output contains `expect`, under `timeout_s`;
no login. `PushConfig` schedules nothing for a host (no artifact, no bootstrap).

## 8. The activities and the step (`internal/lab/flows.go`, `internal/provision/workflow_step.go`)

| | Before | After |
|---|---|---|
| Activities | 15 | 17: `ActStartFlows = "StartFlows"`, `ActReadFlows = "ReadFlows"` |
| Step order | … StageStep → ReconcileLab → Readiness → Push → RecordStep → VerifyTwin | … StageStep → **StartFlows** → ReconcileLab → Readiness → Push → RecordStep → VerifyTwin → **ReadFlows** |
| Version marker | `verify` | `verify`, `flows` (both activities under `GetVersion("flows")`; the seven histories replay) |
| Phases | reconcile, readiness, push, record | + `flows` (an activity error or cancellation at either; diverged as any failure after the stage) |
| `StepInput` | | + `Flows []wire.FlowPlan{Probe, From, To string /* containers */, Far string, Flow FlowSpec}` (the probes both bundles carry, built by the server from the two manifests) and `Added`, `Dropped []string` |
| `StepResult` | | + `Loss *wire.Loss` |

```text
FlowsInput  { TwinDir string; Flows []FlowPlan }
FlowsResult { Flows []FlowOutcome }                              // StartFlows: started / not_started + rule, message
Loss        { Basis "container"; Probes []ProbeLoss; Added, Dropped []string }
ProbeLoss   { Probe, From, To string; Outcome measured|not_started|not_read|interrupted; Sent, Lost int; LongestGapS float64; Rule, Message string }
```

`StartFlows`: per flow, `docker exec -d <from> sh -c 'pkill -x ping; exec <command> >
/run/flow.log 2>&1'`, idempotent, under `start_timeout_s`, heartbeating; a host whose exec
fails is `not_started` under `flow.start.failed` and the activity returns. `ReadFlows`:
per flow, `docker exec <from> sh -c 'pkill -INT -x ping; …wait…; cat /run/flow.log'`,
parsed by `probe.ParsePing` into sent, lost and the longest gap (research R-14); a read
that fails is `not_read` under `flow.read.failed`; a flow never started is carried as it
was. On a failure or cancellation after the stage, `ReadFlows` runs on the record's
disconnected context, every outcome `interrupted`, and the record is written with it. The
dry run carries no loss. `RecordStep` takes `Loss` beside `Wait`; `twin.json`'s
`step.loss` is written by `ReadFlows`' writer as `VerifyTwin` writes `step.wait`. The
loss is in the step document's block (`step.loss`), the record and the rehearsal's stage.
`rehearsal.Mechanism` gains `FlowsMargin`; a rehearsed stage's deadline adds the two
budgets.

## 9. The burst (`internal/verify/assert.go`, `internal/lab/burst.go`)

`KindBurst = "burst"`; `Derive` appends, after the three kinds, one assertion per
`manifest.probes[]` in name order: `{Kind: burst, Node: <from host>, Probe, FarNode: <to
host>, FarAddress, Expected: "<count> replies"}`; the manifest's `probes[]` carries what
the derivation needs and the package supplies the command and the count at read. A host
node derives no other assertion; a synthesized link's two `neighbor` assertions are
`skipped` with the reason `link <id> is synthesized: <host> speaks no discovery protocol`;
the device port's `port_enabled` stands. `Burster` interface in `verify`, `DockerBurster`
in `lab` (`docker exec <from> <burst.command>` rendered, the summary parsed), faked in tier
1 beside the gNMI reader; `Input` gains `Burster` and `Probes probe.Registry`. Outcomes:
held (`received == count`), failed (`verify.burst`, object the probe, message `probe
<name>: <received> of <count> replies from <to> at <far address>`), unread (the exec
failed). `VerifyCounts` and `wait_counts` gain `burst`; the verify block's `nodes[]` admits
a host (`psp` null, `probe` named, no `host_name`, `ports []`) and gains `bursts[]`.
`verifyPackages` reads a host's package from the probe registry.

## 10. The report (`internal/rehearsal`, `contracts/rehearsal.schema.json`)

The table's columns: `| stage | at | snapshot | bundle | step | wait | verify | loss | new
verification failures | verdict |`; `loss` reads `<probe> <lost>/<sent>, gap <s>s` per
probe, joined by `; `, or `—`. The `rehearsal` block's stage gains `loss` (the step's
block, or null). The caveat: *"Fidelity is asserted, not measured: the twin's containers
forward in software and keep their own timing; a loss figure is the container's, never a
hardware forwarder's."* The shortening keeps the column.

## 11. The record: `twin.json` 11 (`internal/lab/twin.go`, `contracts/twin.schema.json`)

`TwinVersion = "11"`; `step.loss` (§8's block or null); `nodes[]` admits a host:
`{name, image, probe: {name, endpoint, format, package}, psp: null, artifact: null, holds,
…}`; a host containerlab created or recreated holds the staged bundle, since its
configuration is the topology's. A record of `10` or earlier reads with `loss` null.
Frozen: `internal/lab/testdata/contracts/019-following-removed/twin.schema.json`.

## 12. The identifiers (`internal/findings`)

| Rule | Severity, exit, step | Object |
|---|---|---|
| `probes.version.unsupported`, `probes.invalid` | rejection, 1, start (a file) or resolve (a sent snapshot) | the file or `probes[<i>].<field>` |
| `probe.name.invalid`, `probe.name.duplicate`, `probe.address.invalid`, `probe.gateway.invalid`, `probe.gateway.outside`, `probe.family.mixed`, `probe.address.duplicate` | rejection, 1, start / resolve | `<probe>` or `<probe>/<a|b>.<field>` |
| `probe.format.unknown`, `probe.device.unknown`, `probe.interface.unknown`, `probe.interface.cabled`, `probe.interface.mgmt_only`, `probe.port.taken`, `probe.host.collision` | rejection, 1, compile (and a stage's compile in a plan) | `<probe>/<a|b>` |
| `probe.kind.absent` | rejection, 1, resolve | `FylgjaProbe` |
| `probe.package.schema`, `probe.package.version.unknown`, `probe.package.format.duplicate`, `probe.package.template` | rejection, 1 (2 at `serve` and `worker run` start), verify | the package path |
| `host.probe_package.missing` | rejection, 1, host_check | the package id |
| `host.image.absent` | unchanged; now also a probe image of any acquisition | the image reference |
| `flow.start.failed`, `flow.read.failed` | warning, 0, flows | `<probe>` |
| `verify.burst` | rejection, 5, observe | `<probe>` |
| `snapshot.flags.conflict` | reworded: `--probes` beside `--snapshot` | `--probes` |
| `snapshot.invalid`, `snapshot.version.unsupported` | reworded for `2` and the elements | as today |

The step phase `flows`; the findings document's `step.loss`, `verify.counts.burst`,
`verify.nodes[].bursts`, `rehearsal.stages[].loss`; `api.schema.json`'s `probes` argument
on `intent.read`, `twin.create`, `twin.step`, `stage.plan`, `twin.rehearse`. None retires.

## 13. The documents

| Document | What moves |
|---|---|
| `contracts/probes.schema.json`, `probes/probe.schema.json` | new (§1, §6) |
| `contracts/snapshot.schema.json` (`2`), `manifest.schema.json` (`6`), `step.schema.json`, `verify.schema.json`, `rehearsal.schema.json`, `twin.schema.json` (`11`), `findings.schema.json`, `api.schema.json` | [contracts/formats.md](contracts/formats.md) |
| `contracts/cli.md`, `contracts/api.md` | "016: probes" sections ([contracts/commands.md](contracts/commands.md)) |
| `schema/fylgja-probe.yaml`, `schema/README.md` | the kind (§2), how a probe is written, the template's addresses and its no-routing sentence |
| `probes/README.md` | format `0.1`, the `ping` package's measured values, the override's `probes/` subdirectory |
| `psp/README.md` | one paragraph pointing at `probes/` |
| `infrahub/queries/device_config.gql`, `infrahub/templates/device_config.j2` | research R-18 |
| `docs/decisions.md` | D-064 (the operator's, research §3.1) |
| `.specify/memory/constitution.md`, `.specify/templates/plan-template.md` | 2.3.0 (the operator's, §3.2) |
| `docs/architecture.md` | §4.2 (provenance no longer all `intent`; the snapshot's `probes`), §4.3 (the synthesis, bundle `6`), §4.4 (the step's two activities, the phases, the counts), §4.5 (the hosts in the lab and the record), §4.6 (`--probes`, `twin verify`'s burst, the report's column), §4.7 (the probe package beside the PSP), §6 (container timing) |
| `docs/glossary.md` | Probe, Readiness probe told apart; Probe declaration, Probe package, Flow, Transient loss, Burst; Synthesized node reworded |
| `docs/development.md` | the layout (`internal/probe`, `probes/`), the tiers' cases, the import graph |
| `README.md` | the walk-through's probe step |
| `docs/brief.md` | Scope and Pipeline, one sentence each |
| `docs/roadmap.md` | F-014's paragraph and the entry built |
| `docs/verified-facts.md`, `CLAUDE.md` | research §4 |
| `docs/c4/workspace.dsl` | research R-28, then `make diagrams` |
| `scripts/e2e.sh` | research R-24 |
