"""The adapter's probes against the core's: the declaration (`internal/probe/decl_test.go`),
the kind's reader (`internal/intent/probes_test.go`) and the request's one list
(`internal/server/probes_test.go`'s `readProbes` cases; the API's plumbing, `probesFiles`
and `probesOf`, stays in the core). Each test is named after the Go test it carries over.
The declarations are copies of `testdata/probes/`, the kind's schema a copy of
`internal/intent/testdata/schema-fylgja-probe.json`, each held to its original."""

import copy
import json
from pathlib import Path

import httpx
import jsonschema
import pytest

from fylgja_orchestrator.adapters.infrahub import packages, probes
from fylgja_orchestrator.adapters.infrahub.client import ClientError, ConfigError, DefaultClient, default_from_env
from fylgja_orchestrator.adapters.infrahub.probes import (
    PROBE_FIELDS,
    PROBE_KIND,
    PROBE_SCHEMA_FILE,
    VERSION,
    ProbeKindError,
    ProbesError,
    check_kind,
    declared,
    parse,
    read_kind,
    validate,
)
from fylgja_orchestrator.adapters.infrahub.read import ReadError
from fylgja_orchestrator.documents.findings import REJECTION

from .conftest import ADDRESS, TOKEN

REPO = Path(__file__).resolve().parents[3]
DATA = Path(__file__).resolve().parents[1] / "data"
PROBES = DATA / "probes"
PROBE_SCHEMA = DATA / "schema" / "schema-fylgja-probe.json"

COPIES = sorted(p.relative_to(PROBES).as_posix() for p in PROBES.rglob("*") if p.is_file())


@pytest.fixture(autouse=True)
def shipped(monkeypatch):
    """The repository's probe packages alone, whatever the environment names."""
    monkeypatch.delenv(packages.ENV_OVERRIDE, raising=False)
    monkeypatch.delenv(packages.ENV_SHIPPED, raising=False)


# The copies.


def test_every_declaration_is_copied():
    originals = sorted(p.relative_to(REPO / "testdata" / "probes").as_posix()
                       for p in (REPO / "testdata" / "probes").rglob("*") if p.is_file())
    assert originals == COPIES


@pytest.mark.parametrize("name", COPIES)
def test_each_copy_is_the_repositorys_declaration(name):
    # A declaration that moves under testdata/probes/ is copied again.
    assert (PROBES / name).read_bytes() == (REPO / "testdata" / "probes" / name).read_bytes()


def test_the_probe_kinds_schema_is_the_recorded_one():
    original = REPO / "internal" / "intent" / "testdata" / "schema-fylgja-probe.json"
    assert PROBE_SCHEMA.read_bytes() == original.read_bytes()


def fixture(name: str) -> bytes:
    return (PROBES / name).read_bytes()


# internal/probe/decl_test.go


@pytest.mark.parametrize(
    "file,name,device,a,b",
    [
        ("n1-loop.json", "n1-loop", "n1", "ethernet-1/10", "ethernet-1/11"),
        ("n2-loop.json", "n2-loop", "n2", "ethernet-1/10", "ethernet-1/11"),
        ("e1-loop.json", "e1-loop", "e1", "Ethernet10", "Ethernet11"),
    ],
)
def test_the_fixtures_parse(file, name, device, a, b):
    # The declarations tier 1 reads parse, each to one probe of two endpoints, R-19's ports
    # and addresses.
    d, found = parse(fixture(file), file)
    assert not found.rejected and d is not None, found
    assert d["probes_version"] == VERSION and len(d["probes"]) == 1, d
    p = d["probes"][0]
    assert p["name"] == name and p["format"] == "ping"
    assert [e["device"] for e in p["endpoints"]] == [device, device]
    assert [e["interface"] for e in p["endpoints"]] == [a, b]


GOOD = """{"probes_version": "1", "probes": [
  {"name": "n1-loop", "format": "ping", "endpoints": [
    {"device": "n1", "interface": "ethernet-1/10", "address": "10.1.10.2/24", "gateway": "10.1.10.1"},
    {"device": "n1", "interface": "ethernet-1/11", "address": "10.1.11.2/24", "gateway": "10.1.11.1"}]}]}"""


