"""`docs/demonstrations.md` holds to the tree: its targets are the `Makefile`'s three demonstration targets, its
preconditions name everything `scripts/demo.py` checks, by that script's own constants, and `CONTRIBUTING.md`
points to the page and no longer lists the preconditions."""

from __future__ import annotations

import importlib.util
import re
import sys
from functools import cache
from types import ModuleType

from pages import ROOT, rows, section, targets, text, ticked

PAGE = "docs/demonstrations.md"
SCRIPT = ROOT / "scripts" / "demo.py"


@cache
def _script() -> ModuleType:
    """`scripts/demo.py`, loaded by path and entered in `sys.modules`, which its dataclasses read."""
    spec = importlib.util.spec_from_file_location("script_demo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]  # read only while the module's classes are made
    return module


def _whole(number: int) -> str:
    """A pattern for `number` as a whole number: not part of a longer one or of a decimal, and one that ends a
    sentence (`4200.`) counts."""
    return rf"(?<!\d)(?<!\d\.){number}(?!\d)(?!\.\d)"


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
    spans = {span for line in body.splitlines() for span in ticked(line)}
    names = [*demo.TOOLS, *demo.GROUPS, *demo.LOGIN, *demo.APPARMOR_LINES, *demo.IMAGES, demo.DEFAULT_LISTEN]
    numbers = [*demo.PORTS.values(), demo.PREFECT_PORT, demo.TWIN_MB, *demo.SOURCE_MB.values(),
               *(demo.SOURCE_MB[source] + demo.TWIN_MB for source in demo.SOURCE_MB)]
    missing = [name for name in names if name not in spans]
    missing += [str(n) for n in numbers if not re.search(_whole(n), body)]
    if "Python 3.14" not in body:
        missing.append("Python 3.14")
    assert not missing, f"the preconditions lack (a name as a `ticked` span): {missing}"
    assert demo.APPARMOR_LOCAL in body
    assert demo.APPARMOR_PROFILE in body


def test_the_page_promises_no_exit_status() -> None:
    assert rows(text(PAGE).splitlines(), "Status") == []


def test_a_number_before_a_full_stop_is_a_whole_number() -> None:
    assert re.search(_whole(4200), "the Prefect port, 4200.")
    assert not re.search(_whole(4200), "version 4200.5 or 14200")


def test_contributing_points_to_the_page_and_no_longer_lists_them() -> None:
    demo = _script()
    lines = section(text("CONTRIBUTING.md"), "## The demonstrations")
    assert lines, "the parse is blind"
    body = "\n".join(lines)
    assert "docs/demonstrations.md" in body
    values = [*(g for g in demo.GROUPS if g != "docker"), *demo.LOGIN, *demo.APPARMOR_LINES, *demo.IMAGES,
              demo.DEFAULT_LISTEN, demo.APPARMOR_LOCAL, demo.APPARMOR_PROFILE]
    numbers = [*demo.SOURCE_MB.values(), demo.TWIN_MB, *(demo.SOURCE_MB[s] + demo.TWIN_MB for s in demo.SOURCE_MB)]
    held = [v for v in values if v in body] + [str(n) for n in numbers if re.search(_whole(n), body)]
    assert not held, f"the section still lists preconditions the page holds: {held}"
    assert "### The host's preconditions" not in body


COMPOSE_PORTS = (15692, 2004, 6362)


def test_the_compose_ports_the_script_does_not_check_are_named_as_stated() -> None:
    """The script holds no list of them: they are Infrahub's Compose file's, read in `design/verified-facts.md`."""
    facts = text("design/verified-facts.md")
    body = _preconditions()
    for port in COMPOSE_PORTS:
        assert re.search(rf"(?<!\d){port}(?!\d)", facts), f"verified-facts.md no longer states {port}"
        assert re.search(rf"(?<!\d){port}(?!\d)", body), f"the preconditions lack {port}"
