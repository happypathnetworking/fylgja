"""A rehearsal's twin, named from the change and the run (D-086).

The name is `rh-<8 hex of sha256(change.id)>-<8 hex of sha256(run_id)>`: 20 characters whatever either id holds,
within the 40 a twin's name has, and lower-case letters, digits and dashes alone, as a twin's name takes. Every twin
a rehearsal of one change makes starts with that change's prefix, so a rehearsal finds the others of its change by it.
"""

from __future__ import annotations

from hashlib import sha256

from fylgja_orchestrator.rehearsal.source import Change


def _hashed(value: str) -> str:
    """The first 8 hex characters of the SHA-256 of `value`'s UTF-8."""
    return sha256(value.encode()).hexdigest()[:8]


def twin_prefix(change: Change) -> str:
    """The start of every twin's name a rehearsal of `change` makes: `rh-`, the change's 8 hex characters and a
    dash."""
    return f"rh-{_hashed(change.id)}-"


def twin_name(change: Change, run_id: str) -> str:
    """The twin the run `run_id` rehearses `change` on."""
    return twin_prefix(change) + _hashed(run_id)
