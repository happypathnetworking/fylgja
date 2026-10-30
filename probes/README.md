# Probe packages

A probe package is what Fylgja must know to run one probe format's hosts: the image a
host runs, how it is addressed and judged ready, how a step's flow and verify's burst run
on it, and what it cannot reproduce ([D-008](../design/decisions.md#d-008)). A blueprint's
probe names its package by its `format`.

Each file is probe package 1, written as YAML and validated against
[`../formats/probe-package-1.schema.json`](../formats/probe-package-1.schema.json). A
declaration file, which the orchestrator reads into a blueprint's probes, is
[`../formats/probes-1.schema.json`](../formats/probes-1.schema.json); examples are in
[`../testdata/probes/`](../testdata/probes/).

| File | Format |
|---|---|
| `ping.yaml` | `ping`: two Alpine hosts, each cabled to an uncabled port of the intent, ping each other through the twin |

**The format keys a mechanism, never a platform** ([D-014](../design/decisions.md#d-014)).
`ping` is the one format the core runs: a flow is `ping`, interrupted and read by its
counters, and a burst's output is read the same way. A package of another format is code
to add before it is data. Within the format, every value is the package's.

## The fields

| Section | What it says |
|---|---|
| `host` | The host's one data port (`eth1`; `eth0` is containerlab's management), and two start-up commands: its address on the port, then a host route to the far host through the gateway |
| `readiness` | A command run inside the host; the host is ready once its output holds `expect`, within `timeout_s` |
| `flow` | A step's flow, one echo every `interval_s`, started after the step's stage and read after its wait |
| `burst` | Verify's burst: `count` echoes, waiting `wait_s` after the last, held when every one is answered |
| `fidelity.approximations` | How the hosts' measurements differ from production traffic |
| `runtime.containerlab` | The image (public unless a `pull_secret` is set), per-host `resources` and the deploy and destroy bounds. The host's kind is always `linux` |

Commands are argument vectors, run without a shell. Placeholders: `{interface}`,
`{address}` (with its prefix), `{far_address}` (without one), `{gateway}`, `{interval}`,
`{count}` and `{wait}`. Format 1 is IPv4 only.

## `ping`

`alpine:3.24.2` carries BusyBox 1.37.0, whose `ping` and `ip` the commands use; it is
about 8 MB. BusyBox `ping` accepts `-i 0.2` as root, and an interrupt ends it and prints
its counters, which is how a flow is read. Each reply's `seq=` (BusyBox) or `icmp_seq=`
(iputils) gives the longest run of unanswered echoes, times the interval, as the gap. A
burst costs about `count × interval + wait_s`, 3 s.
