"""fylgja-step: the proposed change's stage plan, asked of Fylgja (contracts/checks.md, FR-017).

Infrahub runs it on every open proposed change, draft or not, at its creation and on each
re-run of its checks. It asks the API's stage.plan for the source branch and logs the plan's
text and its findings' text as its message. It writes nothing to Infrahub.
"""

import time
from typing import Any

from infrahub_sdk.checks import InfrahubCheck

from .fylgja_api import (
    CLOSE_MARGIN_S,
    RENDER_TEXT,
    Cut,
    Fault,
    call,
    none_open,
    path,
    proposed_change,
    rejections_past_branch_point,
    variables,
)


class FylgjaStep(InfrahubCheck):
    """The plan of every stage of the proposed change, in seconds: failure when a stage is refused
    as intent, when the stages cannot be listed, when the plan does not answer by the check's own
    deadline, or when Fylgja cannot be reached or refuses the token or the version; success
    otherwise, warnings included."""

    # The cheap read the SDK requires (infrahub/queries/branch.gql); its answer is not used.
    query = "fylgja_branch"
    timeout = 300

    async def validate(self, data: dict[str, Any]) -> None:
        # Its own deadline, short of its timeout: a plan that has not answered by then is cut,
        # and the check concludes before Infrahub's timeout would leave its validator
        # in_progress (FR-021).
        close_by = time.monotonic() + self.timeout - CLOSE_MARGIN_S
        try:
            address, token = variables()
            change = await proposed_change(self.client, self.branch_name)
            if change is None:
                self.log_error(none_open(self.branch_name))
                return
            answer = await call(
                address, token, path("stage.plan"), RENDER_TEXT, {"branch": self.branch_name}, close_by=close_by
            )
        except Cut as fault:
            if fault.late:
                self.log_error(
                    f"the stage plan did not answer by this check's own deadline, {self.timeout - CLOSE_MARGIN_S} s "
                    f"after it began ({fault}): nothing was started, and a re-run of the checks asks again"
                )
            else:
                self.log_error(str(fault))
            return
        except Fault as fault:
            self.log_error(str(fault))
            return

        # The plan's text as the out and err frames carried it, then the findings' text, which
        # is the error when the plan fails the change.
        for printed in ("".join(answer.out), "".join(answer.err)):
            if printed.strip():
                self.log_info(printed.rstrip("\n"))
        document = answer.document or {}
        found = answer.text.rstrip("\n")
        if refuses(document):
            self.log_error(found or f"stage plan ended {document.get('status')} with no finding")
        elif found:
            self.log_info(found)


def refuses(document: dict[str, Any]) -> bool:
    """Whether the plan fails the change: stage.plan's status mapped, ok passing and every other
    failing, but for a plan rejected by the branch point's lone contract.node.missing alone."""
    status = document.get("status")
    if status == "ok":
        return False
    if status != "rejected":
        return True
    stages = (document.get("plan") or {}).get("stages")
    return bool(rejections_past_branch_point(document.get("findings"), stages))