def holds(found, rule, object, says):
    """A rejection of rule at object whose message holds says."""
    assert any(
        f.rule == rule and f.object == object and says in f.message and f.severity == REJECTION for f in found
    ), f"no rejection {rule} at {object!r} saying {says!r} among {list(found)}"


FILE = "probes.json"


@pytest.mark.parametrize(
    "doc,rule,object,says",
    [
        pytest.param("[]", "probes.invalid", FILE, "not a JSON object", id="not an object"),
        pytest.param("{", "probes.invalid", FILE, "not a JSON object", id="not JSON"),
        pytest.param("null", "probes.invalid", FILE, "not a JSON object", id="null"),
        pytest.param('" "', "probes.invalid", FILE, "not a JSON object", id="a string"),
        pytest.param('{"probes": []}', "probes.version.unsupported", FILE, "names no probes_version",
                     id="no version"),
        pytest.param('{"probes_version": "2", "probes": []}', "probes.version.unsupported", FILE,
                     'probes_version "2"; this build reads probes "1"', id="version 2"),
        pytest.param('{"probes_version": 1, "probes": []}', "probes.version.unsupported", FILE, "probes_version 1;",
                     id="version a number"),
        pytest.param('{"probes_version": "1", "probes": [], "hosts": []}', "probes.invalid", FILE, 'the key "hosts"',
                     id="an unknown key"),
        pytest.param('{"probes_version": "1"}', "probes.invalid", FILE, "no probes list", id="no probes"),
        pytest.param('{"probes_version": "1", "probes": null}', "probes.invalid", FILE, "no probes list",
                     id="probes null"),
        pytest.param('{"probes_version": "1", "probes": {}}', "probes.invalid", FILE, "not a list",
                     id="probes not a list"),
        pytest.param('{"probes_version": "1", "probes": ["n1-loop"]}', "probes.invalid", "probes[0]",
                     "not a JSON object", id="a probe not an object"),
        pytest.param(GOOD.replace('"format": "ping"', '"format": "ping", "count": 5', 1), "probes.invalid",
                     "probes[0].count", 'the key "count"', id="a probe's unknown key"),
        pytest.param(GOOD.replace('"format": "ping", ', "", 1), "probes.invalid", "probes[0].format",
                     "has no format", id="a probe's missing field"),
        pytest.param(GOOD.replace('"name": "n1-loop"', '"name": 7', 1), "probes.invalid", "probes[0].name",
                     "not a string", id="a field not a string"),
        pytest.param(
            """{"probes_version": "1", "probes": [{"name": "x", "format": "ping", "endpoints": [
			{"device": "n1", "interface": "e", "address": "10.0.0.2/24", "gateway": "10.0.0.1"}]}]}""",
            "probes.invalid", "probes[0].endpoints", "endpoints holds 1; a probe has exactly two", id="one endpoint"),
        pytest.param(fixture("invalid/probes.invalid.json").decode(), "probes.invalid", "probes[0].endpoints",
                     "endpoints holds 3", id="three endpoints"),
        pytest.param('{"probes_version": "1", "probes": [{"name": "x", "format": "ping", "endpoints": {}}]}',
                     "probes.invalid", "probes[0].endpoints", "not a list", id="endpoints not a list"),
        pytest.param(GOOD.replace('"gateway": "10.1.11.1"', '"gateway": "10.1.11.1", "vlan": 10', 1),
                     "probes.invalid", "probes[0].endpoints[1].vlan", 'the key "vlan"',
                     id="an endpoint's unknown key"),
        pytest.param(GOOD.replace(', "gateway": "10.1.11.1"', "", 1), "probes.invalid",
                     "probes[0].endpoints[1].gateway", "has no gateway", id="an endpoint's missing field"),
        # Beyond the Go table: NaN is no JSON to Go's decoder, so the document is not one.
        pytest.param('{"probes_version": "1", "probes": [], "x": NaN}', "probes.invalid", FILE,
                     "not a JSON object", id="NaN"),
    ],
)
def test_parse_refuses_the_shape(doc, rule, object, says):
    # Each fault of the document's shape is probes.invalid at the file or at
    # probes[<i>].<field>, and the version is read first, on its own.
    d, found = parse(doc.encode(), FILE)
    assert d is None, f"a refused declaration was returned: {d}"
    holds(found, rule, object, says)


