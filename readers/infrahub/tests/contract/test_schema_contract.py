"""The schema check against the development Infrahub: the seeded `main`'s present schema holds every kind and field
the mapping reads as the table has them (CONTRIBUTING.md, Test tiers; design/verified-facts.md, "Infrahub 1.11.11").
No assertion message prints the address or a token."""

from __future__ import annotations

import re

from fylgja_infrahub import Infrahub
from fylgja_infrahub.schema import check


def test_the_seeded_branch_conforms(conn: Infrahub) -> None:
    """It ties the table's required fields, peers, choices and users to the instance by inclusion, and cannot catch a
    row the table marks optional where the instance reads it required, since the check holds optionality one way
    (P3-21)."""
    held = conn.schema("main")
    assert re.fullmatch(r"[0-9a-f]+", held.hash), "the schema's hash is no hex digits"
    assert check(held, branch="main") == ()
