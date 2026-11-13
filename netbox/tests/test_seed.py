"""`netbox/seed/seed.py`: the fixture network on `main`, found by its names or made, and refused where `main` is not
the fixture.

NetBox is `fake.FakeNetBox`, an `httpx.MockTransport` handler: nothing here opens a socket or starts a process. The
tokens are values of the tests' own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import seed
import yaml
from box import ADDRESS as ADDRESS_NAME
from box import TOKEN as TOKEN_NAME
from box import Box, BoxError
from fake import ADDRESS, FakeNetBox

FILES = Path(__file__).resolve().parents[1] / "seed"
TOKEN = "nbt_k.t"
SECRET = "nbt_abcdefghijkl.s3cr3ts3cr3t"
"""A token of NetBox's v2 shape, `nbt_<key>.<token>`, that nothing the seed prints may hold a part of."""
HALVES = ("abcdefghijkl", "s3cr3ts3cr3t")

ORDER = [
    "dcim/manufacturers/",
    "extras/config-templates/",
    "dcim/platforms/",
    "dcim/device-types/",
    "dcim/sites/",
    "dcim/device-roles/",
    "extras/tags/",
    *["dcim/devices/"] * 3,
    *["dcim/interfaces/"] * 15,
    *["ipam/ip-addresses/"] * 6,
    *["dcim/cables/"] * 2,
    "extras/config-contexts/",
]
"""The seed's creates over an empty `main`: each after every create whose id its body names."""


def holds_part(text: str) -> bool:
    """Whether `text` holds any five characters in a row of either half of `SECRET`."""
    return any(half[at : at + 5] in text for half in HALVES for at in range(len(half) - 4))


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ADDRESS_NAME, ADDRESS)
    monkeypatch.setenv(TOKEN_NAME, TOKEN)


def held() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((FILES / seed.FIXTURE).read_text())
    return loaded


def over(fake: FakeNetBox) -> Box:
    return Box(ADDRESS, TOKEN, transport=httpx.MockTransport(fake))


def seeded() -> FakeNetBox:
    """A fake whose `main` the seed has filled, its requests forgotten."""
    fake = FakeNetBox()
    seed.seed(over(fake), FILES)
    fake.requests.clear()
    return fake


