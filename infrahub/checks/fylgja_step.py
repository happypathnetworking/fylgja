"""fylgja-step: the proposed change's stage plan, asked of the orchestrator (contracts/checks.md, FR-017).

Infrahub runs it on every open proposed change, draft or not, at its creation and on each
re-run of its checks. It triggers the flow stage-plan for the source branch on the
orchestrator's platform, waits for its run, and logs the plan's text and its findings' text
as its message. It writes nothing to Infrahub.
"""

import time
from typing import Any

from infrahub_sdk.checks import InfrahubCheck

from .fylgja_api import (
    CLOSE_MARGIN_S,
    FLOW_STAGE_PLAN,
    Fault,
    Platform,
    Ran,
    findings_text,
    none_open,
    proposed_change,
    rejections_past_branch_point,
    run,
    variables,
)


class FylgjaStep(InfrahubCheck):
    """The plan of every stage of the proposed change, in seconds: failure when a stage is refused
    as intent, when the stages cannot be listed, when the plan has not ended by the check's own
    deadline, or when the orchestrator's platform cannot be reached, refuses the credential or
    serves no stage-plan; success otherwise, warnings included."""

    # The cheap read the SDK requires (infrahub/queries/branch.gql); its answer is not used.
    query = "fylgja_branch"
    timeout = 300

    async def validate(self, data: dict[str, Any]) -> None:
        # Its own deadline, short of its timeout: a plan that has not ended by then is asked to
        # cancel, and the check concludes before Infrahub's timeout would leave its validator
        # in_progress (FR-021).
        close_by = time.monotonic() + self.timeout - CLOSE_MARGIN_S
        try:
            platform = Platform(*variables())
            change = await proposed_change(self.client, self.branch_name)
            if change is None:
                self.log_error(none_open(self.branch_name))
                return
            ran = await run(platform, FLOW_STAGE_PLAN, {"branch": self.branch_name}, close_by)
        except Fault as fault:
            self.log_error(str(fault))
            return

        if not ran.state.ended:
            asked = (
                "it was asked to cancel"
                if ran.cancel_failure is None
                else f"it could not be asked to cancel: {ran.cancel_failure}"
            )
            self.log_error(
                f"the stage plan did not answer by this check's own deadline, {self.timeout - CLOSE_MARGIN_S} s "
                f"after it began ({ran.heading()}), and {asked}: nothing was started, and a re-run of the checks "
                "asks again"
            )
            return

        # The run's identity, the plan's text as its out lines carried it, then the findings'
        # text, which is the error when the plan fails the change.
        self._print(ran)
        if ran.document is None:
            self.log_error(f"{ran.heading()}, and it filed no document")
            return
        document = ran.document
        found = findings_text(document)
        if refuses(document):
            self.log_error(found or f"stage plan ended {document.get('status')} with no finding")
        elif found:
            self.log_info(found)

    def _print(self, ran: Ran) -> None:
        """The run's identity and its out lines, as the platform's log carried them."""
        printed = "\n".join([ran.heading(), *ran.lines])
        if ran.lines_failure:
            printed += f"\nthe run's out lines could not be read: {ran.lines_failure}"
        self.log_info(printed)


def refuses(document: dict[str, Any]) -> bool:
    """Whether the plan fails the change: stage-plan's status mapped, ok passing and every other
    failing, but for a plan rejected by the branch point's lone scope.empty at read alone."""
    status = document.get("status")
    if status == "ok":
        return False
    if status != "rejected":
        return True
    stages = (document.get("plan") or {}).get("stages")
    return bool(rejections_past_branch_point(document.get("findings"), stages))
