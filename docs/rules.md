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
| `package.patterns.placeholders` | both package loaders | a template uses a placeholder its match does not capture (`node_name`, a rename's `port`), a match captures one twice, or a probe package's command or readiness text names a placeholder that does not exist |
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

## Problems and findings: the credential provider, readiness and the push

| Rule | Raised by | Means |
|---|---|---|
| `credential.missing` | the credential provider | a `FYLGJA_CREDENTIAL_<NAME>_USERNAME` or `_PASSWORD` variable a package's credential names is not set; the message names the variable, never a value ([D-042](../design/decisions.md#d-042)) |
| `readiness.timeout` | readiness | a node's push transport did not answer an authenticated request within the budget (the package's `readiness.timeout_s` unless a caller gives one); the message names the address, the port and the budget |
| `readiness.unauthorized` | readiness | the node's push transport answered HTTP 401 or 403: the credential is refused, and waiting longer would not help |
