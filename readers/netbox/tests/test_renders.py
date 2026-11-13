"""Each device's configuration is what NetBox renders for it at the read, its text taken verbatim (D-095,
Constitution IV): each answer `render-config` can give is judged by its status, then by its bytes, into the text or
the finding that names the device. Over `Rendered` values built in the tests, never NetBox's answers (D-034)."""

from __future__ import annotations

import pytest
from fake import TEXT
from fylgja_core.findings import Finding

from fylgja_netbox import renders
from fylgja_netbox.rows import Device, Rendered

N2 = Device(2, "n2", 1)

NO_TEMPLATE = "{'error': 'No config template found for this device.'}"
"""What NetBox answers a render of a device with no template, 400 in `text/plain`, single-quoted
(design/verified-facts.md, "A device's configuration, rendered")."""

FAILED = "UndefinedError: 'dcim.models.devices.Device object' has no attribute 'nosuch'"
"""What NetBox answers a render whose template fails, 500 in `text/plain` (the same facts)."""


def judged(rendered: Rendered, *, branch: str | None = "b") -> Finding:
    found = renders.judge(N2, rendered, branch=branch)
    assert isinstance(found, Finding), found
    assert (found.severity, found.object) == ("error", "n2")
    assert "n2" in found.message and ("branch b" if branch else "main") in found.message
    return found


@pytest.mark.parametrize(
    ("rendered", "rule", "held"),
    [
        (Rendered(400, NO_TEMPLATE.encode(), TEXT), "render.template.missing", [NO_TEMPLATE]),
        (Rendered(500, FAILED.encode(), TEXT), "render.failed", [FAILED]),
        (Rendered(200, b"", TEXT), "render.empty", []),
        (Rendered(200, b" \n", TEXT), "render.empty", []),
        (Rendered(200, b"\xff\xfe", TEXT), "render.invalid", ["byte 0 of 2"]),
        (Rendered(404, b"x", TEXT), "render.unavailable", ["HTTP 404"]),
        (Rendered(502, b"x", TEXT), "render.unavailable", ["HTTP 502"]),
    ],
    ids=["400", "500", "empty", "whitespace", "no utf-8", "404", "502"],
)
def test_each_answer_is_its_rule(rendered: Rendered, rule: str, held: list[str]) -> None:
    found = judged(rendered)
    assert found.rule == rule
    for said in held:
        assert said in found.message, said
    assert found.message.endswith(".")


def test_a_configuration_is_taken_verbatim() -> None:
    """A render's last byte is the template's (design/verified-facts.md), so the trailing newline is kept."""
    assert renders.judge(N2, Rendered(200, b"set / x\n", TEXT), branch="b") == "set / x\n"
    assert renders.judge(N2, Rendered(200, b"\n  set / x\r\n\n", TEXT), branch=None) == "\n  set / x\r\n\n"


def test_a_refusals_words_are_quoted_as_text_and_cut() -> None:
    """NetBox's words are quoted for a 400 and a 500 alone, as text and never parsed, cut at 300 characters."""
    long = "UndefinedError: " + "y" * 400
    found = judged(Rendered(500, long.encode(), TEXT))
    assert ("UndefinedError: " + "y" * 284) in found.message
    assert ("y" * 285) not in found.message
    assert renders.QUOTED == 300

    found = judged(Rendered(500, b"UndefinedError:\n   'two\tlines'", TEXT), branch=None)
    assert "UndefinedError: 'two lines'" in found.message


def test_an_answer_of_another_status_quotes_no_body() -> None:
    for status in (404, 502, 302):
        found = judged(Rendered(status, b"set / secret-line", TEXT))
        assert found.rule == renders.RULE_UNAVAILABLE
        assert f"HTTP {status}" in found.message
        assert "secret-line" not in found.message


def test_a_404_names_the_grant_a_render_needs() -> None:
    """NetBox answers 404 to a render where the token's account lacks `view` or `render_config` on `dcim.device`
    (design/verified-facts.md), and the read has just listed the device under the same header: the message says so."""
    found = judged(Rendered(404, b'{"detail": "No Device matches the given query."}', TEXT))
    assert "render_config" in found.message and "dcim.device" in found.message
    assert "No Device matches" not in found.message
    other = judged(Rendered(502, b"x", TEXT))
    assert "render_config" not in other.message


def test_no_byte_of_a_configuration_is_quoted() -> None:
    found = judged(Rendered(200, b"set / interface ethernet-1/1\n\xff", TEXT))
    assert found.rule == renders.RULE_INVALID
    assert "ethernet-1/1" not in found.message and "\\xff" not in found.message
    assert "byte 29 of 30" in found.message


def test_a_device_with_no_name_is_named_by_its_id() -> None:
    found = renders.judge(Device(9, None, 1), Rendered(200, b"", TEXT), branch="b")
    assert isinstance(found, Finding)
    assert found.object == "dcim.device 9"
    assert "dcim.device 9" in found.message


def test_the_rules() -> None:
    assert (
        renders.RULE_TEMPLATE_MISSING,
        renders.RULE_FAILED,
        renders.RULE_EMPTY,
        renders.RULE_INVALID,
        renders.RULE_UNAVAILABLE,
    ) == ("render.template.missing", "render.failed", "render.empty", "render.invalid", "render.unavailable")


GONE = Rendered(400, b"Invalid branch identifier", "text/html; charset=utf-8")
"""What NetBox answers a render under the header of a branch that was deleted (design/verified-facts.md, "A render
under the header of a branch that is gone")."""


def test_a_400_is_a_missing_template_only_where_netbox_says_so() -> None:
    """Every request under the header of a branch deleted, syncing or merged is 400, so a 400 whose words are not the
    no-template answer's is no missing template: it is `render.unavailable`, its words quoted, for the read to weigh
    against its bracket."""
    found = judged(GONE)
    assert found.rule == renders.RULE_UNAVAILABLE
    assert "HTTP 400" in found.message and "Invalid branch identifier" in found.message
    assert "template" not in found.message
    assert renders.NO_TEMPLATE == "No config template found for this device."
    assert judged(Rendered(400, NO_TEMPLATE.encode(), TEXT)).rule == renders.RULE_TEMPLATE_MISSING


@pytest.mark.parametrize(
    "content_type", ["text/plain; charset=utf-8", "text/plain", "Text/Plain;charset=UTF-8", " text/plain ; x=y"]
)
def test_a_200_of_text_is_the_configuration(content_type: str) -> None:
    assert renders.judge(N2, Rendered(200, b"set / x\n", content_type), branch="b") == "set / x\n"


@pytest.mark.parametrize(
    ("content_type", "named"),
    [("application/json", "application/json"), ("text/html; charset=utf-8", "text/html"), (None, "no content type")],
)
def test_a_200_that_netbox_does_not_call_text_is_invalid(content_type: str | None, named: str) -> None:
    """Where NetBox answered its JSON envelope, `{configtemplate, content}`, the envelope would otherwise be taken as
    the device's configuration: a 200 is the configuration only where its content type is `text/plain`."""
    body = b'{"configtemplate": {"id": 1}, "content": "set / interface ethernet-1/1\\n"}'
    found = judged(Rendered(200, body, content_type))
    assert found.rule == renders.RULE_INVALID
    assert named in found.message
    assert "ethernet-1/1" not in found.message and "configtemplate" not in found.message
