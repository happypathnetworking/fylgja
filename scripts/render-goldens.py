#!/usr/bin/env python3
"""Write the golden deployments of the four fixtures on the local driver.

Run from the repository root with the venv's Python: `core/.venv/bin/python -I scripts/render-goldens.py`.
Each fixture in `testdata/blueprint/` is compiled with the shipped packages and planned for a twin of its
own name, with the lab of that name and the subnet 172.20.1.0/24. The rendered topology and the deployment
document go to `testdata/deployment/containerlab/<name>/`. Read the result before committing it.
"""

import json
import sys
from pathlib import Path

from fylgja_core import blueprint, compiler, documents, platform_package, probe_package
from fylgja_core.containerlab import plan as clab_plan

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("three-node", "mixed", "lossy", "three-node-probed")
SUBNET = "172.20.1.0/24"


def main() -> int:
    if len(sys.argv) > 1:
        print("usage: core/.venv/bin/python -I scripts/render-goldens.py (no arguments)", file=sys.stderr)
        return 2
    platforms = {
        p.id: p
        for p in map(
            platform_package.load,
            [ROOT / "psp/nokia_srlinux.yaml", ROOT / "psp/arista_eos.yaml", ROOT / "testdata/packages/chassisos.yaml"],
        )
    }
    probes = {p.format: p for p in [probe_package.load(ROOT / "probes/ping.yaml")]}
    for name in NAMES:
        c = compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), platforms, probes)
        planned = clab_plan.plan(c.manifest, c.id, platforms, probes, name, {"lab": name, "mgmt_subnet": SUBNET})
        out = ROOT / "testdata" / "deployment" / "containerlab" / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "topology.clab.yml").write_bytes(planned.files["topology.clab.yml"])
        text = json.dumps(documents.encode(planned.deployment), indent=1, sort_keys=True)
        (out / "deployment.json").write_text(text + "\n")
        print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
