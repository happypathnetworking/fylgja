"""The conformance suite's boundary (design/core.md, phase 6, "The conformance suite"): a
scenario names no runtime. Every module of `tests/conformance` but the package `harness`, the one
that reaches a runtime, imports none of the modules that would and holds none of the runtimes'
words, in any case, so a scenario edited to pass on one driver by naming it fails here; and a
scenario module takes of the harness its protocol and its types alone, never a harness, so it
cannot branch on which one it runs on either. The harness is made by the driver's name, for the
two drivers alone, and shows no secret in a failed assertion: its repr holds neither the node
logins of the environment it was made over nor its token. The cluster's harness, made over an
environment that lacks a variable it reads, or holds an address or a token it cannot use,
refuses in one line naming that variable and no value. A verify asked once a step has ended asks
again while it reads a node unread alone, within its bound, and fails at once on anything else.
A record that is not settled and Ready, or breaks its format, fails saying why and never showing
the record, which holds each node's address.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Any, cast

import pytest
from conformance import reads
from conformance.harness import PROBE_LABEL, Fylgja, Harness, _probe_manifests, make

from fylgja_core import probe_package
from fylgja_core.clabernetes import OWNER_LABEL, TWIN_LABEL

CONFORMANCE = Path(__file__).resolve().parent / "conformance"
HARNESS = CONFORMANCE / "harness"
SCENARIOS = sorted(p for p in CONFORMANCE.rglob("*.py") if HARNESS not in p.parents)
REFUSED = ("subprocess", "lightkube", "fylgja_core.containerlab", "fylgja_core.clabernetes", "fylgja_core.drivers")
"""The modules through which a scenario would reach a runtime, or learn a driver's name."""
WORDS = ("containerlab", "clabernetes", "docker", "kube", "clab-")
"""The runtimes' words, matched in any case: `kube` within `Kubernetes` too."""
TESTS = [p for p in SCENARIOS if p.name.startswith("test_")]
"""The suite's scenario modules."""
PROTOCOL = frozenset({"Fylgja", "Harness", "Mark", "Resume"})
"""What a scenario module may import of the harness: the protocol and its types, never a harness,
so that no scenario branches on `isinstance` without a runtime's word."""
KNOWN = "s3cr3t-known"
CLUSTER = {
    "KUBECONFIG": "/nonexistent/kubeconfig",
    "FYLGJA_API_ADDRESS": "https://192.0.2.10",
    "FYLGJA_API_TOKEN": "t0ken-known-to-the-test-alone",
    "FYLGJA_API_CA": "/nonexistent/ca.crt",
    "FYLGJA_CONFORMANCE_SELECTOR": "app.kubernetes.io/name=fylgja-core",
    "FYLGJA_CREDENTIAL_SRLINUX_USERNAME": "admin",
    "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": KNOWN,
    "FYLGJA_S3_SECRET_KEY": "s3-secret-known-to-the-test",
}
"""The cluster harness's environment, of known values alone: none of them the site's."""
REQUIRED = ("KUBECONFIG", "FYLGJA_API_ADDRESS", "FYLGJA_API_TOKEN", "FYLGJA_API_CA", "FYLGJA_CONFORMANCE_SELECTOR")
"""What the cluster harness cannot be made without."""


def imports(source: str) -> set[str]:
    """Every module `source` imports: a from-import records its module and each name under it,
    so `from fylgja_core import drivers` is seen as `fylgja_core.drivers`."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None and node.level == 0, "a relative import hides its module"
            found.add(node.module)
            found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return found


def refused(module: str) -> bool:
    return any(module == name or module.startswith(f"{name}.") for name in REFUSED)


def words(text: str) -> list[str]:
    """The runtimes' words `text` holds, in any case."""
    lowered = text.lower()
    return sorted(word for word in WORDS if word in lowered)


def from_harness(source: str) -> set[str]:
    """What `source` imports of the harness package, each dotted from `conformance`: `from
    conformance.harness import Harness` takes `conformance.harness.Harness`; `import
    conformance.harness` and `from conformance import harness` take the package whole, and a
    module of it, or a name from one, is taken by its own dotted name."""
    taken: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            taken |= {f"{node.module}.{alias.name}" for alias in node.names}
        elif isinstance(node, ast.Import):
            taken |= {alias.name for alias in node.names}
    return {name for name in taken if name == "conformance.harness" or name.startswith("conformance.harness.")}


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.relative_to(CONFORMANCE).as_posix())
def test_no_module_of_the_suite_but_the_harness_imports_a_runtime(path: Path) -> None:
    found = sorted(m for m in imports(path.read_text()) if refused(m))
    assert found == [], f"{path.name} imports {found}: only the harness reaches a runtime"


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.relative_to(CONFORMANCE).as_posix())
def test_no_module_of_the_suite_but_the_harness_names_a_runtime(path: Path) -> None:
    lines = [i for i, line in enumerate(path.read_text().splitlines(), 1) if words(line)]
    assert words(path.read_text()) == [], f"{path.name} names a runtime on lines {lines}: only the harness does"


