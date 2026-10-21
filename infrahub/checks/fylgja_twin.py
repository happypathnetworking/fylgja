"""fylgja-twin: the proposed change rehearsed on a twin, asked of Fylgja (contracts/checks.md, FR-018).

Infrahub runs it on every open proposed change, at its creation and on each re-run of its
checks. On a draft it asks nothing and passes. Otherwise it asks the API's twin.rehearse for
the source branch, posts the report's markdown as one comment in a new thread on the proposed
change, which its overview shows, logs the report's text as its message, and concludes by the
report's status alone (D-052). That comment, in its thread, is its one write to Infrahub
(D-049, D-053), the thread deleted only when its comment cannot be saved (FR-019); every
verdict, deadline and wording is the server's.
"""

import asyncio
import secrets
import time
from typing import Any

from infrahub_sdk.checks import InfrahubCheck

from .fylgja_api import (
    CLOSE_MARGIN_S,
    RENDER_MARKDOWN,
    Answer,
    Cut,
    Fault,
    call,
    none_open,
    path,
    post_comment,
    proposed_change,
    rejections_past_branch_point,
    variables,
)

# DEADLINE_MARGIN_S is how long before its timeout the check closes its answer: its own
# deadline, at which it interrupts the run and reads the answer on to its document while the
# run cancels and destroys. A check Infrahub times out leaves its validator in_progress and
# the merge blocked (research §1.4), so this deadline, not Infrahub's, is what ends a
# rehearsal that overruns (FR-021, R-16). The timeout less this margin covers the ceiling,
# the destroy's whole budget and the allowance before the run's start (data-model §4); the
# margin less CLOSE_MARGIN_S, the read after the interrupt, covers the destroy's budget.
DEADLINE_MARGIN_S = 240

# CONCLUSION_S is what the comment leaves of the check's timeout for its conclusion: the
# comment's calls to Infrahub are bounded by the rest (T110).
CONCLUSION_S = 5

# DESTROY_S is the destroy's whole budget (PlanTeardown, the largest package's destroy and
# Unstage), and ALLOWANCE_S the time allowed the server before the run's start: the plan, a
# reclaim and the host check, an allowance, not a bound the server enforces (FR-021).
DESTROY_S = 120
ALLOWANCE_S = 300

# RETRY_S is the wait between two asks while the host is held (R-15).
RETRY_S = 30

# HELD are the refusals that say the host is held by a run or a twin, before any start: a
# rehearsal asks again once they clear, where every other refusal is final at once (R-15).
HELD = frozenset({"run.in_flight", "host.lab.present", "host.twin.present"})

# GOES_ON is what FR-021 says of a run whose answer was cut: it goes on to its destroy, and
# nothing reports it here.
GOES_ON = (
    "the run goes on to its destroy and no report will be posted; re-run the checks once fylgja twin show "
    "reports no twin"
)

# LOST is FR-021's sentence for an answer cut once the run had started.
LOST = "the connection to Fylgja was lost while the rehearsal ran; " + GOES_ON


