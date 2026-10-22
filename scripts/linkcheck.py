#!/usr/bin/env python3
"""Check the relative links and anchors of every tracked Markdown file.

Run from the repository root: `python3 -I scripts/linkcheck.py`, or `make linkcheck`.
Exit 0 when every link resolves, 1 when any does not, listing each as
`path:line: target  [why]`. A hand tool, not a CI step.

A link resolves when its target is a tracked file or directory (`git ls-files`: a file
that is on disk but git-ignored counts as missing, as it is in a public clone) and, when
it carries a fragment, the target is a Markdown file holding that anchor: a heading as
GitHub slugs it (lowercase; letters, digits, hyphens, underscores and spaces kept, the
rest dropped; spaces to hyphens; a repeated heading gets `-1`, `-2`, ...), or an explicit
`<a id="...">`, `<a name="...">` or `{#...}`. Text inside fenced or inline code is not a
link. Absolute URLs, of any scheme, are not checked. Reference-style definitions
(`[name]: target`) are checked like inline links.
"""

import collections
import os
import re
import subprocess
import sys
import urllib.parse

FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.M | re.S)
INLINE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"!?\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
REFDEF = re.compile(r"^\[([^\]]+)\]:\s*(\S+)", re.M)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
EXPLICIT = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"|\{#([^}]+)\}")


def git_files():
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True)
    return {f.decode() for f in out.stdout.split(b"\0") if f}


def blank_fences(text):
    """Replace fenced code blocks with newlines, so line numbers hold."""
    return FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def blank_code(text):
    """Blank fenced blocks and inline code spans, keeping every offset."""
    return INLINE.sub(lambda m: " " * len(m.group(0)), blank_fences(text))


def slug(heading):
    heading = re.sub(r"<[^>]+>", "", heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")


def anchors(text):
    """The anchors a Markdown document offers, as GitHub renders them."""
    seen = collections.Counter()
    ids = set()
    for m in HEADING.finditer(blank_fences(text)):
        base = slug(m.group(1))
        n = seen[base]
        seen[base] += 1
        ids.add(base if n == 0 else f"{base}-{n}")
    for m in EXPLICIT.finditer(text):
        ids.add(m.group(1) or m.group(2))
    return ids


def main():
    if len(sys.argv) > 1:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: python3 -I scripts/linkcheck.py (no arguments)", file=sys.stderr)
        return 2
    tracked = git_files()
    dirs = {""}
    for f in tracked:
        d = os.path.dirname(f)
        while d and d not in dirs:
            dirs.add(d)
            d = os.path.dirname(d)
    docs = sorted(f for f in tracked if f.endswith(".md"))
    texts = {f: open(f, encoding="utf-8").read() for f in docs}
    anchor_cache = {}
    checked = external = 0
    broken = []
    for f in docs:
        text = blank_code(texts[f])
        found = [(m.group(2), m.start()) for m in LINK.finditer(text)]
        found += [(m.group(2), m.start()) for m in REFDEF.finditer(text)]
        for target, pos in found:
            target = target.strip("<>")
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):
                external += 1
                continue
            checked += 1
            line = text.count("\n", 0, pos) + 1
            path, _, fragment = target.partition("#")
            path = urllib.parse.unquote(path)
            dest = f if not path else os.path.normpath(os.path.join(os.path.dirname(f), path))
            if path and dest not in tracked and dest not in dirs:
                broken.append((f, line, target, "missing file"))
            elif fragment and dest in tracked and dest.endswith(".md"):
                if dest not in anchor_cache:
                    anchor_cache[dest] = anchors(texts.get(dest) or open(dest, encoding="utf-8").read())
                if fragment not in anchor_cache[dest]:
                    broken.append((f, line, target, "missing anchor"))
            elif fragment and dest in dirs and dest not in tracked:
                broken.append((f, line, target, "fragment on a directory"))
    print(f"{len(docs)} files, {checked} relative links checked, {external} external skipped, "
          f"{len(broken)} broken")
    for f, line, target, why in broken:
        print(f"{f}:{line}: {target}  [{why}]")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