def test_the_scan_sees_the_suite_and_spares_the_harness_alone() -> None:
    names = {p.relative_to(CONFORMANCE).as_posix() for p in SCENARIOS}
    assert {"__init__.py", "conftest.py", "reads.py", "nodes.py", "test_lifecycle.py", "test_zz_end.py"} <= names
    harness = sorted(HARNESS.glob("*.py"))
    assert [p.name for p in harness] == ["__init__.py", "cluster.py", "local.py"]
    assert not any(name.startswith("harness/") for name in names)
    # The harness is the one package that reaches a runtime: the scans would refuse it.
    assert any(refused(m) for p in harness for m in imports(p.read_text()))
    assert any(words(p.read_text()) for p in harness)
    # A refusal is seen however it is written.
    assert {"fylgja_core.drivers", "fylgja_core.containerlab.cli"} <= imports(
        "from fylgja_core import drivers\nimport fylgja_core.containerlab.cli\n")
    assert refused("fylgja_core.containerlab.cli") and not refused("fylgja_core.containerlab_x")
    assert words("Kubernetes, DOCKER, CLAB-x") == ["clab-", "docker", "kube"]


@pytest.mark.parametrize("path", TESTS, ids=lambda p: p.name)
def test_a_scenario_module_imports_of_the_harness_its_protocol_alone(path: Path) -> None:
    taken = sorted(name.removeprefix("conformance.harness.") for name in from_harness(path.read_text()))
    beyond = [name for name in taken if name not in PROTOCOL]
    assert beyond == [], f"{path.name} imports {beyond} of the harness: a scenario takes {sorted(PROTOCOL)} alone"


def test_the_harness_import_scan_sees_each_way_of_importing_it() -> None:
    assert len(TESTS) >= 6 and all(p.name.startswith("test_") for p in TESTS)
    taken = from_harness("from conformance.harness import Harness, LocalHarness\nfrom conformance.reads import TWINS\n")
    assert taken == {"conformance.harness.Harness", "conformance.harness.LocalHarness"}
    assert from_harness("from conformance import harness\nimport conformance.harness.local\n") \
        == {"conformance.harness", "conformance.harness.local"}
    assert from_harness("from conformance.harness.cluster import ClusterHarness\n") \
        == {"conformance.harness.cluster.ClusterHarness"}


def test_a_harness_is_made_for_either_driver_and_no_other(tmp_path_factory: pytest.TempPathFactory) -> None:
    with pytest.raises(ValueError) as refusal:
        make("kind", tmp_path_factory)
    said = str(refusal.value)
    assert "containerlab" in said and "clabernetes" in said, said


