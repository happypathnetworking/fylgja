#!/usr/bin/env python3
"""Write the golden deployments of the four fixtures on both drivers, the local driver and clabernetes.

Run from the repository root with the venv's Python: `core/.venv/bin/python -I scripts/render-goldens.py`.
Each fixture in `testdata/blueprint/` is compiled with the shipped packages and planned for a twin of its
own name by each driver. The local driver's plan takes the lab of that name and the subnet 172.20.1.0/24,
and its rendered topology and deployment document go to `testdata/deployment/containerlab/<name>/`.
clabernetes' plan takes the twin's namespace and `CLABERNETES`, which holds a documentation range and a
reserved name and no site's value, and its three rendered files and deployment document go to
`testdata/deployment/clabernetes/<name>/`. Read the result before committing it.
"""

import json
import sys
from pathlib import Path

from fylgja_core import blueprint, clabernetes, compiler, documents, platform_package, probe_package
from fylgja_core.clabernetes import plan as clabernetes_plan
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.driver import Planned

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("three-node", "mixed", "lossy", "three-node-probed")
SUBNET = "172.20.1.0/24"
CLABERNETES = {"core_namespace": "fylgja", "controller_namespace": "c9s", "pod_cidr": "198.51.100.0/24",
               "registries": {"ARISTA_CEOS": "registry.example:5443/arista"}}


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
        local = clab_plan.plan(c.manifest, c.id, platforms, probes, name, {"lab": name, "mgmt_subnet": SUBNET})
        write(ROOT / "testdata" / "deployment" / "containerlab" / name, local)
        allocation = {"namespace": clabernetes.namespace_of(name), **CLABERNETES}
        on_cluster = clabernetes_plan.plan(c.manifest, c.id, platforms, probes, name, allocation)
        write(ROOT / "testdata" / "deployment" / "clabernetes" / name, on_cluster)
    return 0


def write(out: Path, planned: Planned) -> None:
    """Every rendered file, byte for byte, and the deployment document, its keys sorted and
    indented by one space, in the directory `out`."""
    out.mkdir(parents=True, exist_ok=True)
    for path, content in planned.files.items():
        (out / path).write_bytes(content)
    text = json.dumps(documents.encode(planned.deployment), indent=1, sort_keys=True)
    (out / "deployment.json").write_text(text + "\n")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
