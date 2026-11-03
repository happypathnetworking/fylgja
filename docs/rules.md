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
| `settings.missing` | the settings | a `FYLGJA_*` variable the server needs is not set, or is empty ([D-042](../design/decisions.md#d-042)); the message names the variable, never a value |

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
| `config.missing` | the device's configuration is empty |
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
`rejected`; that rule arrives with the API, like `bundle.rejected`. The object is an interface
as `device:interface`.

| Rule | Means |
|---|---|
| `interface.port.shared` | on a kind with no aliases, the rename puts this cabled interface (a link's end or a probe's endpoint) on a runtime port with another cabled interface of its node, and the twin can cable a port once. An uncabled interface the rename puts on a cabled one's port is an omission fidelity reports (`shared`), not a finding |

## Findings: admission refused

`admit` refuses a twin with one of these rules and a message naming every shortfall or
every absent image ([D-019](../design/decisions.md#d-019)); nothing is reserved. The loop
files the refusal as the run's one finding, an error whose object is the twin by name, and
ends the run `rejected`; that arrives with the loop.

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

## Problems: the API

Answered as problem documents by the server. The rest of the API's rules arrive with its routes.

| Rule | Status | Means |
|---|---|---|
| `auth.token.missing` | 401 | the request has no `Authorization: Bearer <token>` header (`GET /v1/version` needs none) |
| `auth.token.unknown` | 401 | the bearer token is not one a principal holds; the message never carries it |
| `auth.forbidden` | 403 | the principal is known and is not allowed the call |
| `request.invalid` | 400 | the request is malformed: a body that is not JSON, a parameter of the wrong form |
| `bundle.rejected` | 422 | the blueprint compiles to no bundle; the findings give every reason |
| `plan.rejected` | 422 | the bundle has no plan on the driver; the findings give every reason |
