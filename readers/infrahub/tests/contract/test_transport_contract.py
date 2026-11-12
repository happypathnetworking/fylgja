"""The transport against the development Infrahub: its version; its refusals, each with the status Infrahub answered;
the fixture's rows, every list whole; and a list of more than a page read whole (CONTRIBUTING.md, Test tiers;
design/verified-facts.md, "Infrahub 1.11.11"). No assertion message prints the address or a token."""

from __future__ import annotations

import os
import secrets
from typing import Any

import httpx
import pytest
from fylgja_core.client import base_url, trust

from fylgja_infrahub import SUPPORTED, Infrahub, InfrahubError, ReaderDocument, connect, times
from fylgja_infrahub.rows import incomplete
from fylgja_infrahub.transport import KEEPALIVE_S, PAGE

from .conftest import ADDRESS, ca, reader
from .writer import Writer

MISSING = "fylgja-contract-none"
"""A branch Infrahub lacks: no branch of the tier's own, which are named by 8 hex digits."""

PORTS = 120
"""The ports of the device the page test makes: more than `PAGE`, so two pages."""

LAB = 'query { LocationSite(name__value: "lab") { edges { node { id } } } }'
DEVICE = (
    "mutation ($location: String!) { DcimDeviceCreate(data: {name: {value: \"fc-dense\"}, location: {id: $location}}) "
    "{ ok object { id } } }"
)


class Counting(httpx.BaseTransport):
    """A transport that keeps the path of each request it passes on."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner
        self.paths: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


def test_the_version_is_read(conn: Infrahub) -> None:
    with httpx.Client(base_url=base_url(os.environ[ADDRESS]), verify=trust(ca()), trust_env=False) as plain:
        answered = plain.get("/api/info").json()["version"]
    assert conn.version == answered
    assert (conn.unverified is None) == (conn.version in SUPPORTED)


def refused(raised: pytest.ExceptionInfo[InfrahubError], *phrases: str) -> tuple[int | None, list[str]]:
    """The error's status, and those of `phrases` its text lacks: plain values, so that a failing assertion prints
    neither the error, whose text names the address where Infrahub was not reached, nor its repr."""
    text = str(raised.value)
    return raised.value.status, [phrase for phrase in phrases if phrase not in text]


def test_a_branch_infrahub_lacks_is_refused_with_its_status(conn: Infrahub) -> None:
    with pytest.raises(InfrahubError) as raised:
        conn.devices(MISSING, None, "fylgja")
    assert refused(raised, f"branch {MISSING}") == (404, [])


def test_an_at_before_the_branch_is_refused_with_its_status(conn: Infrahub) -> None:
    early = "2000-01-01T00:00:00.000000+00:00"
    with pytest.raises(InfrahubError) as raised:
        conn.devices("main", early, "fylgja")
    assert refused(raised, f"branch main, at {early}") == (422, [])

    malformed = "yesterday"
    assert times.invalid(malformed) is not None, "sent past times, which refuses it"
    with pytest.raises(InfrahubError) as raised:
        conn.devices("main", malformed, "fylgja")
    assert refused(raised, f"branch main, at {malformed}") == (400, [])


@pytest.mark.usefixtures("conn")
def test_a_wrong_token_is_refused_and_never_quoted() -> None:
    """`GET /api/info` refuses a wrong token as a query does, HTTP 401, though it answers a request with none
    (design/verified-facts.md), so `connect` refuses it before any query is sent. It needs the reader's own
    connection made first, so that an Infrahub not reached is the fixture's one sentence."""
    wrong = "wrong-" + secrets.token_hex(4)
    with pytest.raises(InfrahubError) as raised:
        connect(os.environ[ADDRESS], wrong, ca=ca())
    assert refused(raised, "FYLGJA_INFRAHUB_TOKEN") == (401, [])
    quoted = [wrong in text for text in (str(raised.value), repr(raised.value))]
    assert quoted == [False, False], "the error quotes the token"


def test_the_fixtures_rows(conn: Infrahub, seed: dict[str, Any], document: ReaderDocument) -> None:
    at = seed["stages"][0]["at"]
    devices = conn.devices("main", at, "fylgja")
    assert incomplete(devices, branch="main", at=at) is None
    assert devices.count == 3
    assert sorted(device.name for device in devices.items) == ["n1", "n2", "n3"]
    for device in devices.items:
        assert (device.manufacturer, device.platform) == ("Nokia", "SR Linux")
        assert incomplete(device.artifacts, branch="main", at=at) is None
        assert [artifact.definition for artifact in device.artifacts.items].count(document.artifact) == 1

    ids = {device.id for device in devices.items}
    ports = conn.ports("main", at, sorted(ids))
    assert incomplete(ports, branch="main", at=at) is None
    assert ports.count == 15
    assert {port.device for port in ports.items} == ids
    connectors = [port.connector for port in ports.items if port.connector is not None]
    assert len(connectors) == 4, "main's two cables, each from both its ports"
    for connector in connectors:
        assert connector.kind == "DcimCable"
        assert incomplete(connector.ends, branch="main", at=at) is None
        assert [(end.kind, end.device in ids) for end in connector.ends.items] == [("InterfacePhysical", True)] * 2


def test_a_list_of_more_than_a_page_is_read_whole(writer: Writer) -> None:
    with writer.branch() as branch:
        location = writer.gql(branch, LAB)["LocationSite"]["edges"][0]["node"]["id"]
        device = writer.gql(branch, DEVICE, {"location": location})["DcimDeviceCreate"]["object"]["id"]
        for first in range(1, PORTS + 1, 20):
            creates = " ".join(
                f'p{i}: InterfacePhysicalCreate(data: {{name: {{value: "e-{i:03d}"}}, device: {{id: $device}}}}) '
                "{ ok }"
                for i in range(first, first + 20)
            )
            writer.gql(branch, f"mutation ($device: String!) {{ {creates} }}", {"device": device})

        counting = Counting(httpx.HTTPTransport(verify=trust(ca()), limits=httpx.Limits(keepalive_expiry=KEEPALIVE_S)))
        with reader(transport=counting) as paging:
            ports = paging.ports(branch, None, [device])
    assert PORTS > PAGE
    assert (ports.count, len(ports.items), len({port.id for port in ports.items})) == (PORTS, PORTS, PORTS)
    assert incomplete(ports, branch=branch, at=None) is None
    assert sorted(port.name for port in ports.items) == [f"e-{i:03d}" for i in range(1, PORTS + 1)]
    assert counting.paths.count(f"/graphql/{branch}") == 2