def run(fake: FakeNetBox, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = seed.main(["--files", str(FILES)], transport=httpx.MockTransport(fake))
    out, err = capsys.readouterr()
    return code, out, err


def test_the_seed_makes_everything_once_in_the_order_ids_need() -> None:
    fake = FakeNetBox()
    box = over(fake)
    seed.seed(box, FILES)
    posted = fake.sent("POST")
    assert [path for path, _ in posted] == ORDER
    assert fake.sent("PATCH") == [] and fake.sent("DELETE") == []
    assert [what for what, _, _ in box.ensured] == ["made"] * len(ORDER)

    fixture = held()
    bodies: dict[str, list[dict[str, Any]]] = {}
    for path, body in posted:
        bodies.setdefault(path, []).append(body)
    [manufacturer] = fake.rows("dcim/manufacturers/")
    [template] = fake.rows("extras/config-templates/")
    [platform] = fake.rows("dcim/platforms/")
    [device_type] = fake.rows("dcim/device-types/")
    [site] = fake.rows("dcim/sites/")
    [role] = fake.rows("dcim/device-roles/")
    [tag] = fake.rows("extras/tags/")
    assert bodies["dcim/manufacturers/"] == [fixture["manufacturer"]]
    assert bodies["extras/config-templates/"] == [
        {"name": "fylgja-srlinux", "template_code": (FILES / seed.TEMPLATE).read_text().strip()}
    ]
    assert bodies["dcim/platforms/"] == [
        {**fixture["platform"], "manufacturer": manufacturer["id"], "config_template": template["id"]}
    ]
    assert platform["config_template"]["id"] == template["id"]
    assert bodies["dcim/device-types/"] == [{**fixture["device_type"], "manufacturer": manufacturer["id"]}]
    assert bodies["dcim/sites/"] == [{**fixture["site"], "status": "active"}]
    assert bodies["dcim/device-roles/"] == [fixture["role"]]
    assert bodies["extras/tags/"] == [fixture["tag"]]
    assert bodies["dcim/devices/"] == [
        {
            "name": device["name"],
            "device_type": device_type["id"],
            "role": role["id"],
            "site": site["id"],
            "platform": platform["id"],
            "status": "active",
            "tags": [tag["id"]],
            "description": "FYLGJA-MARKER-fixture",
        }
        for device in fixture["devices"]
    ]

    ports = {(row["device"]["name"], row["name"]): row for row in fake.rows("dcim/interfaces/")}
    assert len(ports) == 15
    for device in fixture["devices"]:
        for port in device["interfaces"]:
            row = ports[(device["name"], port["name"])]
            assert (row["type"]["value"], row["mgmt_only"], row["enabled"]) == (port["type"], port["mgmt_only"], True)
    addresses = {
        (row["assigned_object"]["device"]["name"], row["assigned_object"]["name"], row["address"])
        for row in fake.rows("ipam/ip-addresses/")
    }
    assert addresses == {
        (device["name"], port["name"], address)
        for device in fixture["devices"]
        for port in device["interfaces"]
        for address in port["addresses"]
    }
    assert all(body["status"] == "active" for body in bodies["ipam/ip-addresses/"])
    cables = {
        frozenset(
            f"{end['object']['device']['name']}:{end['object']['name']}"
            for end in row["a_terminations"] + row["b_terminations"]
        )
        for row in fake.rows("dcim/cables/")
    }
    assert cables == {frozenset(cable) for cable in fixture["cables"]}
    assert all(body["status"] == "connected" for body in bodies["dcim/cables/"])
    assert bodies["extras/config-contexts/"] == [{**fixture["probes"], "is_active": False}]

    assert seed.differences(box, fixture) == []


def test_a_second_seed_sends_no_write(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeNetBox()
    assert run(fake, capsys)[0] == 0
    fake.requests.clear()
    code, out, err = run(fake, capsys)
    assert (code, err) == (0, "")
    assert fake.writes() == []
    lines = out.splitlines()
    assert len(lines) == len(ORDER)
    assert all(line.startswith("found ") for line in lines), lines


def test_a_first_seed_says_what_it_made(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(FakeNetBox(), capsys)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert len(lines) == len(ORDER)
    assert lines[0] == "made /api/dcim/manufacturers/1/"
    assert all(line.startswith("made /api/") for line in lines)


def test_a_changed_template_an_unassigned_platform_and_an_active_context_are_written_again(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = seeded()
    template = fake.held("extras/config-templates/", name="fylgja-srlinux")
    template["template_code"] = "# an older template"
    platform = fake.held("dcim/platforms/", name="SR Linux")
    platform["config_template"] = None
    context = fake.held("extras/config-contexts/", name="fylgja-probes")
    context["is_active"] = True
    context["data"] = {**context["data"], "probes": []}

    code, _, err = run(fake, capsys)
    assert (code, err) == (0, "")
    assert fake.sent("POST") == [] and fake.sent("DELETE") == []
    assert fake.sent("PATCH") == [
        (f"extras/config-templates/{template['id']}/", {"template_code": (FILES / seed.TEMPLATE).read_text().strip()}),
        (f"dcim/platforms/{platform['id']}/", {"config_template": template["id"]}),
        (f"extras/config-contexts/{context['id']}/", {"data": held()["probes"]["data"], "is_active": False}),
    ]


def test_a_found_object_is_otherwise_left_as_it_is(capsys: pytest.CaptureFixture[str]) -> None:
    """Only the template's code, the platform's template and the context's data and state are written again."""
    fake = seeded()
    fake.held("dcim/devices/", name="n2")["description"] = "edited by hand"
    fake.port("n1", "ethernet-1/10")["enabled"] = False
    code, _, err = run(fake, capsys)
    assert code == 1
    assert fake.writes() == []
    assert "n1 ethernet-1/10" in err and "make netbox-down PURGE=1" in err


def cable(fake: FakeNetBox, a: tuple[str, str], b: tuple[str, str]) -> None:
    fake.add(
        "dcim/cables/",
        {
            "a_terminations": [{"object_type": "dcim.interface", "object_id": fake.port(*a)["id"]}],
            "b_terminations": [{"object_type": "dcim.interface", "object_id": fake.port(*b)["id"]}],
            "status": "connected",
        },
    )


def test_a_main_that_is_not_the_fixture_is_refused_naming_what_differs(capsys: pytest.CaptureFixture[str]) -> None:
    third = seeded()
    cable(third, ("n1", "ethernet-1/2"), ("n3", "ethernet-1/2"))
    code, _, err = run(third, capsys)
    assert code == 1
    assert "n1:ethernet-1/2" in err and "n3:ethernet-1/2" in err
    assert "make netbox-down PURGE=1" in err
    assert third.writes() == []

    fourth = seeded()
    n1 = fourth.held("dcim/devices/", name="n1")
    fourth.add("dcim/devices/", {**{k: v for k, v in n1.items() if k != "id"}, "name": "n4"})
    code, _, err = run(fourth, capsys)
    assert code == 1
    assert "n4" in err and "make netbox-down PURGE=1" in err
    assert fourth.writes() == []

    address = seeded()
    port = address.port("n1", "ethernet-1/2")
    address.add(
        "ipam/ip-addresses/",
        {
            "address": "192.0.2.1/24",
            "status": "active",
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": port["id"],
        },
    )
    code, _, err = run(address, capsys)
    assert code == 1
    assert "192.0.2.1/24" in err and "n1 ethernet-1/2" in err and "make netbox-down PURGE=1" in err
    assert address.writes() == []

    fake = seeded()
    for row in list(fake.objects["dcim/cables/"].values()):
        del fake.objects["dcim/cables/"][row["id"]]
    cable(fake, ("n1", "ethernet-1/1"), ("n3", "ethernet-1/2"))
    code, _, err = run(fake, capsys)
    assert code == 1
    assert "n1 ethernet-1/1" in err and "n3 ethernet-1/2" in err and "n2 ethernet-1/1" in err
    assert "make netbox-down PURGE=1" in err
    assert fake.writes() == []

    with pytest.raises(BoxError, match="n1 ethernet-1/1"):
        seed.seed(over(fake), FILES)
    assert fake.sent("POST") == []


def test_the_differences_are_each_one_sentence() -> None:
    fake = seeded()
    cable(fake, ("n1", "ethernet-1/2"), ("n3", "ethernet-1/2"))
    fake.port("n2", "mgmt0")["mgmt_only"] = False
    fake.held("dcim/devices/", name="n3")["tags"] = []
    found = seed.differences(over(fake), held())
    assert found
    assert all(sentence.count(". ") == 0 and "\n" not in sentence for sentence in found)
    assert any("n3" in sentence and "no device" in sentence for sentence in found)
    assert any("n2 mgmt0" in sentence for sentence in found)


@pytest.mark.parametrize("name", [ADDRESS_NAME, TOKEN_NAME])
def test_a_variable_not_set_is_exit_2_naming_it(
    name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(name)
    fake = FakeNetBox()
    code, out, err = run(fake, capsys)
    assert code == 2
    assert name in err and out == ""
    assert fake.requests == []


def test_a_command_line_not_understood_is_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeNetBox()
    assert seed.main([], transport=httpx.MockTransport(fake)) == 2
    assert seed.main(["--files", str(FILES), "--other"], transport=httpx.MockTransport(fake)) == 2
    capsys.readouterr()
    assert fake.requests == []


def test_nothing_the_seed_prints_holds_the_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(TOKEN_NAME, SECRET)
    fake = FakeNetBox()
    fake.refused[3] = 403
    code, out, err = run(fake, capsys)
    assert code == 1
    third = fake.requests[2]
    assert third.url.path in err and "403" in err
    assert "make netbox-down PURGE=1" in err
    assert not holds_part(out) and not holds_part(err)


PURGE = "make netbox-down PURGE=1, then make netbox-up, then load local/.env again and run make netbox-seed"
"""The purge as the seed says it, with `local/.env` loaded again before the seed: `make netbox-up` replaces the write
token's line after a purge."""


def unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("[Errno 111] Connection refused", request=request)


def failed(kind: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """The seed's exit and its stderr after a failure of `kind`."""
    files, fake = FILES, FakeNetBox()
    transport = httpx.MockTransport(fake)
    if kind == "not answered":
        transport = httpx.MockTransport(unreachable)
    elif kind in ("401", "403", "500"):
        fake.refused[1] = int(kind)
    elif kind == "a difference":
        fake = seeded()
        cable(fake, ("n1", "ethernet-1/2"), ("n3", "ethernet-1/2"))
        transport = httpx.MockTransport(fake)
    elif kind == "cabled elsewhere":
        fake = seeded()
        for row in list(fake.objects["dcim/cables/"].values()):
            del fake.objects["dcim/cables/"][row["id"]]
        cable(fake, ("n1", "ethernet-1/1"), ("n3", "ethernet-1/2"))
        transport = httpx.MockTransport(fake)
    elif kind == "a lookup matched twice":
        for _ in range(2):
            fake.add("dcim/manufacturers/", dict(held()["manufacturer"]))
    elif kind == "a file not there":
        files = tmp_path
        (files / seed.FIXTURE).write_bytes((FILES / seed.FIXTURE).read_bytes())
    capsys.readouterr()
    code = seed.main(["--files", str(files)], transport=transport)
    return code, capsys.readouterr().err


@pytest.mark.parametrize(
    "kind",
    [
        "not answered",
        "401",
        "403",
        "500",
        "a difference",
        "cabled elsewhere",
        "a lookup matched twice",
        "a file not there",
    ],
)
def test_the_remedy_is_said_for_what_failed(kind: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The purge only where `main` is the matter; `make netbox-up` where NetBox did not answer; `local/.env` loaded
    again where NetBox refused the write token, then `make netbox-up`, which provisions a refused token again, and the
    purge named only as what remains; and nothing where no remedy is known, a file that is not there and a lookup
    NetBox answered with two rows among them."""
    code, err = failed(kind, tmp_path, capsys)
    assert code == 1
    said = err.splitlines()
    if kind in ("a difference", "cabled elsewhere"):
        assert said[-1].endswith(f"the seed deletes nothing: {PURGE}"), said
        assert seed.UP not in err and seed.RELOAD not in err
    elif kind == "not answered":
        assert said[-1].startswith("seed: make netbox-up "), said
        assert "PURGE=1" not in err
    elif kind in ("401", "403"):
        assert said[-1].startswith("seed: load local/.env again"), said
        assert said[-1].endswith(f"only where NetBox refuses it after that, {PURGE}"), said
        reload, up, purge = (said[-1].index(words) for words in ("load local/.env", "run make netbox-up", "PURGE=1"))
        assert reload < up < purge, said
        assert "provisions a refused token again without a purge" in said[-1], said
        assert err.count("PURGE=1") == 1
    else:
        assert len(said) == 1, said
        assert "PURGE=1" not in err and "make netbox-up" not in err and "local/.env" not in err
