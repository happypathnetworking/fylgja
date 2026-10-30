"""A branch holding the schema library, as Infrahub 1.11.2's GraphQL answers the read: a
port of `internal/intent/infrahub_test.go`'s fakeInfrahub onto tier 1's FakeInfrahub
(conftest.py). It answers the Devices and Ports queries, in Infrahub's wire shapes (017
research §1.6), from devices, ports, cables and artifacts a test holds, and the object
store from their bytes; every refusal and omission of the read is produced by the code
under test. `from_ctm` seeds it from a CTM fixture as the fixture tool seeds the library's
kinds: each device tagged on its package's first pair, each port physical, the management
port by its role, each link a cable labelled with its canonical id, each device's artifact
Ready with its bytes in the store.
"""

import functools
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
FIXTURE_TAG = "fylgja"
READY = "Ready"


def md5_hex(body: bytes) -> str:
    return hashlib.md5(body, usedforsecurity=False).hexdigest()


def value(v):
    return {"value": v}


def nullable(s: str):
    return value(s if s else None)


def edges(nodes: list) -> dict:
    return {"edges": [{"node": n} for n in nodes]}


def page(nodes: list, limit: int, offset: int) -> dict:
    """One page of nodes as Infrahub's paginated envelope, with the total count."""
    total = len(nodes)
    offset = min(offset, total)
    end = total if limit <= 0 or offset + limit >= total else offset + limit
    out = edges(nodes[offset:end])
    out["count"] = total
    return out


def edge_page(edge_list: list, limit: int, offset: int) -> dict:
    """One page of edges, each as given."""
    end = min(offset + limit, len(edge_list))
    return {"count": len(edge_list), "edges": edge_list[min(offset, len(edge_list)) : end]}


@dataclass
class Port:
    id: str
    name: str
    role: str = ""
    status: str = ""
    cable: str = ""


@dataclass
class Device:
    id: str
    name: str
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    platform: str = ""
    manufacturer: str = ""
    empty_manufacturer: bool = False
    ports: list[Port] = field(default_factory=list)


@dataclass
class End:
    id: str
    kind: str = ""


@dataclass
class Cable:
    id: str
    label: str = ""
    kind: str = ""
    ends: list[End] = field(default_factory=list)


@dataclass
class Artifact:
    name: str
    status: str
    content_type: str
    checksum: str
    storage_id: str
    definition_name: str


@functools.cache
def package_pairs() -> dict[str, tuple[str, str]]:
    """Each package's first manufacturer and platform pair, by its id: the shipped packages
    and those under testdata/psp/lossy and heterogeneous."""
    out = {}
    for directory in ("psp", "testdata/psp/lossy", "testdata/psp/heterogeneous"):
        for path in sorted((REPO / directory).glob("*.yaml")):
            platform = yaml.safe_load(path.read_text())["platform"]
            m = platform["matches"][0]
            out[platform["id"]] = (m["manufacturer"], m["platform"])
    return out


@functools.cache
def _text(path: Path) -> str:
    return path.read_text()


