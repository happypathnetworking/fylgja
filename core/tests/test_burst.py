"""The burst's ping mechanism: the rendered command, the held judgement, the exec budget."""

from __future__ import annotations

from pathlib import Path

from fylgja_core import burst, probe_package
from fylgja_core.driver import Exec

ROOT = Path(__file__).resolve().parents[2]
PING = probe_package.load(ROOT / "probes" / "ping.yaml")

SUMMARY = "5 packets transmitted, {received} packets received, {loss}% packet loss"


def _ping(stdout: str, returncode: int = 0) -> Exec:
    return Exec(returncode=returncode, stdout=stdout, stderr="")


def test_command_renders_the_package_command() -> None:
    assert burst.command(PING, "10.1.11.2") == ["ping", "-c", "5", "-i", "0.2", "-W", "2", "10.1.11.2"]


def test_held_when_every_echo_is_answered() -> None:
    held, detail = burst.held(PING, _ping(SUMMARY.format(received=5, loss=0)))
    assert held is True
    assert detail


def test_not_held_when_some_echoes_are_lost() -> None:
    assert burst.held(PING, _ping(SUMMARY.format(received=3, loss=40))) == (False, "3 of 5 echoes answered")


def test_not_held_without_a_summary_line() -> None:
    held, detail = burst.held(PING, _ping("", returncode=1))
    assert held is False
    assert "exit status 1" in detail


def test_not_held_without_a_summary_on_status_zero() -> None:
    held, detail = burst.held(PING, _ping("PING 10.1.11.2 (10.1.11.2): 56 data bytes\n"))
    assert held is False
    assert detail == "no summary line in the output"


def test_not_held_when_the_count_sent_is_not_the_package_count() -> None:
    held, detail = burst.held(PING, _ping("3 packets transmitted, 3 packets received, 0% packet loss"))
    assert held is False
    assert "3 echoes sent, not 5" in detail


def test_timeout_is_count_times_interval_plus_wait_plus_margin() -> None:
    assert burst.timeout_s(PING) == 8.0
