"""Fylgja's Infrahub reader: a branch of Infrahub read into a blueprint, or the findings that refused it (D-082).

The library logs under `fylgja.infrahub`, and gives that logger a `NullHandler`, as the logging HOWTO advises a
library: where the program attaches no handler, Python's last resort prints nothing of it, and one that wants the log
attaches a handler of its own.
"""

import logging

from fylgja_infrahub.document import Match, ReaderDocument
from fylgja_infrahub.read import Refused, Result, check_schema, head, read
from fylgja_infrahub.rows import Source
from fylgja_infrahub.transport import SUPPORTED, Infrahub, InfrahubError, connect

logging.getLogger("fylgja.infrahub").addHandler(logging.NullHandler())

__all__ = [
    "SUPPORTED",
    "Infrahub",
    "InfrahubError",
    "Match",
    "ReaderDocument",
    "Refused",
    "Result",
    "Source",
    "check_schema",
    "connect",
    "head",
    "read",
]
