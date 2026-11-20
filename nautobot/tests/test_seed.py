"""`nautobot/seed/seed.py`: the templates committed where they differ, the fixture network found by its names or
made, the installed setting pointed at both, each device rendered last, and Nautobot refused where it is not the
fixture.

Nautobot is `fake.FakeNautobot`, an `httpx.MockTransport` handler, and git is `FakeGit`, which keeps its objects in
memory: nothing here opens a socket or starts a process. The tokens are values of the tests' own.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import seed
import yaml
from box import ADDRESS as ADDRESS_NAME
from box import TOKEN as TOKEN_NAME
from box import Box
from fake import ADDRESS, GROUPS, RENDER, SETTINGS, FakeNautobot

FILES = Path(__file__).resolve().parents[1] / "seed"
TOKEN = "0" * 40
SECRET = "5ec4e7a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6"
"""A token of Nautobot's shape, 40 lowercase hex characters, that nothing the seed prints may hold a part of."""

GROUP = "GoldenConfigSetting Default Settings scope"
"""The installed setting's dynamic group, by its name."""

ORDER = [
    "dcim/manufacturers/",
    "dcim/platforms/",
    "dcim/device-types/",
    "dcim/location-types/",
    "dcim/locations/",
    "extras/roles/",
    "extras/tags/",
    *["dcim/devices/"] * 3,
    *["dcim/interfaces/"] * 15,
    *["ipam/prefixes/", "ipam/ip-addresses/", "ipam/ip-address-to-interface/"] * 6,
    *["dcim/cables/"] * 3,
    "extras/config-contexts/",
    "extras/git-repositories/",
    "extras/graphql-queries/",
]
"""The seed's creates over an empty Nautobot: each after every create whose id its body names."""

FOUND = 3
"""The objects of Nautobot's own the seed finds and never makes: the namespace, the setting and its group."""


