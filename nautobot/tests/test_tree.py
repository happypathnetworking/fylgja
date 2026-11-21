"""What `nautobot/` holds, read as files; and the names and addresses it and `scripts/nautobot_dev.py` hold."""

from __future__ import annotations

import ast
import re
import subprocess
import tomllib
from collections.abc import Iterator
from ipaddress import ip_address, ip_network
from pathlib import Path

import nautobot_dev
import yaml

NAUTOBOT = Path(__file__).resolve().parent.parent
ROOT = NAUTOBOT.parent
DEV = NAUTOBOT / "dev"
HERE = Path(__file__).resolve().relative_to(ROOT).as_posix()
"""This file, which names the ranges below by their addresses."""
FIXTURE = "nautobot/seed/main.yaml"
"""The fixture network, the one file under `nautobot/` that holds the fixture's addresses and the repository's
remote."""

ALLOWED = (ip_network("127.0.0.0/8"), ip_network("192.0.2.0/24"), ip_network("203.0.113.0/24"))
"""The IPv4 addresses `nautobot/` may hold: loopback, the documentation range the tests use, and the documentation
range the Compose file gives the project's network."""

URL = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<authority>[A-Za-z0-9\[][^\s/?#\"'`<>()]*)(?P<path>/[^\s?#\"'`<>()]*)?"
)
"""A URL with a host after its scheme, as `infrahub/tests/test_tree.py` reads one, written again here."""

QUAD = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?:/\d{1,2})?(?!\w)(?!\.\d)")
"""A dotted quad standing alone, with its prefix length where it has one, as `infrahub/tests/test_tree.py` reads
one."""

NAMES = (
    "FYLGJA_NAUTOBOT_SECRET_KEY",
    "FYLGJA_NAUTOBOT_DB_PASSWORD",
    "FYLGJA_NAUTOBOT_SUPERUSER_PASSWORD",
    "FYLGJA_NAUTOBOT_WRITE_TOKEN",
    "FYLGJA_NAUTOBOT_ADDRESS",
    "FYLGJA_NAUTOBOT_TOKEN",
)
"""The development Nautobot's names in `.env.example`, in its Nautobot block; the sixth is `make nautobot-seed`'s."""

IMAGE = (
    "fylgja-core-nautobot:${FYLGJA_NAUTOBOT_VERSION:?}-${FYLGJA_GOLDEN_CONFIG_VERSION:?}-py${FYLGJA_NAUTOBOT_PYTHON:?}"
)
CONFIG = "/opt/nautobot/nautobot_config.py"
DIGEST = re.compile(r"[a-z0-9.-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}")


def tracked() -> list[str]:
    """The tree's tracked files, by their paths from its root, as a clone holds them (`git ls-files`)."""
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [path for path in listed.decode().split("\0") if path]


def lines(path: str) -> Iterator[tuple[int, str]]:
    try:
        yield from enumerate((ROOT / path).read_text().splitlines(), 1)
    except UnicodeDecodeError:
        return


def pin(image: object) -> str:
    assert isinstance(image, str) and DIGEST.fullmatch(image), image
    return image


def root_dockerfile() -> list[str]:
    return (ROOT / "Dockerfile").read_text().splitlines()


