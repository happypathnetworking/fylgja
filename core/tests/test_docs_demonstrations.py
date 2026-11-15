"""`docs/demonstrations.md` holds to the tree: its targets are the `Makefile`'s three demonstration targets, its
preconditions name everything `scripts/demo.py` checks, by that script's own constants, and `CONTRIBUTING.md`
points to the page and no longer lists the preconditions."""

from __future__ import annotations

import importlib.util
import re
import sys
from functools import cache
from types import ModuleType

from pages import ROOT, rows, section, targets, text

PAGE = "docs/demonstrations.md"
SCRIPT = ROOT / "scripts" / "demo.py"


@cache
def _script() -> ModuleType:
    """`scripts/demo.py`, loaded by path and entered in `sys.modules`, which its dataclasses read."""
    spec = importlib.util.spec_from_file_location("script_demo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _preconditions() -> str:
    return "\n".join(section(text(PAGE), "## What the host must have"))


def test_the_target_table_is_the_three_demonstration_targets() -> None:
    table = rows(section(text(PAGE), "## Running one"), "Target")
    named = {m.group(1) for row in table if (m := re.match(r"`make ([\w-]+)", row[0]))}
    assert named == {"infrahub-demo", "netbox-demo", "demo-down"}, "the parse is blind"
    assert named <= targets()
    body = text(PAGE)
    assert "REF" in body
    assert "PURGE=1" in body


def test_the_preconditions_name_everything_the_script_checks() -> None:
    demo = _script()
    body = _preconditions()
    assert body.strip(), "the parse is blind"
    wanted = [*demo.TOOLS, *demo.GROUPS, *demo.LOGIN, *demo.APPARMOR_LINES, *demo.IMAGES, demo.DEFAULT_LISTEN,
              "Python 3.14"]
    wanted += [str(port) for port in demo.PORTS.values()]
    wanted += [str(demo.PREFECT_PORT), str(demo.TWIN_MB)]
    wanted += [str(demo.SOURCE_MB[source] + demo.TWIN_MB) for source in demo.SOURCE_MB]
    wanted += [str(demo.SOURCE_MB[source]) for source in demo.SOURCE_MB]
    missing = [name for name in wanted if name not in body]
    assert not missing, f"the preconditions lack: {missing}"
    assert demo.APPARMOR_LOCAL in body


def test_the_page_promises_no_exit_status() -> None:
    assert rows(text(PAGE).splitlines(), "Status") == []


def test_contributing_points_to_the_page_and_no_longer_lists_them() -> None:
    demo = _script()
    lines = section(text("CONTRIBUTING.md"), "## The demonstrations")
    assert lines, "the parse is blind"
    body = "\n".join(lines)
    assert "docs/demonstrations.md" in body
    assert not any(line in body for line in demo.APPARMOR_LINES)
    assert "### The host's preconditions" not in body
