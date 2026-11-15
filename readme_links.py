"""A README's relative links written absolute, under the tree of the release's tag, for the index that publishes it.

Each published distribution's description is its README (D-106), and a relative link resolves nowhere on an index. The
three `setup.py` files, which read the repository's root for `VERSION`, load this file from there by path and call
`readme`, so the rule is written once; `scripts/wheelcheck.py` and the tests load it the same way.

A link `[t](target)` or a reference definition `[t]: target` whose target has no scheme and does not begin `//` is made
absolute: joined to the README's own directory, normalised, and put under
`https://github.com/happypathnetworking/fylgja/blob/v<version>/`, or under `raw/` where it is an image. A target that
is an anchor alone is the README's own page. A target that climbs above the root is an error. An absolute link (a
network path and a one-letter scheme among them), and anything inside fenced or inline code (`scripts/linkcheck.py`'s
FENCE and INLINE), stays as it is.
"""

import posixpath
import re
from pathlib import Path

REPOSITORY = "https://github.com/happypathnetworking/fylgja"
README_BASE = REPOSITORY + "/blob/v{version}/"
IMAGE_BASE = REPOSITORY + "/raw/v{version}/"

_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*:")
_PARTS = re.compile(
    r"(?P<code>^(?P<fence>```|~~~).*?^(?P=fence)[^\n]*$|`[^`\n]*`)"
    r"|(?P<head>!?\[[^\]]*\]\()(?P<target>[^)\s]+)(?P<tail>(?:\s+\"[^\"]*\")?\))"
    r"|(?P<refhead>^\[[^\]]+\]:[ \t]*)(?P<reftarget>\S+)",
    re.M | re.S,
)


def readme_text(text: str, directory: str, version: str) -> str:
    """`text`, the README of `directory` (from the root, "" for the root's own), with its relative links absolute."""

    def absolute(target: str, image: bool) -> str:
        if _SCHEME.match(target) or target.startswith("//"):
            return target
        path, hash_, fragment = target.partition("#")
        path = posixpath.normpath(posixpath.join(directory, path)) if path else posixpath.join(directory, "README.md")
        if path.startswith("/") or path == ".." or path.startswith("../"):
            raise ValueError(f"{target!r} in the README of {directory or '.'!r} climbs above the root")
        return (IMAGE_BASE if image else README_BASE).format(version=version) + path + hash_ + fragment

    def one(found: re.Match[str]) -> str:
        if found.group("code") is not None:
            return found.group(0)
        if found.group("target") is not None:
            head = found.group("head")
            return head + absolute(found.group("target"), head.startswith("!")) + found.group("tail")
        return found.group("refhead") + absolute(found.group("reftarget"), False)

    return _PARTS.sub(one, text)


def readme(root: Path, directory: str, version: str) -> str:
    """The `README.md` under `root`/`directory`, as `readme_text` writes it."""
    return readme_text((root / directory / "README.md").read_text(), directory, version)
