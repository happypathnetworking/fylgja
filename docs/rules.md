# Rules

Every finding and refusal the core files has a stable dotted rule id (Constitution X), and
clients and tests match on the id, never on the wording. This is the catalogue, written
with the code that files each rule ([`findings-1.schema.json`](../formats/findings-1.schema.json)).
A **problem** is a refusal at the door, answered as a problem document
([`problem-1.schema.json`](../formats/problem-1.schema.json)), each with a JSON pointer to
the member at fault. A **finding** is part of a verdict, each naming the object it is about.
Rules the API, the drivers, the push and verify file arrive with their code. The example
orchestrator's rules are its own, never the core's, and its catalogue is
[`orchestrator/rules.md`](../orchestrator/rules.md).

The Infrahub reader's rules are its own too, and its catalogue is
[`readers/infrahub/rules.md`](../readers/infrahub/rules.md).

## Problems: a document refused by its loader

| Rule | Filed by | Means |
|---|---|---|
| `blueprint.version.unsupported` | the blueprint loader | `blueprint_version` is not `1` |
| `blueprint.invalid` | the blueprint loader | the document violates its schema at the pointer; a device name that is not a DNS-1123 label is one such fault ([D-038](../design/decisions.md#d-038)) |
| `blueprint.unencodable` | the blueprint loader | a string of the hashed body holds a lone surrogate, which UTF-8 cannot encode, so the blueprint could have no id |
| `blueprint.unsorted` | the blueprint loader | a list the format sorts arrives out of order, or a link's `a` sorts after its `b`; the core never sorts for a client |
| `blueprint.duplicate` | the blueprint loader | a list the format keeps unique holds a key twice |
| `blueprint.link.endpoint.unknown` | the blueprint loader | a link's end names no device's interface |
| `blueprint.link.interface.shared` | the blueprint loader | an interface ends two links |
| `blueprint.link.mgmt_only` | the blueprint loader | a link ends on a management-only interface |
| `blueprint.probe.gateway.outside` | the blueprint loader | a probe endpoint's gateway lies outside its address's prefix |
| `blueprint.probe.address.shared` | the blueprint loader | two probe endpoints share one host address |
| `package.version.unsupported` | both package loaders | the package's version is not `1` |
| `package.invalid` | both package loaders | the package violates its schema at the pointer |
| `package.rule.name` | the platform package loader | two interface rules share a name |
| `package.management.rule` | the platform package loader | no rule, or more than one, is the management rule |
| `package.patterns.placeholders` | both package loaders | a template uses a placeholder its match does not capture (`node_name`, a rename's `port`), a match captures one twice, a probe package's command or readiness text names a placeholder that does not exist, or a host's start-up command (`host.address`, `host.route`) names one the plan does not render there: it may name `{address}`, `{interface}`, `{far_address}` and `{gateway}` alone |
| `package.ranges.placeholder` | the platform package loader | a `ranges` key is no placeholder of the rule's match |
| `package.rename.coverage` | the platform package loader | a rename names no data rule or names one twice, or a data rule has no rename while the kind has no aliases |
| `package.format.unsupported` | the probe package loader | the format names a mechanism this build does not run ([D-014](../design/decisions.md#d-014)) |
| `probes.version.unsupported` | the declaration loader | `probes_version` is not `1` |
| `probes.invalid` | the declaration loader | the declaration violates its schema at the pointer |
| `probe.name.duplicate` | the declaration loader | two probes share a name |
| `probe.gateway.outside` | the declaration loader | a gateway lies outside its address's prefix |
| `probe.address.duplicate` | the declaration loader | two endpoints share one host address |
| `probe.format.unknown` | the declaration loader, the compiler | no loaded probe package runs the probe's format |
| `bundle.version.unsupported`, `deployment.version.unsupported`, `twin_record.version.unsupported`, `findings.version.unsupported` | the store's and clients' readers | a stored or received document is of a version this core does not read |
| `bundle.invalid`, `deployment.invalid`, `twin_record.invalid`, `findings.invalid`, `problem.invalid` | the store's and clients' readers | the document violates its schema at the pointer |

## Problems: the server's start

| Rule | Filed by | Means |
|---|---|---|
| `server.extra.missing` | the console script | `fylgja-core-server` was run from a base install: a module of the server's libraries is not installed. The line names the module and the extra, `fylgja-core[server]`, and the server exits 2 ([D-084](../design/decisions.md#d-084)) |
| `server.optimised` | the server's start | Python runs with `-O` or `PYTHONOPTIMIZE`, which strip the `assert` inside asyncio that drops a connection accepted in the turn before a lost Lease's cut; the server exits 2 without reading a setting ([D-062](../design/decisions.md#d-062)) |
| `lease.lost` | the Lease | no renewal succeeded within the Lease's 15 s, or another holder took it; the server stops at once and exits 1 ([D-062](../design/decisions.md#d-062)) |
| `package.id.duplicate` | the packages registry | two packages under `FYLGJA_PACKAGES` share an id (platform) or a format (probe); the message names both files |
| `settings.missing` | the settings | a `FYLGJA_*` variable the server needs is not set, empty or malformed, or set to what another setting rules out ([D-042](../design/decisions.md#d-042)); the message names the variable, never a value, and the server exits 2 |
| `store.unconditional` | the object store's proof at start | the S3 endpoint accepted a create over an object, a replace at an earlier ETag or a delete at an earlier ETag ([D-061](../design/decisions.md#d-061)); the message names the condition it ignores, and the store is not opened |

## Findings: a compile refused

Each is an error, and every fault is reported in one pass. A compile with one is refused:
the API answers a 422 problem document, rule `bundle.rejected`, carrying these findings
([`formats/README.md`](../formats/README.md), note 8); that rule arrives with the API. The
object is a device by name, an interface as `device:interface`, a probe by name, or a probe
endpoint as `probe/a` or `probe/b`.

| Rule | Means |
|---|---|
| `network.empty` | the network has no devices, and a twin of nothing cannot be built |
| `platform.unsupported` | no loaded platform package has the device's platform id |
| `config.missing` | the device's configuration is present and blank; a device may carry none, and is then unmanaged ([D-048](../design/decisions.md#d-048)) |
| `interface.unmappable.linked` | a link or a probe ends on an interface the platform has no port for: out of its rule's range, or matched by no rule. An unmappable interface nothing touches is an omission fidelity reports, not a finding |
| `probe.format.unknown` | no loaded probe package runs the probe's format |
| `probe.host.collision` | the host's name, `<probe>-a` or `<probe>-b`, is a device's |
| `probe.device.unknown` | the endpoint names no device of the network |
| `probe.interface.unknown` | the endpoint names no interface of its device |
| `probe.interface.mgmt_only` | the endpoint is on the management port |
| `probe.interface.cabled` | the endpoint is on a port that ends a link |
| `probe.port.taken` | the endpoint is on a port an earlier probe's endpoint took |

## Findings: a plan refused

Each is an error, and every fault is reported in one pass. A driver's plan with one is
refused (`Unplannable`): the API answers a dry run with a 422 problem document, rule
`plan.rejected`, carrying these findings, as it does for `bundle.rejected` (API 1's `Plan`
shape requires a deployment, so a refusal cannot be a plan), and the loop ends such a run
`rejected`, the twin's Ready condition False with the reason `plan.rejected`; the API's
problem rule arrives with the API, like `bundle.rejected`. The object is an interface as
`device:interface`, or for `plan.registry.absent` a node by name.

| Rule | Means |
|---|---|
| `interface.port.shared` | on a kind with no aliases, the rename puts this cabled interface (a link's end or a probe's endpoint) on a runtime port with another cabled interface of its node, and the twin can cable a port once. An uncabled interface the rename puts on a cabled one's port is an omission fidelity reports (`shared`), not a finding |
| `plan.registry.absent` | on clabernetes, a node's package names a pull secret whose registry the twin's allocation does not hold: the credential's `_REGISTRY` variable was not set when the twin was admitted, and a stepping twin keeps its allocation ([D-057](../design/decisions.md#d-057)) |

## Findings: admission refused

`admit` refuses a twin with one of these rules and a message naming every shortfall, every
absent image or the namespace at fault ([D-019](../design/decisions.md#d-019)); nothing is
reserved. The clabernetes driver's `admit` also refuses a twin under a credential's own rule
when a pull credential's registry variable is set badly
([below](#problems-and-findings-the-credential-provider-readiness-and-the-push)). The loop
files the refusal as the run's one finding, an error whose object is the twin by name, and
ends the run `rejected` ([Conditions and runs](#conditions-and-runs)).

| Rule | Filed by | Means |
|---|---|---|
| `admission.capacity` | both drivers | the runtime cannot fit the twin: on the local driver the pool has no /24 that neither a Docker network nor another twin's allocation holds ([D-043](../design/decisions.md#d-043)); on either, the demand exceeds the runtime's free room less the admitted twins' pending demand, or a node fits no host ([D-073](../design/decisions.md#d-073)). The message is one sentence per shortfall, naming what the twin needs, what the reading found free and pending, or the node and the roomiest host |
| `admission.image.absent` | the local driver | a package the twin's nodes use has an account-gated image (one with a `pull_secret`) that is not on the host, which the local driver never pulls ([D-015](../design/decisions.md#d-015)); an ungated image is containerlab's to pull at deploy |
| `admission.namespace.taken` | the clabernetes driver | the namespace `fylgja-twin-<twin>` exists and does not carry the twin's labels ([D-057](../design/decisions.md#d-057)); nothing is reserved |

A client may read the room before it asks, `GET /v1/capacity` ([D-076](../design/decisions.md#d-076)); a dry run's 422 carries the same shortfall a create's `rejected` run would.

## Problems and findings: the credential provider, readiness and the push

| Rule | Raised by | Means |
|---|---|---|
| `credential.missing` | the credential provider; the clabernetes driver's `admit`, refusing the twin | a `FYLGJA_CREDENTIAL_<NAME>_USERNAME`, `_PASSWORD` or `_REGISTRY` variable a package's credential names is not set, or is empty, or, at the clabernetes driver's admission, one of a pull credential whose registry is set, or of one a stepping twin's allocation holds ([D-069](../design/decisions.md#d-069)); the message names the variable, never a value ([D-042](../design/decisions.md#d-042)). An operator-environment fault: neither a retry nor a new spec clears it, only setting the variable |
| `credential.malformed` | the credential provider; the clabernetes driver's `admit`, refusing the twin | a `FYLGJA_CREDENTIAL_<NAME>_REGISTRY` variable is not an image prefix, or, at the clabernetes driver's admission, its `<NAME>` gives a pull secret whose name Kubernetes refuses (not a DNS-1123 subdomain of at most 253 characters), or, at a stepping twin's, it names another prefix than the one the twin was admitted with; the message names the variable, never its value. An operator-environment fault, as `credential.missing` is |
| `readiness.timeout` | readiness | a node's push transport did not answer an authenticated request within the budget (the package's `readiness.timeout_s` unless a caller gives one); the message names the address, the port and the budget |
| `readiness.unauthorized` | readiness | the node's push transport answered HTTP 401 or 403: the credential is refused, and waiting longer would not help |
| `push.refused` | the push | the node refused the replace, and nothing landed ([D-027](../design/decisions.md#d-027)). By `json_rpc`, the message is the node's reason, read after its echo of the commands sent in its recorded shape `At line N: …`, with no diff line; when the node cut its message before the reason, it is the reason one `commit validate` request gives, or else one of the two sentences of [D-028](../design/decisions.md#d-028) and [D-047](../design/decisions.md#d-047). By `eapi`, it names the refused command, its number among the commands sent and the node's errors for it (or that the node named no reason), and the refused session is aborted, best effort |
| `push.unreachable` | the push | the node gave the push no answer: a refused connection, a TLS failure, an answer that cannot be decoded, an HTTP status other than 200, 401 and 403, or a body that is no JSON-RPC answer. Transient: the push is tried again. The message names the URL, never a body |
| `push.timeout` | the push | the node did not answer one push request within the package's `push.timeout_s`. Transient, as `push.unreachable`: the push is tried again. The message names the URL and the budget, never a body |
| `push.unauthorized` | the push | the node answered the push HTTP 401 or 403: the credential is refused, and pushing again would not help, so only a new spec clears it ([D-023](../design/decisions.md#d-023)). The message names the URL, never the credential |

## Findings: verify

Verify reads a running twin against its bundle and changes nothing
([D-051](../design/decisions.md#d-051), [D-053](../design/decisions.md#d-053),
[D-031](../design/decisions.md#d-031)). Each device node is read once, by one gNMI `Get` of
the package's `conformance` paths ([D-030](../design/decisions.md#d-030)), and each probe's
burst runs inside its hosts by `exec`. The verdict, of operation `verify`, carries `counts`:
`held`, the assertions that held, which file no finding; `failed`, those that did not, each
an error below; `skipped`, those not made, each an info `verify.skipped`. The object is a node
by name, a port as `device:interface` in production names, or a burst as `probe/a` or
`probe/b`, by the host it runs from.

| Rule | Severity | Means |
|---|---|---|
| `verify.host_name` | error | a node, configured or not, reports no host name, though the kind's baseline and any configuration both set one; or a node with no configuration reports a host name other than its device name, which the baseline sets it from. A configured node's host name is not asserted against its device name: a source-rendered configuration carries the production hostname, so it is read and reported as a skip |
| `verify.port.enabled` | error | a cabled port intent enables, a link's end or a probe's endpoint, reports an admin state other than its package's `conformance.port.enabled` value; a leaf the node does not report counts as the package's `absent` value, and fails where the package names none |
| `verify.port.neighbor` | error | one end of an intent link lists no neighbour, more than one, or one other than the far node, by its read host name, on the far port, by its node name. Both ends are read, since a shut port still lists a far end that restarted while the far end lists none |
| `verify.claim` | error | the record does not claim the node holds the bundle verified against; a node with no configuration makes no claim ([D-048](../design/decisions.md#d-048)) |
| `verify.burst` | error | a probe's burst, from one host toward the other's address, left an echo of the package's count unanswered; each direction is its own assertion |
| `verify.skipped` | info | an assertion not made, and why: a port intent disables, and its link at both ends; a synthesized link's neighbour; a neighbour whose far node reports no host name to judge it against; the claim of a node with no configuration; a configured node's host name, naming the host name read; both bursts of a probe whose endpoint intent disables, naming the port, since the probe cannot pass by intent, and no echo is sent; every assertion of a node that could not be read, a probe host's burst among them, and each neighbour facing it |
| `verify.node.unread` | error | a node could not be read: the record holds no such node or no address for it, its package's credential is missing (the message is the provider's), its `Get` failed or did not end within the read's budget (the message names the address, the port and the gRPC status or the error's type, `TimeoutError` for the budget, never a credential), a read of this node is still running (another read of it in flight, or one whose caller stopped waiting: this one is refused at once), no read thread of its twin's own was free within the read's budget (sixteen a twin, [D-054](../design/decisions.md#d-054), [D-075](../design/decisions.md#d-075)), or `exec` could not reach a probe host for its burst |

The status is `failed` when a node could not be read, whatever else was found; else
`nonconforming` when an assertion failed; else `ok`. A node that could not be read is never
`nonconforming` ([D-032](../design/decisions.md#d-032)): `failed` here means the read did not
complete.

## Conditions and runs

A create is a run ([D-023](../design/decisions.md#d-023)). It ends `ok`, or `rejected` when
the compile, admission or the plan refuses (nothing was built), or `failed` when a node
does not become ready, the push is refused or unauthorized, a credential is missing, or the
run is cancelled; either way the loop cleans up and waits for the spec to be written again.
Its verdict holds the findings, and the twin's `Ready` condition carries a **reason**, a
rule id too, which is also the `rule` of the run's ending event (the failing phase's
`failed` or `timed_out`, a compile or plan refusal's being `bundle.rejected` or
`plan.rejected`; or `cancel done`, carrying `run.cancelled`). A transient failure (the
driver's runtime failure, an unreachable node, the store) ends no run: its phase's `failed`
event carries the error's rule when it has one, no finding is filed, and the phase's next
`started` is the loop's try again after a backoff.

A cancelled create stops where it is, stopping a call on the runtime in flight, tears down
what it built, and ends `failed` with `run.cancelled`. A twin's deletion cancels a create in
flight that way, then a destroy run tears the twin down and deletes its record; it ends `ok`,
and a destroy run is never stopped halfway. In the partial-lab probe a node that refuses the
login is not silent: the run fails at once with `readiness.unauthorized`, since a reconfigure
would not help. The probe does not run on a driver that declares `reapply`
([D-068](../design/decisions.md#d-068)): a resumed apply there applies again, and a node
refusing the login fails the run in `ready`.

A bundle naming a package this core has not loaded (one compiled elsewhere, or a run resumed
by a core started without a package it began with) is refused with `bundle.rejected`: one
`platform.unsupported` or `probe.format.unknown` finding per package, its object the package
and its message naming who uses it. A driver's `destroy` takes the packages, so a deployment
this core lacks them for is not torn down: the lab stays, with its record, which keeps the
deployment, its allocation and its nodes, until a deletion or a new spec is handled by a core
that has the packages. Here, both are refused the same way, once, and a new spec starts no
create: nothing is compiled, admitted or destroyed over the kept deployment.

A restore is a run too ([D-067](../design/decisions.md#d-067)), the loop's own, by the
principal `core`. A pass on a settled twin (no deletion asked, its generation observed, a
deployment applied, no run in flight, not diverged) inspects it, unless this core lacks a
package its deployment names. A node at another incarnation than the record holds was replaced
behind the core's back and lost its push: it is readied and pushed again, and verify is run,
under a `restore` run, as a step does for a node whose incarnation moved. `ready` waits for each device
node holding nothing and every probe host, `push` pushes each node not holding the twin's
bundle, and verify is waited for within `FYLGJA_STEP_WAIT_S`. With every node running at its
recorded incarnation the pass writes nothing. A restore compiles, admits, plans and applies
nothing, tears nothing down, and leaves the phase, `last_step` and the observed generation as
they were. It sets `Ready` False for `twin.restoring` while it runs and True for `twin.ready`
when it ends `ok`; a twin that does not run what its spec asks, after a refused or cancelled
step, keeps the conditions that step left. A failure only a new spec can clear (a refused or
unauthorized push, a node that does not become ready, a missing credential) ends it `failed`,
or `rejected` for a bundle naming a package this core lacks, with `Ready` False for its rule
where it had set `twin.restoring`. The node keeps its new incarnation either way, holding
nothing when it was not pushed again, so a refusal is not repeated: no later pass finds it
moved. A new spec is the remedy: a step, even one that compiles to the bundle the twin runs,
readies, pushes and verifies whatever holds nothing before the twin is `Ready` again
([Steps](#steps)). A transient failure (the driver's runtime failure, an unreachable node, the
store) is repeated: the run stays in flight, and the next pass after the backoff resumes it,
inspects again, and readies and pushes whatever holds nothing, a node replaced once more at its
newest incarnation. A cancel, by a client or by the twin's deletion, stops the restore where it
is: it ends `failed` with `run.cancelled`, tears nothing down, and `Ready` is False for
`run.cancelled` where it had set `twin.restoring`; a deletion then tears the twin down. It is
not repeated for what the restore recorded: the nodes it found, at their new incarnations. A
cancel that lands before that write (a core stopped between the restore's take and its record
of the nodes, then the cancel) leaves the old incarnations in the record, so the next kick finds
the node moved and restores again. The twin's deployment is the record's, so a restore never
diverges the twin, however it ends. A spec written while a restore runs waits for it, as for a
step: the restore completes toward the bundle the twin runs, and the same pass then steps the
twin to the new spec.

On clabernetes a node whose container ended or restarted in its pod is reached again only through
a new pod: read on an SR Linux node, its management address does not answer again once the
container runs there again ([verified-facts.md](../design/verified-facts.md)). The driver deletes
such a pod as its pod watch delivers the container's end, a state no starting pod passes through,
the cluster makes it anew within the node's boot window, and the pass restores the new pod as any
replaced one ([D-070](../design/decisions.md#d-070)). The rule is every node's alike; only SR Linux
was read. The driver does so at most three times in ten minutes a node. Past that the pod is left,
and the node's restore fails `readiness.timeout`, `Ready` False; no timer revisits it, so it is
left until its pod is delivered again with room in the window (its next end or restart), until the
core restarts, or until someone deletes the pod. A left pod that runs on unchanged, as one does
whose pushed configuration had ended it and which boots again without the push, keeps its twin
`Ready` False until then. A node can still read `twin.node.missing` when its end was missed by the
watch, and it is renewed at its restart about 25 s later, and when it is left, its container
restarting in place under the kubelet's backoff.

A node missing or not running is waited for, then reported, and never made: a runtime that
replaces a node brings it back by itself, and a twin is not repaired. Each node's boot window is
its package's readiness window (60 s for SR Linux, 90 s for cEOS, 30 s for a ping host), counted
from the first pass that saw that node absent, so a node gone after another, as when a drain
evicts a twin's pods one after another, is not judged on the other's clock. A node that runs
again drops its count, a create or step run drops the twin's, and a restarted core counts again.
While any absent node is inside its window the pass writes nothing and looks again within 5 s.
Once none is, a warning in the log names each node, since a condition carries no message, and
`Ready` is False for `twin.node.missing`, unless the twin does not run what its spec asks,
whose conditions stand; a restore under way ends `failed` instead, with one `twin.node.missing`
finding per node. The twin stays so until the node returns, or the twin is stepped or deleted:
each later kick looks again, and once every node runs a restore readies and pushes whatever
holds nothing and verifies the twin before it is `Ready` again. A container removed on the local
driver does not return by itself.

The findings the loop files itself, each an error:

| Rule | Ends the run | Means |
|---|---|---|
| `blueprint.missing` | `rejected` | the spec's blueprint is not in the store; the object is its id |
| `bundle.missing` | `rejected` | the spec's bundle is not in the store; the object is its id |
| `run.cancelled` | `failed` | the run was cancelled, by a client or by the twin's deletion during it, and cleaned up; a step cancelled before its apply began cleans nothing up, since it touched nothing ([Steps](#steps)); a restore cancelled stops where it is and tears nothing down, a node it had not pushed again holding nothing at its new incarnation, so it is not repeated once it recorded the nodes it found ([D-067](../design/decisions.md#d-067)); the API files it too, for a run it queued and withdrew before it started because its request's write failed (lost to another, or failed outright); and the loop, for a create, step or restore run still queued, or queued and marked cancelling by a client, when it takes another create or step run of the twin afresh (made, or the newest queued): superseded before it started by that run, its message says, naming it (a client's, or the loop's own), as when two specs are written before the loop takes the first, or the API queued a create or a step by the record as it stood and the loop's later reading differs. A destroy run is never superseded |
| `twin.driver.unknown` | `rejected` | the spec names a driver this core does not serve; the object is the twin. The API refuses such a spec with a problem of the same rule, so the loop meets one only when a core was started without a driver its records name: every run of the twin in flight ends `rejected`, and nothing is torn down |
| `twin.node.missing` | `failed` | a restore's node, the object, is missing or not running, and did not return within its boot window ([D-067](../design/decisions.md#d-067)); one finding per node, and a `ready failed` event per node, naming it and carrying the rule, ends the run. The loop never makes a node: the restore ends without it, tears nothing down, and sets `Ready` False for this rule where it had set `twin.restoring`. The twin stays so until the node returns, or the twin is stepped or deleted |

The `Ready` condition's reasons:

| Reason | Status | Means |
|---|---|---|
| `twin.ready` | `True` | the create reached `pushed`: every device node holds the bundle and answered; or a restore ended `ok`: every node it found replaced readied and pushed again, and verify run, which is advisory, so a restore whose wait expired (`step.wait.expired`) ends `ok` too ([D-032](../design/decisions.md#d-032)); a step's reasons are under [Steps](#steps) |
| `twin.creating` | `False` | a create runs |
| `twin.restoring` | `False` | a restore runs ([D-067](../design/decisions.md#d-067)): a node of a settled twin was found at another incarnation, and is readied and pushed again, then verify is run, which is advisory; or every node of a twin reported `twin.node.missing` runs again, and verify is run before it is Ready. Not set on a twin that does not run what its spec asks: a restore leaves the conditions a refused or cancelled step left |
| `twin.node.missing` | `False` | a node of a settled twin is missing or not running past its boot window, or a restore ended for it ([D-067](../design/decisions.md#d-067)); the log names each node. It is never made: the twin stays so until the node returns, when a restore readies and pushes what holds nothing and runs verify, which is advisory, before it is Ready, or until the twin is stepped or deleted. Not set on a twin that does not run what its spec asks |
| `twin.deleting` | `False` | the twin's deletion was asked, and the loop tears it down |
| `bundle.rejected` | `False` | the compile refused the blueprint; the run's verdict holds every finding ([a compile refused](#findings-a-compile-refused)) |
| `plan.rejected` | `False` | the driver's plan refused the bundle; the run's verdict holds every finding ([a plan refused](#findings-a-plan-refused)) |
| a finding's rule | `False` | the run ended with that one finding: `blueprint.missing`, `bundle.missing`, `run.cancelled`, `twin.driver.unknown`, an `admission.*` rule, `readiness.timeout`, `readiness.unauthorized`, `credential.missing`, `push.refused` or `push.unauthorized` |

## Steps

A step is a run too ([D-050](../design/decisions.md#d-050)): the create's phases, then
`verified` and `flows`, taking a running twin to the spec's new bundle. It ends `ok`, stepped
or unchanged (the spec's bundle is the twin's); `rejected` when it is refused before it touches
anything, the twin running what it ran: for one of the rules below, or for one a create's
refusal carries (an uncompilable blueprint, a running deployment naming a node no loaded
package runs, or one whose bundle names a package this core has not loaded, is
`bundle.rejected`); `failed` with `run.cancelled` when it is cancelled before
its apply began, the twin running what it ran, or with a readiness or push rule when an
unchanged step fails (below); or `diverged` when it fails or is cancelled from
its apply on, an `apply started` of any pass of its run. There is no rollback
([D-029](../design/decisions.md#d-029)): a step never tears anything down, and a diverged twin
is left as it stands. It accepts only deletion, which destroys the deployment its record names
(the step's target once `applied` was recorded, else the one the twin ran) and deletes the
record, as any twin's; the loop, deleting a twin, first cancels a step run it finds in flight. A transient failure
ends no step, as it ends no create: the next pass resumes it, and probes the lab first when the
apply had begun, on a driver that does not declare `reapply`. A step whose phases have all run
has completed: a cancel then, a deletion's too, ends it as it would have ended, `ok`. A dry run
of a step (`PUT …?dry_run=true` on a twin that runs) answers the refusal the loop would make, by
the same rules, in its `Plan`'s verdict, `rejected`, beside what the step would change.

A step whose spec compiles to the bundle the twin runs (the same blueprint with `allow_restart`
changed, or that bundle named) changes nothing of the lab: it plans and applies nothing. Where
every device node holds that bundle it ends at `compiled`. Where one does not, as a restore that
failed or was cancelled leaves a node ([D-067](../design/decisions.md#d-067)), it first readies,
pushes and verifies it, as a restore does, so such a step is the remedy a client is given after
that restore; it then ends `ok`, `last_step` `unchanged`. Such a step records no phase past
`compiled`, whatever it pushed: its `last_step.phase` reads `compiled`, and its events say what
it readied, pushed and verified. A resume after it began to ready or push finishes those phases
and compiles no spec again, so a spec written meanwhile is the next run's. A failure in that
readiness or push ends it `failed`, `last_step` `rejected`, `Ready` and `Stepping` False for the
failing rule, and leaves the twin as a failed restore does: up, not diverged, nothing torn down,
since no apply began. Ending `ok`, it sets `Ready` True, unless `Ready` is False for
`twin.node.missing`: that reason is the pass on a settled twin's, which verifies the twin once
its nodes run again, so a step that changes nothing leaves it.

The findings the loop files on a step:

| Rule | Severity | Ends the run | Means |
|---|---|---|---|
| `step.twin.diverged` | error | `rejected` | the twin is diverged: no bundle describes it, so it accepts only deletion. Refused at `compiled`, whatever the spec, and again after `planned` on a resume. The object is the twin. The refusal leaves `last_step` as the step that diverged the twin wrote it, its bundles, run and phase ([D-029](../design/decisions.md#d-029)), and writes the observed generation, no run, and `Ready` and `Stepping` False for this rule; `Diverged` stays True |
| `step.restart.required` | error | `rejected` | the driver's `changes` restarts or recreates the node, the object, and the spec's `allow_restart` is false; the message names the node's action and reasons. Refused after `planned`, before anything is touched, one finding per node. The spec is the one the run was taken under: a newer spec a client writes during the run is the next run's, and so is its `allow_restart`. A resume into an apply already begun does not check again: the pass that began the apply passed this check under the run's own spec, and the pure re-plan is that plan, so a newer spec refuses nothing there (the other refusals are made again, and one that holds then ends the step `diverged`) |
| `step.relink.unsupported` | error | `rejected` | the driver cannot make the change: one it cannot satisfy for a node, the object, or links that change on a driver that cannot change a running twin's links, the object being the twin. Refused after `planned`, before anything is touched |
| `step.wait.expired` | warning | `ok` | verify did not hold within the step's wait, or a restore's, `FYLGJA_STEP_WAIT_S` ([D-032](../design/decisions.md#d-032)); the message names the run's operation, the budget and the last verdict's status, and the `verify done` event carries the rule. Verify is advisory: the step goes on, and ends stepped, and a restore ends `ok`. The object is the twin |
| `step.node.silent` | error | `diverged` | on a resume into an apply already begun, a device node, the object, is silent (present but stopped, without an address, or not answering), and the reconfigure that would remedy it makes every node anew, which the `allow_restart` of the spec the run was taken under does not allow; the message names the last phase recorded and what each node holds. A node missing from the lab is not silent: the plain apply that follows makes it anew, as it makes a node the step adds. It does not arise on a driver that declares `reapply` ([D-068](../design/decisions.md#d-068)): a resume there applies again, with no probe |
| `step.diverged` | error | `diverged` | the step failed or was cancelled after its apply began, and the twin is left as it stands. The object is the twin; the message names the phase it stopped in, where it stopped in one (a deletion's cancel, or a core without the twin's driver, stops none), the last phase it recorded and what each node holds as the record knows it (before `applied` the record still names the running twin's nodes, which the lab may no longer match). After a failure, the failing finding is in the verdict beside it, and the failing phase's event carries that finding's rule; after a cancel, `cancel done` carries `step.diverged` |

A step sets three conditions of the twin record
([`twin-record-1.schema.json`](../formats/twin-record-1.schema.json)), and `last_step` says how
it ended: `running`, `stepped`, `unchanged`, `rejected`, `cancelled` or `diverged`, naming the
run. Once a step leaves the twin diverged, its `last_step` stays: a later run, refused or
cancelled, writes the conditions alone.

| Condition | Reason | Status | Means |
|---|---|---|---|
| `Ready` | `twin.stepping` | `False` | a step is under way: from `compiled`, once it knows the bundle changes, until it ends |
| `Ready` | `twin.ready` | `True` | the step ended stepped, at `flows`, or unchanged, at `compiled` or once it pushed each device node that did not hold the twin's bundle: the twin runs what the spec asks. An unchanged step leaves a `Ready` False for `twin.node.missing` as it is |
| `Ready` | a refusal's rule, or `run.cancelled` | `False` | the step was refused, or cancelled before its apply began; the twin runs what it ran, or, diverged already, stays as it stands, its `last_step` the diverging step's |
| `Ready` | a readiness or push rule | `False` | an unchanged step failed to ready or push a device node that did not hold the twin's bundle; the twin is up and not diverged, and `last_step` is `rejected` |
| `Ready` | `step.diverged`, `step.node.silent` | `False` | the step left the twin diverged |
| `Stepping` | `twin.stepping` | `True` | a step is under way, as for `Ready` |
| `Stepping` | `twin.ready` | `False` | the step ended `ok`, stepped or unchanged |
| `Stepping` | the rule it ended for | `False` | the step ended short of its target, the rule being `Ready`'s: a refusal's, `run.cancelled`, an unchanged step's readiness or push rule, `step.diverged` or `step.node.silent` |
| `Diverged` | `step.diverged`, `step.node.silent` | `True` | the step failed or was cancelled after its apply began. It is never set back: the twin accepts only deletion |

A core that does not serve the twin's driver ends a step in flight as it ends a create
(`twin.driver.unknown`): `Ready` and `Stepping` False for that rule, the step `rejected`, or
`diverged` with `step.diverged` beside it when its apply had begun, `Diverged` then True for
`step.diverged`; a step whose phases have all run ends `ok`, as it would have. A step whose run
ended with the record's last write lost is recorded from its verdict first, by any core, since
it tears nothing down.

## Problems: the API

Answered as problem documents by the server. A blueprint its loader refuses is `400`, under
the first problem's rule ([a document refused by its loader](#problems-a-document-refused-by-its-loader)),
with every problem a finding whose object is its pointer.

| Rule | Status | Means |
|---|---|---|
| `auth.token.missing` | 401 | the request has no `Authorization: Bearer <token>` header (`GET /v1/version` needs none) |
| `auth.token.unknown` | 401 | the bearer token is not one a principal holds; the message never carries it |
| `auth.forbidden` | 403 | reserved until roles exist ([D-025](../design/decisions.md#d-025)): a known principal not allowed the call. No route files it yet: every known principal may make every call |
| `request.invalid` | 400 | the request is malformed: a body that is not JSON (RFC 8259, so no `NaN`), a body its schema refuses (a finding per violation, at its pointer), a package of neither kind, a twin name to write or filter by that is no DNS-1123 label, a query parameter of the wrong form (`watch` not `true` or `false`; `since_revision`, `after` or a `Last-Event-ID` not an integer of 0 or more), an `If-None-Match` other than `*` |
| `request.not_found` | 404 | API 1 has no such path |
| `request.method` | 405 | the path does not take the method; the `Allow` header names those it takes |
| `blueprint.not_found` | 404 | no blueprint is filed under the id, or the id is not one (64 lowercase hex digits) |
| `bundle.not_found` | 404 | no bundle is filed under the id, or the id is not one |
| `twin.not_found` | 404 | no twin has the name, or the name is not one a twin can have |
| `run.not_found` | 404 | no run has the id, or the id is no ULID |
| `twin.conflict` | 412 | `If-Match` names a revision the record has moved past, or a twin that does not exist; or the write lost to another, and the run queued for it was withdrawn (`run.cancelled`). A new spec that lost to the loop's own write of the status alone is written once more over it, its refusals checked again, and fails so only when it loses again or `If-Match` named a revision |
| `twin.exists` | 412 | `If-None-Match: *` asks to create a twin that exists, or a create lost to another, its run withdrawn |
| `twin.driver.unknown` | 400 | the spec names a driver this core does not serve; the message names those it serves |
| `twin.driver.fixed` | 409 | the spec names another driver than the one the twin was created on |
| `twin.not_running` | 409 | verify was asked of a twin with no applied deployment, so there is nothing to read; a create's deployment is applied once the record holds its nodes, at `applied` |
| `twin.deleting` | 409 | the twin's deletion was asked, so its spec is not written again |
| `twin.diverged` | 409 | a new spec of a diverged twin, which accepts only deletion ([D-029](../design/decisions.md#d-029)): the one refusal of a step the door reads from the record ([D-050](../design/decisions.md#d-050)), for a dry run too. The spec the twin has already answers `200`, changing nothing |
| `run.ended` | 409 | the run asked to cancel has ended; the message names its verdict's status |
| `bundle.rejected` | 422 | the blueprint compiles to no bundle; the findings give every reason |
| `plan.rejected` | 422 | the bundle has no plan on the driver; the findings give every reason |
| an `admission.*` rule | 422 | a dry run's admission refused the twin; the one finding is the refusal's ([admission refused](#findings-admission-refused)), since a refusal reserves nothing to plan with |
| `capacity.unread` | 503 | the running driver could not read its runtime's room for `GET /v1/capacity`; the answer names nothing of the fault, which the log holds ([D-076](../design/decisions.md#d-076)) |
| `server.error` | 500 | the server failed; the answer names nothing of the fault, which its log holds with the traceback |
