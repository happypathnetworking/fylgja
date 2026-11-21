"""`docs/demonstrations.md` is a short page that says where the demonstrations went: it links `fylgja-examples`' page
of them at its tag, names no make target of this repository, and keeps the heading the entries' links reach."""

from __future__ import annotations

import re

from pages import text

PAGE = "docs/demonstrations.md"
EXAMPLES = "https://github.com/happypathnetworking/fylgja-examples/"


def test_the_page_says_where_the_demonstrations_went() -> None:
    body = text(PAGE)
    assert body.startswith("# The demonstrations\n"), "the heading the entries' links reach"
    assert EXAMPLES + "blob/v1.1.0/docs/demonstrations.md" in body
    assert not re.search(r"make [\w-]+", body), "a make target of the example is not this repository's"
    assert len(body.splitlines()) < 40, "the page is short: what it says is the example's page's"


def test_the_pages_that_link_it_still_reach_it() -> None:
    for page in ("README.md", "docs/README.md", "CHANGELOG.md", "CONTRIBUTING.md"):
        assert "docs/demonstrations.md" in text(page) or "(demonstrations.md" in text(page), page
