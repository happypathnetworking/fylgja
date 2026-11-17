"""What `infrahub/` holds, read as files; and the names and addresses the tree holds."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterator
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

import infrahub_dev
import yaml

INFRAHUB = Path(__file__).resolve().parent.parent
ROOT = INFRAHUB.parent
HERE = Path(__file__).resolve().relative_to(ROOT).as_posix()
"""This file, which names the ranges and the exceptions below by their addresses."""

DOCUMENTATION = tuple(
    ip_network(network) for network in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
)
LOOPBACK = (ip_network("127.0.0.0/8"), ip_network("::1/128"))

FIXTURES = ("testdata/", "infrahub/seed/main/", "netbox/seed/main.yaml")
"""The fixtures, whose addresses are the design's fixture's own, 10.x (testdata/blueprint/three-node.json): the
blueprints, and the network each development source of truth's seed puts on its `main`."""

QUOTING = ("formats/",)
"""Where the fixtures' addresses may be quoted besides the documents (`*.md`): the formats' examples. Every other held
file, source code among them, holds none of them."""

VENDORED = ("infrahub/schema/dcim/",)
"""The schema library as OpsMill wrote it, at its commit and never edited."""

REFERENCES = {
    "github.com": "the formats' ids and their problem types, under the organisation the ids name, and `CITED`",
    "json-schema.org": "the dialect each format's schema names",
    "www.apache.org": "the licence's own text",
    "infrahub.opsmill.io": "Infrahub's published Compose file, fetched by scripts/infrahub_dev.py",
    "containerlab.dev": "containerlab's documentation, cited",
    "ghcr.io": "the registry a public image is pulled from",
    "test.pypi.org": "TestPyPI's upload address, where the publish workflow uploads a candidate's wheels",
}
"""Hosts the tree names as public references, none of them a site's."""

CITED = {
    "opsmill/infrahub": "Infrahub's repository, cited by README.md",
    "clabernetes/clabernetes": "clabernetes' repository, cited by README.md",
    "netbox-community/netbox-docker": "netbox-docker's release, fetched by scripts/netbox_dev.py",
}
"""Repositories on github.com the tree cites outside the organisation the formats' ids name."""

LOCKED = {"uv.lock": ("pypi.org", "files.pythonhosted.org")}
"""The hosts a file alone may name, each file by its path: the lock's index and its files (D-108). A lock written
through a site's mirror names that site's host, and fails."""

NOT_HOSTS = {
    ("s3", "fylgja"): "the S3 bucket an `s3` URL names in the place of a host, its endpoint given apart",
    ("http", "versity"): "the deploy base's own Service, named in its namespace",
    ("scheme", "host"): "the placeholder of the form of an address a docstring of the core's configuration gives",
    ("http", "host.docker.internal"): (
        "the name Compose's `host-gateway` gives the development host inside a container, where `make prefect-up` "
        "serves the edge's Prefect"
    ),
}
"""Names in a URL's place of a host that name no host of a site's, each under the one scheme it is written with."""

NOT_A_SITES = {
    "0.0.0.0": "every address: a listener on all interfaces, and the whole IPv4 space of a policy",
    "1.37.0.8": "lightkube-models' version",
    "172.20.0.0": "the local driver's default pool of lab subnets (core/src/fylgja_core/containerlab/pool.py)",
    "172.20.1.0": "the subnet the golden deployments are rendered with, from that pool (scripts/render-goldens.py)",
    "172.20.20.3": "a management address containerlab gave on its own default network, as read",
    "10.244.0.0": "the example network of FYLGJA_POD_CIDR's documentation (.env.example, CONTRIBUTING.md)",
}
"""Dotted quads the tree holds that are no address of a site's: product defaults, every address, a version."""

URL = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<authority>[A-Za-z0-9\[][^\s/?#\"'`<>()]*)(?P<path>/[^\s?#\"'`<>()]*)?"
)
"""A URL with a host after its scheme: a letter, a digit or `[`, and its path where it has one. A scheme joined to a
variable or a placeholder in code or prose (`{`, `<`) names no host."""

QUAD = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?:/\d{1,2})?(?!\w)(?!\.\d)")
"""A dotted quad standing alone, with its prefix length where it has one."""


class Url(NamedTuple):
    """What a URL names: its scheme, lower-cased, its host and its path."""

    scheme: str
    host: str
    path: str


def tracked() -> list[str]:
    """The tree's tracked files, by their paths from its root, as a clone holds them (`git ls-files`)."""
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [path for path in listed.decode().split("\0") if path]


def text(path: str) -> str | None:
    try:
        return (ROOT / path).read_text()
    except UnicodeDecodeError:
        return None