@pytest.mark.parametrize(
    "doc",
    [
        pytest.param(b"", id="zero bytes"),
        pytest.param(b"\n", id="a newline alone"),
        pytest.param(b" \t\r\n \n", id="whitespace alone"),
        pytest.param(fixture("none.json"), id="testdata/probes/none.json"),
        pytest.param(b'{"probes_version": "1", "probes": []}', id="probes: []"),
    ],
)
def test_an_empty_file_declares_none(doc):
    # A file that is empty, or of whitespace alone, declares no probes: probes 1 with an
    # empty list, never None, and no finding, as a declaration of probes: [] reads.
    d, found = parse(doc, FILE)
    assert d is not None and len(found) == 0, (d, found)
    assert d == {"probes_version": VERSION, "probes": []}


@pytest.mark.parametrize(
    "file,formats,rule,object,says",
    [
        ("probe.name.invalid.json", None, "probe.name.invalid", "N1_loop", 'probe name "N1_loop" is not'),
        ("probe.name.duplicate.json", None, "probe.name.duplicate", "n1-loop", "declared at probes[0] and probes[1]"),
        ("probe.format.unknown.json", ["ping"], "probe.format.unknown", "n1-loop",
         'format "traceroute": no probe package declares it; the formats loaded are ping'),
        ("probe.address.invalid.json", None, "probe.address.invalid", "n1-loop/b.address",
         'address "10.1.11.2" is not an address with a prefix length'),
        ("probe.gateway.invalid.json", None, "probe.gateway.invalid", "n1-loop/b.gateway",
         'gateway "10.1.11.1/24" carries a prefix length'),
        ("probe.gateway.outside.json", None, "probe.gateway.outside", "n1-loop/b.gateway",
         "gateway 10.1.12.1 is not within 10.1.11.0/24"),
        ("probe.family.mixed.json", None, "probe.family.mixed", "n1-loop", "two families (IPv4, IPv4, IPv6, IPv6)"),
        ("probe.address.duplicate.json", None, "probe.address.duplicate", "n2-loop/a.address",
         "address 10.1.10.2 of probe n2-loop endpoint a is probe n1-loop endpoint a's too"),
    ],
)
def test_validate_names_the_probe_the_endpoint_and_the_field(file, formats, rule, object, says):
    # Each rule that reads no CTM names the probe, the endpoint and the field. parse holds a
    # declaration to them with no registry; the format is held where a registry is at hand.
    decl, found = parse(fixture("invalid/" + file), file)
    if formats is None:
        assert decl is None, f"parse returned a declaration it refused: {decl}"
        holds(found, rule, object, says)
        return
    # The format is the one rule parse leaves to a registry.
    assert not found.rejected, f"parse refused a declaration only a registry refuses: {found}"
    holds(validate(decl["probes"], formats), rule, object, says)


def probe_of(name, a, b, format="ping"):
    return {
        "name": name,
        "format": format,
        "endpoints": [
            {"device": a[0], "interface": a[1], "address": a[2], "gateway": a[3]},
            {"device": b[0], "interface": b[1], "address": b[2], "gateway": b[3]},
        ],
    }


def test_validate_reports_every_fault_in_one_pass():
    # An endpoint's other faults: a gateway that is no address, an address of a gateway's
    # family mismatched without a prefix, and every fault of one probe in one pass.
    p = probe_of("x", ("n1", "e1", "nonsense", "also nonsense"), ("n1", "e2", "10.0.0.2/24", "fe80::1%eth1"))
    found = validate([p])
    holds(found, "probe.address.invalid", "x/a.address", '"nonsense"')
    holds(found, "probe.gateway.invalid", "x/a.gateway", 'gateway "also nonsense" is not an address')
    holds(found, "probe.gateway.invalid", "x/b.gateway", '"fe80::1%eth1"')
    assert sum(1 for f in found if f.severity == REJECTION) == 3, found


def test_validate_names_a_probe_as_the_caller_does():
    # object_of names a probe as the caller does: the snapshot by its position.
    p = probe_of("x", ("n1", "e1", "10.0.0.2/24", "10.0.1.1"), ("n1", "e2", "10.0.1.2/24", "10.0.1.1"))
    found = validate([p], None, lambda i: "probes[0]")
    holds(found, "probe.gateway.outside", "probes[0]/a.gateway", "not within 10.0.0.0/24")


