# Golden deployments

What the local driver's pure `plan` renders for each fixture, one directory per driver
(`containerlab/`) and per fixture (`three-node`, `mixed`, `lossy`, `three-node-probed`):

- `topology.clab.yml`: the rendered containerlab topology, byte for byte;
- `deployment.json`: the deployment document, as `documents.encode` gives it (sorted keys,
  one-space indent).

Each fixture in `testdata/blueprint/` is compiled with the shipped packages (`psp/` and
`probes/`, plus `testdata/packages/chassisos.yaml`) and planned for a twin of its own name,
with the allocation `{"lab": "<name>", "mgmt_subnet": "172.20.1.0/24"}`.
`core/tests/test_containerlab_plan.py` holds the plan to these files.

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
port the cabled `c1:Ethernet1/1` holds. `core/tests/test_containerlab_plan.py` holds a row
per fixture, the rule and the objects the plan must report, and fails on a fixture without
one.
