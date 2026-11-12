"""Infrahub's time strings: read to compare, never rewritten but by `after`, and refused where Infrahub would read
another instant than the one given (design/verified-facts.md, "Infrahub 1.11.11")."""

from __future__ import annotations

import pytest

from fylgja_infrahub import times


def test_after_is_the_next_microsecond_in_the_zone_given() -> None:
    assert times.after("2026-10-08T05:48:38.544482+00:00") == "2026-10-08T05:48:38.544483+00:00"
    assert times.after("2026-12-31T23:59:59.999999Z") == "2027-01-01T00:00:00.000000Z"
    assert times.after("2026-11-09T10:00:00.000000+00:00") == "2026-11-09T10:00:00.000001+00:00"
    assert times.after("2026-10-08T07:48:38.5+02:00") == "2026-10-08T07:48:38.500001+02:00"


def test_a_time_is_compared_as_the_instant_it_names() -> None:
    assert times.later("2026-10-08T05:48:38.544483+00:00", "2026-10-08T07:48:38.544482+02:00")
    assert not times.later("2026-10-08T07:48:38.544482+02:00", "2026-10-08T05:48:38.544482Z")
    assert times.parse("2026-10-08T07:48:38.544482+02:00") == times.parse("2026-10-08T05:48:38.544482Z")
    assert times.parse("1970-01-01T00:00:01.5Z") == 1_500_000_000
    assert times.parse("1970-01-01T00:00:00.000000001Z") == 1


def test_latest_is_the_first_given_that_names_the_latest_instant() -> None:
    first, same = "2026-10-08T05:48:38.544483+00:00", "2026-10-08T07:48:38.544483+02:00"
    assert times.latest(["2026-10-08T05:48:38.544482Z", first, same]) == first
    assert times.latest([]) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "2026-10-08",
        "2026-10-08 05:48:38Z",
        "2026-10-08T05:48:38",
        "2026-10-08T05:48:38+0000",
        "2026-10-08T05:48:38+00:60",
        "2026-13-08T05:48:38Z",
    ],
)
def test_parse_refuses_what_is_no_rfc_3339_time(value: str) -> None:
    with pytest.raises(ValueError):
        times.parse(value)


def test_a_value_that_is_no_time_is_invalid() -> None:
    finding = times.invalid("yesterday")
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == ("at.invalid", "error", "yesterday")
    assert times.RULE_INVALID == "at.invalid"
    assert "'yesterday'" in finding.message
    assert times.invalid("2026-11-09T10:00:00.123456+00:00") is None
    assert times.invalid("2026-11-09T10:00:00Z") is None


def test_an_invalid_time_names_the_branch_where_one_is_given() -> None:
    for value in ("yesterday", "2026-11-09T10:00:00.1234565+00:00"):
        named, bare = times.invalid(value, branch="third-link"), times.invalid(value)
        assert named is not None and bare is not None
        assert "branch third-link" in named.message
        assert "branch" not in bare.message
        assert (named.rule, named.severity, named.object) == (bare.rule, bare.severity, bare.object)
        assert (named.rule, named.object) == ("at.invalid", value)


def test_more_than_six_fractional_digits_are_invalid() -> None:
    """Infrahub cuts every digit past the sixth: a read at T with a seventh digit, or nine, answers what one at T
    does, not what the next microsecond does (reading (c), design/verified-facts.md). So such an `at` would pin a read
    at another instant than the one given, and is refused; `parse` still reads it, to compare."""
    value = "2026-11-09T10:00:00.1234565+00:00"
    finding = times.invalid(value)
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == ("at.invalid", "error", value)
    assert "honours six" in finding.message
    assert repr(value) in finding.message, "the value is quoted as the other message quotes it"
    assert times.invalid("2026-11-09T10:00:00.123456500Z") is not None
    assert times.parse(value) == times.parse("2026-11-09T10:00:00.123456+00:00") + 500