def test_validate_accepts_a_good_declaration():
    # A good declaration passes every rule, the format included, and an empty list is a
    # declaration of none.
    d, found = parse(GOOD.encode(), FILE)
    assert not found.rejected, found
    assert len(validate(d["probes"], ["ping"])) == 0
    none, found = parse(b'{"probes_version": "1", "probes": []}', "none.json")
    assert not found.rejected and none is not None and len(none["probes"]) == 0, (none, found)


def test_a_name_with_a_trailing_newline_is_invalid():
    # Go's $ ends the name; Python's would match before a trailing newline.
    p = probe_of("n1-loop\n", ("n1", "e1", "10.0.0.2/24", "10.0.0.1"), ("n1", "e2", "10.0.1.2/24", "10.0.1.1"))
    holds(validate([p]), "probe.name.invalid", "n1-loop\n", 'probe name "n1-loop\\n" is not')


# The contract: every declaration a file's read accepts (parse, then the formats the probe
# packages declare) is an instance of probes.schema.json. parse alone also accepts
# probe.format.unknown.json, whose format the contract's enum and the registry refuse.

PROBES_SCHEMA = json.loads((REPO / "contracts" / "probes.schema.json").read_text())


def contract_validator():
    return jsonschema.validators.validator_for(PROBES_SCHEMA)(PROBES_SCHEMA)


@pytest.mark.parametrize("name", COPIES)
def test_every_accepted_declaration_holds_to_the_contract(name):
    got, found = declared(str(PROBES / name))
    if got is None:
        assert found.rejected
        return
    contract_validator().validate({"probes_version": VERSION, "probes": got})
    if fixture(name).strip():
        contract_validator().validate(json.loads(fixture(name)))


def test_the_accepted_copies_are_the_ones_expected():
    assert [name for name in COPIES if parse(fixture(name), name)[0] is not None] == [
        "e1-loop.json", "invalid/probe.format.unknown.json", "n1-loop.json", "n2-loop.json", "none.json"]
    assert [name for name in COPIES if declared(str(PROBES / name))[0] is not None] == [
        "e1-loop.json", "n1-loop.json", "n2-loop.json", "none.json"]
    # The one parse leaves to the registry, the contract refuses by its format alone.
    errors = list(contract_validator().iter_errors(json.loads(fixture("invalid/probe.format.unknown.json"))))
    assert [list(e.absolute_path) for e in errors] == [["probes", 0, "format"]]


# internal/intent/probes_test.go


def probe_kind_node(drop=()) -> dict:
    """FylgjaProbe as Infrahub 1.11.2 answers it on a default branch holding
    schema/fylgja-probe.yaml, less the attributes named in drop."""
    node = json.loads(PROBE_SCHEMA.read_text())
    assert node["kind"] == PROBE_KIND, f"the recorded node is {node['kind']}, not {PROBE_KIND}"
    node["attributes"] = [a for a in node["attributes"] if a["name"] not in drop]
    return node


def with_probe_kind(infrahub, drop=()):
    """The default branch's schema: the recorded library's, with the kind."""
    schema = copy.deepcopy(infrahub.schema)
    schema["nodes"] = list(schema["nodes"]) + [probe_kind_node(drop)]
    infrahub.default_schema = schema


def probe_node(p: dict) -> dict:
    """One FylgjaProbe as Infrahub's GraphQL answers the Probes query."""
    node = {"name": {"value": p["name"]}, "format": {"value": p["format"]}}
    for end, e in zip(("a", "b"), p["endpoints"], strict=True):
        for k in ("device", "interface", "address", "gateway"):
            node[f"{end}_{k}"] = {"value": e[k]}
    return node


def serve_probes(infrahub, listed: list[dict]):
    """The Probes query answered from listed, paged by its limit and offset."""

    def answer(variables, query_text, branch, params):
        limit, offset = variables["limit"], variables["offset"]
        page = listed[offset:offset + limit]
        return {"data": {"FylgjaProbe": {"count": len(listed), "edges": [{"node": n} for n in page]}}}

    infrahub.default_operations["Probes"] = answer


def reader_of(infrahub) -> DefaultClient:
    return DefaultClient(ADDRESS, TOKEN, requester=infrahub)


