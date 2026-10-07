# Platform Support Packages

A PSP is everything Fylgja needs to know about one NOS, as data. Adding a platform is a
data change, never a code change; a platform is *supported* when its PSP passes the
conformance suite. See architecture
[§4.7](../docs/architecture.md#47-platform-support-packages).

| File | Purpose |
|---|---|
| `psp.schema.json` | JSON Schema every PSP is validated against (`fylgja psp validate`) |
| `nokia_srlinux.yaml` | The first PSP: Nokia SR Linux |
| `arista_eos.yaml` | The second: Arista EOS on cEOS. Its image is **imported by hand and never pulled** ([development.md](../docs/development.md#local-environment)) |

PSPs are compiled into the binary with `embed` and may be overridden at runtime from a
directory (`--psp-dir` or `FYLGJA_PSP_DIR`;
[development.md](../docs/development.md#repository-layout)). The override is the lab
host's: `--psp-dir` is a flag of `fylgja serve` and `fylgja worker run` alone, and a
client's command is checked against the server's packages. An override package is
validated when it is loaded, by every role that loads it: a package `psp validate`
rejects is refused with its `psp.*` findings — exit 1 from a command, and exit 2 from
`worker run` and `serve` at start, each printing the package's findings before it
refuses — rather than accepted and failing later.

## Supported packages

A shipped package is supported when it has passed both halves of the conformance suite
(`internal/conformance`): the pure half in tier 1, on every `make test`, and the boot half
against a twin the product provisioned. The row names the run whose twin the boot half
read. The `link change` column is the package's `fidelity.link_change` (format 0.6): what
containerlab 0.79.0's reconcile does to a node of that image when a link of its is added
or removed.

| Package | Image | Version read | Passed | Date | Tier-3 run | Link change |
|---|---|---|---|---|---|---|
| `nokia_srlinux` | `ghcr.io/nokia/srlinux:24.7.1` | `v24.7.1-330-g38f237abfe` | both halves | 2026-09-19 | `fylgja-provision 01a0bad3-8f22-771d-8768-8c956e8db709` (case 1) | `live`: re-cabled with no lifecycle action, its push kept |
| `arista_eos` | `ceos:4.32.0.2F` (imported by hand; never pulled) | `4.32.0.2F-41889544.43202F (engineering build)` | both halves | 2026-09-21 | `fylgja-provision 01a0c486-3013-7cdc-b211-e235d1d66c9d` (case 6, the mixed twin) | `restart`: restarted in place, back on its startup configuration about 50–55s later, its push lost |

`arista_eos`'s row is tier 3's **case 6**, the mixed twin of `s1`, `e1` and `e2`: the boot
half read all three nodes there, each over its own package's transport (EOS plaintext gNMI
on 6030, SR Linux over TLS on 57400), with both cross-vendor adjacencies seen, in 13.1s.
`nokia_srlinux`'s row is tier 3's case 1. Tier 3 runs the boot half in both cases, so every
tier-3 run reads both packages again.

A shipped package without a row is not supported. `chassisos`
(`testdata/psp/lossy/`), `fastos` and `slowos` (`testdata/psp/heterogeneous/`) are test
packages: they pass the pure half only, declare no boot half, and are never shipped or
deployed. Nothing at run time consults this table.

Both rows hold on format 0.6. The pure half also checks `link_change` (below), on every
`make test`. Tier 3 creates every twin by the replace push and reads each create back,
case 1's and case 6's boot halves included; case 8 steps the mixed twin, and containerlab
restarts `e1` in place and re-cables `s1` live, as each package declares.

`twin verify` and a step's wait read a running twin by the same `conformance` facet and
readers, and this changes nothing about what "supported" means: verify holds a twin to the
intent it was built from, where the suite holds a package to what it declares, and neither
reads the other's verdict ([D-037](../docs/decisions.md#d-037)). Tier 3 verifies case 1's
and case 6's twins and requires them `ok`, each node read over its own package's transport.

## Format 0.6

`psp_version` is `"0.6"`. An earlier package is refused as `psp.version.unknown`
("declares format version "0.5", this build understands "0.6""), beside `psp.schema` for
the missing field; `testdata/psp/defects/version-0-5-m10.yaml`, the SR Linux package at
format 0.5, is kept to prove it. The change is one required field, one run-time meaning
and two reworded rules. **Nothing of it enters a bundle**: `mode` and `link_change`
travel on the wire, so neither moves a `bundle_id`, a golden or a recorded history
([D-033](../docs/decisions.md#d-033)).

| Field | Required | Meaning |
|---|---|---|
| `fidelity.link_change` | **yes** | What containerlab's reconcile does to a node of this kind when a link of its is added or removed. `restart`: the node is restarted in place and returns on its startup configuration, its push lost. `live`: it is re-cabled with no lifecycle action, and its push is kept. It is fidelity: asserted here, **measured by containerlab's plan at each step** (`clab deploy --dry-run`), and both are recorded in `twin.json`. Where they differ the step warns `step.restart.undeclared` and acts on containerlab's plan. Values other than the two are refused by the schema |
| `config.mode: replace` | changed meaning | [D-033](../docs/decisions.md#d-033)'s reset for the package's `delivery`: the push resets the candidate to the **baseline** containerlab left on the node, sends the bootstrap, then the artifact, asks the device for its diff and commits, in one request with one atomic commit. The device computes the difference; Fylgja reads none of the node's configuration back. `replace` with `commit: implicit` is refused (`psp.config.push.missing`): the reset needs a candidate |
| `config.bootstrap_via` | changed meaning under `replace` | Says only how a **deploy** delivers the bootstrap: `startup_config` or `push`. Under `mode: replace` the push sends the bootstrap after the reset whatever this says; under `merge` it is format 0.5's |

**The replace per delivery**:

- **`json_rpc`** (SR Linux): one JSON-RPC `cli` request — `enter candidate private`, `load
  startup`, the bootstrap's lines, the artifact's lines, `diff flat`, `commit now`. The
  answer is one text entry holding every command's output, and the device's diff is in
  it. A refusal's reason is cut at its first empty line, and no `insert`, `delete`,
  `update` or `replace` line of it is kept. SR Linux cuts its error message at about
  1 KiB, inside its echo of the commands, so a replace whose reason is cut asks once more
  with `enter candidate private`, `commit validate`, which commits nothing
  ([D-034](../docs/decisions.md#d-034)). A check the node makes only as a commit applies,
  such as the port range, passes `commit validate`, so its reason is not recovered and
  the finding says so ([D-035](../docs/decisions.md#d-035)). A refused line left in the
  private candidate is cleared by the next replace's `load startup`.
- **`eapi`** (EOS): one eAPI `runCmds` request in a named configuration session —
  `enable`, `configure session fylgja-<attempt>-<ns>`, `rollback clean-config`, `copy
  startup-config session-config`, the bootstrap's lines, the artifact's lines, `show
  session-config diffs`, `commit` — **sent with `format: text`**, because the diff command
  has no JSON model and `format: json` fails the whole request with code 1003 and leaves
  the session pending. The pair makes the session exactly the baseline: the copy alone
  would merge. A refused session is aborted before the next attempt, as format 0.5's is.

The device's diff is the push activity's result, kept in the run's history alone; no
record, finding, document or log line carries it.

**The baseline is containerlab's and is never read.** It is SR Linux's startup
configuration and cEOS's `flash:startup-config`, which hold containerlab's management
configuration (and on SR Linux the deploy's bootstrap). Nothing Fylgja does writes either,
because no push saves the running configuration. It is containerlab's, so the reset and
`link_change` are **re-verified on a containerlab or image upgrade**. Both were verified
against containerlab 0.79.0, SR Linux 24.7.1 and cEOS 4.32.0.2F.

**`merge` creates but does not step.** A package on `mode: merge` loads, validates and
creates a twin as at format 0.5. `twin step` refuses a twin with any node on such a
package, before anything is touched, as `step.package.merge`, naming the package and its
nodes: a step must remove what the previous artifact added, and only a replace does that.
Both shipped packages declare `replace`.

Two rules are reworded:

- **`psp.config.bootstrap_via` loses its replace clause.** `bootstrap_via: push` with
  `mode: replace` validated as a contradiction under format 0.5 ("the artifact would
  replace the bootstrap the same request had just applied"), which described a replace
  that began with `delete /`. D-033's resets before the bootstrap is sent, and the shipped
  EOS package is exactly this pair. The rule's other clause, a push needs a delivery that
  carries configuration lines, is unchanged word for word.
- **`psp.config.push.missing`, for `replace` with `commit: implicit`**, now reads `mode is
  replace with commit implicit; the reset loads the baseline into a candidate and commits
  it, which an implicit commit has none of, so no command list is defined for this pair`.

The conformance suite's pure half gains one check, `link_change`: the field is present
and one of the two values (`package <id> (<path>): link_change: declared <value or
nothing>, produced <not one of restart, live>`). The boot half is unchanged.

## Format 0.5

Format 0.5 is **purely additive**: six optional fields and a run-time meaning for two enum
values 0.4 already named, so a 0.4 package decodes under it and means exactly what it did.
The version line moved anyway, so that this file can record each field under the version
it arrived in.

Every field below exists because a real second platform needed it, and each one selects a
**mechanism** — code that already exists in kind — rather than adding a branch on the
platform ([D-031](../docs/decisions.md#d-031)). A package that names a value this build
has no mechanism for is refused at load, naming the ones there are:

| Field | Required | Meaning |
|---|---|---|
| `readiness.tls` | no (`true`) | Whether the gNMI probe — and the conformance suite's reader, which shares its dial — speaks TLS. `false` is plaintext gRPC, which cEOS serves under containerlab's default (`transport grpc default`, no SSL profile). SR Linux leaves it out |
| `readiness.await_push_transport` | no (`false`) | Whether the node is *ready* only once the endpoint `config.push` names also accepts a connection, not merely when the probe answers. cEOS's gNMI server answers about a second before its eAPI endpoint, and on that platform the bootstrap itself travels over the push, so without this the push meets `connection refused` on a node just called ready ([D-029](../docs/decisions.md#d-029)). Only a scheme and a port are used: no login is sent for the wait. Asking for it with no `config.push` is `psp.readiness.await_push_transport`. SR Linux leaves it out — its push transport is up when its probe answers |
| `config.comment_prefix` | no (`#`) | The marker that begins a comment line in this platform's startup-config syntax. The compiler writes the bootstrap file's one generated header line under it. **It is data, not a constant**, because with `bootstrap_via: push` that header is sent to the node as a command like every other line: cEOS refuses `#` at token 0 and reads `!` as a comment. SR Linux leaves it out |
| `config.bootstrap_via` | no (`startup_config`) | How the bootstrap file reaches the node. `startup_config`: the topology names it and containerlab applies it at deploy. `push`: the file is still written to `configs/<node>.<startup_format>` and named in the manifest, the topology node carries **no** `startup-config`, and the push sends its lines ahead of the artifact's in the same request. cEOS needs `push` because its containerlab kind reads a startup file as the node's **whole** configuration, so a partial bootstrap given that way would replace everything the image already sets. `push` with `mode: replace`, or with a delivery that carries no configuration lines, is `psp.config.bootstrap_via`; format 0.6 retires the `mode: replace` clause |
| `conformance.port.*.absent` | no | What the node means by reporting **nothing** at a checked path. OpenConfig reports no default, so cEOS's `…/state/enabled` is absent while LLDP runs and `false` when it is not. Without it an absent value fails nothing |
| `conformance.port.neighbor.system_name`, `.port_id` | changed meaning | A `/`-separated path **relative to one neighbour entry** (`state/system-name`). A single element is the one-element path, so no package written for 0.4 changes |

Two enum values 0.4 already accepted gained a run-time meaning:

- **`config.delivery: eapi`** is now implemented. `json_rpc` and `eapi` are the two
  mechanisms this build pushes by, and `psp.config.delivery.unimplemented` names both.
  `config.push` is required for either (`psp.config.push.missing`).
- **`image.acquisition`** decides whether the image may be fetched. `public_registry`: the
  deploy may pull, under the deploy budget. **Any other value** — `account_gated`,
  `licensed`, `vrnetlab_vm` — means the host check verifies the image is present under
  exactly this reference and refuses the run before anything is staged when it is not
  (`host.image.absent`). **Nothing is ever pulled or tagged**, and the same image under
  another tag is absent.

**A note on EOS's breakout names.** cEOS carries production's names one to one, so
`psp/arista_eos.yaml` declares no lossy rule. Its `modular` rule matches
`Ethernet{slot}/{port}` and its `breakout` rule `Ethernet{slot}/{port}/{sub}`; a name of
the first shape is genuinely ambiguous on real hardware — it can mean a linecard port or
a breakout lane on a fixed chassis — and the profile reads it as the modular form,
because that is what the node reports for the containerlab endpoint either way. A
platform where the two must be told apart needs the distinction in intent, not in the
pattern.

## Format 0.4

Format 0.4 makes the Interfaces facet a declarative **mapping
profile** and adds an optional `conformance` facet:

| Field | Required | Meaning |
|---|---|---|
| `interfaces.rules` | yes | Ordered. For a production name that is not `mgmt_only`, the first rule whose `match` fits decides it, in range or out of it; a match is never passed to a later rule |
| `rules[].name` | yes | Unique in the profile (`psp.rule.name`). Findings, the fidelity record and the conformance suite name a rule by it |
| `rules[].match` | on a data rule | The pattern syntax: `{name}` captures one path segment, the rest is literal |
| `rules[].ranges` | no | Per captured placeholder, `[min, max]` inclusive. A value under a range that is not a decimal integer within it is **out of range under this rule**: omitted when uncabled, refused when cabled. A placeholder with no range accepts any value |
| `rules[].port` | yes | containerlab's endpoint name, rendered from the captured values; may use only what `match` captures. What it leaves out is the rule's **dropped** set |
| `rules[].node_name` | yes | What the node's operating system calls the port; may use only placeholders `port` keeps, since one port has one node name. Recorded in the bundle's mapping row where it differs from the production name |
| `rules[].lossy` | on a data rule | Must equal "the dropped set is non-empty" (`psp.patterns.placeholders`). A rule that only renames inverts and is not lossy |
| `rules[].breakout.parent` | no | Marks the matches as breakout children and renders the parent's production name from the child's values (`psp.patterns.breakout`). Whether children spread onto their own ports or collapse onto the parent's is `port`'s business |
| `rules[].management` | on exactly one rule | The management rule (`psp.management.rule`): only `name`, `port` and `node_name`. It decides the device's `mgmt_only` interface whatever it is called, and its `port` is the manifest node's `management_port`. No data rule may match its node name, or render its port or its node name with every value inside the rule's ranges (`psp.management.collides`) |
| `interfaces.mappings` | yes, non-empty | Declared mappings the conformance suite holds the profile to (`psp.mappings.invalid`): a mapped one (`production`, `rule`, `port`, `node_name`, `lossy`) or an unmappable one (`production`, `unmappable: no_rule` or `out_of_range` with its `rule`). Consumed by the suite alone, so a change here moves no `bundle_id` |
| `conformance` | no | How the suite's boot half reads a booted node over the readiness probe's transport: `host_name` and `version` paths, and for a cabled port `port.enabled`, `port.discovering` (a path and the value it must read) and `port.neighbor` (the neighbour list and the leaves naming the far node and port). `{node_name}` renders the port's node name. Never reaches a bundle. `twin verify` and the step's wait read three of its facts (host name, `port.enabled`, `port.neighbor`) by the same paths, against intent; a package without it, or whose probe is not gNMI, is refused by verify as `verify.package.unreadable`, and what "supported" means is unchanged |

The 0.3 fields `hardware_pattern`, `container_pattern`, `breakout_pattern`,
`container_breakout_pattern`, `management`, `max_ports` and `lossy` are gone. A package
carrying them is refused for them by the schema, and one that declares `0.3` is named as
`psp.version.unknown` beside those findings, though it no longer decodes. That is why
`testdata/psp/defects/version-0-3-m5.yaml` is kept as the real format-0.3 SR Linux package
byte for byte: a synthetic old-version fixture that still decodes hides the strict
decoder's refusals. From 0.4 the boot half checks
`platform.versions` against the version the node reports: a listed `24.7` matches a read
`v24.7.1-…`.

## Format 0.3

Format 0.3 added which rendered artifact is this platform's configuration and how it is
pushed to a booted node ([D-028](../docs/decisions.md#d-028)):

| Field | Required | Meaning |
|---|---|---|
| `config.artifact_name` | yes | The artifact definition's `artifact_name` whose artifact is a device's configuration on this platform. The read selects, per device, the one artifact of this name. It must differ from `startup_format`, so `configs/<node>.<artifact_name>` cannot collide with the bootstrap's `configs/<node>.<startup_format>` (`psp.config.artifact_name`) |
| `config.artifact_content_types` | yes | The content types the read accepts; anything else is `artifact.content_type.unsupported`. Text only — the CTM carries content as UTF-8 text (`psp.config.content_type`) |
| `config.mode` | yes | `merge`: the artifact's lines over the bootstrap's, a line it does not set standing. `replace`: the node runs exactly the artifact, which must then carry everything bootstrap did, management included. No default: guessing either way would be a false assertion about what the twin runs. **Amended by format 0.6** ([D-033](../docs/decisions.md#d-033)): `replace` resets the candidate to the baseline containerlab left on the node, which holds its management, then sends the bootstrap and the artifact; the artifact never has to carry management, and no package's replace sends `delete /` |
| `config.push_timeout_s` | yes | Seconds one node may take to accept its artifact, from the push activity's start to the node's commit. The push step's budget is the largest value among the bundle's platforms plus the mechanism's margin. Per-platform, never a shared constant |
| `config.push` | for `json_rpc` | `scheme`, `port` and `login` — how the node is reached. `login` holds the **names** of the environment variables carrying the push login, never the values, and may name the same variables as `readiness.login` (`psp.config.push.missing`) |

`config.delivery` and `config.commit`, carried since 0.1 and consumed by nothing, are read
from 0.3 by the push: `json_rpc` from 0.3 and `eapi` from 0.5 are the mechanisms, and
every other value is refused at load as `psp.config.delivery.unimplemented` rather than
silently skipped. `commit: explicit` wraps the artifact's lines in `enter candidate private` …
`commit now`; `implicit` sends the lines alone.

## Format 0.2

Format 0.2 added what a provisioning run needs to boot a node; every field below is carried
unchanged by the later formats:

| Field | Required | Meaning |
|---|---|---|
| `image.deploy_timeout_s` | yes | Deploy budget for a node of this platform; the deploy step takes the largest over the bundle's nodes. An image pull counts against it |
| `image.destroy_timeout_s` | yes | Teardown budget, taken the same way |
| `readiness.encoding` | for `gnmi_get` and `gnmi_subscribe` | The gNMI encoding the probe requests. SR Linux refuses the proto default as `Unimplemented`, so a probe without one never succeeds |
| `readiness.port` | no (57400 for gNMI) | The port the probe dials on the node's management address |
| `readiness.login` | yes | `username_env` and `password_env`: the **names** of the environment variables holding the probe's login, never the values. Names must match `^[A-Z][A-Z0-9_]*$`, so a value cannot be written there by accident. The server and the worker read the variables from their own environments; the host check refuses with `host.probe.login_unset`, naming the variable, when one is unset |

`readiness.probe`, `readiness.path`, `readiness.timeout_s` and `image.resources.memory_mb`
keep their 0.1 meaning; the SR Linux values are measured ones, each commented with its
measurement.

None of these fields reaches a bundle. The worker reads them from its own packages at
provision time, looked up by each node's manifest `psp.id`, so a package change that moves
a budget does not move `bundle_id`.

## Bootstrap placeholders

`config.bootstrap` lines are templates. `{node}` renders the node name wherever it
appears. A line containing `{interface}` or `{port}` is emitted once per cabled port:

| Placeholder | Renders | SR Linux example |
|---|---|---|
| `{interface}` | the node's own name for the port: the deciding rule's `node_name` (from 0.4; on a one-to-one platform it is the production name) | `ethernet-1/1` |
| `{port}` | containerlab's endpoint name for the port | `e1-1` |
| `{node}` | the node name | `n1` |

A command the NOS runs wants `{interface}`. `{port}` is containerlab's name, not the
NOS's: SR Linux refuses `set / interface e1-1 admin-state enable`, because its name for
that port is `ethernet-1/1`. Which name a platform's configuration needs is the package's
choice; the compiler only substitutes. On a platform whose rule renames (`Ethernet1/1` → `Ethernet1`) or collapses a breakout onto its parent's
port, `{interface}` renders the node's name, because bootstrap is what the node runs.
Each line repeats on its own, so a per-port command must fit on one line: a block such as
`interface {interface}` then `no shutdown` renders every `interface` line and then one
`no shutdown`, which on a modal CLI enables only the last port
([D-021](../docs/decisions.md#d-021)). EOS does not meet this: the `ceos` kind's own
default configuration already sets the host name and brings every port up, so EOS's
bootstrap has no per-port line at all. The limit stands for the next platform that needs
one, and closing it is a format change, never a compiler branch.

**From 0.5 a package may deliver its bootstrap through the push** rather than as a startup
file (`config.bootstrap_via: push`). Nothing above changes for it: the same templates
render the same lines into the same `configs/<node>.<startup_format>` file, under the
package's `comment_prefix`. Only how that file reaches the node differs — its lines go
ahead of the artifact's in one push request, and a refusal's line number is re-based onto
whichever of the two files the line came from.
