from ipaddress import IPv4Network as N

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
