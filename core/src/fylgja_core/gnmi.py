"""The gNMI reader of the fact vocabulary: one Get of a package's conformance paths (D-030, D-052).

pygnmi is the one mechanism, keyed by the package's `gnmi` section: TLS or plaintext, the
port, json_ietf, and a boot-time certificate accepted unverified. pygnmi is synchronous, so
the call runs in a daemon thread of its own, the whole read bounded by its budget: at most
`READ_THREADS` at once, a read finding none free waiting for one within its budget, and at most
one per node's address, so a node whose last read still runs is unreadable at once. A message
names where and what, never a credential or an answer.

The answer is mapped back to the paths asked element by element, a module prefix stripped
from each name (verified-facts.md, "gNMI" under SR Linux and cEOS). An update at or under an
asked path is collected into its value: a list asked without a key is its entries, one per
update at an entry; an update above an asked path is read down to it. A path no update reaches
is left out, so an absent value is never taken for another; an answer the reader cannot map is
`Unreadable`.
- SR Linux answers each path in a notification of its own, its elements prefixed
  (`srl_nokia-system:system/...`), and a neighbour list at the entry above it: the update
  at `.../interface[name=X]` holds `{"neighbor": [...]}`.
- cEOS answers bare OpenConfig elements, and a neighbour list one update per entry
  (`.../neighbors/neighbor[id=1]`), each entry's members prefixed (`openconfig-lldp:state`).
- An absent value is a notification with no update, on both.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import threading
import time
from collections.abc import Awaitable, Sequence
from typing import Any, Protocol

import grpc
from pygnmi.client import gNMIclient

from fylgja_core.credentials import Credential
from fylgja_core.node_http import authority
from fylgja_core.platform_package import PlatformPackage

GNMI_TIMEOUT_S = 15.0
RULE_UNREAD = "verify.node.unread"
READ_THREADS = 16
SLOT_POLL_S = 0.05  # between looks for a free read thread

# The reads' threads. pygnmi's Get has no deadline, so a read abandoned at its budget runs on in
# its thread until the node's TCP gives up (verified-facts.md, "An abandoned read keeps its
# thread"). Each read is a daemon thread of its own, never one of an executor's: the loop's close
# joins its default executor (`asyncio.Runner.close` waits up to 300 s) and the interpreter's exit
# joins every executor's workers, while neither waits on a daemon thread. `_SLOTS` bounds them, and
# a thread frees its slot when pygnmi returns, whether or not its caller still waits. `_READING`
# holds the addresses whose read's thread still runs: a node is read by one thread at a time, so a
# lost node's retries never add stuck threads.
_SLOTS = threading.BoundedSemaphore(READ_THREADS)
_READING: set[str] = set()
_LOCK = threading.Lock()


class Unreadable(Exception):
    """The node's state could not be read over gNMI: where, and the gRPC status or the error's type."""

    rule = RULE_UNREAD

    def __init__(self, where: str, what: str) -> None:
        super().__init__(f"{where} unreadable over gNMI: {what}")
        self.where = where
        self.what = what


class ReadFn(Protocol):
    """`get`'s signature, for injection."""

    def __call__(
        self,
        address: str,
        package: PlatformPackage,
        credential: Credential,
        paths: Sequence[str],
        *,
        timeout_s: float = ...,
    ) -> Awaitable[dict[str, Any]]: ...


Element = tuple[str, tuple[tuple[str, str], ...]]
"""One path element: its name without a module prefix, and its keys, sorted."""

_ELEMENT = re.compile(r"(?:[^/\[]|\[[^\]]*\])+")
_KEY = re.compile(r"\[([^=\]]+)=([^\]]*)\]")
_QUOTED = re.compile(r"""^(['"])(.*)\1$""")

# pygnmi logs through a stdout handler of its own beside the root's (a line on every TLS dial),
# and at CRITICAL quotes a failed call's gRPC details, the node's own words. The core's log is
# JSON on stderr and quotes no node, and `Unreadable` carries the status: pygnmi's log is dropped.
_PYGNMI_LOG = logging.getLogger("pygnmi.client")
_PYGNMI_LOG.handlers[:] = [logging.NullHandler()]
_PYGNMI_LOG.propagate = False


def _bare(name: str) -> str:
    """A YANG name without its module prefix: `srl_nokia-system:system` is `system`."""
    return name.rsplit(":", 1)[-1]


def _text(value: Any) -> str:
    """A key's value as both sides compare it: its text, spaces round it and one pair of quotes
    round it dropped, the spaces within kept (`[name="my vrf"]` and `"my vrf"` alike)."""
    text = str(value).strip()
    quoted = _QUOTED.match(text)
    return quoted.group(2) if quoted else text