@pytest.mark.parametrize(
    "present,drop,missing,message",
    [
        pytest.param(True, (), [], "", id="present"),
        pytest.param(True, ("description",), [], "", id="description absent"),
        pytest.param(False, (), [], "the default branch's schema has no kind FylgjaProbe", id="absent"),
        pytest.param(True, ("b_gateway",), ["b_gateway"],
                     "kind FylgjaProbe on the default branch lacks the attribute b_gateway, which this build reads",
                     id="one missing"),
        pytest.param(True, ("a_address", "format"), ["format", "a_address"],
                     "kind FylgjaProbe on the default branch lacks the attributes format, a_address, which this "
                     "build reads", id="two missing"),
    ],
)
def test_probe_reader_checks_the_kind(infrahub, present, drop, missing, message):
    # The kind's presence and its ten attributes are read from the schema endpoint before
    # any query; what is missing is named, in PROBE_FIELDS' order. The description, which
    # nothing reads, may be absent.
    if present:
        with_probe_kind(infrahub, drop)
    else:
        infrahub.default_schema = copy.deepcopy(infrahub.schema)
    if not message:
        check_kind(reader_of(infrahub))
        return
    with pytest.raises(ProbeKindError) as raised:
        check_kind(reader_of(infrahub))
    assert raised.value.missing == missing
    assert str(raised.value) == message
    assert infrahub.count("/graphql") == 0, "check_kind sent a query"


N1 = probe_of("n1-loop", ("n1", "ethernet-1/10", "10.1.10.2/24", "10.1.10.1"),
              ("n2", "ethernet-1/11", "10.1.11.2/24", "10.1.11.1"))
V6 = probe_of("v6-loop", ("s1", "Ethernet7", "2001:db8:7::2/64", "2001:db8:7::1"),
              ("e1", "Ethernet8", "2001:db8:8::2/64", "2001:db8:8::1"), format="ping-v6")


def test_probe_reader_maps_a_page_of_two(infrahub):
    # A page of two, answered out of name order: each object becomes the declaration's
    # element, every one of its ten values verbatim in its place, and the list comes back in
    # name order. One page is asked for, of a hundred from the start, and the query selects
    # the ten attributes and not the description.
    with_probe_kind(infrahub)
    serve_probes(infrahub, [probe_node(V6), probe_node(N1)])
    assert read_kind(reader_of(infrahub)) == [N1, V6]
    asked = infrahub.served("Probes")
    assert len(asked) == 1, f"asked Probes {len(asked)} times, want once"
    assert (asked[0]["variables"]["limit"], asked[0]["variables"]["offset"]) == (100, 0)
    for field in PROBE_FIELDS:
        assert field + " " in asked[0]["query_text"], f"the query does not select {field}"
    assert "description" not in asked[0]["query_text"], "the query selects the description, which is never read"


def test_probe_reader_reads_every_page(infrahub):
    # Every page is read, a hundred at a time, and the list is in name order whatever the
    # server answered.
    with_probe_kind(infrahub)
    empty = ("", "", "", "")
    serve_probes(infrahub, [probe_node(probe_of(f"p{i:03d}", empty, empty)) for i in range(100, -1, -1)])
    got = read_kind(reader_of(infrahub))
    assert len(got) == 101 and got[0]["name"] == "p000" and got[100]["name"] == "p100"
    assert [r["variables"]["offset"] for r in infrahub.served("Probes")] == [0, 100]


@pytest.mark.parametrize("edges", [[], None], ids=["no edge", "edges null"])
def test_probe_reader_reads_an_empty_list(infrahub, edges):
    # The kind with no object is an empty list, not None: a snapshot's probes is a list, and
    # [] is what it carries when the take has none.
    with_probe_kind(infrahub)
    infrahub.default_operations["Probes"] = lambda *_: {"data": {"FylgjaProbe": {"count": 0, "edges": edges}}}
    got = read_kind(reader_of(infrahub))
    assert json.dumps(got) == "[]"


def test_probe_reader_names_no_branch(infrahub):
    # The reader names no branch and pins nothing: the schema endpoint and GraphQL on their
    # unnamed paths, with no query string, so the default branch answers whatever it is
    # called.
    with_probe_kind(infrahub)
    serve_probes(infrahub, [])
    r = reader_of(infrahub)
    check_kind(r)
    read_kind(r)
    for req in infrahub.requests:
        assert httpx.URL(req["url"]).query == b"", (
            f"{req['path']} carries a query string; the reader names no branch and pins nothing")
    assert [req["path"] for req in infrahub.requests] == ["/api/schema", "/graphql"]