def test_compose_is_the_five_services_and_no_value() -> None:
    """The image built from `nautobot/dev/` at the three versions, for both of its services, no check of Docker's
    on either; Nautobot on loopback alone; the configuration mounted over the image's; the secrets from `local/.env`
    alone; the pins by digest; and the project's network on the subnet `scripts/nautobot_dev.py` names."""
    compose = yaml.safe_load((DEV / "compose.yml").read_text())
    secrets = {
        "NAUTOBOT_DB_PASSWORD": "${FYLGJA_NAUTOBOT_DB_PASSWORD:?}",
        "NAUTOBOT_SECRET_KEY": "${FYLGJA_NAUTOBOT_SECRET_KEY:?}",
    }
    shared = {
        "NAUTOBOT_CONFIG": CONFIG,
        "NAUTOBOT_DB_HOST": "db",
        "NAUTOBOT_DB_NAME": "nautobot",
        "NAUTOBOT_DB_USER": "nautobot",
        "NAUTOBOT_REDIS_HOST": "redis",
        **secrets,
    }
    common = {
        "image": IMAGE,
        "pull_policy": "never",
        "depends_on": ["db", "redis"],
        "volumes": [f"${{FYLGJA_NAUTOBOT_DEV:?}}/nautobot_config.py:{CONFIG}:ro"],
        "healthcheck": {"disable": True},
    }
    services = compose["services"]
    git = services["git"]
    assert compose == {
        "x-nautobot": {**{k: v for k, v in common.items() if k != "healthcheck"}, "environment": shared},
        "services": {
            "nautobot": {
                **common,
                "build": {
                    "context": "${FYLGJA_NAUTOBOT_DEV:?}",
                    "args": {
                        "NAUTOBOT_VERSION": "${FYLGJA_NAUTOBOT_VERSION:?}",
                        "NAUTOBOT_PYTHON": "${FYLGJA_NAUTOBOT_PYTHON:?}",
                        "GOLDEN_CONFIG_VERSION": "${FYLGJA_GOLDEN_CONFIG_VERSION:?}",
                    },
                },
                "ports": ["127.0.0.1:8810:8080"],
                "environment": {
                    **shared,
                    "NAUTOBOT_CREATE_SUPERUSER": "true",
                    "NAUTOBOT_SUPERUSER_NAME": "admin",
                    "NAUTOBOT_SUPERUSER_EMAIL": "admin@fylgja.example",
                    "NAUTOBOT_SUPERUSER_PASSWORD": "${FYLGJA_NAUTOBOT_SUPERUSER_PASSWORD:?}",
                    "NAUTOBOT_SUPERUSER_API_TOKEN": "${FYLGJA_NAUTOBOT_WRITE_TOKEN:?}",
                },
            },
            "worker": {
                **common,
                "entrypoint": ["nautobot-server", "celery", "worker"],
                "environment": shared,
            },
            "db": {
                "image": services["db"]["image"],
                "environment": {
                    "POSTGRES_DB": "nautobot",
                    "POSTGRES_USER": "nautobot",
                    "POSTGRES_PASSWORD": "${FYLGJA_NAUTOBOT_DB_PASSWORD:?}",
                },
                "volumes": ["db:/var/lib/postgresql/data"],
            },
            "redis": {"image": services["redis"]["image"]},
            "git": {
                "image": git["image"],
                "init": True,
                "command": ["python", "-m", "http.server", "8000", "--directory", "/srv/git"],
                "volumes": ["${FYLGJA_NAUTOBOT_GIT:?}:/srv/git:ro"],
                "networks": {"default": {"aliases": ["templates.fylgja.example"]}},
            },
        },
        "volumes": {"db": {}},
        "networks": {"default": {"ipam": {"config": [{"subnet": nautobot_dev.SUBNET}]}}},
    }
    assert [name for name, service in services.items() if "ports" in service] == ["nautobot"]
    assert services["nautobot"]["ports"][0].startswith("127.0.0.1:")
    for name in ("db", "redis"):
        assert pin(services[name]["image"]).startswith({"db": "postgres:", "redis": "redis:"}[name])
    from_lines = {line.split()[1] for line in root_dockerfile() if line.startswith("FROM ")}
    assert from_lines == {git["image"]}, "the git service's image is the root Dockerfile's FROM"
    pin(git["image"])


def test_the_dockerfile_is_one_layer_by_uv_at_the_versions_it_is_given() -> None:
    """No default: a build not given the three versions fails. `ARG NAUTOBOT_VERSION` is declared again after `FROM`,
    since an argument declared before it is out of scope for the `RUN` line."""
    text = (DEV / "Dockerfile").read_text()
    held = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    [copy] = [line for line in root_dockerfile() if line.startswith("COPY --from=ghcr.io/astral-sh/uv:")]
    assert held == [
        "ARG NAUTOBOT_VERSION",
        "ARG NAUTOBOT_PYTHON",
        "FROM networktocode/nautobot:${NAUTOBOT_VERSION}-py${NAUTOBOT_PYTHON}",
        "ARG NAUTOBOT_VERSION",
        "ARG GOLDEN_CONFIG_VERSION",
        copy,
        "USER root",
        "RUN uv pip install --no-cache --python /usr/local/bin/python "
        "nautobot==${NAUTOBOT_VERSION} nautobot-golden-config==${GOLDEN_CONFIG_VERSION}",
        "USER nautobot",
    ]
    assert re.search(r"\d\.\d", "\n".join(line for line in held if line != copy)) is None


def literal(node: ast.expr) -> object:
    return ast.literal_eval(node)


def ipv4(found: str) -> bool:
    try:
        return ip_address(found).version == 4
    except ValueError:
        return False


