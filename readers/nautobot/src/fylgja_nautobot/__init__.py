"""Fylgja's Nautobot reader: Nautobot as it stands, read into a blueprint, or the findings that refused it (D-118).

The library logs under `fylgja.nautobot`, and gives that logger a `NullHandler`, as the logging HOWTO advises a library:
where the program attaches no handler, Python's last resort prints nothing of it, and one that wants the log attaches
a handler of its own.
"""

import logging

from fylgja_nautobot.document import Match, ReaderDocument
from fylgja_nautobot.read import Result, check, read
from fylgja_nautobot.rows import Source
from fylgja_nautobot.transport import SUPPORTED, Nautobot, NautobotError, connect, redact

logging.getLogger("fylgja.nautobot").addHandler(logging.NullHandler())

__all__ = [
    "SUPPORTED",
    "Match",
    "Nautobot",
    "NautobotError",
    "ReaderDocument",
    "Result",
    "Source",
    "check",
    "connect",
    "read",
    "redact",
]
