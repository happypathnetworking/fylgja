"""The clabernetes driver: a twin as a containerlab topology in its own Kubernetes namespace,
kept apart by the network (D-019, D-057).

Its names, which its plan and its `apply` share so that the two cannot disagree: every object
the driver makes is labelled `OWNER_LABEL: OWNER` and `TWIN_LABEL: <twin>`, a twin runs in the
namespace `namespace_of(twin)`, and the Secret a pull credential becomes there is named
`pull_secret(key)`. This module imports the seam alone.
"""

from fylgja_core.driver import Capabilities

NAME = "clabernetes"

CAPABILITIES = Capabilities(
    nodes="provisions", relink=True, forwarding="software", access="direct", isolation="network", reapply=True)

OWNER_LABEL = "fylgja.owner"
OWNER = "core"
TWIN_LABEL = "fylgja.twin"


def namespace_of(twin: str) -> str:
    """The namespace the twin `twin` runs in, its own."""
    return f"fylgja-twin-{twin}"


def pull_secret(key: str) -> str:
    """The name of the pull secret, in a twin's namespace, for a pull credential's key as
    `credentials.key` writes it: the key lower-cased, its underscores as dashes, so that it is
    `fylgja-pull-<pull_secret>` for a package's `image.pull_secret`."""
    return "fylgja-pull-" + key.lower().replace("_", "-")
