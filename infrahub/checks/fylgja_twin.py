"""fylgja-twin: the proposed change rehearsed on a twin, asked of the orchestrator (contracts/checks.md, FR-018).

Infrahub runs it on every open proposed change, at its creation and on each re-run of its
checks. On a draft it asks nothing and passes. Otherwise it triggers the flow twin-rehearse
for the source branch on the orchestrator's platform, waits for its run, logs the run's out
lines and the report's findings as its message, and concludes by the report's status alone
(D-052). It writes nothing to Infrahub: the rehearse flow posts the report on the proposed
change itself (020's R-11), and every verdict, deadline and wording is the orchestrator's.
"""

import asyncio
import time
from typing import Any

from infrahub_sdk.checks import InfrahubCheck

from .fylgja_api import (
    CLOSE_MARGIN_S,
    DEPLOYMENT,
    FLOW_TWIN_REHEARSE,
    Fault,
    Lost,
    Platform,
    Ran,
    findings_text,
    none_open,
    proposed_change,
    rejections_past_branch_point,
    run,
    variables,
)

# DEADLINE_MARGIN_S is how long before its timeout the check asks the rehearsal's run to
# cancel: its own deadline, after which it waits on while the run destroys and files its
# document. A check Infrahub times out leaves its validator in_progress and the merge blocked
# (015's research §1.4), so this deadline, not Infrahub's, is what ends a rehearsal that
# overruns (FR-021). The timeout less this margin is the flow's own timeout_seconds (the
# allowance, the ceiling and the destroy; twin_rehearse.TIMEOUT_S); the margin less
# CLOSE_MARGIN_S, the wait after the cancellation, covers the runner's grace in which the
# cancelled flow reads its destroy and files its report (020's research §5.18).
DEADLINE_MARGIN_S = 240

# DESTROY_S is the destroy's whole budget (PlanTeardown, the largest package's destroy and
# Unstage), and ALLOWANCE_S the time allowed the flow before its run's start: the plan, a
# reclaim and the host check, an allowance, not a bound the flow enforces (FR-021). Each is
# the rehearse flow's own of the same name.
DESTROY_S = 120
ALLOWANCE_S = 300

# RETRY_S is the wait between two asks while the host is held (015's R-15).
RETRY_S = 30

# HELD are the refusals that say the host is held by a run or a twin, before any start: a
# rehearsal asks again once they clear, where every other refusal is final at once (015's R-15).
HELD = frozenset({"run.in_flight", "host.lab.present", "host.twin.present"})

# GOES_ON is what FR-021 says of a rehearsal whose run the check could not follow to its end:
# the core's runs it started go on to their destroy.
GOES_ON = (
    "any run of the core's it started goes on to its destroy, and a report it could not file is not posted; "
    "re-run the checks once fylgja twin show reports no twin"
)