def _elements(path: str) -> tuple[Element, ...]:
    """A path's elements, split at each `/` outside a key's brackets, each name stripped of
    spaces and of its module prefix and each key value read by `_text`. Elements are compared by
    those bare names, so two modules' elements of one name at one place are read as one, where
    `_member` reads two such members of one object as absent; neither kind answers either. It
    does not read a gNMI `origin:` before the first element."""
    found: list[Element] = []
    for part in _ELEMENT.findall(path):
        name = part.split("[", 1)[0].strip()
        if not name:
            continue
        keys = tuple(sorted((_bare(k.strip()), _text(v)) for k, v in _KEY.findall(part)))
        found.append((_bare(name), keys))
    return tuple(found)


def _member(node: dict[str, Any], name: str) -> Any:
    """The member `name` of a json_ietf object, matched with or without its module prefix; None
    when absent, or when two members of different modules share the name."""
    if name in node:
        return node[name]
    found = [value for key, value in node.items() if _bare(key) == name]
    return found[0] if len(found) == 1 else None


def _merge(into: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    """`value`'s members copied into `into`, objects merged member by member."""
    for key, member in value.items():
        if isinstance(member, dict):
            into[key] = _merge(into[key] if isinstance(into.get(key), dict) else {}, member)
        else:
            into[key] = member
    return into


def _keyed(entry: Any, keys: tuple[tuple[str, str], ...]) -> bool:
    """Whether a list entry holds `keys`, each its member's text as `_text` reads it."""
    return isinstance(entry, dict) and all(
        (member := _member(entry, k)) is not None and _text(member) == v for k, v in keys)


def _entry(node: dict[str, Any], name: str, keys: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    """The entry with `keys` of the list `name` in `node`, made when absent."""
    entries: list[dict[str, Any]] = node.setdefault(name, [])
    found = next((entry for entry in entries if _keyed(entry, keys)), None)
    if found is None:
        found = dict(keys)  # its keys among its members, so that a later update finds it
        entries.append(found)
    return found


def _place(tree: dict[str, Any], elements: Sequence[Element], value: Any) -> None:
    """`value` put at `elements` inside `tree`: a keyed element is the entry of a list with its
    keys among its members, and an object is merged into what is there."""
    node = tree
    *above, (last, keys) = elements
    for name, at in above:
        node = _entry(node, name, at) if at else node.setdefault(name, {})
    if keys:
        entry = _entry(node, last, keys)
        if isinstance(value, dict):
            _merge(entry, value)
            for k, _ in keys:  # a key the value holds under its module's prefix is kept once, as answered
                if k not in value and _member(value, k) is not None:
                    del entry[k]
    elif isinstance(value, dict):
        node[last] = _merge(node[last] if isinstance(node.get(last), dict) else {}, value)
    else:
        node[last] = value


def _descend(value: Any, elements: Sequence[Element]) -> Any:
    """The member at `elements` inside a json_ietf value, a keyed element its one matching
    entry; None when absent."""
    node = value
    for name, keys in elements:
        node = _member(node, name) if isinstance(node, dict) else None
        if keys:
            matches = [entry for entry in node if _keyed(entry, keys)] if isinstance(node, list) else []
            node = matches[0] if len(matches) == 1 else None
        if node is None:
            return None
    return node


def _value(asked: tuple[Element, ...], updates: Sequence[tuple[tuple[Element, ...], Any]]) -> Any:
    """The asked path's value from the updates: those at or under it collected, an asked list
    with no key answered by its entries; else read down from an update above it; else None."""
    if not asked:
        return None
    depth, (name, keys) = len(asked), asked[-1]
    under = [(at, value) for at, value in updates
             if len(at) >= depth and at[: depth - 1] == asked[:-1] and at[depth - 1][0] == name
             and (at[depth - 1][1] == keys or not keys)]
    if under:
        tree: dict[str, Any] = {}
        for at, value in under:
            _place(tree, ((name, at[depth - 1][1] if not keys else ()), *at[depth:]), value)
        return tree[name]
    for at, value in updates:
        if len(at) < depth and asked[: len(at)] == at:
            found = _descend(value, asked[len(at):])
            if found is not None:
                return found
    return None


def _answer(paths: Sequence[str], reply: dict[str, Any]) -> dict[str, Any]:
    """Each asked path the updates reach, mapped to its value; one none reaches is left out."""
    updates: list[tuple[tuple[Element, ...], Any]] = []
    for note in reply.get("notification") or []:
        prefix = _elements(str(note.get("prefix") or ""))
        for update in note.get("update") or []:
            updates.append((prefix + _elements(str(update.get("path") or "")), update.get("val")))
    return {path: value for path in paths if (value := _value(_elements(path), updates)) is not None}


def _read(
    address: str, package: PlatformPackage, credential: Credential, paths: Sequence[str], timeout_s: float
) -> Any:
    tls = package.gnmi.tls
    with gNMIclient(
        target=(address, package.gnmi.port),
        username=credential.username,
        password=credential.password,
        insecure=not tls,
        skip_verify=tls,
        gnmi_timeout=timeout_s,
    ) as client:
        return client.get(path=list(paths), encoding="json_ietf")


def _claim(address: str) -> bool:
    """Whether `address` was free to read, and is now marked being read."""
    with _LOCK:
        if address in _READING:
            return False
        _READING.add(address)
        return True


def _unclaim(address: str) -> None:
    with _LOCK:
        _READING.discard(address)


async def _slot(where: str, deadline: float) -> None:
    """A read thread's slot, taken once one is free before `deadline`; else `Unreadable`."""
    while not _SLOTS.acquire(blocking=False):
        if time.monotonic() >= deadline:
            raise Unreadable(where, "no read thread free")
        await asyncio.sleep(SLOT_POLL_S)


def _reading(
    loop: asyncio.AbstractEventLoop, answer: asyncio.Future[Any], address: str, package: PlatformPackage,
    credential: Credential, paths: Sequence[str], timeout_s: float,
) -> None:
    """A read thread's work: pygnmi's Get, then the slot and the address freed, then the reply or
    the error handed to the loop, unless its caller has stopped waiting or the loop has closed."""
    reply: Any = None
    error: Exception | None = None
    try:
        reply = _read(address, package, credential, paths, timeout_s)
    except Exception as e:
        error = e
    finally:
        _unclaim(address)
        _SLOTS.release()

    def hand() -> None:
        if answer.done():  # the caller's budget ran out first
            return
        if error is not None:
            answer.set_exception(error)
        else:
            answer.set_result(reply)

    with contextlib.suppress(RuntimeError):  # the loop has closed: no one waits for the answer
        loop.call_soon_threadsafe(hand)


async def get(
    address: str,
    package: PlatformPackage,
    credential: Credential,
    paths: Sequence[str],
    *,
    timeout_s: float = GNMI_TIMEOUT_S,
) -> dict[str, Any]:
    """One Get of every path; each requested path mapped to its value, a path unreported left out.
    `Unreadable` at once while the address's last read still runs, and once the budget has passed
    with no read thread free."""
    where = authority(address, package.gnmi.port)
    if not _claim(address):
        raise Unreadable(where, "a read of this node is still running")
    deadline = time.monotonic() + timeout_s
    try:
        await _slot(where, deadline)
    except BaseException:
        _unclaim(address)
        raise
    loop = asyncio.get_running_loop()
    answer: asyncio.Future[Any] = loop.create_future()
    thread = threading.Thread(target=_reading, args=(loop, answer, address, package, credential, paths, timeout_s),
                              name=f"fylgja-gnmi {where}", daemon=True)
    try:
        thread.start()
    except BaseException:
        _unclaim(address)
        _SLOTS.release()
        raise
    try:
        # pygnmi fetches a TLS node's certificate with no timeout, and its Get has none: a
        # just-stopped node held a read 38-73 s (verified-facts.md). The thread runs on to its end.
        reply = await asyncio.wait_for(answer, max(0.0, deadline - time.monotonic()))
    except Exception as error:
        # pygnmi wraps a gRPC failure in its own exception, the original on `orig_exc`.
        cause = getattr(error, "orig_exc", None) or error
        code = cause.code() if isinstance(cause, grpc.RpcError) and callable(getattr(cause, "code", None)) else None
        raise Unreadable(where, getattr(code, "name", None) or type(cause).__name__) from None
    try:
        return _answer(paths, reply)
    except Exception as error:  # a shape neither kind answers, such as an object and entries at one list
        raise Unreadable(where, f"the answer could not be read ({type(error).__name__})") from None


def leaf(value: Any, subpath: str) -> Any:
    """The member at a `/`-separated subpath inside a json_ietf value, None when absent; each
    member matched with or without its module prefix (cEOS's `openconfig-lldp:state`).

    A list's one element is taken when it has exactly one, else None.
    """
    node = value
    for part in [p for p in subpath.split("/") if p]:
        if isinstance(node, list):
            node = node[0] if len(node) == 1 else None
        if not isinstance(node, dict):
            return None
        node = _member(node, part)
    return node