def host(authority: str) -> str:
    """The host of a URL's authority, without its user, its port or an IPv6 address's brackets."""
    after = authority.rsplit("@", 1)[-1]
    if after.startswith("["):
        return after[1:].split("]", 1)[0]
    found = re.match(r"[A-Za-z0-9._~%-]*", after)
    return found[0].rstrip(".") if found else ""


def among(found: str, networks: tuple[IPv4Network | IPv6Network, ...]) -> bool:
    """Whether `found`, an address, lies in one of `networks`; a text that is no address does not."""
    try:
        address = ip_address(found)
    except ValueError:
        return False
    return any(address in network for network in networks)


def ipv4(found: str) -> bool:
    try:
        return ip_address(found).version == 4
    except ValueError:
        return False


def addresses(paths: list[str]) -> Iterator[tuple[str, int, str]]:
    """Each dotted quad of `paths` that is an IPv4 address, with its path and its line."""
    for path in paths:
        for number, line in enumerate((text(path) or "").splitlines(), 1):
            for found in QUAD.finditer(line):
                if ipv4(found[1]):
                    yield path, number, found[1]


def urls(paths: list[str]) -> Iterator[tuple[str, int, Url]]:
    """Each URL of `paths` that has a host, with its file's path and its line."""
    for path in paths:
        for number, line in enumerate((text(path) or "").splitlines(), 1):
            for found in URL.finditer(line):
                yield path, number, Url(found["scheme"].lower(), host(found["authority"]), found["path"] or "")


def public(path: str, found: Url) -> bool:
    """Whether a URL of the file `path` names loopback, a `*.example` name, a documentation range, a public reference,
    a name that is no host, or a host `LOCKED` lists for that path."""
    return (
        found.host == "localhost"
        or found.host.endswith(".example")
        or among(found.host, DOCUMENTATION + LOOPBACK)
        or found.host in REFERENCES
        or (found.scheme, found.host) in NOT_HOSTS
        or found.host in LOCKED.get(path, ())
    )


def organisations() -> set[str]:
    """The github.com organisations the formats' ids name (each `formats/*.schema.json`'s `$id`)."""
    found = set()
    for schema in sorted((ROOT / "formats").glob("*.schema.json")):
        named = urlsplit(json.loads(schema.read_text())["$id"])
        assert named.hostname == "github.com", schema.name
        found.add(named.path.split("/")[1])
    return found


def on_github(path: str, ours: set[str]) -> bool:
    """Whether a github.com URL's `path` is under one of `ours`, the formats' organisations, or a repository of
    `CITED`."""
    parts = path.split("/")[1:]
    return bool(parts) and (parts[0] in ours or "/".join(parts[:2]) in CITED)


class Replaced(NamedTuple):
    """A list under Compose's own tag `!override`, which replaces the published file's list where an untagged one
    would be added to it (design/verified-facts.md, "Docker Compose v5.6.0")."""

    items: list[str]


class Override(yaml.SafeLoader):
    """YAML as Compose reads an override: `!override` on a list, and no other tag of Compose's."""


def replaced(loader: Override, node: yaml.SequenceNode) -> Replaced:
    return Replaced(loader.construct_sequence(node))


Override.add_constructor("!override", replaced)


def test_the_override_holds_no_value_and_no_host() -> None:
    """The Compose override is two read-only mounts, their sources set by `infrahub_dev.py`, the edge's Prefect's
    address and basic auth with the host's name they reach it by, Neo4j's cap, its health check's start period,
    and every port the published file publishes, each bound to loopback in place of every interface: the
    server's, the message queue's metrics, and the database's metrics and backup."""
    override = yaml.load((INFRAHUB / "dev" / "compose.override.yml").read_text(), Loader=Override)
    assert override == {
        "services": {
            "infrahub-server": {"ports": Replaced(["127.0.0.1:8000:8000"])},
            "message-queue": {"ports": Replaced(["127.0.0.1:15692:15692"])},
            "task-worker": {
                "volumes": [
                    "${FYLGJA_INFRAHUB_REPO:?}:/srv/fylgja:ro",
                    "${FYLGJA_INFRAHUB_REPOS:?}:/srv/fylgja-repos:ro",
                ],
                "extra_hosts": ["host.docker.internal:host-gateway"],
                "environment": {
                    "FYLGJA_ORCHESTRATOR_ADDRESS": "host.docker.internal:4200",
                    "FYLGJA_ORCHESTRATOR_AUTH": "${FYLGJA_ORCHESTRATOR_AUTH:-}",
                },
            },
            "database": {
                "ports": Replaced(["127.0.0.1:2004:2004", "127.0.0.1:6362:6362"]),
                "environment": {
                    "NEO4J_server_memory_heap_initial__size": "1g",
                    "NEO4J_server_memory_heap_max__size": "2g",
                    "NEO4J_server_memory_pagecache_size": "1g",
                },
                "healthcheck": {"start_period": "180s"},
            },
        },
    }


