"""The checks under `infrahub/checks/` run on Infrahub's task worker, which holds none of Fylgja's packages and whose
Prefect environment is Infrahub's own (D-085): read by `ast`, their imports are the standard library and httpx, the
glue beside them and the SDK's base class, and each class binds the query and the timeout its registration needs. The
two check modules are never imported here: their base class is the worker's."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECKS = ROOT / "infrahub" / "checks"
GLUE = "fylgja_glue.py"
CLASSES = {"fylgja_step.py": ("FylgjaStep", "STEP_TIMEOUT_S"), "fylgja_twin.py": ("FylgjaTwin", "TWIN_TIMEOUT_S")}
NEVER = ("fylgja_core", "fylgja_infrahub", "fylgja_orchestrator", "prefect")


def imports(source: str) -> set[str]:
    """Every module `source` imports, anywhere in it, a function's body included: a relative one written with its
    leading dots (`.fylgja_glue`)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
    return found


def standard_or_httpx(name: str) -> bool:
    return name.partition(".")[0] in sys.stdlib_module_names or name == "httpx" or name.startswith("httpx.")


def test_no_check_imports_fylgja_or_prefect() -> None:
    files = sorted(path.name for path in CHECKS.glob("*.py"))
    assert files == sorted([GLUE, *CLASSES])
    assert [path.name for path in CHECKS.iterdir() if path.name != "__pycache__" and path.suffix != ".py"] == []
    outside: list[str] = []
    for name in files:
        found = imports((CHECKS / name).read_text())
        assert found, f"the scan of {name} is blind"
        allowed = set() if name == GLUE else {".fylgja_glue", "infrahub_sdk.checks"}
        for module in sorted(found):
            if (not standard_or_httpx(module) and module not in allowed) or module.lstrip(".").split(".")[0] in NEVER:
                outside.append(f"{name}: {module}")
    assert outside == []
    assert "httpx" in imports((CHECKS / GLUE).read_text())


def test_the_scan_sees_an_import_inside_a_function_and_keeps_a_relative_one() -> None:
    source = "import json\nfrom .fylgja_glue import step\ndef f():\n    from prefect import flow\n"
    assert imports(source) == {"json", ".fylgja_glue", "prefect"}


def test_each_check_class_binds_its_query_and_the_glues_timeout() -> None:
    for name, (cls, timeout) in CLASSES.items():
        tree = ast.parse((CHECKS / name).read_text())
        [found] = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == cls]
        assert [ast.unparse(base) for base in found.bases] == ["InfrahubCheck"]
        bound = {
            target.id: ast.unparse(node.value)
            for node in found.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert bound == {"query": "'fylgja_branch'", "timeout": timeout}
        glued = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == "fylgja_glue"
            for alias in node.names
        }
        assert timeout in glued
        [validate] = [node for node in found.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "validate"]
        assert [argument.arg for argument in validate.args.args] == ["self", "data"]


def test_the_registration_names_both_checks_and_their_files_exist() -> None:
    registration = yaml.safe_load((ROOT / ".infrahub.yml").read_text())
    assert registration["check_definitions"] == [
        {"name": "fylgja-step", "file_path": "infrahub/checks/fylgja_step.py", "class_name": "FylgjaStep"},
        {"name": "fylgja-twin", "file_path": "infrahub/checks/fylgja_twin.py", "class_name": "FylgjaTwin"},
    ]
    for definition in registration["check_definitions"]:
        tree = ast.parse((ROOT / definition["file_path"]).read_text())
        assert definition["class_name"] in {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    [query] = [entry for entry in registration["queries"] if entry["name"] == "fylgja_branch"]
    assert query == {"name": "fylgja_branch", "file_path": "infrahub/queries/fylgja_branch.gql"}
    text = (ROOT / query["file_path"]).read_text()
    query_text = [line for line in text.splitlines() if not line.startswith("#")]
    assert query_text == ["query fylgja_branch { Branch { name } }"]
