import re

from fylgja_core import clock


def test_now_is_rfc3339_utc_with_microseconds() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", clock.now())
