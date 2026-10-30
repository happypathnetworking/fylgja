"""The rehearsal's report posted on its proposed change (R-11; D-049, D-053): the code of
`infrahub/checks/fylgja_api.py`'s `post_comment`, moved to the rehearse flow, which posts
what the check posted. One comment as the proposed change's view shows one and writes one: a
`CoreChangeThread` on the proposed change, then one `CoreThreadComment` in it whose text is
the report's markdown, both saved on the default branch through the SDK. The overview lists
the proposed change's events, and only a thread's creation is one of them; a
`CoreChangeComment` is counted but never shown (015's research §5.9). A thread whose comment
cannot be saved is deleted, as the view deletes its own, so that no empty thread is left.

The markdown's 4,092-byte cut is the renderer's (`documents.rehearsal.COMMENT_MAX`): what
arrives here already fits. No sentence names the token.
"""

import time
from collections.abc import Callable, Mapping

from .client import TIMEOUT_S, ConfigError, _sdk, _sdk_settings, env_credentials, redact

DEFAULT_BRANCH = "main"
"""The branch the proposed change and its comments live on."""

THREAD_LABEL = "Conversation"
"""The label the proposed change's view gives the thread it opens for a comment written in
its overview, and so the one a comment posted here carries."""

MAX_CAUSE_CHARS = 500


class Unfinished(Exception):
    """A call the time given left no room for."""


def cause(exc: BaseException) -> str:
    """An error as one bounded line: a GraphQL error's messages, as the SDK carries them, rather
    than its query, which would quote the comment's markdown; otherwise its first line."""
    errors = getattr(exc, "errors", None)
    if isinstance(errors, list) and errors:
        text = "; ".join(e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in errors)
    else:
        lines = str(exc).strip().splitlines()
        text = lines[0] if lines else type(exc).__name__
    return text if len(text) <= MAX_CAUSE_CHARS else text[: MAX_CAUSE_CHARS - 1] + "…"


def post_comment(client, change_id: str, text: str, by: float | None = None,
                 clock: Callable[[], float] = time.monotonic) -> str | None:
    """One comment on the proposed change: a thread on it, then one comment in it holding
    text, both on the default branch. None when posted; otherwise why not, for the flow to
    file as rehearsal.report.unposted, since a comment that cannot be posted changes no status.

    With by, a `clock` value, no call is made once it has passed, the empty thread's delete
    among them, each named in what is returned; each call is bounded by the SDK's own timeout."""
    thread = None

    def within(call: Callable, what: str):
        if by is not None and by - clock() <= 0:
            raise Unfinished(f"{what} was not made: no time remained")
        return call()

    try:
        thread = within(lambda: client.create(kind="CoreChangeThread", branch=DEFAULT_BRANCH,
                                              data={"change": change_id, "label": THREAD_LABEL, "resolved": False}),
                        "the thread's creation")
        within(thread.save, "the thread's save")
        comment = within(lambda: client.create(kind="CoreThreadComment", branch=DEFAULT_BRANCH,
                                               data={"text": text, "thread": thread.id}),
                         "the comment's creation")
        within(comment.save, "the comment's save")
    except Exception as exc:  # noqa: BLE001 - reported, and the status stays the report's
        failure = cause(exc)
        if thread is not None and getattr(thread, "id", None):
            try:
                within(thread.delete, "the delete")
            except Unfinished as left:
                failure += f"; its empty thread {thread.id} is left: {left}"
            except Exception as left:  # noqa: BLE001 - reported beside the first
                failure += f"; its empty thread {thread.id} could not be deleted: {cause(left)}"
        return failure
    return None


def client_from_env(environ: Mapping[str, str]):
    """The SDK's client of the default branch from INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN, as
    every read of the adapter's is built; ConfigError naming the variable when one is unset."""
    address, token = env_credentials(environ)
    _, sdk_client, _, _ = _sdk()
    client = sdk_client(address=address, config=_sdk_settings(token))
    client.default_branch = DEFAULT_BRANCH
    return client


def post(environ: Mapping[str, str], change_id: str, text: str, by: float | None = None) -> str | None:
    """The report posted with the environment's credentials: None when posted, else why not,
    the token never named."""
    try:
        client = client_from_env(environ)
    except ConfigError as e:
        return str(e)
    failure = post_comment(client, change_id, text, by)
    if failure is None:
        return None
    _, token = env_credentials(environ)
    return redact(failure, token)


__all__ = ["DEFAULT_BRANCH", "THREAD_LABEL", "TIMEOUT_S", "cause", "client_from_env", "post", "post_comment"]
