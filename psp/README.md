# Platform packages

A platform package is what Fylgja must know of one network operating system that the
runtime's kind does not already know ([D-015](../design/decisions.md#d-015)). The kind
already provides the default login, the baseline configuration (host name, linked ports
enabled, LLDP, gNMI) and, where it has them, interface aliases; a package states none of
these. Adding a platform is a data change, never a code change. See architecture
[§4.10](../design/architecture.md#410-platform-and-probe-packages).

Each file is platform package 1, written as YAML and validated against
[`../formats/platform-package-1.schema.json`](../formats/platform-package-1.schema.json).
Read the schema's `$comment` for the cross-field rules the core holds when it loads a
package, and each property's description for its consumer.

| File | Platform | containerlab kind | Image |
|---|---|---|---|
| `nokia_srlinux.yaml` | Nokia SR Linux 24.7 | `nokia_srlinux` | `ghcr.io/nokia/srlinux:24.7.1`, public |
| `arista_eos.yaml` | Arista EOS 4.32 on cEOS | `ceos` | `ceos:4.32.0.2F`, account-gated: imported by hand, never pulled locally ([CONTRIBUTING.md](../CONTRIBUTING.md#local-environment)) |

## What a package holds

| Section | What it says |
|---|---|
| `id`, `versions` | The platform's identity, which a blueprint device's `platform` names, and the software versions its values were measured on |
| `credentials` | The name the credential provider resolves to the node login; never a value |
| `interfaces.rules` | Which production interface names the platform has, in order: each data rule's `match` and `ranges`, and one management rule. A `node_name` only where the node's name differs from the production name |
| `push` | How the configuration reaches a booted node: `json_rpc` or `eapi`, always a replace with one atomic commit ([D-027](../design/decisions.md#d-027)) |
| `readiness` | How long the push transport may take to answer once the nodes are up |
| `gnmi`, `conformance` | How verify and the conformance suite read a booted node |
| `fidelity.approximations` | How a twin of this platform differs from production |
| `runtime.containerlab` | The kind, the image (with a `pull_secret` when gated), per-node `resources`, the deploy and destroy bounds, `link_apply_mode`, `alias` (with a `rename` per data rule when false) and `hot_add_ports` |

Every timeout and resource figure is a measurement with a margin, and the comment beside
it says what was measured. The orchestrator holds what only a source-of-truth reader
needs: the manufacturer and platform names that select a package, and the rendered
config's artifact name and content type.

## How the two packages differ

| | `nokia_srlinux` | `arista_eos` |
|---|---|---|
| Interface aliases | Yes: production names are endpoints (`ethernet-1/1` becomes `e1-1`) | No: one `rename` per rule (`Ethernet{a}` to `eth{a}`, `Ethernet{a}/{b}` to `eth{a}_{b}`, `Ethernet{a}/{b}/{c}` to `eth{a}_{b}_{c}`) |
| Push | JSON-RPC `cli` on 443 | eAPI `runCmds` in a configuration session on 443 |
| gNMI | TLS on 57400 | Plaintext on 6030 |
| `link_apply_mode` | `live` | `live` |
| `hot_add_ports` | `true` (not yet read back from the node) | `false`: a port added after boot never appears in EOS |
| Memory per node | 2048 MB (about 1.6–2 GiB measured) | 1536 MB (0.9–1.5 GiB measured) |

`link_apply_mode` and `hot_add_ports` were measured on containerlab 0.79 and clabernetes
0.10.1 on 2026-10-30. The cases each interface rule must decide, once carried in the
packages as `mappings`, are test data now:
[`../testdata/packages/mappings.yaml`](../testdata/packages/mappings.yaml).

Probe hosts are not platforms. Their packages are in [`../probes/`](../probes/README.md).
