# Rules

Every finding and refusal the core files has a stable dotted rule id (Constitution X), and
clients and tests match on the id, never on the wording. This is the catalogue, written
with the code that files each rule ([`findings-1.schema.json`](../formats/findings-1.schema.json)).
A **problem** is a refusal at the door, answered as a problem document
([`problem-1.schema.json`](../formats/problem-1.schema.json)), each with a JSON pointer to
the member at fault. A **finding** is part of a verdict, each naming the object it is about.
Rules the API, the drivers, the push and verify file arrive with their code.

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
| `package.id.duplicate` | the packages registry | two packages under `FYLGJA_PACKAGES` share an id (platform) or a format (probe); the message names both files |
| `settings.missing` | the settings | a `FYLGJA_*` variable the server needs is not set, empty or malformed ([D-042](../design/decisions.md#d-042)); the message names the variable, never a value, and the server exits 2 |

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
`device:interface`.

| Rule | Means |
|---|---|
| `interface.port.shared` | on a kind with no aliases, the rename puts this cabled interface (a link's end or a probe's endpoint) on a runtime port with another cabled interface of its node, and the twin can cable a port once. An uncabled interface the rename puts on a cabled one's port is an omission fidelity reports (`shared`), not a finding |

## Findings: admission refused

`admit` refuses a twin with one of these rules and a message naming every shortfall or
every absent image ([D-019](../design/decisions.md#d-019)); nothing is reserved. The loop
files the refusal as the run's one finding, an error whose object is the twin by name, and
ends the run `rejected` ([Conditions and runs](#conditions-and-runs)).

| Rule | Filed by | Means |
|---|---|---|
| `admission.capacity` | the local driver | the host cannot fit the twin: the pool has no /24 that neither a Docker network nor another twin's allocation holds ([D-043](../design/decisions.md#d-043)), or the deployment's demand exceeds the host's available memory (`/proc/meminfo`'s `MemAvailable`) or its CPU count |
| `admission.image.absent` | the local driver | a package the twin's nodes use has an account-gated image (one with a `pull_secret`) that is not on the host, which the local driver never pulls ([D-015](../design/decisions.md#d-015)); an ungated image is containerlab's to pull at deploy |

## Problems and findings: the credential provider, readiness and the push

| Rule | Raised by | Means |
|---|---|---|
| `credential.missing` | the credential provider | a `FYLGJA_CREDENTIAL_<NAME>_USERNAME` or `_PASSWORD` variable a package's credential names is not set, or is empty; the message names the variable, never a value ([D-042](../design/decisions.md#d-042)). An operator-environment fault: neither a retry nor a new spec clears it, only setting the variable |
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
| `verify.node.unread` | error | a node could not be read: the record holds no such node or no address for it, its package's credential is missing (the message is the provider's), its `Get` failed or did not end within the read's budget (the message names the address, the port and the gRPC status or the error's type, `TimeoutError` for the budget, never a credential), a read of this node is still running (another read of it in flight, or one whose caller stopped waiting: this one is refused at once), no read thread was free within the read's budget (sixteen at most, [D-054](../design/decisions.md#d-054)), or `exec` could not reach a probe host for its burst |

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
would not help.

A bundle naming a package this core has not loaded (one compiled elsewhere, or a run resumed
by a core started without a package it began with) is refused with `bundle.rejected`: one
`platform.unsupported` or `probe.format.unknown` finding per package, its object the package
and its message naming who uses it. A driver's `destroy` takes the packages, so a deployment
this core lacks them for is not torn down: the lab stays, with its record, which keeps the
deployment, its allocation and its nodes, until a deletion or a new spec is handled by a core
that has the packages. Here, both are refused the same way, once, and a new spec starts no
create: nothing is compiled, admitted or destroyed over the kept deployment.

The findings the loop files itself, each an error:

| Rule | Ends the run | Means |
|---|---|---|
| `blueprint.missing` | `rejected` | the spec's blueprint is not in the store; the object is its id |
| `bundle.missing` | `rejected` | the spec's bundle is not in the store; the object is its id |
| `run.cancelled` | `failed` | the run was cancelled, by a client or by the twin's deletion during it, and cleaned up; a step cancelled before its apply began cleans nothing up, since it touched nothing ([Steps](#steps)); the API files it too, for a run it queued and withdrew before it started because its request's write failed (lost to another, or failed outright); and the loop, for a create or step run still queued, or queued and marked cancelling by a client, when it takes another create or step run of the twin afresh (made, or the newest queued): superseded before it started by that run, its message says, naming it (a client's, or the loop's own), as when two specs are written before the loop takes the first, or the API queued a create or a step by the record as it stood and the loop's later reading differs. A destroy run is never superseded |
| `twin.driver.unknown` | `rejected` | the spec names a driver this core does not serve; the object is the twin. The API refuses such a spec with a problem of the same rule, so the loop meets one only when a core was started without a driver its records name: every run of the twin in flight ends `rejected`, and nothing is torn down |

The `Ready` condition's reasons:

| Reason | Status | Means |
|---|---|---|
| `twin.ready` | `True` | the create reached `pushed`: every device node holds the bundle and answered; a step's reasons are under [Steps](#steps) |
| `twin.creating` | `False` | a create runs |
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
its apply began, the twin running what it ran; or `diverged` when it fails or is cancelled from
its apply on, an `apply started` of any pass of its run. There is no rollback
([D-029](../design/decisions.md#d-029)): a step never tears anything down, and a diverged twin
is left as it stands. It accepts only deletion, which destroys the deployment its record names
(the step's target once `applied` was recorded, else the one the twin ran) and deletes the
record, as any twin's; the loop, deleting a twin, first cancels a step run it finds in flight. A transient failure
ends no step, as it ends no create: the next pass resumes it, and probes the lab first when the
apply had begun. A step whose phases have all run has completed: a cancel then, a deletion's
too, ends it as it would have ended, `ok`. A dry run of a step (`PUT …?dry_run=true` on a twin
that runs) answers the refusal the loop would make, by the same rules, in its `Plan`'s verdict,
`rejected`, beside what the step would change.

The findings the loop files on a step:

| Rule | Severity | Ends the run | Means |
|---|---|---|---|
| `step.twin.diverged` | error | `rejected` | the twin is diverged: no bundle describes it, so it accepts only deletion. Refused at `compiled`, whatever the spec, and again after `planned` on a resume. The object is the twin. The refusal leaves `last_step` as the step that diverged the twin wrote it, its bundles, run and phase ([D-029](../design/decisions.md#d-029)), and writes the observed generation, no run, and `Ready` and `Stepping` False for this rule; `Diverged` stays True |
| `step.restart.required` | error | `rejected` | the driver's `changes` restarts or recreates the node, the object, and the spec's `allow_restart` is false; the message names the node's action and reasons. Refused after `planned`, before anything is touched, one finding per node. The spec is the one the run was taken under: a newer spec a client writes during the run is the next run's, and so is its `allow_restart`. A resume into an apply already begun does not check again: the pass that began the apply passed this check under the run's own spec, and the pure re-plan is that plan, so a newer spec refuses nothing there (the other refusals are made again, and one that holds then ends the step `diverged`) |
| `step.relink.unsupported` | error | `rejected` | the driver cannot make the change: one it cannot satisfy for a node, the object, or links that change on a driver that cannot change a running twin's links, the object being the twin. Refused after `planned`, before anything is touched |
| `step.wait.expired` | warning | `ok` | verify did not hold within the step's wait, `FYLGJA_STEP_WAIT_S` ([D-032](../design/decisions.md#d-032)); the message names the budget and the last verdict's status, and the `verify done` event carries the rule. Verify is advisory: the step goes on, and ends stepped. The object is the twin |
| `step.node.silent` | error | `diverged` | on a resume into an apply already begun, a device node, the object, is silent (present but stopped, without an address, or not answering), and the reconfigure that would remedy it makes every node anew, which the `allow_restart` of the spec the run was taken under does not allow; the message names the last phase recorded and what each node holds. A node missing from the lab is not silent: the plain apply that follows makes it anew, as it makes a node the step adds |
| `step.diverged` | error | `diverged` | the step failed or was cancelled after its apply began, and the twin is left as it stands. The object is the twin; the message names the phase it stopped in, where it stopped in one (a deletion's cancel, or a core without the twin's driver, stops none), the last phase it recorded and what each node holds as the record knows it (before `applied` the record still names the running twin's nodes, which the lab may no longer match). After a failure, the failing finding is in the verdict beside it, and the failing phase's event carries that finding's rule; after a cancel, `cancel done` carries `step.diverged` |

A step sets three conditions of the twin record
([`twin-record-1.schema.json`](../formats/twin-record-1.schema.json)), and `last_step` says how
it ended: `running`, `stepped`, `unchanged`, `rejected`, `cancelled` or `diverged`, naming the
run. Once a step leaves the twin diverged, its `last_step` stays: a later run, refused or
cancelled, writes the conditions alone.

| Condition | Reason | Status | Means |
|---|---|---|---|
| `Ready` | `twin.stepping` | `False` | a step is under way: from `compiled`, once it knows the bundle changes, until it ends |
| `Ready` | `twin.ready` | `True` | the step ended stepped, at `flows`, or unchanged at `compiled`: the twin runs what the spec asks |
| `Ready` | a refusal's rule, or `run.cancelled` | `False` | the step was refused, or cancelled before its apply began; the twin runs what it ran, or, diverged already, stays as it stands, its `last_step` the diverging step's |
| `Ready` | `step.diverged`, `step.node.silent` | `False` | the step left the twin diverged |
| `Stepping` | `twin.stepping` | `True` | a step is under way, as for `Ready` |
| `Stepping` | `twin.ready` | `False` | the step ended `ok`, stepped or unchanged |
| `Stepping` | the rule it ended for | `False` | the step ended short of its target, the rule being `Ready`'s: a refusal's, `run.cancelled`, `step.diverged` or `step.node.silent` |
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
| `server.error` | 500 | the server failed; the answer names nothing of the fault, which its log holds with the traceback |
