"""fylgja-step: the proposed change's stage plan, asked of Fylgja (contracts/checks.md, FR-017).

Infrahub runs it on every open proposed change, draft or not, at its creation and on each
re-run of its checks. It asks the API's stage.plan for the source branch and logs the plan's
text and its findings' text as its message. It writes nothing to Infrahub.
"""

from typing import Any

from infrahub_sdk.checks import InfrahubCheck

from .fylgja_api import RENDER_TEXT, Fault, call, none_open, path, proposed_change, variables

# FR-017's one exception, the one rule the check holds beside the status's mapping (D-052):
# a branch point refused contract.node.missing, for want of a network on main, is not a
# refusal of the change, and the plan's other stages decide. It reads the finding's rule and
# the stage's at_source and nothing else.
RULE_NODE_MISSING = "contract.node.missing"
AT_BRANCH_POINT = "branch_point"


class FylgjaStep(InfrahubCheck):
    """The plan of every stage of the proposed change, in seconds: failure when a stage is refused
    as intent, when the stages cannot be listed, or when Fylgja cannot be reached or refuses the
    token or the version; success otherwise, warnings included."""

    # The cheap read the SDK requires (infrahub/queries/branch.gql); its answer is not used.
    query = "fylgja_branch"
    timeout = 300

    async def validate(self, data: dict[str, Any]) -> None:
        try:
            address, token = variables()
            change = await proposed_change(self.client, self.branch_name)
            if change is None:
                self.log_error(none_open(self.branch_name))
                return
            answer = await call(address, token, path("stage.plan"), RENDER_TEXT, {"branch": self.branch_name})
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
    rejections = [f for f in document.get("findings") or [] if f.get("severity") == "rejection"]
    for excused in _branch_point_refusal(document):
        key = _key(excused)
        for i, f in enumerate(rejections):
            if _key(f) == key:
                del rejections[i]
                break
    return bool(rejections)


def _branch_point_refusal(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The branch point's one rejection when it is contract.node.missing, else none. Each stage's
    findings are also in the document's own list (contracts/stages.schema.json)."""
    for stage in (document.get("plan") or {}).get("stages") or []:
        if stage.get("at_source") != AT_BRANCH_POINT:
            continue
        rejections = [f for f in stage.get("findings") or [] if f.get("severity") == "rejection"]
        if len(rejections) == 1 and rejections[0].get("rule") == RULE_NODE_MISSING:
            return rejections
    return []


def _key(finding: dict[str, Any]) -> tuple[Any, ...]:
    """A finding as the document's list and a stage's both carry it."""
    return tuple(finding.get(k) for k in ("severity", "rule", "object", "step", "message"))
