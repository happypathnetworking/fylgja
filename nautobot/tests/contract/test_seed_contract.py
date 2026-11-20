"""`nautobot/seed/seed.py` against the running development Nautobot: a read after the seed, the fixture on Nautobot,
each device's configuration as Golden Config renders it, the probes' context, a template pushed, and a second seed.

The module's fixture commits the templates and seeds Nautobot first, as `make nautobot-seed` does; on a Nautobot the
seed has filled it writes nothing. A template a test pushes is pushed back, and each device rendered after, so that
the head the repository's `current_head` names is the tracked templates' again.

Every request is given `box.py`'s `TIMEOUT_S`, 30 s, a first value (design/verified-facts.md, "Nautobot 3.2.8 with
Golden Config 3.0.8"): a render read 0.32 s to 0.48 s, the first after a push 8.17 s once, and one that cloned the
repository again after a recreate 9.26 s, the slowest; 30 s is about 3.2 times that, a derivation.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import seed
from box import Box

ROOT = Path(__file__).resolve().parents[3]
FILES = ROOT / "nautobot" / "seed"

FIRST = "# {name}: production configuration rendered by Golden Config (fylgja-templates)"
"""The first line of each configuration: the template's own, where the blueprint's is Infrahub's."""


@pytest.fixture(scope="module")
def fixture(box: Box, served: Path) -> dict[str, Any]:
    """The templates committed and Nautobot seeded, and the fixture it was seeded from."""
    seed.templates(seed.command, served, FILES)
    seed.seed(box, FILES)
    return seed.load(FILES)


def devices(box: Box) -> dict[str, dict[str, Any]]:
    return {str(row["name"]): row for row in box.listed("dcim/devices/", tags=seed.TAG)}


def render(box: Box, number: str) -> dict[str, Any]:
    """Golden Config's render of the device whose id is `number`, by the superuser's token."""
    answer: dict[str, Any] = box.get(seed.RENDER, device_id=number)
    return answer


def head(box: Box, fixture: dict[str, Any]) -> str:
    """The repository's `current_head`, the commit Nautobot last fetched."""
    found = box.one("extras/git-repositories/", name=fixture["repository"]["name"])
    assert found is not None
    return str(found["current_head"])


def changelog(box: Box) -> tuple[int, str | None]:
    """The changelog's count and its newest row's time."""
    answer = box.get("extras/object-changes/", limit=1)
    results = answer["results"]
    return answer["count"], results[0]["time"] if results else None


def configurations() -> dict[str, list[str]]:
    """The blueprint's configuration of each device, by its name, as lines."""
    return {name: text.split("\n") for name, text in seed.configurations().items()}


