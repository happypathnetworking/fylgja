import re
import time

from fylgja_core import ulid

PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")  # twin-record-1 run_id


def test_a_ulid_is_the_formats_run_id() -> None:
    assert PATTERN.fullmatch(ulid.new())
    assert ulid.PATTERN.pattern == PATTERN.pattern


def test_ulids_sort_by_creation_within_a_process() -> None:
    ids = [ulid.new() for _ in range(1000)]
    assert ids == sorted(ids) and len(set(ids)) == 1000


def test_the_time_part_is_milliseconds_since_the_epoch() -> None:
    before = int(time.time() * 1000)
    made = ulid.new()
    after = int(time.time() * 1000)
    assert before <= ulid.timestamp_ms(made) <= after


def test_a_second_ulid_in_the_same_millisecond_increments_the_random_part() -> None:
    a = ulid.new_at(1_000, 7)
    b = ulid.new_at(1_000, 7)
    assert a < b and ulid.timestamp_ms(a) == ulid.timestamp_ms(b) == 1_000