def echo(status, shaped=True):
    """An Infrahub that answers every request with status, quoting the request's own key:
    in Infrahub's error shape (`{"message": ...}`), or, as the Go test's server, a string."""

    def answer(url, method, headers, timeout, payload=None):
        said = "rejected key " + headers.get("X-INFRAHUB-KEY", "")
        body = json.dumps({"errors": [{"message": said} if shaped else said]}).encode()
        return httpx.Response(status, content=body, request=httpx.Request(method.value, url))

    return answer


@pytest.mark.parametrize(
    "requester,address,want",
    [
        pytest.param(echo(401), ADDRESS, "INFRAHUB_API_TOKEN", id="401"),
        # The Go test's body, errors as strings, which the SDK's relogin hook cannot read:
        # the client decides by the status (client.py's _relogin_failure).
        pytest.param(echo(401, shaped=False), ADDRESS, "INFRAHUB_API_TOKEN", id="401 errors as strings"),
        pytest.param(echo(500), ADDRESS, "<redacted>", id="500 quoting the key"),
        pytest.param(echo(500, shaped=False), ADDRESS, "<redacted>", id="500 quoting the key as a string"),
        pytest.param(None, "http://127.0.0.1:9", "(the default branch)", id="unreachable"),
    ],
)
def test_probe_reader_keeps_the_credential_out(requester, address, want):
    # An unreachable Infrahub, a refused credential and a non-200 are errors that carry no
    # credential, even from a server that quotes the request's own header back, and none is
    # taken for the kind's absence. A refused credential names the variable to fix.
    r = DefaultClient(address, TOKEN, requester=requester)
    for what, call in (("check", check_kind), ("read", read_kind)):
        with pytest.raises((ClientError, ReadError)) as raised:
            call(r)
        err = raised.value
        assert not isinstance(err, ProbeKindError), f"{what}: a transport failure reported as the kind's absence"
        assert TOKEN not in str(err), f"{what}: the credential reached the error: {err}"
        assert want in str(err), f"{what}: error {err} does not carry {want!r}"


def test_probe_reader_from_env(monkeypatch):
    # The reader is built from the variables a read uses, and refuses alike when one is unset.
    monkeypatch.setenv("INFRAHUB_ADDRESS", "")
    monkeypatch.setenv("INFRAHUB_API_TOKEN", "t")
    with pytest.raises(ConfigError) as raised:
        default_from_env()
    assert str(raised.value) == "INFRAHUB_ADDRESS is not set"
    monkeypatch.setenv("INFRAHUB_ADDRESS", "http://infrahub.invalid/")
    monkeypatch.setenv("INFRAHUB_API_TOKEN", "")
    with pytest.raises(ConfigError) as raised:
        default_from_env()
    assert str(raised.value) == "INFRAHUB_API_TOKEN is not set"


# internal/server/probes_test.go: readProbes, as `declared`.


def declared_probes(name: str) -> list[dict]:
    """The probes of a declaration under tests/data/probes/."""
    d, found = parse(fixture(name), name)
    assert d is not None, found
    return d["probes"]


def kind_answering(infrahub, listed: list[dict]):
    """FylgjaProbe on the default branch holding listed."""
    with_probe_kind(infrahub)
    serve_probes(infrahub, [probe_node(p) for p in listed])


def asked(infrahub) -> tuple[int, int]:
    """The kind's checks and reads."""
    return infrahub.count("/api/schema"), len(infrahub.served("Probes"))


def test_read_probes_takes_the_file_else_the_kind(infrahub):
    # The request's one list (FR-005): the file when one is sent, replacing the kind's, which
    # is then never asked; else the kind's; else, the kind holding none, [] with no warning.
    n1, n2 = declared_probes("n1-loop.json"), declared_probes("n2-loop.json")
    kind_answering(infrahub, n2)
    got, found = declared(str(PROBES / "n1-loop.json"), reader_of(infrahub))
    assert (got, list(found)) == (n1, []), "with a file: want the file's"
    assert asked(infrahub) == (0, 0), "with a file the kind was asked"

    got, found = declared(None, reader_of(infrahub))
    assert (got, list(found)) == (n2, [])
    assert asked(infrahub) == (1, 1), "with no file: want the kind's, once"


