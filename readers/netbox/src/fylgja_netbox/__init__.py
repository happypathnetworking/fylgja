"""Fylgja's NetBox reader: a branch of NetBox's branching plugin, or `main`, read into a blueprint, or the findings
that refused it (D-095).

The library logs under `fylgja.netbox`, and gives that logger a `NullHandler`, as the logging HOWTO advises a library:
where the program attaches no handler, Python's last resort prints nothing of it, and one that wants the log attaches
a handler of its own.
"""

import logging

from fylgja_netbox.document import Match, ReaderDocument
from fylgja_netbox.read import Result, check, read
from fylgja_netbox.rows import Source
from fylgja_netbox.transport import SUPPORTED, NetBox, NetBoxError, connect, redact

logging.getLogger("fylgja.netbox").addHandler(logging.NullHandler())

__all__ = [
    "SUPPORTED",
    "Match",
    "NetBox",
    "NetBoxError",
    "ReaderDocument",
    "Result",
    "Source",
    "check",
    "connect",
    "read",
    "redact",
]
