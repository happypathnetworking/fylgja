"""The local driver: a twin as a containerlab lab on this host (D-017, D-019)."""

from fylgja_core.driver import Capabilities

NAME = "containerlab"

CAPABILITIES = Capabilities(
    nodes="provisions", relink=True, forwarding="software", access="direct", isolation="names", reapply=False)
