"""fylgja-step: the plan of a proposed change, by a run of the edge's `stage-plan/main` (D-085, `fylgja_glue`).

Infrahub runs it on every open proposed change, draft or not, at its creation and at each re-run of its checks. It
passes exactly when the run's plan 1 document's status is `planned`, the plan's headline its message; it writes
nothing to Infrahub.
"""

from collections.abc import Mapping
from typing import Any

from infrahub_sdk.checks import InfrahubCheck

from .fylgja_glue import STEP_TIMEOUT_S, step


class FylgjaStep(InfrahubCheck):
    """The proposed change's stage plan: success where it is planned, failure otherwise, with the glue's message."""

    # The read the SDK requires of a check (infrahub/queries/fylgja_branch.gql); its answer is not used.
    query = "fylgja_branch"
    timeout = STEP_TIMEOUT_S

    async def validate(self, data: dict[str, Any]) -> None:
        async def ask(query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
            return await self.client.execute_graphql(query=query, variables=dict(variables), branch_name="main")

        outcome = await step(ask, self.branch_name, timeout=self.timeout)
        if outcome.passed:
            self.log_info(outcome.message)
        else:
            self.log_error(outcome.message)
