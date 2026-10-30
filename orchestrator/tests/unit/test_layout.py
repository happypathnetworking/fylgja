"""The orchestrator's layout (research R-02): the package and its subpackages import with
nothing else, and tier 2 skips without Infrahub's variables."""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "module",
    [
        "fylgja_orchestrator",
        "fylgja_orchestrator.adapters.infrahub",
        "fylgja_orchestrator.documents",
        "fylgja_orchestrator.flows",
    ],
)
def test_the_packages_import(module):
    importlib.import_module(module)


def test_importing_the_package_imports_no_prefect():
    code = "import sys, fylgja_orchestrator.flows; print('prefect' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_tier_2_skips_without_infrahub():
    env = {k: v for k, v in os.environ.items() if not k.startswith("INFRAHUB_")}
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-m", "contract", "-p", "no:cacheprovider", "tests/contract"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "skipped" in out.stdout
    assert "passed" not in out.stdout
