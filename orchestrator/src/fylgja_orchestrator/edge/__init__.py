"""The example's edge (D-085): what starts the rehearsal library, and the one layer that knows Prefect.

`settings` reads the runner's nine variables once; `run` wires them to the library and the Infrahub change source,
with no Prefect; `flows` wraps `run` in the two Prefect flows a check starts, `stage-plan` and `twin-rehearse`, and
`serve` serves them; `cli` is the command `fylgja-orchestrator`, which calls `run` and the library in its own process.
Only `flows` and `serve` import Prefect, and `cli` imports `serve` inside its `serve` command alone, so this package
imports none of its modules: a command loads `run` and never the flows.
"""