class FakeGit:
    """git, over a repository kept in memory: each object named by a hash of what it holds, `main` the one ref, and
    every command line recorded. `failing` names the subcommand that fails, as git fails, with status 128."""

    def __init__(self, *, failing: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.trees: dict[str, str] = {}
        """Each commit's tree."""
        self.main: str | None = None
        self.failing = failing

    def __call__(self, argv: Sequence[str], stdin: str = "", /) -> str:
        argv = list(argv)
        self.calls.append(argv)
        rest = list(argv)
        while rest[0] in ("-c", "--git-dir"):
            rest = rest[2:]
        verb = rest[0]
        if verb == self.failing:
            raise subprocess.CalledProcessError(128, ["git", *argv], output="", stderr="fatal: refused by the test\n")
        if verb == "init":
            Path(rest[-1]).mkdir(parents=True)
            return ""
        if verb == "hash-object":
            return digest(Path(rest[-1]).read_text()) + "\n"
        if verb == "mktree":
            return digest(stdin) + "\n"
        if verb == "for-each-ref":
            return f"{self.main} {self.trees[self.main]}\n" if self.main is not None else ""
        if verb == "commit-tree":
            commit = digest(f"{len(self.trees)} {rest}")
            self.trees[commit] = rest[2]
            return commit + "\n"
        if verb == "update-ref":
            assert rest[1] == "refs/heads/main"
            self.main = rest[2]
            return ""
        if verb == "update-server-info":
            return ""
        raise AssertionError(f"FakeGit runs no {verb}")

    def verbs(self) -> list[str]:
        """Each command's subcommand, in order."""
        found = []
        for argv in self.calls:
            rest = list(argv)
            while rest[0] in ("-c", "--git-dir"):
                rest = rest[2:]
            found.append(rest[0])
        return found


def digest(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def holds_part(text: str) -> bool:
    """Whether `text` holds any eight characters in a row of `SECRET`."""
    return any(SECRET[at : at + 8] in text for at in range(len(SECRET) - 7))


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ADDRESS_NAME, ADDRESS)
    monkeypatch.setenv(TOKEN_NAME, TOKEN)


def held() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((FILES / seed.FIXTURE).read_text())
    return loaded


def over(fake: FakeNautobot) -> Box:
    return Box(ADDRESS, TOKEN, transport=httpx.MockTransport(fake))


def seeded() -> FakeNautobot:
    """A fake the seed has filled, its requests forgotten."""
    fake = FakeNautobot()
    seed.seed(over(fake), FILES)
    fake.requests.clear()
    return fake


def run(
    fake: FakeNautobot, capsys: pytest.CaptureFixture[str], served: Path, git: FakeGit | None = None
) -> tuple[int, str, str]:
    code = seed.main(
        ["--files", str(FILES), "--git", str(served)], transport=httpx.MockTransport(fake), git=git or FakeGit()
    )
    out, err = capsys.readouterr()
    return code, out, err


def test_the_seed_makes_everything_once_in_the_order_ids_need() -> None:
    fake = FakeNautobot()
    box = over(fake)
    seed.seed(box, FILES)
    posted = fake.sent("POST")
    assert [path for path, _ in posted] == ORDER
    assert fake.sent("DELETE") == []
    assert [what for what, _, _ in box.ensured] == ["found"] + ["made"] * len(ORDER) + ["found"] * 2

    fixture = held()
    bodies: dict[str, list[dict[str, Any]]] = {}
    for path, body in posted:
        bodies.setdefault(path, []).append(body)
    [manufacturer] = fake.rows("dcim/manufacturers/")
    [platform] = fake.rows("dcim/platforms/")
    [device_type] = fake.rows("dcim/device-types/")
    [location_type] = fake.rows("dcim/location-types/")
    [location] = fake.rows("dcim/locations/")
    [role] = fake.rows("extras/roles/")
    [tag] = fake.rows("extras/tags/")
    namespace = fake.held("ipam/namespaces/", name="Global")["id"]
    assert bodies["dcim/manufacturers/"] == [{"name": "Nokia"}]
    assert bodies["dcim/platforms/"] == [
        {"name": "SR Linux", "network_driver": "nokia_srl", "manufacturer": manufacturer["id"]}
    ]
    assert bodies["dcim/device-types/"] == [{"model": "7220 IXR-D2L", "manufacturer": manufacturer["id"]}]
    assert bodies["dcim/location-types/"] == [{"name": "Site", "content_types": ["dcim.device"]}]
    assert bodies["dcim/locations/"] == [{"name": "lab", "location_type": location_type["id"], "status": "Active"}]
    assert bodies["extras/roles/"] == [{"name": "fylgja", "content_types": ["dcim.device"]}]
    assert bodies["extras/tags/"] == [{"name": "fylgja", "content_types": ["dcim.device"]}]
    assert bodies["dcim/devices/"] == [
        {
            "name": device["name"],
            "status": "Active",
            "role": role["id"],
            "device_type": device_type["id"],
            "location": location["id"],
            "platform": platform["id"],
            "tags": [tag["id"]],
            "comments": "FYLGJA-MARKER-fixture",
        }
        for device in fixture["devices"]
    ]

    names = {row["id"]: row["name"] for row in fake.rows("dcim/devices/")}
    ports = {(names[row["device"]["id"]], row["name"]): row for row in fake.rows("dcim/interfaces/")}
    assert len(ports) == 15
    for device in fixture["devices"]:
        for port in device["interfaces"]:
            row = ports[(device["name"], port["name"])]
            assert (row["type"]["value"], row["mgmt_only"], row["enabled"]) == (port["type"], port["mgmt_only"], True)
    assert all(body["status"] == "Active" for body in bodies["dcim/interfaces/"])

    assert [body["prefix"] for body in bodies["ipam/prefixes/"]] == [
        f"10.{d}.{port}.0/24" for d in (1, 2, 3) for port in (10, 11)
    ]
    assert all(
        (body["namespace"], body["type"], body["status"]) == (namespace, "network", "Active")
        for body in bodies["ipam/prefixes/"]
    )
    prefixes = {row["prefix"]: row["id"] for row in fake.rows("ipam/prefixes/")}
    addresses = {row["id"]: row for row in fake.rows("ipam/ip-addresses/")}
    for body in bodies["ipam/ip-addresses/"]:
        assert (body["namespace"], body["type"], body["status"]) == (namespace, "host", "Active")
        assert body["parent"] == prefixes[body["address"].replace(".1/24", ".0/24")]
    by_id = {row["id"]: key for key, row in ports.items()}
    assigned = {
        (*by_id[row["interface"]["id"]], addresses[row["ip_address"]["id"]]["address"])
        for row in fake.rows("ipam/ip-address-to-interface/")
    }
    assert assigned == {
        (device["name"], port["name"], address)
        for device in fixture["devices"]
        for port in device["interfaces"]
        for address in port["addresses"]
    }
    assert len(assigned) == 6

    cables = {
        frozenset(":".join(by_id[row[f"termination_{side}_id"]]) for side in ("a", "b"))
        for row in fake.rows("dcim/cables/")
    }
    assert cables == {frozenset(cable) for cable in fixture["cables"]}
    assert len(cables) == 3
    assert all(
        (body["termination_a_type"], body["termination_b_type"], body["status"])
        == ("dcim.interface", "dcim.interface", "Connected")
        for body in bodies["dcim/cables/"]
    )
    assert bodies["extras/config-contexts/"] == [{**fixture["probes"], "is_active": False}]
    assert bodies["extras/git-repositories/"] == [
        {**fixture["repository"], "provided_contents": ["nautobot_golden_config.jinjatemplate"]}
    ]
    assert bodies["extras/graphql-queries/"] == [
        {"name": "fylgja-sotagg", "query": (FILES / seed.QUERY).read_text().strip()}
    ]

    [repository] = fake.rows("extras/git-repositories/")
    [query] = fake.rows("extras/graphql-queries/")
    setting = fake.held(SETTINGS, slug="default")
    group = fake.group()
    assert fake.sent("PATCH") == [
        (
            f"{SETTINGS}{setting['id']}/",
            {
                "jinja_repository": repository["id"],
                "jinja_path_template": "{{ obj.platform.network_driver }}.j2",
                "sot_agg_query": query["id"],
            },
        ),
        (f"{GROUPS}{group['id']}/", {"filter": {"tags": ["fylgja"]}}),
    ]
    assert sorted(group["members"]) == sorted(names)

    assert seed.differences(box, fixture) == []


def test_a_second_seed_sends_no_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake, git = FakeNautobot(), FakeGit()
    code, out, err = run(fake, capsys, tmp_path, git)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0] == f"made {seed.REPOSITORY} {git.main}"
    assert len(lines) == 1 + FOUND + len(ORDER)
    assert lines[1].startswith("found /api/ipam/namespaces/")
    assert all(line.startswith("made /api/") for line in lines[2 : 2 + len(ORDER)]), lines

    fake.requests.clear()
    git.calls.clear()
    code, out, err = run(fake, capsys, tmp_path, git)
    assert (code, err) == (0, "")
    assert fake.writes() == []
    assert "commit-tree" not in git.verbs() and "update-ref" not in git.verbs()
    lines = out.splitlines()
    assert lines[0] == f"found {seed.REPOSITORY}"
    assert len(lines) == 1 + FOUND + len(ORDER)
    assert all(line.startswith("found /api/") for line in lines[1:]), lines