class Dcim:
    """The branch: its devices in Infrahub's order, its cables by id, each device's
    artifacts by name, and `short`, for a cable it names, the count its
    connected_endpoints answers in place of the ends it lists."""

    def __init__(self, infrahub, branch: str = "fylgja-fixture"):
        self.infrahub = infrahub
        self.branch = branch
        infrahub.branches.add(branch)
        self.devices: list[Device] = []
        self.cables: dict[str, Cable] = {}
        self.artifacts: dict[str, list[Artifact]] = {}
        self.short: dict[str, int] = {}
        infrahub.operations["Devices"] = self._devices
        infrahub.operations["Ports"] = self._ports

    @classmethod
    def from_ctm(cls, infrahub, path: Path | str = REPO / "testdata" / "ctm" / "three-node.json") -> "Dcim":
        fixture = json.loads(_text(Path(path)))
        f = cls(infrahub, fixture["envelope"]["branch"])
        pairs = package_pairs()
        for d in fixture["devices"]:
            manufacturer, platform = pairs[d["platform"]["package"]]
            dev = Device(id="id-" + d["name"], name=d["name"], tags=[FIXTURE_TAG], platform=platform,
                         manufacturer=manufacturer)
            for i in d["interfaces"]:
                dev.ports.append(Port(id=f"{d['name']}:{i['name']}", name=i["name"],
                                      role="management" if i.get("mgmt_only") else "",
                                      status="disabled" if i.get("enabled") is False else ""))
            f.devices.append(dev)
            a = d["artifact"]
            storage = "storage-" + d["name"]
            f.artifacts[d["name"]] = [Artifact(a["name"], READY, a["content_type"], a["checksum"], storage, a["name"])]
            infrahub.objects[storage] = (200, a["content"].encode())
        for i, link in enumerate(fixture["links"]):
            f.cable("cable-" + chr(ord("a") + i), link["id"],
                    *(f"{e['device']}:{e['interface']}" for e in link["endpoints"]))
        return f

    def device(self, name: str) -> Device:
        for d in self.devices:
            if d.name == name:
                return d
        raise KeyError(f"the fake holds no device {name}")

    def port(self, port_id: str) -> tuple[Device | None, Port | None]:
        for d in self.devices:
            for p in d.ports:
                if p.id == port_id:
                    return d, p
        return None, None

    def add_device(self, name: str, manufacturer: str, platform: str, tags: list[str], *ports: str) -> Device:
        """A device carrying tags, on the pair given, with physical ports by name, and no
        artifact."""
        d = Device(id="id-" + name, name=name, tags=list(tags), platform=platform, manufacturer=manufacturer)
        d.ports = [Port(id=f"{name}:{p}", name=p) for p in ports]
        self.devices.append(d)
        return d

    def add_ports(self, device: str, *names: str) -> None:
        """More physical ports on a device, uncabled (cable_test.go's addPorts)."""
        d = self.device(device)
        d.ports.extend(Port(id=f"{device}:{n}", name=n) for n in names)

    def add_ready_artifact(self, device: str, body: bytes | None = None) -> None:
        """A device's configuration, Ready, its bytes in the object store."""
        body = body if body is not None else f"# {device}: sentinel configuration\n".encode()
        storage = "storage-" + device
        self.artifacts[device] = [
            Artifact("device-config", READY, "text/plain", md5_hex(body), storage, "device-config")
        ]
        self.infrahub.objects[storage] = (200, body)

    def set_content(self, device: str, body: bytes) -> None:
        """A device's artifact bytes replaced, the listing's checksum theirs."""
        a = self.artifacts[device][0]
        self.artifacts[device][0] = Artifact(a.name, a.status, a.content_type, md5_hex(body), a.storage_id,
                                             a.definition_name)
        self.infrahub.objects[a.storage_id] = (200, body)

    def cable(self, cable_id: str, label: str, *ends: str) -> Cable:
        """A cable labelled label between ports by id, `<device>:<port>`, each port's
        connector; an end `<kind>#<id>` is an endpoint of another kind."""
        c = Cable(id=cable_id, label=label)
        for e in ends:
            kind, sep, other = e.partition("#")
            if sep:
                c.ends.append(End(id=other, kind=kind))
                continue
            _, p = self.port(e)
            if p is None:
                raise KeyError(f"the fake holds no port {e}")
            p.cable = cable_id
            c.ends.append(End(id=e))
        self.cables[cable_id] = c
        return c

    def _devices(self, variables, query, branch, params):
        nodes = []
        for d in self.devices:
            if variables.get("tag") not in d.tags:
                continue
            arts = [
                {
                    "name": value(a.name),
                    "status": value(a.status),
                    "content_type": value(a.content_type),
                    "checksum": value(a.checksum),
                    "storage_id": value(a.storage_id),
                    "definition": {"node": {"artifact_name": value(a.definition_name)}},
                }
                for a in self.artifacts.get(d.name, [])
            ]
            platform = None
            if d.platform:
                manufacturer = None
                if d.manufacturer or d.empty_manufacturer:
                    manufacturer = {"name": value(d.manufacturer)}
                platform = {"name": value(d.platform), "manufacturer": {"node": manufacturer}}
            nodes.append({"id": d.id, "name": value(d.name), "platform": {"node": platform}, "artifacts": edges(arts)})
        return {"data": {"DcimDevice": page(nodes, variables["limit"], variables["offset"])}}

    def _ports(self, variables, query, branch, params):
        nodes = []
        ids = variables.get("devices") or []
        for d in self.devices:
            if d.id not in ids:
                continue
            for p in d.ports:
                nodes.append({
                    "id": p.id,
                    "name": value(p.name),
                    "role": nullable(p.role),
                    "status": nullable(p.status),
                    "device": {"node": {"__typename": "DcimDevice", "id": d.id}},
                    "connector": {"node": self._connector(p.cable)},
                })
        return {"data": {"InterfacePhysical": page(nodes, variables["limit"], variables["offset"])}}

    def _connector(self, cable_id: str):
        c = self.cables.get(cable_id)
        if c is None:
            return None
        ends = []
        for e in c.ends:
            if e.kind:
                ends.append({"__typename": e.kind, "id": e.id})
                continue
            d, p = self.port(e.id)
            ends.append({"__typename": "InterfacePhysical", "id": p.id, "name": value(p.name),
                         "device": {"node": {"__typename": "DcimDevice", "id": d.id}}})
        endpoints = edges(ends)
        endpoints["count"] = self.short.get(c.id, len(ends))
        if c.kind:
            return {"__typename": c.kind, "id": c.id, "connected_endpoints": endpoints}
        return {"__typename": "DcimCable", "id": c.id, "label": nullable(c.label), "connected_endpoints": endpoints}
