"""The contract tier's guard of its credentials (P5-60), in the pure tier: a fixture that fails while it holds a token,
run in a pytest of its own under the tier's hooks, and its whole output searched for the token's value. No network.

A token held as a `Secret` shows its name alone in any `repr`; one a fixture holds as a bare string, as a frame of the
source's or the reader's holds its own, is replaced by its variable's name in the report, whether the tier read it
from its variable or a test made it and hid it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from contract.conftest import Secret

TESTS = Path(__file__).resolve().parent

# Test values, never a credential: one in a `Secret`, one read from a variable of the tier's, one made by the test.
HELD = "held-test-token-0000000000000000"
READ = "read-test-token-1111111111111111"
MADE = "made-test-token-2222222222222222"

CONFTEST = """
from contract.conftest import pytest_runtest_makereport  # noqa: F401, the tier's hook, as its conftest has it
"""

FAILING = f"""
import os

import pytest

from contract.conftest import Secret, hide


@pytest.fixture
def held():
    return Secret("FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN", {HELD!r})


@pytest.fixture
def read():
    return os.environ["FYLGJA_INFRAHUB_WRITE_TOKEN"]


@pytest.fixture
def made():
    return hide(Secret("the test's own", {MADE!r})).value


@pytest.fixture
def broken(held, read, made):
    raise RuntimeError("a fixture that fails while it holds three tokens")


def test_held(broken):
    pass


def test_failing(held, read, made):
    print(read, made)
    assert read == made
"""


def test_a_secret_shows_its_name_alone() -> None:
    held = Secret("FYLGJA_INFRAHUB_TOKEN", HELD)
    assert HELD not in repr(held) and HELD not in str(held) and HELD not in repr([held])
    assert "FYLGJA_INFRAHUB_TOKEN" in repr(held)


def test_a_fixture_failing_while_it_holds_a_token_shows_no_value(tmp_path: Path) -> None:
    (tmp_path / "conftest.py").write_text(CONFTEST)
    (tmp_path / "test_failing.py").write_text(FAILING)
    environ = {"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{TESTS}:{TESTS.parents[1] / 'core' / 'tests'}",
               "FYLGJA_INFRAHUB_WRITE_TOKEN": READ}
    ran = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rA", "--tb=long", "-p", "no:cacheprovider", "-p", "no:randomly",
         str(tmp_path)],
        cwd=tmp_path, env=environ, capture_output=True, text=True, timeout=120,
    )
    output = ran.stdout + ran.stderr
    found = [name for name, value in (("held", HELD), ("read", READ), ("made", MADE)) if value in output]
    assert "1 failed, 1 error" in output, output[-2000:]
    assert "RuntimeError: a fixture that fails" in output
    assert "<FYLGJA_INFRAHUB_WRITE_TOKEN>" in output and "<the test's own>" in output
    assert found == []