@pytest.mark.parametrize("edges", [[], None], ids=["no edge", "edges null"])
def test_read_probes_takes_neither(infrahub, edges):
    # With neither (the kind answering none): [], no finding.
    with_probe_kind(infrahub)
    infrahub.default_operations["Probes"] = lambda *_: {"data": {"FylgjaProbe": {"count": 0, "edges": edges}}}
    got, found = declared(None, reader_of(infrahub))
    assert got == [] and len(found) == 0
    # And with no reader at all, as an orchestrator that reads no kind.
    got, found = declared(None, None)
    assert got == [] and len(found) == 0


def test_read_probes_takes_an_empty_file(infrahub):
    # An empty file declares none: [] as with neither, and it replaces the kind's, which is
    # never asked (spec, Edge Cases).
    kind_answering(infrahub, declared_probes("n2-loop.json"))
    got, found = declared(str(PROBES / "none.json"), reader_of(infrahub))
    assert got == [] and len(found) == 0
    assert asked(infrahub) == (0, 0), "with an empty file the kind was asked"


@pytest.mark.parametrize(
    "file,rule,object",
    [
        ("probes.version.unsupported.json", "probes.version.unsupported", ""),
        ("probe.address.invalid.json", "probe.address.invalid", "n1-loop/b.address"),
        ("probe.gateway.outside.json", "probe.gateway.outside", ".gateway"),
        ("probe.format.unknown.json", "probe.format.unknown", "n1-loop"),
    ],
)
def test_read_probes_refuses_a_malformed_file_at_start(infrahub, file, rule, object):
    # A malformed file is refused at start under its own rule, naming the file, the probe and
    # the field; a format no probe package declares is refused there too, with the registry's
    # formats; and the kind is never asked.
    kind_answering(infrahub, [])
    path = str(PROBES / "invalid" / file)
    got, found = declared(path, reader_of(infrahub))
    assert got is None and found.rejected and len(found) > 0, found
    f = found[0]
    assert f.rule == rule and f.step == "start" and object in f.object, f
    assert f.object == path or path in f.message, f"finding {f} names neither in its object nor its message the file"
    assert asked(infrahub) == (0, 0), "the kind was asked beside a file"


def test_read_probes_names_the_file_in_a_probes_finding():
    # in_file: a finding at the file is left as it is; any other says the path first.
    path = str(PROBES / "invalid" / "probe.address.invalid.json")
    _, found = declared(path)
    assert [f.message for f in found] == [
        f'probe file {path}: address "10.1.11.2" is not an address with a prefix length, as 10.1.10.2/24'
    ]
    path = str(PROBES / "invalid" / "probes.version.unsupported.json")
    _, found = declared(path)
    assert [(f.object, f.message) for f in found] == [
        (path, 'the probe declaration is probes_version "2"; this build reads probes "1"')
    ]


def test_read_probes_refuses_an_unreadable_file():
    # A file that cannot be read is operation.failed at start, about --probes (the core's
    # request carrying no file under the path).
    with pytest.raises(ProbesError) as raised:
        declared(str(PROBES / "absent.json"))
    assert (raised.value.step, raised.value.object) == ("start", "--probes")
    assert str(raised.value).startswith(f"reading the probe file {PROBES / 'absent.json'}: ")


def bad_probes() -> list[dict]:
    bad = declared_probes("n1-loop.json")
    bad[0]["endpoints"][0]["address"] = "10.1.10.2"
    return bad


