# Golden deployments

What each driver's pure `plan` renders for each fixture, one directory per driver
(`containerlab/` and `clabernetes/`) and per fixture (`three-node`, `mixed`, `lossy`,
`three-node-probed`). Each fixture in `testdata/blueprint/` is compiled with the shipped
packages (`psp/` and `probes/`, plus `testdata/packages/chassisos.yaml`) and planned for a
twin of its own name.

The local driver's, under `containerlab/<name>/`, planned with the allocation
`{"lab": "<name>", "mgmt_subnet": "172.20.1.0/24"}`:

- `topology.clab.yml`: the rendered containerlab topology, byte for byte;
- `deployment.json`: the deployment document, as `documents.encode` gives it (sorted keys,
  one-space indent).

`core/tests/test_containerlab_plan.py` holds the local plan to these files.

clabernetes', under `clabernetes/<name>/`, planned with this allocation, which holds a
documentation range and a reserved name and no site's value:

```json
{"namespace": "fylgja-twin-<name>", "core_namespace": "fylgja", "controller_namespace": "c9s",
 "pod_cidr": "198.51.100.0/24", "registries": {"ARISTA_CEOS": "registry.example:5443/arista"}}
```

- `namespace.yaml`, `networkpolicy.yaml` and `topology.yaml`: the twin's Namespace, its
  NetworkPolicy and the `Topology` wrapping its containerlab definition, byte for byte;
- `deployment.json`: the deployment document, written as the local driver's is.

`core/tests/test_clabernetes_plan.py` holds the clabernetes plan to these files.

They were made by `core/.venv/bin/python -I scripts/render-goldens.py`, run from the
repository root, and read by hand against the design before they were committed. A change
to the renderer or to a fixture changes them, and they change in a commit of their own
([`CONTRIBUTING.md`](../../CONTRIBUTING.md)).

## Plans refused

`rejected/` holds the rejection fixtures for a driver's plan: valid blueprints the compiler
accepts and the plan refuses (`Unplannable`), one fault each, named in the blueprint's
`source` envelope as the compiler's are ([D-045](../../design/decisions.md#d-045)).
`port-shared-link.json` and `port-shared-probe.json` are the lossy fixture with a link, and
with a probe's host, on `c1:Ethernet2/1`, which the `chassisos` rename puts on `eth1`, the
port the cabled `c1:Ethernet1/1` holds. Both plans' tests read them:
`core/tests/test_containerlab_plan.py` holds a row per fixture, the rule and the objects the
plan must report, and fails on a fixture without one, and
`core/tests/test_clabernetes_plan.py` holds the clabernetes plan to refusing each as the
local plan does.