def test_the_local_harness_shows_no_secret_and_is_made_without_io(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An environment of known values alone: no login of the shell's reaches the harness.
    for variable in [v for v in os.environ if v.startswith("FYLGJA_")]:
        monkeypatch.delenv(variable)
    monkeypatch.setenv("FYLGJA_CREDENTIAL_SRLINUX_USERNAME", "admin")
    monkeypatch.setenv("FYLGJA_CREDENTIAL_SRLINUX_PASSWORD", KNOWN)
    before = sorted(tmp_path_factory.getbasetemp().iterdir())
    harness = make("containerlab", tmp_path_factory)
    assert sorted(tmp_path_factory.getbasetemp().iterdir()) == before, "constructing the harness made a directory"
    kept = harness.secrets()
    assert sorted(kept) == ["FYLGJA_API_TOKEN", "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD"]
    token = kept["FYLGJA_API_TOKEN"]
    # Each a bool before it is asserted, so that a failure shows neither the repr nor a value.
    shown = repr(harness)
    holds_login, holds_token = KNOWN in shown, bool(token) and token in shown
    assert kept["FYLGJA_CREDENTIAL_SRLINUX_PASSWORD"] == KNOWN and len(token) >= 32
    assert not holds_login, "the harness's repr holds a node's password"
    assert not holds_token, "the harness's repr holds its token"


def known_cluster_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """`CLUSTER` alone: no login, token or kubeconfig of the shell's reaches the harness."""
    for variable in [v for v in os.environ if v.startswith("FYLGJA_") or v == "KUBECONFIG"]:
        monkeypatch.delenv(variable)
    for variable, value in CLUSTER.items():
        monkeypatch.setenv(variable, value)


@pytest.mark.parametrize("variable", REQUIRED)
def test_the_cluster_harness_refuses_an_environment_without_a_variable_it_reads_naming_it_alone(
    variable: str, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    known_cluster_environment(monkeypatch)
    monkeypatch.delenv(variable)
    with pytest.raises(pytest.UsageError) as refusal:
        make("clabernetes", tmp_path_factory)
    said = str(refusal.value)
    shown = [name for name, value in CLUSTER.items() if value in said]  # names, never the values
    assert variable in said and "\n" not in said, said
    assert shown == [], f"the refusal shows the values of {shown}"


def test_the_cluster_harness_refuses_an_address_that_is_no_https_url_without_showing_it(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    known_cluster_environment(monkeypatch)
    monkeypatch.setenv("FYLGJA_API_ADDRESS", "192.0.2.10:7650")
    with pytest.raises(pytest.UsageError) as refusal:
        make("clabernetes", tmp_path_factory)
    said = str(refusal.value)
    assert "FYLGJA_API_ADDRESS" in said and "192.0.2.10" not in said, said


def test_the_cluster_harness_refuses_a_token_that_is_no_bearer_token_without_showing_it(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A token file with CRLF line endings: the HTTP stack would quote the header it makes whole.
    known_cluster_environment(monkeypatch)
    monkeypatch.setenv("FYLGJA_API_TOKEN", CLUSTER["FYLGJA_API_TOKEN"] + "\r")
    with pytest.raises(pytest.UsageError) as refusal:
        make("clabernetes", tmp_path_factory)
    said = str(refusal.value)
    shows = any(part in said for part in CLUSTER["FYLGJA_API_TOKEN"].split("-") if len(part) > 2)
    assert "FYLGJA_API_TOKEN" in said and "\n" not in said, said
    assert not shows, "the refusal shows a part of the token"


def test_the_cluster_harness_shows_no_secret_and_is_made_without_io(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    known_cluster_environment(monkeypatch)
    before = sorted(tmp_path_factory.getbasetemp().iterdir())
    harness = make("clabernetes", tmp_path_factory)
    assert sorted(tmp_path_factory.getbasetemp().iterdir()) == before, "constructing the harness made a directory"
    kept = harness.secrets()
    assert sorted(kept) == ["FYLGJA_API_TOKEN", "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD", "FYLGJA_S3_SECRET_KEY"]
    assert all(kept[name] == CLUSTER[name] for name in kept)
    # Each a bool before it is asserted, so that a failure shows neither the repr nor a value.
    shown = repr(harness)
    held = sorted(name for name, value in CLUSTER.items() if name in kept and value in shown)
    holds_address = CLUSTER["FYLGJA_API_ADDRESS"] in shown
    assert held == [], f"the harness's repr holds the values of {held}"
    assert not holds_address, "the harness's repr holds the API's address"


def _verdict(status: str, errors: list[tuple[str, str]], counts: tuple[int, int, int]) -> dict[str, Any]:
    """A verify verdict of a `three-node` twin, held to findings 1: its errors, and each node's host
    name a skip."""
    findings = [{"rule": rule, "severity": "error", "object": node, "message": f"{node} failed."}
                for rule, node in errors]
    findings += [{"rule": "verify.skipped", "severity": "info", "object": node, "message": f"{node} reported."}
                 for node in ("n1", "n2", "n3")]
    held, failed, skipped = counts
    return {"findings_version": "1", "operation": "verify", "status": status, "subject": {"twin": "cf-step"},
            "findings": findings, "counts": {"held": held, "failed": failed, "skipped": skipped}}


HELD = _verdict("ok", [], (15, 0, 3))
UNREAD = _verdict("failed", [("verify.node.unread", "n2")], (11, 0, 3))
DOWN = _verdict("nonconforming", [("verify.interface.up", "n2:ethernet-1/1")], (14, 1, 3))


def scripted(*answers: tuple[int, dict[str, Any]]) -> tuple[Fylgja, list[tuple[str, ...]]]:
    """A CLI that answers `twin verify` with each of `answers` in turn, the last again once they
    run out, and the calls it was given."""
    calls: list[tuple[str, ...]] = []

    def fylgja(*args: str) -> tuple[int, str]:
        calls.append(args)
        code, doc = answers[min(len(calls), len(answers)) - 1]
        return code, json.dumps(doc)

    return fylgja, calls


@pytest.fixture
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    """The re-ask's interval made short, so no test waits on it."""
    monkeypatch.setattr(reads, "UNREAD_EVERY_S", 0.01)


def test_a_verify_that_reads_a_node_unread_asks_again_and_answers_once_it_holds(quick: None) -> None:
    fylgja, calls = scripted((1, UNREAD), (1, UNREAD), (0, HELD))
    assert reads.verified(fylgja, "cf-step", "three-node") == HELD
    assert len(calls) == 3


def test_a_verify_with_another_error_fails_at_its_first_ask(quick: None) -> None:
    fylgja, calls = scripted((1, DOWN), (0, HELD))
    with pytest.raises(AssertionError):
        reads.verified(fylgja, "cf-step", "three-node")
    assert len(calls) == 1


def test_a_verify_still_unread_past_its_bound_fails(quick: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reads, "UNREAD_S", 0.05)
    fylgja, calls = scripted((1, UNREAD))
    with pytest.raises(AssertionError):
        reads.verified(fylgja, "cf-step", "three-node")
    assert len(calls) >= 2


class Ran:
    """A harness whose every twin's newest run carries `verdict`, for `reads.verdict_of`: nothing more."""

    def __init__(self, verdict: dict[str, Any]) -> None:
        self.verdict = verdict

    def runs(self, twin: str) -> list[dict[str, Any]]:
        return [{"id": "r1", "verdict": self.verdict}]


ADDRESS = "192.0.2.21"
"""A node's address in the records below: no failure may show it."""


def test_a_record_not_settled_and_ready_fails_saying_why_and_never_showing_the_record() -> None:
    record: dict[str, Any] = {"name": "cf-step", "generation": 2,
                              "status": {"observed_generation": 1,
                                         "conditions": [{"type": "Ready", "status": "False"}],
                                         "nodes": [{"name": "n1", "address": ADDRESS}]}}
    with pytest.raises(AssertionError) as failed:
        reads.assert_settled_ready(cast(Harness, Ran(UNREAD)), record, "cf-step before its step")
    said = str(failed.value)
    assert "cf-step before its step" in said and "settled False, Ready False" in said, said
    assert "verify.node.unread" in said, said
    assert ADDRESS not in said, "the failure shows a node's address"
    record["status"] |= {"observed_generation": 2, "conditions": [{"type": "Ready", "status": "True"}]}
    reads.assert_settled_ready(cast(Harness, Ran(HELD)), record, "cf-step before its step")


def test_a_record_that_breaks_its_format_fails_naming_where_and_never_a_value() -> None:
    # A value that breaks its type: jsonschema's own message for it would quote the value.
    record = {"record_version": "1", "name": "cf-step", "revision": "1", "generation": ADDRESS, "spec": {},
              "status": {}}
    with pytest.raises(AssertionError) as failed:
        reads.assert_twin_record(record)
    said = str(failed.value)
    assert "cf-step" in said and "$.generation" in said, said
    assert ADDRESS not in said, "the failure shows a value of the record"


def test_the_probe_s_namespace_and_pod_carry_the_suite_s_label_and_no_owner_s_or_twin_s() -> None:
    """What the cluster harness makes for a place of no twin is the suite's alone: the core's watch
    and the session's leftover checks, which go by the owner's and a twin's labels, pass it by."""
    made = _probe_manifests()
    assert [obj["kind"] for obj in made] == ["Namespace", "Pod"]
    for obj in made:
        labels = obj["metadata"]["labels"]
        assert labels.items() >= PROBE_LABEL.items(), obj["kind"]
        assert OWNER_LABEL not in labels and TWIN_LABEL not in labels, obj["kind"]


def test_the_probe_pod_runs_the_ping_package_s_image_once_and_mounts_no_secret_or_token() -> None:
    """The pod runs `sleep 3600` on `probes/ping.yaml`'s image and is never restarted, so one a
    session killed hard leaves runs out within the hour; it holds no Secret and no API token."""
    _, pod = _probe_manifests()
    spec = pod["spec"]
    (container,) = spec["containers"]
    ping = probe_package.load(reads.ROOT / "probes" / "ping.yaml")
    assert container["image"] == ping.runtime.containerlab.image.ref
    assert container["command"] == ["sleep", "3600"]
    assert spec.get("restartPolicy") == "Never"
    assert spec.get("automountServiceAccountToken") is False
    assert not {"volumes", "imagePullSecrets"} & spec.keys(), sorted(spec)
    assert not {"volumeMounts", "env", "envFrom"} & container.keys(), sorted(container)
