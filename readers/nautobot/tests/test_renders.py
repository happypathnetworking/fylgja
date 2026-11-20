"""Each device's configuration is Golden Config's render of it at the read, `intended_config` taken verbatim (D-118,
Constitution IV): each answer `generate-intended-config` can give is judged by its status, then by Golden Config's
words, into the text or the finding that names the device. Over `Rendered` values built in the tests, never Golden
Config's answers (D-034); the words are Golden Config's as design/verified-facts.md holds them, "Nautobot 3.2.8 with
Golden Config 3.0.8", "Golden Config's render"."""

from __future__ import annotations

import pytest
from fylgja_core.findings import Finding

from fylgja_nautobot import renders
from fylgja_nautobot.rows import Device, Rendered

N2 = Device("device-2", "n2", "platform-1")

NO_SETTING = "No Golden Config settings found for this device"
MISSING = "Error rendering Jinja template: Jinja template eos.j2 not found in git repository templates"
FAILED = "Error rendering Jinja template: Subtask: GENERATE CONFIG (failed)\n"
NOT_FOUND = "Device with id 'x' not found"


def judged(rendered: Rendered) -> Finding:
    found = renders.judge(N2, rendered)
    assert isinstance(found, Finding), found
    assert (found.severity, found.object) == ("error", "n2")
    assert "n2" in found.message
    assert found.message.endswith(".")
    return found


def test_a_device_in_no_settings_group_names_the_refresh() -> None:
    found = judged(Rendered(400, None, NO_SETTING))
    assert found.rule == "render.setting.absent"
    assert NO_SETTING in found.message
    assert "refresh" in found.message and "dynamic group" in found.message


def test_a_template_the_repository_lacks_is_missing() -> None:
    found = judged(Rendered(400, None, MISSING))
    assert found.rule == "render.template.missing"
    assert MISSING in found.message


def test_a_template_that_raises_says_the_cause_is_in_nautobots_log() -> None:
    found = judged(Rendered(400, None, FAILED))
    assert found.rule == "render.failed"
    assert "Error rendering Jinja template: Subtask: GENERATE CONFIG (failed)" in found.message
    assert "log" in found.message


def test_golden_configs_words_are_cut_at_300() -> None:
    long = "Error rendering Jinja template: " + "y" * 400
    found = judged(Rendered(400, None, long))
    assert found.rule == "render.failed"
    assert long[:300] in found.message
    assert long[:301] not in found.message
    assert renders.QUOTED == 300

    found = judged(Rendered(400, None, "Error rendering Jinja template:\n   two\tlines\n"))
    assert "Error rendering Jinja template: two lines" in found.message


def test_a_device_golden_config_cannot_find_names_the_accounts_grants() -> None:
    found = judged(Rendered(400, None, NOT_FOUND))
    assert found.rule == "render.device.unknown"
    assert NOT_FOUND in found.message
    assert "view" in found.message and "dcim.device" in found.message and "account" in found.message


@pytest.mark.parametrize("text", ["   \n", "", "\t\r\n"])
def test_a_render_of_whitespace_alone_is_empty(text: str) -> None:
    found = judged(Rendered(200, text, None))
    assert found.rule == "render.empty"


def test_a_200_with_no_text_is_invalid() -> None:
    found = judged(Rendered(200, None, None))
    assert found.rule == "render.invalid"
    assert "intended_config" in found.message


@pytest.mark.parametrize(
    ("rendered", "held"),
    [
        (Rendered(502, None, None), ["HTTP 502"]),
        (Rendered(500, None, "Server Error"), ["HTTP 500"]),
        (Rendered(302, None, None), ["HTTP 302"]),
        (Rendered(400, None, "Select a valid choice."), ["HTTP 400", "Select a valid choice."]),
        (Rendered(400, None, None), ["HTTP 400"]),
        (Rendered(400, None, "Device with id 'x' not found, or else"), ["HTTP 400", "or else"]),
    ],
    ids=["502", "500", "302", "400 in other words", "400 with no words", "400 beyond the not-found words"],
)
def test_any_other_answer_is_unavailable(rendered: Rendered, held: list[str]) -> None:
    found = judged(rendered)
    assert found.rule == "render.unavailable"
    for said in held:
        assert said in found.message, said


def test_only_a_400s_words_are_quoted() -> None:
    """Golden Config's words are quoted for a render's 400 alone (D-118)."""
    found = judged(Rendered(500, None, "set / interface ethernet-1/1 secret-line"))
    assert "secret-line" not in found.message


def test_a_configuration_is_taken_verbatim() -> None:
    """`intended_config` is the configuration, its last newline as Golden Config answered it."""
    assert renders.judge(N2, Rendered(200, "set / x\n", None)) == "set / x\n"
    assert renders.judge(N2, Rendered(200, "\n  set / x\r\n\n", None)) == "\n  set / x\r\n\n"


def test_no_byte_of_a_configuration_is_quoted() -> None:
    found = judged(Rendered(200, " \n\t", None))
    assert "\t" not in found.message


def test_a_device_with_no_name_is_named_by_its_id() -> None:
    found = renders.judge(Device("device-9", None, None), Rendered(200, " ", None))
    assert isinstance(found, Finding)
    assert found.object == "dcim.device device-9"
    assert "dcim.device device-9" in found.message


def test_the_rules_and_golden_configs_words() -> None:
    assert (
        renders.RULE_SETTING_ABSENT,
        renders.RULE_TEMPLATE_MISSING,
        renders.RULE_FAILED,
        renders.RULE_EMPTY,
        renders.RULE_INVALID,
        renders.RULE_DEVICE_UNKNOWN,
        renders.RULE_UNAVAILABLE,
    ) == (
        "render.setting.absent",
        "render.template.missing",
        "render.failed",
        "render.empty",
        "render.invalid",
        "render.device.unknown",
        "render.unavailable",
    )
    assert renders.NO_SETTING == NO_SETTING
    assert renders.FAILED == "Error rendering Jinja template:"
    assert renders.TEMPLATE_MISSING.fullmatch(MISSING)
    assert not renders.TEMPLATE_MISSING.fullmatch(FAILED.strip())
    assert renders.NOT_FOUND.fullmatch("Device with id '00000000-0000-4000-8000-000000000001' not found")
    assert not renders.NOT_FOUND.fullmatch("Device with id 'x' not found, or else")