@pytest.mark.parametrize(
    "case",
    ["absent", "an attribute missing", "unreachable", "the list unreadable", "a probe refused"],
)
def test_read_probes_from_the_kind_refuses(infrahub, case):
    # The kind absent from the default branch is probe.kind.absent at resolve, naming the
    # schema file, when the read is asked for; an Infrahub that cannot be asked is
    # operation.failed there (ProbesError at resolve, about the kind); a probe the kind holds
    # that the declaration's rules refuse is refused at resolve, naming the kind.
    reader = reader_of(infrahub)
    if case == "absent":
        infrahub.default_schema = copy.deepcopy(infrahub.schema)
    elif case == "an attribute missing":
        with_probe_kind(infrahub, ("a_gateway",))
    elif case == "unreachable":
        reader = DefaultClient("http://127.0.0.1:9", TOKEN)
    elif case == "the list unreadable":
        with_probe_kind(infrahub)
        infrahub.default_operations["Probes"] = lambda *_: (500, {"errors": [{"message": "connection refused"}]})
    else:
        kind_answering(infrahub, bad_probes())

    if case in ("unreachable", "the list unreadable"):
        with pytest.raises(ProbesError) as raised:
            declared(None, reader)
        assert (raised.value.step, raised.value.object) == ("resolve", PROBE_KIND)
        return
    got, found = declared(None, reader)
    assert got is None and len(found) == 1, found
    f = found[0]
    want = "probe.address.invalid" if case == "a probe refused" else "probe.kind.absent"
    assert f.rule == want and f.step == "resolve", f
    if want == "probe.kind.absent":
        assert f.object == PROBE_KIND and PROBE_SCHEMA_FILE in f.message, f
    else:
        assert PROBE_KIND in f.message, f


@pytest.mark.parametrize(
    "drop,message",
    [
        ((), "the default branch's schema has no kind FylgjaProbe: load schema/fylgja-probe.yaml on it; only a "
             "request that sends no --probes file reads it"),
        (("a_gateway",), "kind FylgjaProbe on the default branch lacks the attribute a_gateway, which this build "
                         "reads: load schema/fylgja-probe.yaml on it; only a request that sends no --probes file "
                         "reads it"),
    ],
)
def test_read_probes_names_the_remedy(infrahub, drop, message):
    # probe.kind.absent's message: the kind's error, then the file to load.
    if drop:
        with_probe_kind(infrahub, drop)
    else:
        infrahub.default_schema = copy.deepcopy(infrahub.schema)
    _, found = declared(None, reader_of(infrahub))
    assert [(f.rule, f.object, f.message, f.step) for f in found] == [
        ("probe.kind.absent", PROBE_KIND, message, "resolve")
    ]


def test_read_probes_names_the_kind_in_a_probes_finding(infrahub):
    # in_kind: every finding about a probe read from the kind says the kind first.
    kind_answering(infrahub, bad_probes())
    _, found = declared(None, reader_of(infrahub))
    assert [(f.object, f.message) for f in found] == [
        ("n1-loop/a.address",
         'FylgjaProbe on the default branch: address "10.1.10.2" is not an address with a prefix length, as '
         "10.1.10.2/24")
    ]


# The formats the probe packages declare, as the core's registry loads them.


def test_formats_are_the_shipped_packages():
    assert probes.formats() == ["ping"]


def test_formats_add_the_override_directorys(tmp_path, monkeypatch):
    (tmp_path / "probes").mkdir()
    (tmp_path / "probes" / "trace.yaml").write_text("format: traceroute\n")
    (tmp_path / "probes" / "again.yaml").write_text("format: ping\n")
    assert probes.formats(str(tmp_path)) == ["ping", "traceroute"]
    monkeypatch.setenv(packages.ENV_OVERRIDE, str(tmp_path))
    assert probes.formats() == ["ping", "traceroute"]
    # A format an override declares is known to a file's read.
    got, found = declared(str(PROBES / "invalid" / "probe.format.unknown.json"))
    assert got is not None and len(found) == 0, found


def test_formats_refuse_no_package(tmp_path):
    with pytest.raises(ProbesError) as raised:
        probes.formats(shipped=tmp_path)
    assert (raised.value.step, raised.value.object) == ("start", "start")
    assert str(raised.value) == f"no probe package under {tmp_path}"


def test_formats_failing_is_at_the_step_of_the_read(tmp_path, monkeypatch, infrahub):
    # A package that cannot be read fails the file's read at start and the kind's at resolve,
    # each about its step, as loadFailureAt files it.
    (tmp_path / "probes").mkdir()
    (tmp_path / "probes" / "broken.yaml").write_text("format: [\n")
    monkeypatch.setenv(packages.ENV_OVERRIDE, str(tmp_path))
    with pytest.raises(ProbesError) as raised:
        declared(str(PROBES / "n1-loop.json"))
    assert (raised.value.step, raised.value.object) == ("start", "start")
    kind_answering(infrahub, declared_probes("n1-loop.json"))
    with pytest.raises(ProbesError) as raised:
        declared(None, reader_of(infrahub))
    assert (raised.value.step, raised.value.object) == ("resolve", "resolve")
