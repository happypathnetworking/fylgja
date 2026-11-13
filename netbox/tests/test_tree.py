"""What `netbox/` holds, read as files; and the names and addresses it and `scripts/netbox_dev.py` hold."""

from __future__ import annotations

import ast
import re
import subprocess
from collections.abc import Iterator
from ipaddress import ip_address, ip_network
from pathlib import Path

import account
import box
import netbox_dev
import yaml

NETBOX = Path(__file__).resolve().parent.parent
ROOT = NETBOX.parent
DEV = NETBOX / "dev"
HERE = Path(__file__).resolve().relative_to(ROOT).as_posix()
"""This file, which names the ranges below by their addresses."""
FIXTURE = "netbox/seed/main.yaml"
"""The fixture network on `main`, the one file under `netbox/` whose own addresses are the fixture's."""

ALLOWED = (ip_network("127.0.0.0/8"), ip_network("192.0.2.0/24"), ip_network("198.51.100.0/24"))
"""The IPv4 addresses `netbox/` may hold: loopback, the documentation range the tests use, and the documentation range
the override gives the project's network."""

URL = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<authority>[A-Za-z0-9\[][^\s/?#\"'`<>()]*)(?P<path>/[^\s?#\"'`<>()]*)?"
)
"""A URL with a host after its scheme, as `infrahub/tests/test_tree.py` reads one, written again here."""

QUAD = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?:/\d{1,2})?(?!\w)(?!\.\d)")
"""A dotted quad standing alone, with its prefix length where it has one, as `infrahub/tests/test_tree.py` reads
one."""

NAMES = (
    "FYLGJA_NETBOX_SUPERUSER_PASSWORD",
    "FYLGJA_NETBOX_SECRET_KEY",
    "FYLGJA_NETBOX_API_TOKEN_PEPPER",
    "FYLGJA_NETBOX_ADDRESS",
    "FYLGJA_NETBOX_WRITE_TOKEN",
    "FYLGJA_NETBOX_TOKEN",
)
"""The development NetBox's names in `.env.example`, in its NetBox block; the seventh is the example's."""

EXAMPLES = "FYLGJA_ORCHESTRATOR_NETBOX_TOKEN"

IMAGE = "fylgja-core-netbox:${FYLGJA_NETBOX_VERSION:?}-${FYLGJA_NETBOX_BRANCHING_VERSION:?}"
PLUGINS = "${FYLGJA_NETBOX_DEV:?}/plugins.py:/etc/netbox/config/plugins.py:ro"
HOSTS = ["host.docker.internal:host-gateway"]
KEYS = {
    "SECRET_KEY": "${FYLGJA_NETBOX_SECRET_KEY:?}",
    "API_TOKEN_PEPPER_1": "${FYLGJA_NETBOX_API_TOKEN_PEPPER:?}",
}

DATABASE = {
    "NAME": "DB_NAME",
    "USER": "DB_USER",
    "PASSWORD": "DB_PASSWORD",
    "HOST": "DB_HOST",
    "PORT": "DB_PORT",
    "CONN_MAX_AGE": "DB_CONN_MAX_AGE",
}
"""Each of `DATABASES["default"]`'s keys, and the variable netbox-docker's `configuration.py` reads it from."""


def tracked() -> list[str]:
    """The tree's tracked files, by their paths from its root, as a clone holds them (`git ls-files`)."""
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [path for path in listed.decode().split("\0") if path]


def lines(path: str) -> Iterator[tuple[int, str]]:
    try:
        yield from enumerate((ROOT / path).read_text().splitlines(), 1)
    except UnicodeDecodeError:
        return


def test_the_override_is_the_two_services_and_no_value() -> None:
    """The plugin's image, built from `netbox/dev/` at the three versions, for both services; NetBox on loopback; the
    plugin's configuration mounted over the release's; the secrets from `local/.env` alone; and the project's network
    on the subnet `scripts/netbox_dev.py` judges it by."""
    override = yaml.safe_load((DEV / "compose.override.yml").read_text())
    assert override == {
        "services": {
            "netbox": {
                "image": IMAGE,
                "pull_policy": "never",
                "build": {
                    "context": "${FYLGJA_NETBOX_DEV:?}",
                    "args": {
                        "NETBOX_VERSION": "${FYLGJA_NETBOX_VERSION:?}",
                        "NETBOX_DOCKER_VERSION": "${FYLGJA_NETBOX_DOCKER_VERSION:?}",
                        "NETBOX_BRANCHING_VERSION": "${FYLGJA_NETBOX_BRANCHING_VERSION:?}",
                    },
                },
                "ports": ["127.0.0.1:8800:8080"],
                "volumes": [PLUGINS],
                "extra_hosts": HOSTS,
                "environment": {
                    "SKIP_SUPERUSER": "false",
                    "SUPERUSER_NAME": "admin",
                    "SUPERUSER_EMAIL": "admin@fylgja.example",
                    "SUPERUSER_PASSWORD": "${FYLGJA_NETBOX_SUPERUSER_PASSWORD:?}",
                    **KEYS,
                },
            },
            "netbox-worker": {
                "image": IMAGE,
                "pull_policy": "never",
                "volumes": [PLUGINS],
                "extra_hosts": HOSTS,
                "environment": KEYS,
            },
        },
        "networks": {"default": {"ipam": {"config": [{"subnet": netbox_dev.SUBNET}]}}},
    }