class FylgjaTwin(InfrahubCheck):
    """The proposed change's stages rehearsed on a twin: success when the report's status is ok,
    or on a draft, which is skipped; failure on every other status, when the host is still held
    once what remains of the check's own deadline no longer covers the run it asks for, when
    that deadline cuts the run, and when Fylgja cannot be reached, refuses the token or the
    version, or its answer is cut."""

    # The cheap read the SDK requires (infrahub/queries/branch.gql); its answer is not used.
    query = "fylgja_branch"
    timeout = 4260

    async def validate(self, data: dict[str, Any]) -> None:
        began = time.monotonic()
        deadline = began + self.timeout - DEADLINE_MARGIN_S
        close_by = began + self.timeout - CLOSE_MARGIN_S
        # The draft skip needs nothing of Fylgja's, so it comes before the variables (FR-020).
        try:
            change = await proposed_change(self.client, self.branch_name)
            if change is None:
                self.log_error(none_open(self.branch_name))
                return
            if change.is_draft:
                self.log_info(
                    f"skipped: proposed change {change.id} is a draft; "
                    "mark it ready for review and re-run the checks to rehearse it"
                )
                return
            address, token = variables()
        except Fault as fault:
            self.log_error(str(fault))
            return

        # Ask, and ask again every RETRY_S while the host is held and what would remain of the
        # check's own deadline at the next ask still covers the run it asks for (FR-007, FR-021),
        # so that no run this check starts is interrupted by it. A cancellation by Infrahub
        # while an answer is open interrupts its run from call's handler, with a blocking call
        # (R-16); between two answers no run of this check's is open, and nothing is sent.
        asks = 0
        logged: tuple[str, ...] = ()
        while True:
            asks += 1
            try:
                answer = await call(
                    address,
                    token,
                    path("twin.rehearse"),
                    RENDER_MARKDOWN,
                    {"branch": self.branch_name},
                    stream=secrets.token_hex(16),
                    deadline=deadline,
                    close_by=close_by,
                )
            except Cut as fault:
                self._print(fault.answer)
                if fault.answer.started and fault.answer.interrupted:
                    self.log_error(f"{asked_to_cancel(self.timeout, fault.answer)}; then {fault}; {GOES_ON}")
                elif fault.answer.started:
                    self.log_error(f"{LOST} ({fault})")
                elif fault.answer.interrupted:
                    self.log_error(f"{passed_before_start(self.timeout)}; then {fault}")
                else:
                    self.log_error(str(fault))
                return
            except Fault as fault:
                self.log_error(str(fault))
                return
            held = holders(answer)
            remains = deadline - time.monotonic() - RETRY_S
            if not held or remains < needs(answer):
                break
            # A retried refusal is logged, once while it says the same, and never posted.
            this = (*answer.out, *answer.err, answer.text)
            if this != logged:
                self._print(answer)
                self.log_info(f"{answer.text.rstrip()}\nthe host is held; asking again every {RETRY_S} s")
                logged = this
            await asyncio.sleep(RETRY_S)

        # The final answer: its lines, its one comment, then its conclusion.
        self._print(answer)
        if answer.markdown:
            failure = await post_comment(
                self.client, change.id, answer.markdown, by=began + self.timeout - CONCLUSION_S
            )
        else:
            failure = "Fylgja's answer carried no markdown"
        if failure:
            self.log_info(f"the comment could not be posted: {failure}")

        document = answer.document or {}
        status = document.get("status")
        text = answer.text.rstrip("\n")
        said: list[str] = []
        if answer.started and answer.interrupted:
            said.append(asked_to_cancel(self.timeout, answer))
        elif held:
            asked = f"{asks} ask" if asks == 1 else f"{asks} asks"
            said.append(
                f"the host was still held by {', '.join(held)} after {asked}, {time.monotonic() - began:.0f} s "
                f"after this check began: what would remain of its own deadline at another ask, "
                f"{max(0, remains):.0f} s, does not cover the rehearsal's deadline of {deadline_of(answer)} s, "
                f"the destroy's {DESTROY_S} s and the {ALLOWANCE_S} s allowed before its start"
            )
        if status == "ok" and not said:
            if text:
                self.log_info(text)
            return
        said.append(text or f"the rehearsal ended {status} with no finding")
        self.log_error("\n".join(said))

    def _print(self, answer: Answer) -> None:
        """The answer's printed lines, as the out and err frames carried them."""
        for printed in ("".join(answer.out), "".join(answer.err)):
            if printed.strip():
                self.log_info(printed.rstrip("\n"))


def holders(answer: Answer) -> list[str]:
    """What holds the host, when the answer is a refusal whose every rejection says the host is
    held (R-15), the branch point's lone contract.node.missing passed over as fylgja-step passes
    it over (FR-017): each as its rule and object, the run or the twin it names. That holds
    whether the server found the holder before its start frame or after it: the start refused
    by a run begun since the host was read or by the rehearsal's fixed id, or a run refused at
    its baseline's start, touched nothing (T106). Empty for any other answer, which is final,
    and for one whose run was asked to cancel. An answer interrupted before any start is the
    refusal it carries, since no run was asked to cancel."""
    if answer.started and answer.interrupted:
        return []
    document = answer.document or {}
    if document.get("status") != "rejected":
        return []
    stages = (document.get("rehearsal") or {}).get("stages")
    rejections = rejections_past_branch_point(document.get("findings"), stages)
    if not rejections or any(f.get("rule") not in HELD for f in rejections):
        return []
    return [f"{f.get('rule')} {f.get('object')}" for f in rejections]


def deadline_of(answer: Answer) -> int:
    """The deadline of the rehearsal the answer refused, from its block (data-model §4)."""
    return int(((answer.document or {}).get("rehearsal") or {}).get("deadline_s") or 0)


def needs(answer: Answer) -> int:
    """What a run started by another ask needs of the check's own deadline (FR-007, FR-021): the
    refused rehearsal's deadline, the destroy's budget and the allowance before its start."""
    return deadline_of(answer) + DESTROY_S + ALLOWANCE_S


def asked_to_cancel(timeout: int, answer: Answer) -> str:
    """The sentence for the check's own deadline passing with the run started (FR-021)."""
    sentence = (
        f"this check's own deadline, {timeout - DEADLINE_MARGIN_S} s after it began, passed with the "
        "rehearsal still answering: its run was asked to cancel"
    )
    if answer.interrupt_failure:
        sentence += f", but the interrupt was not delivered: {answer.interrupt_failure}"
    return sentence


def passed_before_start(timeout: int) -> str:
    """The sentence for the check's own deadline passing before the run's start (FR-021)."""
    return (
        f"this check's own deadline, {timeout - DEADLINE_MARGIN_S} s after it began, passed before the "
        "rehearsal's run started"
    )
