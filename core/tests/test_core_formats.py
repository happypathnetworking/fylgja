"""The core's wheel carries the core's formats by a list, `CORE_FORMATS` in `core/setup.py`
(D-066, D-084), so another distribution's formats in `formats/` never ship in it. The wheel check
and the image check each read the list by `ast`, with a copy of one function, since `-I` gives a
script no sibling to import: both copies answer alike, and the list is held equal to what the
core's code reads, its `$ref`s closed."""

from __future__ import annotations

import ast
import importlib.util
import json
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("wheelcheck", "imagecheck")


@cache
def _script(name: str) -> ModuleType:
    """The script `scripts/<name>.py`, loaded by path."""
    spec = importlib.util.spec_from_file_location(f"script_{name}", ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _named() -> set[str]:
    """The first-argument string literals of every call to `schema_problems` or `validator` under
    `core/src/fylgja_core`."""
    named: set[str] = set()
    for path in sorted((ROOT / "core" / "src" / "fylgja_core").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func, first = node.func, node.args[0]
            called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            literal = first.value if isinstance(first, ast.Constant) else None
            if called in ("schema_problems", "validator") and isinstance(literal, str):
                named.add(literal)
    return named


def _refs(value: Any) -> list[str]:
    """Every `$ref` in a document, at any depth."""
    if isinstance(value, dict):
        own = [value["$ref"]] if isinstance(value.get("$ref"), str) else []
        return own + [ref for member in value.values() for ref in _refs(member)]
    if isinstance(value, list):
        return [ref for member in value for ref in _refs(member)]
    return []


def test_both_scripts_read_the_list_setup_py_states() -> None:
    wheel, image = (_script(name).core_formats() for name in SCRIPTS)
    assert wheel == image
    assert isinstance(wheel, tuple) and all(isinstance(name, str) for name in wheel)
    assert list(wheel) == sorted(wheel)
    assert len(set(wheel)) == len(wheel)


def _code(script: str) -> str:
    """`scripts/<script>.py`'s `core_formats` by `ast.dump`, its docstring left out."""
    path = ROOT / "scripts" / f"{script}.py"
    (function,) = [
        node
        for node in ast.parse(path.read_text(), str(path)).body
        if isinstance(node, ast.FunctionDef) and node.name == "core_formats"
    ]
    if ast.get_docstring(function) is not None:
        function.body = function.body[1:]
    return ast.dump(function)


def test_both_scripts_hold_one_core_formats_but_for_its_docstring() -> None:
    wheel, image = (_code(name) for name in SCRIPTS)
    assert wheel == image


def test_the_list_is_what_the_cores_code_reads_and_nothing_else() -> None:
    named = _named()
    assert "blueprint-1" in named
    assert set(_script("wheelcheck").core_formats()) == {f"{n}.schema.json" for n in named} | {"api-1.openapi.yaml"}


def test_every_listed_format_is_a_file_whose_refs_stay_in_the_list() -> None:
    listed = _script("wheelcheck").core_formats()
    outside: list[str] = []
    for name in listed:
        path = ROOT / "formats" / name
        assert path.is_file(), name
        doc = json.loads(path.read_text()) if path.suffix == ".json" else yaml.safe_load(path.read_text())
        outside += [f"{name}: {r}" for r in _refs(doc) if not r.startswith("#") and r.split("#")[0] not in listed]
    assert outside == []


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize(
    "text",
    ['PATTERNS = ("*.schema.json", "api-1.openapi.yaml")\n', 'CORE_FORMATS = ["a"]\n', 'CORE_FORMATS = ("a", 1)\n'],
    ids=["absent", "a-list", "not-all-strings"],
)
def test_a_setup_py_without_the_list_is_refused(tmp_path: Path, script: str, text: str) -> None:
    module = _script(script)
    setup = tmp_path / "setup.py"
    setup.write_text(f"from setuptools import setup\n\n{text}\nsetup()\n")
    with pytest.raises(module.Failure):
        module.core_formats(setup)
