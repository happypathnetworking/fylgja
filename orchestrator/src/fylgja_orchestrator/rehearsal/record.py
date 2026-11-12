"""The record a twin (D-086): which change, and which stage of it, a twin `twin create` or `twin step` made stands at.

The core's record of a twin names its blueprint and no stage, so the commands keep a file a twin of their own,
`<root>/twins/<twin>.json`, under the root their caller gives them. It is trusted only while its blueprint id is the
one the twin runs: a twin stepped or made again by anyone else since leaves its record behind, and the record then
says nothing. One writer and one reader, both here, so it is no format of Fylgja's; no database (Constitution IX).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

VERSION = "1"
# A twin's name as the core takes it, twin-record-1's pattern: a DNS-1123 label of at most 40 characters.
TWIN_NAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?")


@dataclass(frozen=True)
class Record:
    """Where a twin stands: its name; the change, by the source's id for it, the reference it was named by and the
    scope its stages were read under; the label of the stage; the blueprint that stage read as, which the twin ran
    when this was written; and when that was, in RFC 3339, UTC to the second."""

    twin: str
    change_id: str
    ref: str
    scope: str
    label: str
    blueprint_id: str
    written_at: str


def write(root: Path, record: Record) -> None:
    """`record` as `<root>/twins/<twin>.json`, replacing whatever was there whole: written to a file beside it and
    moved in by `os.replace`, so a reader finds the old record or the new, never half of one. A twin name that is no
    twin name is a `ValueError`, before any path is made."""
    _named(record.twin)
    directory = root / "twins"
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / f".tmp-{secrets.token_hex(8)}"
    try:
        temp.write_text(json.dumps({"record_version": VERSION, **asdict(record)}, indent=2) + "\n")
        os.replace(temp, directory / f"{record.twin}.json")
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise


def read(root: Path, twin: str) -> Record | None:
    """The record of `twin` under `root`; None where there is none, where the file is no version-1 record of that
    twin, and for a name that is no twin name, since no record can be written under one: its path is never made."""
    if not TWIN_NAME.fullmatch(twin):
        return None
    try:
        doc = json.loads((root / "twins" / f"{twin}.json").read_text())
    except (FileNotFoundError, ValueError):  # no file, or one that is not JSON in UTF-8
        return None
    return _record(doc, twin)


def listed(root: Path) -> tuple[Record, ...]:
    """Every record under `root`, by twin name: a file that is no record of the twin it is named for is left out."""
    directory = root / "twins"
    if not directory.is_dir():
        return ()
    found = (read(root, path.stem) for path in directory.glob("*.json"))
    return tuple(sorted((record for record in found if record is not None), key=lambda record: record.twin))


def trusted(record: Record, twin: Mapping[str, Any]) -> bool:
    """Whether `record` says where `twin`, the core's record of it, stands: its blueprint id is the one the twin
    runs."""
    running: str | None = twin["status"].get("blueprint_id")
    return record.blueprint_id == running


def _named(twin: str) -> None:
    if not TWIN_NAME.fullmatch(twin):
        raise ValueError(f"{twin!r} is not a twin name: a DNS-1123 label of at most 40 characters")


def _record(doc: Any, twin: str) -> Record | None:
    """The record `doc` holds, if it is a version-1 record of `twin`: every member a string, and no other."""
    names = [f.name for f in fields(Record)]
    if not isinstance(doc, dict) or doc.get("record_version") != VERSION or set(doc) != {"record_version", *names}:
        return None
    if not all(isinstance(doc[name], str) for name in names) or doc["twin"] != twin:
        return None
    return Record(**{name: doc[name] for name in names})
