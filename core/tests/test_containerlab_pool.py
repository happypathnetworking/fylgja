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
