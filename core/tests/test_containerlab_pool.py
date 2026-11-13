import json
from ipaddress import IPv4Network as N

from fylgja_core import config
from fylgja_core.containerlab import pool


def test_the_first_free_slash24_is_chosen() -> None:
    assert pool.choose(N("172.20.0.0/16"), []) == N("172.20.0.0/24")
    assert pool.choose(N("172.20.0.0/16"), [N("172.20.0.0/24"), N("172.20.1.0/24")]) == N("172.20.2.0/24")


def test_a_wider_taken_network_blocks_every_slash24_inside_it() -> None:
    assert pool.choose(N("172.20.0.0/16"), [N("172.20.0.0/17")]) == N("172.20.128.0/24")
    assert pool.choose(N("172.20.0.0/16"), [N("172.16.0.0/12")]) is None


def test_an_exhausted_pool_answers_none() -> None:
    assert pool.choose(N("172.20.0.0/23"), [N("172.20.0.0/24"), N("172.20.1.0/24")]) is None


def test_the_allocation_is_the_lab_and_the_subnet() -> None:
    assert pool.allocation("three-node", N("172.20.5.0/24")) == {"lab": "three-node", "mgmt_subnet": "172.20.5.0/24"}


def test_the_holders_are_the_networks_that_overlap_the_pool_sorted() -> None:
    networks = [("zeta", N("172.20.5.0/24")), ("bridge", N("172.17.0.0/16")), ("alpha", N("172.16.0.0/12")),
                ("alpha", N("172.20.9.0/24"))]
    # A network wider than the pool holds it whole, and one beside it, the bridge, none of it.
    assert pool.holders(N("172.20.0.0/16"), networks) == [
        ("alpha", N("172.16.0.0/12")), ("alpha", N("172.20.9.0/24")), ("zeta", N("172.20.5.0/24"))]
    assert pool.holders(N("172.20.0.0/16"), iter(networks[1:2])) == []


def test_the_refusal_names_each_holder_and_the_setting() -> None:
    assert pool.refusal(N("198.51.100.0/24"), [("lab", N("198.51.100.0/24"))]) == (
        "The pool 198.51.100.0/24 has no /24 that neither a Docker network nor another twin holds. "
        "Docker networks holding part of it: lab (198.51.100.0/24). "
        "Set FYLGJA_LAB_POOL to an IPv4 network with a free /24, and start the core again.")
    several = pool.refusal(N("172.20.0.0/16"), [("alpha", N("172.16.0.0/12")), ("zeta", N("172.20.5.0/24"))])
    assert " Docker networks holding part of it: alpha (172.16.0.0/12), zeta (172.20.5.0/24). Set " in several


def test_a_refusal_with_no_holder_names_the_setting_alone() -> None:
    assert pool.refusal(N("198.51.100.0/24"), []) == (
        "The pool 198.51.100.0/24 has no /24 that neither a Docker network nor another twin holds. "
        "Set FYLGJA_LAB_POOL to an IPv4 network with a free /24, and start the core again.")


def test_the_variable_is_the_one_the_settings_read() -> None:
    assert pool.VARIABLE == "FYLGJA_LAB_POOL"
    assert config.lab_pool({pool.VARIABLE: "198.51.100.0/24"}) == N("198.51.100.0/24")


def test_the_format_asks_each_networks_name_and_its_ipam_config() -> None:
    assert pool.FORMAT == "{{json .Name}} {{json .IPAM.Config}}"


def test_the_networks_are_each_name_with_each_ipv4_subnet_it_holds() -> None:
    # Lines as Docker 29.8.1 printed them for `FORMAT` (verified-facts.md): a name as a JSON string, one space, and
    # the IPAM config, a list or `null`. A network with no IPv4 subnet gives nothing, and an IPv6 subnet is passed over.
    answered = (
        '"bridge" [{"Subnet":"172.17.0.0/16","Gateway":"172.17.0.1"}]\n'
        '"host" null\n'
        '"empty" []\n'
        '"six" [{"Subnet":"2001:db8::/64","Gateway":"2001:db8::1"}]\n'
        '"dual" [{"Subnet":"198.51.100.0/24","Gateway":"198.51.100.1"},{"Subnet":"2001:db8:1::/64"}]\n'
        '"two" [{"Subnet":"192.0.2.0/25"},{"Subnet":"192.0.2.128/25"}]\n'
    )
    assert pool.networks(answered) == [
        ("bridge", N("172.17.0.0/16")), ("dual", N("198.51.100.0/24")),
        ("two", N("192.0.2.0/25")), ("two", N("192.0.2.128/25"))]
    assert pool.networks("") == [] and pool.networks("\n") == []


def test_a_name_that_holds_a_line_separator_is_one_networks_still() -> None:
    # Docker ends a network's line with a newline. Should a name hold what `str.splitlines` also splits on, U+0085 or
    # U+2028 say, or a space, it is one network's still: the answer is split on the newline alone, and the name read
    # as the JSON string it is. Whether Docker lets a name hold one was not read.
    for name in ("a\u0085b", "a\u2028b", "a b", 'a "b" (c), d'):
        line = json.dumps(name, ensure_ascii=False) + ' [{"Subnet":"198.51.100.0/24","Gateway":"198.51.100.1"}]\n'
        assert pool.networks('"host" null\n' + line) == [(name, N("198.51.100.0/24"))], name


def test_the_refusal_quotes_a_name_that_is_not_plain() -> None:
    # A plain name, letters, digits, `_`, `.` and `-` after a letter or digit, is written as it is; any other reaches
    # the finding as a JSON string, so that a space, a comma, a parenthesis or a control character cannot be misread.
    def named(name: str) -> str:
        return pool.refusal(N("198.51.100.0/24"), [(name, N("198.51.100.0/24"))])

    def holding(written: str) -> str:
        return f" Docker networks holding part of it: {written} (198.51.100.0/24). Set "

    for plain in ("lab", "fylgja-core-netbox_default", "0a.b-c_d"):
        assert holding(plain) in named(plain)
    for name, written in [
        ("a b", '"a b"'),
        ("a, b", '"a, b"'),
        ("lab (198.51.100.0/24), other", '"lab (198.51.100.0/24), other"'),
        ("a\nb", '"a\\nb"'),
        ("a\u0085b", '"a\\u0085b"'),
        ('a"b', '"a\\"b"'),
        ("-lab", '"-lab"'),
        ("", '""'),
    ]:
        assert holding(written) in named(name), name
