# Step fixtures

Each blueprint here is one change from a base fixture in the directory above, so every kind
of change a step must handle has a pair. The bundle diff's tests (`core/tests/test_diff.py`)
and both drivers' `changes` (`core/tests/test_containerlab_changes.py` and
`core/tests/test_clabernetes_changes.py`, which answer alike), all pure, read every pair, and
the loop's pure tests some. The live tier steps a twin from each base to each of
these through the local driver, `changes` held to containerlab's dry run
(`core/tests/live/test_changes_live.py`, where `three-node-n1-disabled` stands for
`three-node-unmanaged`, the same topology). The conformance suite steps a twin end to end
through the API on any driver: every pair (`core/tests/conformance/test_steps.py`), and
`two-node` to `three-node` with the core killed at each phase of the step, in its apply and
before a deletion, and the step cancelled (`core/tests/conformance/test_step_kills.py`).
The cluster tier steps a twin through every
pair too, `three-node-n1-disabled` again standing for `three-node-unmanaged`, the clabernetes
driver's `changes` held to the pods' uids
(`core/tests/cluster/test_clabernetes_changes_cluster.py`). Each is a valid, sorted blueprint 1 that compiles with
the shipped packages, and says in its `source` what it changes.

| Fixture | Base | The change | What the diff says |
|---|---|---|---|
| `three-node-unlinked.json` | `three-node` | the link `n2:ethernet-1/2`-`n3:ethernet-1/1` removed | links removed 1; `n2`, `n3` changed (`mapping`) |
| `two-node.json` | `three-node` | device `n3` and its two links removed | `n3` removed; links removed 2; `n1`, `n2` changed (`mapping`) |
| `three-node-n3-eos.json` | `three-node` | `n3` becomes `arista_eos`, with a two-line configuration; its links move to `Ethernet2` and `Ethernet1` | `n3` changed (`platform`, `mapping`, `config`); links removed 2, added 2 |
| `three-node-n1-disabled.json` | `three-node` | `n1`'s `ethernet-1/2` has `enabled: false` | `n1` changed (`mapping`) |
| `three-node-probed.json` (in the directory above) | `three-node` | the probe `n1-loop` added, between `n1:ethernet-1/10` and `n1:ethernet-1/11` | probes added `n1-loop`; `n1` changed (`mapping`) |
| `three-node-unmanaged.json` (in the directory above) | `three-node` | `n2` carries no configuration | `n2` changed (`config`) |
| `mixed-e2-port.json` | `mixed` | the link `e1:Ethernet10`-`e2:Ethernet10` added | links added 1; `e1`, `e2` changed (`mapping`) |
| `three-node-probed-moved.json` | `three-node-probed` | probe `n1-loop` moves whole to `n2`, keeping its name: `a` on `n2:ethernet-1/10` (`10.2.10.2/24`), `b` on `n2:ethernet-1/11` (`10.2.11.2/24`) | probe `n1-loop` added and removed; `n1`, `n2` changed (`mapping`) |

This table is the complete list of pairs, and `PAIRS` in `core/tests/test_diff.py` agrees with it.
A pair stepped in reverse swaps added and removed: nodes, links and probes alike; the changed
nodes and their reasons stay.