def test_the_dockerfile_adds_one_layer_at_the_versions_it_is_given() -> None:
    """No default: a build not given the three versions fails."""
    text = (DEV / "Dockerfile").read_text()
    held = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert held == [
        "ARG NETBOX_VERSION",
        "ARG NETBOX_DOCKER_VERSION",
        "FROM docker.io/netboxcommunity/netbox:v${NETBOX_VERSION}-${NETBOX_DOCKER_VERSION}",
        "ARG NETBOX_BRANCHING_VERSION",
        "RUN uv pip install --python /opt/netbox/venv/bin/python "
        "netboxlabs-netbox-branching==${NETBOX_BRANCHING_VERSION}",
    ]
    assert re.search(r"\d\.\d", text) is None


def literal(node: ast.expr) -> object:
    return ast.literal_eval(node)


def is_get(call: ast.Call) -> bool:
    """Whether `call` is `environ.get(…)`."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and isinstance(func.value, ast.Name)
        and func.value.id == "environ"
    )


def ipv4(found: str) -> bool:
    try:
        return ip_address(found).version == 4
    except ValueError:
        return False


def test_the_plugins_configuration_assigns_four_settings_and_holds_no_value() -> None:
    """Parsed, never imported: it runs in NetBox alone."""
    tree = ast.parse((DEV / "plugins.py").read_text())
    assigned = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert sorted(assigned) == ["DATABASES", "DATABASE_ROUTERS", "EVENTS_PIPELINE", "PLUGINS"]
    assert literal(assigned["PLUGINS"]) == ["netbox_branching"]
    assert literal(assigned["DATABASE_ROUTERS"]) == ["netbox_branching.database.BranchAwareRouter"]
    assert literal(assigned["EVENTS_PIPELINE"]) == [
        "netbox_branching.events.add_branch_context",
        "extras.events.process_event_queue",
    ]

    databases = assigned["DATABASES"]
    assert isinstance(databases, ast.Call) and isinstance(databases.func, ast.Name)
    assert databases.func.id == "DynamicSchemaDict"
    [outer] = databases.args
    assert isinstance(outer, ast.Dict) and [literal(key) for key in outer.keys if key] == ["default"]
    [default] = outer.values
    assert isinstance(default, ast.Dict)
    read: dict[str, str] = {}
    for key, value in zip(default.keys, default.values, strict=True):
        assert key is not None
        [got] = [node for node in ast.walk(value) if isinstance(node, ast.Call) and is_get(node)]
        read[str(literal(key))] = str(literal(got.args[0]))
    assert read == DATABASE

    gets = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and is_get(node)]
    assert sorted(str(literal(node.args[0])) for node in gets) == sorted(DATABASE.values())
    [password] = [node for node in gets if literal(node.args[0]) == "DB_PASSWORD"]
    assert [literal(arg) for arg in password.args[1:]] == [""]


def test_netbox_names_no_host_and_the_script_two_addresses() -> None:
    """No tracked file under `netbox/` holds a URL with a host, and none but this one an IPv4 address outside loopback,
    the documentation range and the fixture's own: `netbox/seed/main.yaml`'s six, `10.<d>.10.1` and `10.<d>.11.1`,
    and its probe's two hosts, which `netbox/` may hold as `infrahub/` holds its seed's;
    `scripts/netbox_dev.py` holds two URLs, the release's and the address."""
    paths = tracked()
    assert HERE in paths
    assert FIXTURE in paths
    netbox = [path for path in paths if path.startswith("netbox/")]
    assert [(path, number) for path in netbox for number, line in lines(path) if URL.search(line)] == []
    seeded = {quad[1] for _, line in lines(FIXTURE) for quad in QUAD.finditer(line) if ipv4(quad[1])}
    probe = ["10.1.10.2", "10.1.11.2"]
    assert sorted(seeded) == sorted([*(f"10.{d}.{port}.1" for d in (1, 2, 3) for port in (10, 11)), *probe])
    found = [
        (path, number, quad[1])
        for path in netbox
        if path != HERE
        for number, line in lines(path)
        for quad in QUAD.finditer(line)
        if ipv4(quad[1])
        and not any(ip_address(quad[1]) in network for network in ALLOWED)
        and quad[1] not in seeded
    ]
    assert found == []

    release = URL.search(netbox_dev.RELEASE_URL)
    assert release is not None
    script = (ROOT / "scripts" / "netbox_dev.py").read_text()
    assert [hit[0] for hit in URL.finditer(script)] == [release[0], netbox_dev.ADDRESS]


def test_the_names_the_tasks_share_are_one() -> None:
    """`make netbox-up` writes the address and the write token, which `box.py` reads, and `account.py` the two
    accounts' tokens: each name is written where it is read, and the seven listed here are those."""
    assert (netbox_dev.NAMES[3], netbox_dev.WRITE_TOKEN) == (box.ADDRESS, box.TOKEN)
    assert (*NAMES, EXAMPLES) == (*netbox_dev.NAMES, netbox_dev.WRITE_TOKEN, *account.LINES.values())


def test_the_env_example_lists_each_name_commented() -> None:
    """Six in the development NetBox's block, after Infrahub's, and the example's own in the example's block."""
    held = (ROOT / ".env.example").read_text().splitlines()
    at = {line: number for number, line in enumerate(held)}
    for name in (*NAMES, EXAMPLES):
        assert f"# {name}=" in at, name
    places = [at[f"# {name}="] for name in NAMES]
    assert places == sorted(places)
    assert at["# FYLGJA_INFRAHUB_CA="] < places[0] and places[-1] < at["# FYLGJA_ORCHESTRATOR_AUTH="]
    assert at[f"# {EXAMPLES}="] > at["# FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN="]