class FylgjaTwin(InfrahubCheck):
    """The proposed change's stages rehearsed on a twin: success when the report's status is ok,
    or on a draft, which is skipped; failure on every other status, when the host is still held
    once what remains of the check's own deadline no longer covers the run it asks for, when
    that deadline cuts the run, and when the orchestrator's platform cannot be reached, refuses
    the credential, serves no twin-rehearse or cannot be read while the run runs."""

    # The cheap read the SDK requires (infrahub/queries/branch.gql); its answer is not used.
    query = "fylgja_branch"
    timeout = 4260

    async def validate(self, data: dict[str, Any]) -> None:
        began = time.monotonic()
        deadline = began + self.timeout - DEADLINE_MARGIN_S
        close_by = began + self.timeout - CLOSE_MARGIN_S
        # The draft skip needs nothing of the orchestrator's, so it comes before the variables
        # (FR-020).
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
            platform = Platform(*variables())
        except Fault as fault:
            self.log_error(str(fault))
            return

        # Ask, and ask again every RETRY_S while the host is held and what would remain of the
        # check's own deadline at the next ask still covers the run it asks for (FR-007, FR-021),
        # so that no run this check starts is cancelled by it. A cancellation by Infrahub while
        # a run has not ended cancels the run from run's handler, with a blocking call; between
        # two asks no run of this check's is open, and nothing is sent.
        asks = 0
        logged: tuple[str, ...] = ()
        while True:
            asks += 1
            try:
                ran = await run(platform, FLOW_TWIN_REHEARSE, {"branch": self.branch_name}, deadline, close_by)
            except Lost as fault:
                self.log_error(f"{fault}; {GOES_ON}")
                return
            except Fault as fault:
                self.log_error(str(fault))
                return
            if not ran.state.ended:
                self.log_error(
                    f"{asked_to_cancel(self.timeout, ran)}; it had still not ended {CLOSE_MARGIN_S} s before this "
                    f"check's timeout ({ran.heading()}); {GOES_ON}"
                )
                return
            held = holders(ran)
            remains = deadline - time.monotonic() - RETRY_S
            if not held or remains < needs(ran):
                break
            # A retried refusal is logged, once while it says the same; the flow posts none.
            found = findings_text(ran.document)
            this = (*ran.lines, found)
            if this != logged:
                self._print(ran)
                self.log_info(f"{found}\nthe host is held; asking again every {RETRY_S} s")
                logged = this
            await asyncio.sleep(RETRY_S)

        # The final run: its lines, then its conclusion.
        self._print(ran)
        document = ran.document
        said: list[str] = []
        if ran.cancelled:
            said.append(asked_to_cancel(self.timeout, ran))
        if document is None:
            said.append(f"{ran.heading()}, and it filed no document; {GOES_ON}")
            self.log_error("\n".join(said))
            return
        status = document.get("status")
        text = findings_text(document)
        if held:
            asked = f"{asks} ask" if asks == 1 else f"{asks} asks"
            said.append(
                f"the host was still held by {', '.join(held)} after {asked}, {time.monotonic() - began:.0f} s "
                f"after this check began: what would remain of its own deadline at another ask, "
                f"{max(0, remains):.0f} s, does not cover the rehearsal's deadline of {deadline_of(ran)} s, "
                f"the destroy's {DESTROY_S} s and the {ALLOWANCE_S} s allowed before its start"
            )
        if status == "ok" and not said:
            if text:
                self.log_info(text)
            return
        said.append(text or f"the rehearsal ended {status} with no finding")
        self.log_error("\n".join(said))

    def _print(self, ran: Ran) -> None:
        """The run's identity and its out lines, as the platform's log carried them."""
        printed = "\n".join([ran.heading(), *ran.lines])
        if ran.lines_failure:
            printed += f"\nthe run's out lines could not be read: {ran.lines_failure}"
        self.log_info(printed)


def holders(ran: Ran) -> list[str]:
    """What holds the host, when the run's document is a refusal whose every rejection says the
    host is held (015's R-15), the branch point's lone scope.empty at read passed over as
    fylgja-step passes it over (FR-017): each as its rule and object, the run or the twin it
    names. A refusal because the host is held touched nothing, whenever the flow found the
    holder. Empty for any other document, which is final, and for a run asked to cancel."""
    if ran.cancelled:
        return []
    document = ran.document or {}
    if document.get("status") != "rejected":
        return []
    stages = (document.get("rehearsal") or {}).get("stages")
    rejections = rejections_past_branch_point(document.get("findings"), stages)
    if not rejections or any(f.get("rule") not in HELD for f in rejections):
        return []
    return [f"{f.get('rule')} {f.get('object')}" for f in rejections]


def deadline_of(ran: Ran) -> int:
    """The deadline of the rehearsal the run refused, from its block (data-model §4)."""
    return int(((ran.document or {}).get("rehearsal") or {}).get("deadline_s") or 0)


def needs(ran: Ran) -> int:
    """What a run started by another ask needs of the check's own deadline (FR-007, FR-021): the
    refused rehearsal's deadline, the destroy's budget and the allowance before its start."""
    return deadline_of(ran) + DESTROY_S + ALLOWANCE_S


def asked_to_cancel(timeout: int, ran: Ran) -> str:
    """The sentence for the check's own deadline passing with the run not ended (FR-021)."""
    sentence = (
        f"this check's own deadline, {timeout - DEADLINE_MARGIN_S} s after it began, passed with flow run "
        f"{ran.flow_run_id} of {ran.flow}/{DEPLOYMENT} still running: it was asked to cancel"
    )
    if ran.cancel_failure:
        sentence += f", but the cancellation was not delivered: {ran.cancel_failure}"
    return sentence
