# Fylgja — Roadmap

What is built, what comes next, and the order of the work after it. Each milestone is one
pass of the Spec Kit workflow or more, sized so that each pass has one contract boundary
and one kind of infrastructure in its tests. The architecture is in
[architecture.md](architecture.md), and every decision the milestones rely on is in the
[decision log](decisions.md).

A size here is a comparison with a built milestone, made before any research, and is
re-based when the item gets a spec, so the totals are a shape, not a commitment. An item
becomes a milestone, with the next free number, when its feature is specified; M8 and M9
keep the numbers they were planned with.

## Built

| | Theme | Delivers |
|---|---|---|
| **M1** | Read and compile | the intent reader and the pure compiler: a branch, at an optional point in time, read into the CTM and compiled into a deterministic, content-addressed bundle with its provenance and fidelity manifest; the schema's conformance and completeness checks; golden bundles |
| **M2** | Provision and destroy | the `fylgja-provision` and `fylgja-destroy` workflows, the worker, the containerlab driver, readiness, the twin directory and the CLI; one SR Linux twin end to end |
| **M3** | Operate | refusal while a twin exists; orphan detection at create and at the worker's start; destroy then create across references; a pinned `at` that reproduces its bundle |
| **M4** | Walking | following: a scheduled `Reconcile` that rebuilds the twin when its branch's `bundle_id` changes; `--no-follow`; `twin show` |
| **M5** | Configuration | each device's configuration as Infrahub renders it, carried in the bundle and pushed after readiness, so the twin runs what production will ([D-028](decisions.md#d-028)) |
| **M6** | PSP format and lossy mapping | a mapping profile that expresses many-to-one, breakout and management cases; the conformance suite; proven on SR Linux |
| **M7** | EOS | the EOS support package, as data; the account-gated `docker import` acquisition path; a mixed SR Linux and EOS twin |
| **M10** | Waypoints | `FylgjaWaypoint`, an operator-written, branch-agnostic name for a pinned reference ([D-032](decisions.md#d-032)); `twin create --waypoint`; `waypoint list` and `waypoint plan` with no lab; the pure step between two bundles |
| **M11** | Stepping | a running twin taken from one waypoint's bundle to another without a rebuild: the `fylgja-step` workflow, a replace push per package ([D-033](decisions.md#d-033)), a changed topology applied to a live lab, and a failed step left up and recorded as diverged ([D-036](decisions.md#d-036)) |
| **M12** | Verify | `twin verify`: the intent conformance report over the running twin, advisory and machine-readable, one finding per failed assertion and per record claim not held, exit 5 when the twin does not conform; its waiting form after every step's record ([D-037](decisions.md#d-037)–[D-039](decisions.md#d-039)) |
| **M13** | API | `fylgja serve` on the lab host as the boundary of the core ([D-040](decisions.md#d-040)–[D-042](decisions.md#d-042)): every command behind it, the stage commands included, and the CLI as its client holding the API's own token alone; runs started, followed and cancelled through it; the operator's files crossing it |
| **M14**, the cut | Reproducible and visible | this repository's first commit ([D-043](decisions.md#d-043)): the code with its comments and documents written for a reader of this repository, the contracts in [contracts/](../contracts/), the architecture drawn from one C4 model, the artifacts template ([D-044](decisions.md#d-044)), the module path `github.com/happypathnetworking/fylgja` and the Apache-2.0 license |
| **M14**, the launch | Reproducible and visible | the repository made public at its start ([D-043](decisions.md#d-043)), with `SECURITY.md` and pull requests refused; `scripts/bring-up.sh`, which takes a fresh Ubuntu 26.04 host to tiers 1 and 2 and the three processes running, for SR Linux alone when the cEOS tar is absent; CI running tier 1 on every push and pull request, and tier 2 on every push to `main` against a real Infrahub the script brings up on the runner, with no secret; Infrahub rendering from this repository, registered read-only on `main` with no credential ([D-044](decisions.md#d-044)); tier 3's platform list and its partial pass; the development host on Ubuntu 26.04; the recorded session, the one-page write-up and the first release, `v0.1.0` |

## Next

**7. The pure proposed-change check**, the first item of the order below, specified as
one pass with items 8 and 9, which share the API and the artifacts template with it: a
check beside the template that reports the step between a proposed change's source and
destination branches (item 7), a pinned twin of the source branch, verified, reported on
the proposed change (item 8), and a webhook that starts a check early (item 9). None has a
spec, a decision entry or a researched estimate; the order sizes the three at 8–10 hours,
and [the items](#the-items) say what each is.

## The order after the launch

The Infrahub-facing items come first, then observing, then M8 and M9, a third platform,
Ixia-c and a WebUI. Read-only production data stays [parked](decisions.md#parked). The
items keep the numbers the order was set with; the first six became M11 to M14, which are
built above.

None of these items has a feature spec, a decision entry or a researched estimate. M8, M9
and items 11, 13, 14, 15, 19, 20 and 21 are each one pass, with one contract boundary and
one new kind of infrastructure. Items 7 to 9 share one pass, since they share the API and
the artifacts template. Items 10, 12 and 16 are chores or records, with no spec.

| # | Item | What it bundles | Needs | Hours | Why here |
|---|---|---|---|---|---|
| 7 | **Pure proposed-change check** | a check beside the artifacts template that reports the step between source and destination | M13 | 3–4 | The first time Fylgja appears inside Infrahub's workflow. |
| 8 | **Live proposed-change check** | a pinned twin of the source branch, verified, reported on the proposed change | M12, M13 | 3–4 | Small, since verify and the API exist. |
| 9 | **Webhook-triggered checks** | a webhook starts a check early; the compare is unchanged | M13 | 2 | [D-026](decisions.md#d-026) already names it as the next step. |
| 10 | **Generic transform** | a template rendering a baseline artifact from the generics alone | nothing new | 2 | Makes item 11 cheap and is an OpsMill artefact in itself. |
| 11 | **Second schema via `infrahub-sync`** | a NetBox-shaped schema implementing the generics; a sync mapping; a twin of a NetBox-sourced network | item 10, a NetBox instance | 5–8 | The strongest OpsMill signal, and the first test of Constitution III. |
| 12 | **Agent surface** | a skill in OpsMill's format over the CLI; a small MCP server over the API | M12, M13 | 2–5 | Cheap once there is something to ask. |
| 13 | **Observation** | markers with bundle id and waypoint; a `gnmic` targets export; a documented collector and Grafana dashboard; a per-capability definition of settled | M11, M13 | 4–6 | Convergence across a step becomes a graph. |
| 14 | **Probes** | a Fylgja-owned probe kind; synthesized ping and iperf3 hosts; loss across a step; a probe package format | M11, M12 | 5–7 | The headline demo: loss during a change on a running twin. |
| 15 | **Operational state diff** | adjacencies and routes snapshotted at each waypoint pause and diffed; posted on the proposed change | M11, M12, item 8 | 4–6 | Builds on verify's readers and its observed facts. |
| 16 | **Upgrade rehearsal** | the same intent on another NOS version through the package override, then verified | M12, a second image version | 2–4 | Cheap and operationally compelling. |
| 17 | **M8** Object storage and Temporal cluster | as below | nothing new | 6–10 | Needed either way before M9. |
| 18 | **M9** Remote hosts | as below; parallel twins for A/B of two changes | M8, lab hosts or a cluster | 12–20 | Gated, so it waits. |
| 19 | **Third platform, Cisco IOL** | the parked platform order's next vendor, as data | the IOL image | 5–14 | Independent of everything. Filler whenever a gated item blocks. |
| 20 | **Ixia-c** | the OTG probe mechanism; flows, rates, loss and latency | item 14 | 8–12 | After ping probes have proven the kind and the manifest. |
| 21 | **WebUI** | Go templates and htmx from the same binary, or a decision amending Constitution I | M12, M13, item 13 | 6–10 | Last, so it has verify, steps and observation to show. |

| Phase | Items | Hours |
|---|---|---|
| Infrahub-facing | 7–12 | 17–25 |
| Observing | 13–16 | 15–23 |
| Scale and surface | 17–21 | 37–66 |
| **All** | | **69–114** |

### The items

**7. The pure proposed-change check.** Infrahub's change workflow is the proposed change
with its checks, and Fylgja is a read-only consumer that never closes the loop. The first
check compiles the proposed change's source and destination branches and reports the step
between them on the proposed change, as an advisory. `step.Diff` already does this between
two waypoints, so it needs no twin and answers in seconds. The check lives beside the
artifacts template in this repository, as the OpsMill skills describe it
(`check_definitions` in `.infrahub.yml`, `InfrahubCheck`), and runs inside Infrahub's task
worker, so it reaches Fylgja through the API, not by running the binary. The check writes
the result: Fylgja never writes to Infrahub ([D-026](decisions.md#d-026), citing
Constitution III). Its report takes verify's advisory form ([D-039](decisions.md#d-039)).
Size: about M3's.

**8. The live proposed-change check.** The second check asks the API for a pinned twin of
the source branch, runs `twin verify` and reports its result on the proposed change. Open
for the spec: a boot takes one to three minutes, so whether the check waits for the twin or
a later check reads its result. With item 15 it also carries what changed operationally.
Size: about M3's.

**9. Webhook-triggered checks.** [D-026](decisions.md#d-026) closes with the candidate:
once Fylgja runs a long-lived HTTP listener, a webhook may start a check early, adding to
the interval and never replacing the compare. `fylgja serve` is that listener. A webhook
from Infrahub starts a check, the check reads, compiles and compares as it always has, and
following's latency falls from the interval to seconds. Size: small.

**10. The generic transform.** A transform beside the artifacts template, written against
the generics (`FylgjaDevice`, `FylgjaInterface`, `FylgjaLink`) rather than the reference
schema's kinds, rendering a baseline artifact for any schema that implements them.
[D-009](decisions.md#d-009) holds: Infrahub renders. The OpsMill transforms skill applies.
It is what makes item 11 cheap, and it is an OpsMill artefact in itself. Size: small.

**11. The second schema, fed by `infrahub-sync`.** [D-001](decisions.md#d-001) rejected
NetBox and Nautobot as the source of truth because they lack branching. It did not reject
them upstream. A one-way sync into Infrahub keeps the source of truth where branching
lives, and the sync writes, not Fylgja, so no decision changes. OpsMill ships
`infrahub-sync` for NetBox, Nautobot and others, with a config-driven mapping, so a sync
inside Fylgja would duplicate their product and add a runtime (Constitution I). What
Fylgja owes is a NetBox-shaped schema implementing the four generics, a sync mapping onto
it, and a twin of a NetBox-sourced network rendered through item 10. That schema matters
more than the sync: only the reference schema has ever implemented the contract, so
Constitution III's "demand the least possible" is untested until a second one does. The
mapping looks tractable. NetBox's interface carries `mgmt_only` already, its interface
types sort into physical and loopback, and a cable with two terminations is a link. A
multi-termination cable, a LAG and a platform without a vendor and NOS are the refusals to
expect, and each is a finding the second schema will word. Following works as it does now:
the sync writes to a branch on a schedule, and the twin follows that branch, so the
latency is the sync cadence plus the check interval. Needs a NetBox instance with demo
data. Size: about M3's plus the instance.

**12. The agent surface.** OpsMill ships Claude skills and an MCP server for Infrahub. A
`fylgja` skill in their format, or a small MCP server, exposes `twin create`, `show`,
`verify`, `destroy` and `waypoint plan` to an agent over the JSON every command already
prints with `--json`, so that an agent can ask whether a branch boots and converges, with
the credentials staying in the server's and the worker's environment as they do now. The
skill is the cheaper form, prose over the existing CLI; the MCP server is a client of the
API. Size: a few hours for the skill.

**13. Observation.** Stepping keeps a pause and recorded timings at each waypoint and
leaves telemetry out on purpose. The seeds exist: the package's `state` facet names the
transport and OpenConfig coverage, the conformance facet names the paths, and
[D-037](decisions.md#d-037)'s observed facts are the normalized vocabulary. Fylgja never
becomes a telemetry pipeline. It emits markers through the API, twin ready and step
applied, each with the bundle id, waypoint and timestamp, and it exports the twin's
targets, each node's management address, gNMI port, TLS and encoding, as a `gnmic` targets
file or Prometheus file discovery. A collector such as `gnmic` subscribes and exports to
Prometheus or InfluxDB, and Grafana computes convergence between the step marker and the
state settling. What "settled" means is defined per capability, for example route-table
counts unchanged for some seconds, or every BGP session established, and that is the
item's research. The honesty constraint is already written:
[architecture §6](architecture.md#6-known-limitations) and each package's fidelity say
convergence timing differs in containers, so these measurements compare change A with
change B on the same twin and predict nothing absolute, and every surface that reports one
says so (Constitution X). Item 8 can then carry a convergence time as an advisory. Size:
about M3's for the markers and the export, plus a documented collector setup and
dashboard.

**14. Probes.** [Architecture §4.2](architecture.md#42-canonical-topology-model-ctm)
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
across a change applied to a running twin. Size: about M6's, the kind and the manifest
included.

**15. Operational state diff.** With verify's readers, snapshot adjacencies and routes at
each waypoint pause and diff them, so a proposed change carries what changed
operationally, not only what changed in the topology, through item 8. Builds on
[D-037](decisions.md#d-037)'s observed facts. Size: about M6's.

**16. Upgrade rehearsal.** The same intent booted on another NOS version through the
package override directory and the package's `versions`, then verified. "Will this
configuration survive the next release" is a question every operator has. Mostly a
procedure and a package, gated on a second image version. Size: small.

**17. M8, object storage and a Temporal cluster.** Object storage replaces the bundle
store's directory behind its interface ([D-014](decisions.md#d-014)), and a self-hosted
Temporal cluster replaces `temporal server start-dev`. Both stay on the development host
unless M8's spec moves Infrahub and the cluster to a host of their own; either way the
storage and orchestration seams are crossed before the host seam. The width is the bundle
store's seam, not the cluster: `bundle.Store`'s `Path` and the wire's `BundlePath` cross
the task queue as local paths, so M8 is the first milestone since M2 to change what
`internal/lab/wire` means. Needed either way before M9.

**18. M9, remote hosts.** Remote lab hosts, per-host task queues in place of the one queue
([D-015](decisions.md#d-015)), and a scheduler that places each twin on a host. Excluding
the hosts' provisioning. The API already gives an operator access to a twin from another
machine. It does not reach a host it does not run on: `fylgja serve` runs on the lab host
and reads the host in its own process ([D-041](decisions.md#d-041)), so how the server
reaches a remote host, and whether the task queue is the answer, are M9's. Two twins at
once, one per host or namespace, are what make A/B of two changes possible, which items 13
and 14 make worth having.

**M9's runtime is open** ([the decision log's open questions](decisions.md#open-questions)).
If M9 targets clabernetes, as recommended, the cluster schedules the twin and pulls its
images, so the per-host queues, the scheduler and the image shipping largely give way to a
second lab driver, and the milestone also waits for clabernetes 0.9's release and a
cluster. M9 is re-scoped and re-sized when the question closes, before it is specified.

**19. A third platform as data: Cisco IOL.** The strongest proof of
[D-031](decisions.md#d-031) is a vendor nobody designed for. The parked platform order
names IOL next, then PAN-OS ([Parked](decisions.md#parked)). IOL needs no KVM, so it boots
on a host that does not nest, and its image is account-gated, so M7's `docker import` path
and `host.image.absent` carry over. Research first: readiness is gNMI-only and push is
JSON-RPC or eAPI, and whether IOL serves either is unverified, so the package may need a
new readiness or delivery mechanism. That is a format change under D-031, never a platform
branch, and the write-up must say so: a third vendor is "just YAML" only where the
existing mechanisms fit. Supported means both halves of the conformance suite pass
([psp/README.md](../psp/README.md)). It depends on nothing above, so it is the filler
whenever a gated item blocks. Size: between M6's and M7's; M7's if a mechanism is new.

**20. Ixia-c.** Keysight's community edition is a container with a containerlab kind, and
the Open Traffic Generator client has a Go implementation, so it stays Go end to end and
gives flows, rates, loss and latency where ping gives loss alone. It is a second mechanism
under item 14's probe package format. TRex needs hugepages and DPDK and is too heavy for
the development host. Size: about M7's.

**21. The WebUI.** Constitution I is where a UI bites: a JavaScript front end is a second
runtime. Either serve Go templates with htmx from the same static binary, with the assets
embedded as the packages are, which keeps the principle, or write a decision entry
exempting the UI. Its content is what the JSON already carries: `twin show`, following,
waypoints and plans, verify reports, steps and observation. Last, so it has something to
show beyond a status line. It is a second client of the same API. Size: between M6's and
M10's.

## Decisions the order needs

- At item 9: whether the webhook needs an entry beside [D-026](decisions.md#d-026), which
  already names it and keeps the compare.
- At item 14: a second Fylgja-owned kind on [D-032](decisions.md#d-032)'s pattern, and what
  a probe package is beside a platform package.
- Before item 18: M9's runtime, the decision log's
  [open question](decisions.md#open-questions).
- At item 21: whether the WebUI keeps Constitution I through server-rendered templates or
  amends it.