def test_a_setting_a_query_a_repository_and_a_context_found_otherwise_are_written_again(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = seeded()
    fixture = held()
    setting = fake.held(SETTINGS, slug="default")
    setting["jinja_path_template"] = "other.j2"
    query = fake.held("extras/graphql-queries/", name="fylgja-sotagg")
    query["query"] = "query { other }"
    repository = fake.held("extras/git-repositories/", name="fylgja-templates")
    repository["remote_url"] = f"{ADDRESS}/other.git"
    repository["branch"] = "other"
    context = fake.held("extras/config-contexts/", name="fylgja-probes")
    context["is_active"] = True
    context["data"] = {**context["data"], "probes": []}

    code, _, err = run(fake, capsys, tmp_path)
    assert (code, err) == (0, "")
    assert fake.sent("POST") == [] and fake.sent("DELETE") == []
    assert fake.sent("PATCH") == [
        (f"extras/config-contexts/{context['id']}/", {"data": fixture["probes"]["data"], "is_active": False}),
        (
            f"extras/git-repositories/{repository['id']}/",
            {"remote_url": fixture["repository"]["remote_url"], "branch": "main"},
        ),
        (f"extras/graphql-queries/{query['id']}/", {"query": (FILES / seed.QUERY).read_text().strip()}),
        (f"{SETTINGS}{setting['id']}/", {"jinja_path_template": fixture["setting"]["path"]}),
    ]


def test_the_groups_members_are_refreshed_only_where_they_are_not_the_tagged_devices(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = seeded()
    group = fake.group()
    three = list(group["members"])
    group["members"] = three[:2]
    code, _, err = run(fake, capsys, tmp_path)
    assert (code, err) == (0, "")
    assert fake.sent("PATCH") == [(f"{GROUPS}{group['id']}/", {"filter": {"tags": ["fylgja"]}})]
    assert sorted(group["members"]) == sorted(three)
    assert fake.sent("POST") == [] and fake.sent("DELETE") == []

    fake.requests.clear()
    code, _, err = run(fake, capsys, tmp_path)
    assert (code, err) == (0, "")
    assert fake.writes() == []

    fake.requests.clear()
    group["members"] = three[:2]
    fake.stale.add(group["id"])
    code, _, err = run(fake, capsys, tmp_path)
    assert code == 1
    assert fake.sent("PATCH") == [(f"{GROUPS}{group['id']}/", {"filter": {"tags": ["fylgja"]}})]
    assert GROUP in err and "2 members" in err and "make nautobot-down PURGE=1" in err
    assert fake.sent("DELETE") == []
    assert not any(request.url.path == f"/api/{RENDER}" for request in fake.requests)


def test_a_nautobot_that_is_not_the_fixture_is_refused_naming_what_differs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = seeded()
    n1 = fake.held("dcim/devices/", name="n1")
    fake.add("dcim/devices/", {**{k: v for k, v in n1.items() if k != "id"}, "name": "n4"})
    a, b = fake.port("n1", "ethernet-1/1"), fake.port("n2", "ethernet-1/1")
    cable = fake.cable_of(a["id"])
    assert cable is not None
    del fake.objects["dcim/cables/"][cable["id"]]
    elsewhere = fake.port("n2", "ethernet-1/10")
    fake.add(
        "dcim/cables/",
        {
            "termination_a_type": "dcim.interface",
            "termination_a_id": a["id"],
            "termination_b_type": "dcim.interface",
            "termination_b_id": elsewhere["id"],
            "status": "Connected",
        },
    )
    namespace = fake.held("ipam/namespaces/", name="Global")["id"]
    address = fake.add("ipam/ip-addresses/", {"address": "192.0.2.1/24", "namespace": namespace, "type": "host"})
    port = fake.port("n1", "ethernet-1/2")
    fake.add("ipam/ip-address-to-interface/", {"ip_address": address["id"], "interface": port["id"]})

    code, _, err = run(fake, capsys, tmp_path)
    assert code == 1
    assert "the device n4 tagged fylgja, which the fixture does not" in err
    assert "no cable n1:ethernet-1/1 to n2:ethernet-1/1" in err
    assert "the cable n1:ethernet-1/1 to n2:ethernet-1/10, which the fixture does not" in err
    assert "the address 192.0.2.1/24 on n1 ethernet-1/2, which the fixture does not" in err
    assert err.splitlines()[-1].endswith("the seed deletes nothing: " + seed.PURGE)
    assert fake.sent("DELETE") == []
    assert [path for path, _ in fake.sent("POST")] == []
    assert b["id"] not in {path for path, _ in fake.sent("PATCH")}
    assert not any(request.url.path == f"/api/{RENDER}" for request in fake.requests)


def test_templates_are_committed_only_where_they_differ(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    served = tmp_path / "served"
    repository = served / seed.REPOSITORY
    git = FakeGit()
    first = seed.templates(git, served, FILES)
    assert git.calls[0] == ["init", "--bare", "--initial-branch=main", str(repository)]
    assert git.verbs() == [
        "init",
        "hash-object",
        "mktree",
        "for-each-ref",
        "commit-tree",
        "update-ref",
        "update-server-info",
    ]
    assert all(argv[argv.index("--git-dir") + 1] == str(repository) for argv in git.calls[1:])
    [hashed] = [argv for argv in git.calls if "hash-object" in argv]
    assert hashed[-2:] == ["-w", str(FILES / seed.TEMPLATES / "nokia_srl.j2")]
    [made] = [argv for argv in git.calls if "update-ref" in argv]
    assert made[-2:] == ["refs/heads/main", first]
    assert first is not None and git.main == first

    git.calls.clear()
    assert seed.templates(git, served, FILES) is None
    assert git.verbs() == ["hash-object", "mktree", "for-each-ref"]

    other = tmp_path / "other"
    shutil.copytree(FILES / seed.TEMPLATES, other / seed.TEMPLATES)
    template = other / seed.TEMPLATES / "nokia_srl.j2"
    template.write_text(template.read_text() + "# another line\n")
    git.calls.clear()
    second = seed.templates(git, served, other)
    assert git.verbs() == ["hash-object", "mktree", "for-each-ref", "commit-tree", "update-ref", "update-server-info"]
    [committed] = [argv for argv in git.calls if "commit-tree" in argv]
    assert committed[committed.index("-p") + 1] == first
    assert second is not None and second != first and git.main == second

    fake = FakeNautobot()
    code, out, err = run(fake, capsys, served, FakeGit(failing="mktree"))
    assert code == 1
    assert f"git --git-dir {repository} mktree exited 128: fatal: refused by the test" in err
    assert "make nautobot-down PURGE=1" in err
    assert out == ""
    assert fake.requests == []


def test_the_seed_renders_each_device_last_and_holds_it_to_the_fixture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeNautobot()
    code, _, err = run(fake, capsys, tmp_path)
    assert (code, err) == (0, "")
    devices = {row["id"]: row["name"] for row in fake.rows("dcim/devices/")}
    rendered = [
        (index, devices[request.url.params["device_id"]])
        for index, request in enumerate(fake.requests)
        if request.url.path == f"/api/{RENDER}"
    ]
    assert [name for _, name in rendered] == ["n1", "n2", "n3"]
    last = max(index for index, request in enumerate(fake.requests) if request.method != "GET")
    assert all(index > last for index, _ in rendered)
    assert [index for index, _ in rendered] == list(range(len(fake.requests) - 3, len(fake.requests)))

    fake.requests.clear()
    configuration = seed.configurations()
    fake.rendered["n1"] = "\n".join(["# n1: another first line", *configuration["n1"].split("\n")[1:]])
    lines = configuration["n2"].split("\n")
    assert lines[4] == "set / interface ethernet-1/1 description \"to n1 ethernet-1/1\""
    fake.rendered["n2"] = "\n".join([*lines[:4], *lines[5:]])
    code, _, err = run(fake, capsys, tmp_path)
    assert code == 1
    said = err.splitlines()
    assert not any(line.startswith("seed: the render of n1") for line in said), said
    [differs] = [line for line in said if "render" in line]
    assert differs.startswith("seed: the render of n2 differs from three-node.json's configuration at its line 5:")
    assert said[-1].endswith("the seed deletes nothing: " + seed.PURGE)
    renders = [request for request in fake.requests if request.url.path == f"/api/{RENDER}"]
    assert [devices[request.url.params["device_id"]] for request in renders] == ["n1", "n2", "n3"]


@pytest.mark.parametrize("name", [ADDRESS_NAME, TOKEN_NAME])
def test_a_variable_not_set_is_exit_2_naming_it(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(name)
    fake, git = FakeNautobot(), FakeGit()
    code, out, err = run(fake, capsys, tmp_path, git)
    assert code == 2
    assert name in err and out == ""
    assert fake.requests == [] and git.calls == []


def test_a_command_line_not_understood_is_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake, git = FakeNautobot(), FakeGit()
    transport = httpx.MockTransport(fake)
    assert seed.main([], transport=transport, git=git) == 2
    assert seed.main(["--files", str(FILES)], transport=transport, git=git) == 2
    assert seed.main(["--files", str(FILES), "--git", str(tmp_path), "--other"], transport=transport, git=git) == 2
    capsys.readouterr()
    assert fake.requests == [] and git.calls == []


def test_nothing_the_seed_prints_holds_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(TOKEN_NAME, SECRET)
    fake = FakeNautobot()
    fake.refused[3] = 403
    code, out, err = run(fake, capsys, tmp_path)
    assert code == 1
    third = fake.requests[2]
    assert third.url.path in err and "403" in err
    assert "make nautobot-down PURGE=1" in err
    assert not holds_part(out) and not holds_part(err)


def test_untagged_objects_about_the_fixture_are_no_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Plan 2's tier leaves untagged contract objects about: an untagged device, an address on its port and a cable
    between untagged devices are not the fixture's to refuse, so the seed exits 0 and writes nothing."""
    fake, git = FakeNautobot(), FakeGit()
    assert run(fake, capsys, tmp_path, git)[0] == 0
    n1 = fake.held("dcim/devices/", name="n1")
    base = {k: v for k, v in n1.items() if k not in ("id", "tags")}
    first = fake.add("dcim/devices/", {**base, "name": "x1"})
    second = fake.add("dcim/devices/", {**base, "name": "x2"})
    template = {k: v for k, v in fake.port("n1", "ethernet-1/1").items() if k != "id"}
    ports = [
        fake.add("dcim/interfaces/", {**template, "device": device["id"], "name": name})
        for device in (first, second)
        for name in ("ethernet-1/1", "ethernet-1/2")
    ]
    namespace = fake.held("ipam/namespaces/", name="Global")["id"]
    address = fake.add("ipam/ip-addresses/", {"address": "192.0.2.77/24", "namespace": namespace, "type": "host"})
    fake.add("ipam/ip-address-to-interface/", {"ip_address": address["id"], "interface": ports[1]["id"]})
    fake.add(
        "dcim/cables/",
        {
            "termination_a_type": "dcim.interface",
            "termination_a_id": ports[0]["id"],
            "termination_b_type": "dcim.interface",
            "termination_b_id": ports[2]["id"],
            "status": "Connected",
        },
    )
    fake.requests.clear()
    git.calls.clear()
    code, _out, err = run(fake, capsys, tmp_path, git)
    assert (code, err) == (0, "")
    assert fake.writes() == []
    assert "commit-tree" not in git.verbs() and "update-ref" not in git.verbs()
