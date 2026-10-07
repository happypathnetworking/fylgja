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

## Next

**The launch**, M14's second half, is the first feature specified here (`013-launch`). It
ends with this repository public and a stranger able to stand Fylgja up: one bring-up
script takes a clean host to every tier passing, and both of its consumers run it, the
setup of a fresh Ubuntu 26.04 VM and CI on a hosted runner. **Size**: 10–14 hours.

**The bring-up script.** One script takes a clean Ubuntu 26.04 install to every tier
passing, and the hand walk-through in [development.md](development.md) becomes its record.
It covers:

- **Toolchain.** `make`, `git`, a bootstrap Go that lets `go.mod` fetch its own
  toolchain, golangci-lint 2.14, the Temporal CLI, `gnmic`, and a Python venv with
  `infrahub-sdk[ctl]` and the `.gitignore` inside it.
- **Lab host.** Docker Engine with the user in `docker`, containerlab 0.79 with the user
  in `clab_admins`, the SR Linux image pulled, the cEOS image imported from an
  operator-provided tar, and the AppArmor widening for SR Linux's `rsyslogd`.
- **Infrahub.** The 1.11.2 Compose with the override that pins the version and caps
  Neo4j, the schema loaded on `main`, the group `fylgja-devices`, this repository
  registered read-only on `main` ([D-044](decisions.md#d-044)), which needs no
  credential once the repository is public, and the fixture seeded.
- **Fylgja.** `local/.env` scaffolded from `.env.example`, then `make build`, `make test`
  and `make test-contract` as the script's own proof, ending with the worker's and the
  server's start-up reports naming both packages.

Its test infrastructure is a fresh VM. The facts in [verified-facts.md](verified-facts.md)
were verified on Ubuntu 24.04, and a new release changes the kernel, the AppArmor profiles
and the packaged Docker, so the script's first run is the re-verification those facts ask
for on any upgrade. The cEOS tar stays the operator's to provide: the script asks for it
and refuses to continue without it, rather than silently skipping the steps that need it,
unless the launch gives it an SR Linux-only path (tiers 1 and 2, and tier 3 without the
EOS cases), which it then names as such.

**CI with a real Infrahub.** A GitHub Actions workflow runs tier 1, then the script's
Infrahub half (OpsMill's published Compose for 1.11.2, this repository registered, the
import awaited, the fixture seeded), then tier 2, with a badge in the README. The contract
job in `.github/workflows/ci.yml` is disabled until then. Tier 3 stays out of CI by
design ([development.md](development.md)). The seed refuses unless the artifacts
repository is connected and in sync on `main`, and the fixture tool does not register it,
which is why CI runs the script's Infrahub half rather than the Compose alone. Whether a
hosted runner boots Infrahub, imports and renders inside the job's time is a question only
a run answers. In a public repository a fork's pull request gets no secrets, so the
contract job runs on pushes to `main` alone, and never under `pull_request_target`, which
would run a fork's code with the job's secrets.

**Infrahub renders from this repository.** Until the launch, the development host's
Infrahub renders the configuration from a private copy of the template, registered with a
credential. The launch registers this repository in its place, read-only on `main` with
no credential, as [D-044](decisions.md#d-044) decides, once it is public. The template's
bytes are the same, so no artifact or fixture id moves. Whether Infrahub 1.11.2 takes a new
commit on a `ref` update or only on re-creation is verified then, and the fixture tool's
message that names the private repository is reworded.

**Visible.** The repository goes public at the launch's close, so the first view has the
script, CI and the README. Two things make it worth reading, neither a feature: a README
that says what is built and how to stand it up, and one recorded session of a create, a
step and a verify. With them:

- **`SECURITY.md`, the threat model.** The API is one bearer token sent in the clear, on
  loopback unless `--listen` says otherwise ([D-042](decisions.md#d-042)), and the server
  holds Infrahub's token and both node logins. A reader running it on a shared host is
  told so, and how to report a vulnerability.
- **A first release**: tag `v0.1.0` with a static binary attached, stamped by `make build
  VERSION=…`.
- **The repository's settings**: `main` protected, issues open and pull requests not taken
  (the README's Contributing), and topics (Infrahub, containerlab, digital twin, network
  automation).

Two records go with them:

- **A write-up of how Fylgja was built**, one page, `docs/how-it-was-built.md`: what a
  Spec Kit pass is, what a convergence pass finds, and what the hours say about
  AI-assisted engineering with a human deciding. It summarises the private development
  record ([D-043](decisions.md#d-043)) and does not cite it.
- **Issues filed against Infrahub.** [verified-facts.md](verified-facts.md) holds
  behaviours of Infrahub 1.11.2 that its documentation does not state, each verified live:
  an artifact is never regenerated on its own and nothing marks one stale; a `?branch=`
  parameter on `POST /graphql` is ignored and answers for `main` with no error; an
  attribute name is 3–64 characters, so `at` is refused by the JSON schema; a
  `BranchCreate` straight after a `BranchDelete` of the same name can fail with
  `graphql: None`; the SDL's field order is not stable between two fetches of one branch.
  Each is a candidate issue or discussion on `opsmill/infrahub`, through OpsMill's
  `infrahub-reporting-issues` skill, which classifies it, searches for a duplicate and
  shows the draft before anything is submitted.

The launch's tests need two kinds of infrastructure, a VM and a runner, one more than a
milestone is sized for. It is kept whole because both run the one script, and its spec may
still split CI out if the runner needs more than the script gives.

## The order after the launch

The Infrahub-facing items come first, then observing, then M8 and M9, a third platform,
Ixia-c and a WebUI. Read-only production data stays [parked](decisions.md#parked). The
items keep the numbers the order was set with; the first six became M11 to M14, which are
built or next above.

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
| The launch (M14) | — | 10–14 |
| Infrahub-facing | 7–12 | 17–25 |
| Observing | 13–16 | 15–23 |
| Scale and surface | 17–21 | 37–66 |
| **All** | | **79–128** |

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

- At the launch: whether the bring-up script offers an SR Linux-only path. Where the
  template lives and how Infrahub registers it are settled ([D-044](decisions.md#d-044)).
- At item 9: whether the webhook needs an entry beside [D-026](decisions.md#d-026), which
  already names it and keeps the compare.
- At item 14: a second Fylgja-owned kind on [D-032](decisions.md#d-032)'s pattern, and what
  a probe package is beside a platform package.
- Before item 18: M9's runtime, the decision log's
  [open question](decisions.md#open-questions).
- At item 21: whether the WebUI keeps Constitution I through server-rendered templates or
  amends it.
