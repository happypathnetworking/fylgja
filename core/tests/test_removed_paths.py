"""What left this repository for `fylgja-examples` is named by no tracked file as a path of this one (D-126): a link
into `fylgja-examples` is not such a name, and `design/` and `CHANGELOG.md` are history and keep the old paths."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REMOVED = (
    "orchestrator/",
    "scripts/demo.py",
    "scripts/edge_dev.py",
    "scripts/demo_dependencies.sh",
    "plan-1.schema.json",
    "rehearsal-1.schema.json",
)
HISTORY = ("design/", "CHANGELOG.md")
# A path is a name when no word character, dot or hyphen runs into it: fylgja_orchestrator/ is a package's.
BOUNDARY = r"(?<![\w.-])"
URL = r"https://github\.com/happypathnetworking/fylgja-examples/[^\s)]*"
LINK = re.compile(r"\[[^\]]*\]\(" + URL + r"\)|" + URL)
# Files the next tasks of the trim remove whole, each with the example's seed script or test that names the path.
PENDING = (
    "netbox/seed/hook.py",
    "netbox/seed/change.py",
    "netbox/tests/test_hook.py",
    "netbox/tests/test_change.py",
)


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [name for name in out.split("\0") if name and not name.startswith(HISTORY)]


def test_the_scan_is_not_blind() -> None:
    assert len(_tracked()) > 100
    link = "https://github.com/happypathnetworking/fylgja-examples/blob/v1.1.0/orchestrator/x.md"
    assert LINK.sub("", f"see {link} now") == "see  now"
    assert LINK.sub("", f"see [`orchestrator/`]({link}) now") == "see  now"
    assert re.search(BOUNDARY + re.escape("orchestrator/"), "see orchestrator/rules.md")
    assert not re.search(BOUNDARY + re.escape("orchestrator/"), "fylgja_orchestrator/__init__.py")


def test_no_tracked_file_names_a_removed_path() -> None:
    found: list[str] = []
    for name in _tracked():
        if name == "core/tests/test_removed_paths.py" or name in PENDING or not (ROOT / name).is_file():
            continue
        try:
            body = (ROOT / name).read_text()
        except UnicodeDecodeError:
            continue
        body = LINK.sub("", body)
        for number, line in enumerate(body.splitlines(), 1):
            for path in REMOVED:
                if re.search(BOUNDARY + re.escape(path), line):
                    found.append(f"{name}:{number}: {path}")
    assert found == []
    assert not [name for path in REMOVED if path.endswith("/") for name in _tracked() if name.startswith(path)]
