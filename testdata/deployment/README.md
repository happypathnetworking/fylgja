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