NEO4J_SLOWEST_START_S = 53.8
"""The slowest start of the development database read on kept volumes, from its container's start to Neo4j's
`Started.`, under Infrahub 1.11.11: 51.6 s on 2026-11-13; 53.8 s, 27.7 s and 26.1 s from stopped on 2026-11-16, the
first of them after 47 hours stopped (design/verified-facts.md, "Infrahub 1.11.11")."""


def test_the_databases_health_check_waits_for_a_start_on_kept_volumes() -> None:
    """Infrahub's published check probes every 2 s, 20 retries after a 3 s start period, and called the database
    unhealthy 43.9 s into the start of 53.8 s, which `make infrahub-up` then failed twice. The override's start period,
    180 s, is about 3.3 times that slowest start, and is there to tell a database still starting from one that will
    not. It sets the period alone: the probe, its interval and its retries stay the published file's."""
    override = yaml.load((INFRAHUB / "dev" / "compose.override.yml").read_text(), Loader=Override)
    assert override["services"]["database"]["healthcheck"] == {"start_period": "180s"}
    start_period_s = float(override["services"]["database"]["healthcheck"]["start_period"].removesuffix("s"))
    assert start_period_s >= 3 * NEO4J_SLOWEST_START_S


def test_pypi_is_a_public_reference_in_the_lock_alone() -> None:
    """The lock names PyPI's index and its files' host (D-108); no other file may, and a lock written through another
    index names that index's host and is no reference."""
    assert public("uv.lock", Url("https", "files.pythonhosted.org", "/packages/a.whl"))
    assert public("uv.lock", Url("https", "pypi.org", "/simple"))
    assert not public("uv.lock", Url("https", "mirror.corp.invalid", "/simple"))
    assert not public("README.md", Url("https", "pypi.org", "/simple"))


def test_the_tree_names_no_address() -> None:
    """The tree holds no host name, address or value of a site (CONTRIBUTING.md): outside its test directories, a URL
    names loopback, a `*.example` name, a documentation range or a public reference, and a bare address is in loopback
    or a documentation range; the fixtures alone hold their own, and the documents (`*.md`) and the formats may quote
    them, source code never; the fixtures are `testdata/` and the Infrahub and NetBox seeds' networks on `main`. A URL
    on github.com names the organisation the formats' ids name, or a repository cited.
    `infrahub/` holds no URL with a host at all, and no address but the documentation range's, loopback in the Compose
    override alone, where the published ports are bound, and, in the fixture's object files, the fixture's six and its
    probe's two hosts. `scripts/infrahub_dev.py` holds the tree's two addresses for the development Infrahub."""
    paths = tracked()
    assert HERE in paths
    held = [path for path in paths if "tests" not in Path(path).parts and not path.startswith(FIXTURES + VENDORED)]
    fixtures = {found for _, _, found in addresses([path for path in paths if path.startswith(FIXTURES)])}

    named = [
        (path, number, found)
        for path, number, found in urls(held)
        if not public(path, found)
    ]
    assert named == []
    ours = organisations()
    github = [
        (path, number, found.path)
        for path, number, found in urls(held)
        if found.host == "github.com" and not on_github(found.path, ours)
    ]
    assert github == []
    bare = [
        (path, number, found)
        for path, number, found in addresses(held)
        if not (
            among(found, DOCUMENTATION + LOOPBACK)
            or found in NOT_A_SITES
            or (found in fixtures and (path.endswith(".md") or path.startswith(QUOTING)))
        )
    ]
    assert bare == []

    infrahub = [path for path in paths if path.startswith("infrahub/") and not path.startswith(VENDORED)]
    infrahub.remove(HERE)
    assert [*urls([*infrahub, HERE, ".infrahub.yml"])] == []
    seeded = {found for path, _, found in addresses(infrahub) if path.startswith("infrahub/seed/main/")}
    probe = ["10.1.10.2", "10.1.11.2"]
    assert sorted(seeded) == sorted([*(f"10.{d}.{port}.1" for d in (1, 2, 3) for port in (10, 11)), *probe])
    documentation = (ip_network("192.0.2.0/24"),)
    override = "infrahub/dev/compose.override.yml"
    bound = [hit for hit in addresses(infrahub) if among(hit[2], LOOPBACK)]
    assert {path for path, _, _ in bound} == {override}
    rest = [hit for hit in addresses(infrahub) if hit not in bound]
    assert [hit for hit in rest if not among(hit[2], documentation) and hit[2] not in seeded] == []

    compose = URL.search(infrahub_dev.COMPOSE_URL)
    assert compose is not None
    script = (ROOT / "scripts" / "infrahub_dev.py").read_text()
    assert [found[0] for found in URL.finditer(script)] == [compose[0], infrahub_dev.ADDRESS]