def test_the_configuration_enables_intended_and_sotagg_alone() -> None:
    """Parsed, never imported: it runs in Nautobot alone. The database, Redis and the key come from `NAUTOBOT_*`,
    which Nautobot's own settings read, so the file reads no environment."""
    source = (DEV / "nautobot_config.py").read_text()
    tree = ast.parse(source)
    [star] = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
    assert star.module == "nautobot.core.settings"
    assert [alias.name for alias in star.names] == ["*"]
    assigned = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert list(assigned) == ["ALLOWED_HOSTS", "PLUGINS", "PLUGINS_CONFIG"]
    assert [type(node).__name__ for node in tree.body] == ["ImportFrom", "Assign", "Assign", "Assign"]
    assert literal(assigned["ALLOWED_HOSTS"]) == ["*"]
    assert literal(assigned["PLUGINS"]) == ["nautobot_plugin_nornir", "nautobot_golden_config"]
    config = literal(assigned["PLUGINS_CONFIG"])
    assert isinstance(config, dict) and list(config) == ["nautobot_plugin_nornir", "nautobot_golden_config"]
    assert config["nautobot_plugin_nornir"] == {
        "nornir_settings": {
            "credentials": "nautobot_plugin_nornir.plugins.credentials.env_vars.CredentialsEnvVars",
            "runner": {"plugin": "threaded", "options": {"num_workers": 20}},
        }
    }
    assert config["nautobot_golden_config"] == {
        "enable_backup": False,
        "enable_compliance": False,
        "enable_intended": True,
        "enable_sotagg": True,
        "enable_plan": False,
        "enable_deploy": False,
        "enable_postprocessing": False,
    }
    assert "environ" not in source and "getenv" not in source


def test_nautobot_names_no_host_and_the_script_one_address() -> None:
    """No tracked file under `nautobot/` holds a URL with a host but the fixture's, which holds one, the repository's
    remote; none holds an IPv4 address outside loopback and the documentation ranges but the fixture's, which holds
    exactly the fixture's six and its probe's two hosts. `scripts/nautobot_dev.py` holds one URL, the address."""
    paths = tracked()
    assert HERE in paths and FIXTURE in paths
    nautobot = [path for path in paths if path.startswith("nautobot/")]
    remote = yaml.safe_load((ROOT / FIXTURE).read_text())["repository"]["remote_url"]
    urls = [(path, hit[0]) for path in nautobot for _, line in lines(path) for hit in URL.finditer(line)]
    assert urls == [(FIXTURE, remote)]
    found = [
        (path, number, quad[1])
        for path in nautobot
        if path != HERE
        for number, line in lines(path)
        for quad in QUAD.finditer(line)
        if ipv4(quad[1]) and not any(ip_address(quad[1]) in network for network in ALLOWED)
    ]
    assert [hit for hit in found if hit[0] != FIXTURE] == []
    seeded = {quad for _, _, quad in found}
    probe = {"10.1.10.2", "10.1.11.2"}
    assert seeded == {f"10.{d}.{port}.1" for d in (1, 2, 3) for port in (10, 11)} | probe
    script = (ROOT / "scripts" / "nautobot_dev.py").read_text()
    assert [hit[0] for hit in URL.finditer(script)] == [nautobot_dev.ADDRESS]
    assert nautobot_dev.ADDRESS.endswith(":8810")


def test_the_env_example_lists_each_name_commented() -> None:
    """Six in the development Nautobot's block, after NetBox's and before its own CA line."""
    held = (ROOT / ".env.example").read_text().splitlines()
    at = {line: number for number, line in enumerate(held)}
    for name in NAMES:
        assert f"# {name}=" in at, name
    places = [at[f"# {name}="] for name in NAMES]
    assert places == sorted(places)
    assert at["# FYLGJA_NETBOX_CA="] < places[0] and places[-1] < at["# FYLGJA_NAUTOBOT_CA="]
    assert NAMES[:5] == nautobot_dev.NAMES


def test_the_pyproject_is_pytests_settings_alone() -> None:
    document = tomllib.loads((NAUTOBOT / "pyproject.toml").read_text())
    assert document == {
        "tool": {
            "pytest": {
                "ini_options": {
                    "testpaths": ["tests"],
                    "pythonpath": ["seed", "../scripts"],
                    "markers": [
                        "contract_nautobot: reads and writes the development Nautobot, under tests/contract; "
                        "deselected by default"
                    ],
                    "addopts": "-p no:cacheprovider -m 'not contract_nautobot'",
                }
            }
        }
    }
    members = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["workspace"]["members"]
    assert "nautobot" not in members
