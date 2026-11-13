"""Imports run one way (D-081, D-085, D-097): Prefect is the edge's alone, and within the edge its flows' and its
runner's alone, so a command calls the library in its own process and never loads Prefect; each change source imports
nothing of the edge or of the other source, and the rehearsal library nothing of either source or the edge. Held by a
fresh interpreter for what a command loads, and by `ast` over every file of `orchestrator/src` for what each names, a
function-local import included."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from test_imports import imported

SRC = Path(__file__).resolve().parents[1] / "src"
PACKAGE = SRC / "fylgja_orchestrator"
EDGE = PACKAGE / "edge"
OWN = "fylgja_orchestrator"

CROSSED = (
    ("infrahub", ("fylgja_netbox", "fylgja_orchestrator.netbox")),
    ("netbox", ("fylgja_infrahub", "fylgja_orchestrator.infrahub")),
)
"""What each change source never imports: the other source and its reader. `scripts/wheelcheck.py` judges the same of
the installed wheel, and `core/tests/test_wheelcheck.py` holds its tuple to this one."""

# Run in a fresh interpreter, isolated (`-I`): a command's module imported and its help asked, then the modules of
# Prefect loaded, one a line, after a line of its own.
PROBE = """
import contextlib
import io
import sys

from fylgja_orchestrator.edge import cli

with contextlib.redirect_stdout(io.StringIO()):
    code = cli.main(["stage", "list", "--help"])
print(code)
print("\\n".join(sorted(m for m in sys.modules if m == "prefect" or m.startswith("prefect."))))
"""


def _files() -> list[Path]:
    """Every Python file under `orchestrator/src`."""
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _names(path: Path) -> set[str]:
    """Every name the file `path` imports, anywhere in it, a relative import resolved against its package."""
    parts = path.relative_to(SRC).with_suffix("").parts
    module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    return imported(path.read_text(), package)


def _under(name: str, root: str) -> bool:
    return name == root or name.startswith(f"{root}.")


def _loaded(probe: str) -> tuple[str, list[str]]:
    """What `probe` printed in a fresh interpreter: the help's exit code, and the modules of Prefect loaded."""
    done = subprocess.run([sys.executable, "-I", "-c", probe], check=True, capture_output=True, text=True)
    code, *loaded = done.stdout.splitlines()
    return code, [name for name in loaded if name]


def test_the_commands_load_no_prefect() -> None:
    assert _loaded(PROBE) == ("0", [])
    _, flows = _loaded(PROBE.replace("import cli\n", "import cli, flows\n"))
    assert "prefect" in flows, "the probe is blind"


def test_prefect_is_named_by_the_flows_and_the_runner_alone() -> None:
    files = _files()
    assert EDGE / "flows.py" in files and EDGE / "cli.py" in files, "the scan is blind"
    naming = {path.relative_to(PACKAGE).as_posix() for path in files
              if any(_under(name, "prefect") for name in _names(path))}
    assert naming == {"edge/flows.py", "edge/serve.py"}


def _serve_imports(tree: ast.Module) -> list[tuple[str, ...]]:
    """Each import of `edge.serve` in `tree`, by the functions around it, outermost first."""
    found: list[tuple[str, ...]] = []

    def visit(node: ast.AST, around: tuple[str, ...]) -> None:
        if isinstance(node, ast.Import | ast.ImportFrom):
            if any(_under(name, f"{OWN}.edge.serve") for name in imported(ast.unparse(node), f"{OWN}.edge")):
                found.append(around)
            return
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            around = (*around, node.name)
        for child in ast.iter_child_nodes(node):
            visit(child, around)

    visit(tree, ())
    return found


def test_the_commands_name_neither_the_flows_nor_the_runner_but_in_its_serve_branch() -> None:
    for name in ("cli.py", "run.py", "settings.py"):
        names = _names(EDGE / name)
        assert not any(_under(each, f"{OWN}.edge.flows") for each in names), name
    for name in ("run.py", "settings.py"):
        assert not any(_under(each, f"{OWN}.edge.serve") for each in _names(EDGE / name)), name
    # The command imports the runner once, inside `main`, so that importing `cli` never imports it, nor Prefect.
    assert _serve_imports(ast.parse((EDGE / "cli.py").read_text())) == [("main",)]
    assert _serve_imports(ast.parse("from fylgja_orchestrator.edge import serve\n")) == [()], "the scan is blind"


def test_the_source_imports_nothing_of_the_edge_and_the_library_nothing_of_either() -> None:
    of: dict[str, set[str]] = {}
    for path in _files():
        layer = path.relative_to(PACKAGE).parts[0]
        of.setdefault(layer, set()).update(_names(path))
    assert {"edge", "infrahub", "netbox", "rehearsal"} <= set(of), "the scan is blind"
    for source, reader in (("infrahub", "fylgja_infrahub"), ("netbox", "fylgja_netbox")):
        outside = {name for name in of[source] if name.partition(".")[0] not in sys.stdlib_module_names}
        may = (reader, "fylgja_core", "httpx", f"{OWN}.rehearsal.source", f"{OWN}.rehearsal.report", f"{OWN}.{source}")
        # Each change source imports its reader, the core, httpx and of the library the seam and the report alone ...
        assert {name for name in outside if not any(_under(name, m) for m in may)} == set(), source
        # ... and nothing of the edge, or of the other source or its reader.
        assert not any(_under(name, f"{OWN}.edge") for name in of[source]), source
    assert not any(_under(name, root) for source, roots in CROSSED for name in of[source] for root in roots)
    # The rehearsal library imports nothing of either change source or the edge.
    layers = ("infrahub", "netbox", "edge")
    assert not any(_under(name, f"{OWN}.{layer}") for name in of["rehearsal"] for layer in layers)
    # Nor of either reader or Prefect.
    roots = ("fylgja_infrahub", "fylgja_netbox", "prefect")
    assert not any(_under(name, root) for name in of["rehearsal"] for root in roots)


def _claims(tree: ast.Module) -> int:
    """How many calls of an attribute `claim` `tree` makes."""
    return sum(1 for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "claim")


def test_only_the_edges_run_calls_claim() -> None:
    # A request is taken once, by the edge, after the draft question and before the library (D-097): nothing else
    # of the example takes it, the library and `stage mark` among them.
    calling = {path.relative_to(PACKAGE).as_posix() for path in _files() if _claims(ast.parse(path.read_text()))}
    assert calling == {"edge/run.py"}
    assert not any(name.startswith("rehearsal/") for name in calling)
    assert _claims(ast.parse("source.claim(change)\n")) == 1, "the scan is blind"
