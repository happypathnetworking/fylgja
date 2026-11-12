"""fylgja-twin: the rehearsal of a proposed change on a twin, by a run of the edge's `twin-rehearse/main` (D-085,
`fylgja_glue`).

Infrahub runs it on every open proposed change at its creation and at each re-run of its checks. A draft passes having
started nothing; any other passes exactly when the run's rehearsal 1 document's status is `passed`, its headline the
message. The flow posts the report as a thread of the proposed change (D-087); the check writes nothing to Infrahub.
"""

from collections.abc import Mapping
from typing import Any

from infrahub_sdk.checks import InfrahubCheck

from .fylgja_glue import TWIN_TIMEOUT_S, twin


class FylgjaTwin(InfrahubCheck):
    """The proposed change's rehearsal: success where it passed or is a draft, failure otherwise, with the glue's
    message."""

    # The read the SDK requires of a check (infrahub/queries/fylgja_branch.gql); its answer is not used.
    query = "fylgja_branch"
    timeout = TWIN_TIMEOUT_S

    async def validate(self, data: dict[str, Any]) -> None:
        async def ask(query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
            return await self.client.execute_graphql(query=query, variables=dict(variables), branch_name="main")

        outcome = await twin(ask, self.branch_name, timeout=self.timeout)
        if outcome.passed:
            self.log_info(outcome.message)
        else:
            self.log_error(outcome.message)
