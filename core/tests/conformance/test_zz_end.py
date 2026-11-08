"""The suite's last module, by its name: what the session leaves. The runtime holds nothing of a
twin that no record names, and nothing of the suite's twins, each scenario having removed its
own; and every line the core logged is one JSON object holding no secret (Constitution X).
"""

from __future__ import annotations

from conformance.harness import Harness
from conformance.reads import TWINS, assert_log_clean


def test_the_runtime_holds_nothing_no_record_names(harness: Harness) -> None:
    listed = harness.client().get("/v1/twins")
    assert listed.status_code == 200, listed.text
    named = {record["name"] for record in listed.json()["twins"]}
    held = harness.twins()
    print(f"\n[conformance] the runtime holds {sorted(held)}; the records name {sorted(named)}", flush=True)
    assert held <= named, f"the runtime holds twins no record names: {sorted(held - named)}"
    assert not held & set(TWINS), f"the runtime still holds the suite's {sorted(held & set(TWINS))}"


def test_every_line_the_core_logged_is_json_and_holds_no_secret(harness: Harness) -> None:
    assert_log_clean(harness)
