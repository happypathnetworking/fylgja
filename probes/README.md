# Probe packages

A probe package is everything Fylgja needs to know about one probe format's hosts, as
data: the image a host runs, how it is addressed and judged ready, how a step's flow and
verify's burst are run on it, and what it cannot reproduce. It sits beside the
[platform support packages](../psp/README.md), in their shape where the two share a field,
and a probe names its package by its `format` ([D-064](../docs/decisions.md#d-064)). What a
probe is, and how one is declared, is [schema/README.md](../schema/README.md#probes-declaring-one);
the declaration file is [contracts/probes.schema.json](../contracts/probes.schema.json).

| File | Purpose |
|---|---|
| `probe.schema.json` | JSON Schema every probe package is validated against, format `0.1` |
| `ping.yaml` | The one shipped package: two Alpine hosts that ping each other through the twin |

Packages are compiled into the binary with `embed`, as the PSPs are, and loaded by `fylgja
serve` and `fylgja worker run` into the probe registry, keyed by format. Each role names
every package in its start-up report, after the platform packages:

```text
fylgja worker: ping (embedded): image alpine:3.24.2 (public_registry, present on this host), flow ping every 0.2s, burst 5
```

and, the image absent, `… (public_registry, absent from this host; a create needing it is
refused until docker pull alpine:3.24.2 fetches it)`.

**The format keys a mechanism, never a platform** ([D-031](../docs/decisions.md#d-031)).
`ping` is the one format this build runs: the lab starts a flow as `ping`, interrupts it
with `pkill -INT -x ping` and reads its counters, and a burst's output is read the same
way, by `probe.ParsePing`, which reads busybox's and iputils' output. So a package of
another format, or one whose flow is not `ping`, is code to add before it is data; within
the format, every value below is the package's, read from it by the lab, the host check,
the compiler and verify, never from a constant.

## The override directory's `probes/`

A probe package is overridden from the PSP override directory's `probes/` subdirectory
(`<psp-dir>/probes/*.yaml`, `--psp-dir` or `FYLGJA_PSP_DIR`), so no flag is added. An
override shadows the embedded package of its format. The PSP loader reads the directory's
own `*.yaml` alone and never descends into `probes/`, so one directory holds both kinds
(`TestThePSPLoaderSkipsTheProbesSubdirectory`). An override is validated when it is loaded,
and a package the validation rejects refuses `fylgja serve` and `fylgja worker run` at
start, exit 2, with its findings:

| Rule | When |
|---|---|
| `probe.package.version.unknown` | `probe_version` is not `"0.1"`, naming both; nothing else of the file is checked |
| `probe.package.schema` | the package is not of `probe.schema.json`, naming each field refused |
| `probe.package.template` | a command template names a placeholder its field does not render |
| `probe.package.format.duplicate` | two packages of one origin declare one format, naming both files |

The conformance suite's pure half holds every shipped package to the same validation, its
`probes` check, on every `make test`.

## Format 0.1

`probe_version` is `"0.1"`. Every field is required.

| Field | Meaning |
|---|---|
| `format` | The value a declaration's probe names (`ping`), and what keys the mechanism |
| `image.clab_kind` | containerlab's kind for a host (`linux`) |
| `image.ref` | The host's image, verified present under exactly this reference |
| `image.acquisition` | As a PSP's: `public_registry`, `account_gated` or `licensed`. Whatever it says, the host check verifies the image present and **a run never pulls it**: a host's deploy budget is sized for a container already held, and a pull inside a step's reconcile would be timed as the step's. An absent image is `host.image.absent`, whose remedy follows the acquisition (`docker pull <ref>` for `public_registry`) |
| `image.resources` | `cpu` and `memory_mb`, a host's budget; the host check sums `memory_mb` with the devices' |
| `image.deploy_timeout_s`, `destroy_timeout_s` | A host's two budgets, taken as a device's are |
| `host.interface` | The host's data port, cabled to the endpoint's device port; `eth0` is containerlab's management |
| `host.address`, `host.route` | The topology's two `exec` lines, one argument an element: the host's address on its port, then a host route to the far host through the gateway. A host route, since a default route would collide with containerlab's management default and a prefix route with the connected prefix when both endpoints share one |
| `readiness` | `probe: exec`, run inside the container through the lab's runner, with no login; the host is ready once `command`'s output contains `expect`, within `timeout_s` |
| `flow` | A step's transient flow: `command`, started in host `a` after the stage and read after the wait, one echo every `interval_s`, which also counts a gap; `start_timeout_s` and `read_timeout_s` bound the two flow activities, and a rehearsed stage's deadline gains both |
| `burst` | verify's fourth kind of assertion: `command` sends `count` echoes from host `a` to host `b`, waiting `wait_s` after the last; held when every one is answered, `verify.burst` otherwise |
| `fidelity` | What the hosts cannot reproduce: `forwarding: software`, `timing: container`, and the `approximations` in words |

**The placeholders.** `{address}` (the host's address with its prefix length),
`{gateway}`, `{far_address}` (the other host's address, without one) and `{interface}`
render in every template; `{interval}` in `flow` and `burst`; `{count}` and `{wait}` in
`burst`. Any other is `probe.package.template`.

## `ping`

`probes/ping.yaml`, the shipped package:

| Value | Where it comes from |
|---|---|
| `alpine:3.24.2`, `linux`, `public_registry` | Alpine 3.24.2 carries BusyBox 1.37.0, whose `ping` and `ip` the format's commands use: verified on the host's Docker 29.8.1 in an image of that release already present, without pulling ([016's research §1.2](../specs/016-probes/research.md#12-busybox-ping-and-ip-the-ping-mechanisms-tools)). About 8 MB. The image's digest, a host booted beside a privileged SR Linux node, its `exec` lines and its reach through the device are the live session's to record in [docs/verified-facts.md](../docs/verified-facts.md) |
| `host.address`: `ip addr add {address} dev {interface}`; `host.route`: `ip route add {far_address}/32 via {gateway} dev {interface}` | BusyBox `ip` has `address` and `route` (§1.2); containerlab 0.79.0's dry run accepts a `linux` node with two such `exec` lines beside SR Linux, pulling nothing (§1.3) |
| `readiness`: `ip -4 -o addr show dev {interface}`, expecting `{address}` | The address the first `exec` line adds, read back; 30 s |
| `flow`: `ping -i {interval} {far_address}`, `interval_s: 0.2` | BusyBox `ping` accepts `-i 0.2` as root with no minimum-interval refusal, and an interrupt ends it and prints its counters (`6 packets transmitted, 6 packets received, 0% packet loss` after 1.1 s), which is how a flow is read (§1.2). Each reply's `seq=` (busybox) or `icmp_seq=` (iputils) gives the longest run of unanswered echoes, times the interval, as the gap. 30 s to start and 30 s to read |
| `burst`: `ping -c {count} -i {interval} -W {wait} {far_address}`, `count: 5`, `wait_s: 2` | `-W` is the seconds to wait for a response after the last of the `-c` echoes (§1.2). A burst costs about `count × interval + wait_s`, 3 s, inside a wait's budget |
| `memory_mb: 32`, `cpu: 0.1`, deploy 60 s, destroy 30 s | Budgets for a shell and one `ping`, set at the plan; the live session re-measures them |
| `fidelity` | The hosts forward in their container's kernel and the devices in theirs, so a loss figure is the container's, never a hardware forwarder's; timing is the lab host's scheduler's, under its load; a host speaks no discovery protocol, so a synthesized link's neighbour is never asserted; format `0.1` is IPv4 |

## What enters a bundle

A host is a node of the bundle (format `6`), of `provenance: synthesized`, and the package
reaches it through these alone:

- **the topology**: the host's `kind` (`image.clab_kind`), its `image` (`image.ref`) and
  its two `exec` lines (`host.address` and `host.route`, rendered with the endpoint's
  values), and the link from `<probe>-<a|b>:<host.interface>` to the device's port;
- **the manifest**: the host node's `image`, its `probe` (`name`, `endpoint`, `format`,
  `package: {id, source}`), the host's own mapping row on `host.interface`, and
  `probes[]`, each probe as compiled with its hosts and its package's
  `fidelity.forwarding` and `fidelity.timing`.

**Nothing else of a package enters a bundle**: its `acquisition`, `resources`, the two
budgets, `readiness`, `flow`, `burst` and the `approximations` are read at run time from the
worker's and the server's own packages, looked up by the manifest's `probe.package.id`, as a
PSP's budgets are. A change to any of them moves no `bundle_id`; a change to the image, the
kind, the port or an `exec` line does. A host whose package the worker lacks is refused at
the host check as `host.probe_package.missing`, naming the manifest's source and the hosts.