def test_a_read_after_the_seed_finds_the_head_fetched(
    box: Box, served: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`make nautobot-seed`'s last act renders each device, so the head a push of its moved is fetched before any
    read: a render after it moves no head and adds no changelog row."""
    code = seed.main(["--files", str(FILES), "--git", str(served)])
    _, err = capsys.readouterr()
    assert (code, err) == (0, "")
    fixture = seed.load(FILES)
    before = head(box, fixture), changelog(box)
    for row in devices(box).values():
        render(box, row["id"])
    assert (head(box, fixture), changelog(box)) == before


def test_nautobot_holds_the_fixture(box: Box, fixture: dict[str, Any]) -> None:
    held = devices(box)
    assert sorted(held) == ["n1", "n2", "n3"]
    ports = [row for device in held.values() for row in box.listed("dcim/interfaces/", device_id=device["id"])]
    assert len(ports) == 15
    names = {row["id"]: f"{row['device']['id']} {row['name']}" for row in ports}
    assert sorted(row["name"] for row in ports if row["mgmt_only"]) == ["mgmt0"] * 3
    assigned = [row for row in box.listed("ipam/ip-address-to-interface/") if row["interface"]["id"] in names]
    assert len(assigned) == 6
    cables = {row["id"] for device in held.values() for row in box.listed("dcim/cables/", device_id=device["id"])}
    assert len(cables) == 3
    setting = box.one(seed.SETTINGS, slug=fixture["setting"]["slug"])
    assert setting is not None
    members = box.listed(f"{seed.GROUPS}{setting['dynamic_group']['id']}/members/")
    assert sorted(row["name"] for row in members) == ["n1", "n2", "n3"]
    assert seed.differences(box, fixture) == []


def test_each_device_renders_three_nodes_configuration(box: Box, fixture: dict[str, Any]) -> None:
    """The blueprint's line for line after the first; each ends in one newline, the loop's own, as Golden Config was
    read to drop a template's last."""
    wanted = configurations()
    for name, row in devices(box).items():
        text = render(box, row["id"])["intended_config"]
        lines = text.split("\n")
        assert lines[0] == FIRST.format(name=name)
        assert lines[1:] == wanted[name][1:], name
        assert text.endswith("\n") and not text.endswith("\n\n"), name


def test_the_probes_context_is_inactive_and_reaches_no_render(box: Box, fixture: dict[str, Any]) -> None:
    context = box.one("extras/config-contexts/", name=fixture["probes"]["name"])
    assert context is not None
    assert context["is_active"] is False
    assert context["data"] == fixture["probes"]["data"]
    for name, row in devices(box).items():
        data = render(box, row["id"])["graphql_data"]
        assert data["hostname"] == name
        assert "probes" not in data["config_context"], name
        assert "probes_version" not in json.dumps(data), name


def test_a_template_pushed_is_rendered_at_the_next_render(
    box: Box, fixture: dict[str, Any], served: Path, scratch: str, tmp_path: Path
) -> None:
    """A comment line added to a copy of the templates and committed: Nautobot fetches it at the next render, which
    holds the line; then the tracked templates are committed back and each device rendered, the head the new
    commit."""
    other = tmp_path / "files"
    shutil.copytree(FILES / seed.TEMPLATES, other / seed.TEMPLATES)
    template = other / seed.TEMPLATES / "nokia_srl.j2"
    line = f"# {scratch}"
    template.write_text(template.read_text() + line + "\n")
    held = devices(box)
    before = head(box, fixture)
    back: str | None = None
    try:
        pushed = seed.templates(seed.command, served, other)
        assert pushed is not None
        assert head(box, fixture) == before
        text = render(box, held["n1"]["id"])["intended_config"]
        assert head(box, fixture) == pushed
        assert line in text.split("\n")
    finally:
        back = seed.templates(seed.command, served, FILES)
        for row in held.values():
            render(box, row["id"])
    assert back is not None and head(box, fixture) == back
    assert line not in render(box, held["n1"]["id"])["intended_config"].split("\n")


def counts(box: Box) -> dict[str, int]:
    held = devices(box)
    ports = {row["id"] for device in held.values() for row in box.listed("dcim/interfaces/", device_id=device["id"])}
    cables = {row["id"] for device in held.values() for row in box.listed("dcim/cables/", device_id=device["id"])}
    assigned = [row for row in box.listed("ipam/ip-address-to-interface/") if row["interface"]["id"] in ports]
    return {"devices": len(held), "interfaces": len(ports), "addresses": len(assigned), "cables": len(cables)}


def test_the_seed_run_twice_writes_nothing(box: Box, fixture: dict[str, Any], served: Path) -> None:
    """No commit to the repository and no write to Nautobot: the changelog's count and newest row stay."""
    before = changelog(box), counts(box)
    assert seed.templates(seed.command, served, FILES) is None
    already = len(box.ensured)
    seed.seed(box, FILES)
    assert [what for what, _, _ in box.ensured[already:]] == ["found"] * (len(box.ensured) - already)
    assert (changelog(box), counts(box)) == before
    assert before[1] == {"devices": 3, "interfaces": 15, "addresses": 6, "cables": 3}
