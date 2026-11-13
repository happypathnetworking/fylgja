"""The example's edge (D-085): what starts the rehearsal library, and the one layer that knows Prefect.

`settings` reads once which change source the runner opens, Infrahub's or NetBox's, and that source's nine variables;
`run` wires them to the library and that source, with no Prefect; `flows` wraps `run` in the two Prefect flows a check
or a tag starts, `stage-plan` and `twin-rehearse`, and `serve` serves them; `cli` is the command `fylgja-orchestrator`,
which calls `run`, the library and, to mark a NetBox branch, the source in its own process.
Only `flows` and `serve` import Prefect, and `cli` imports `serve` inside its `serve` command alone, so this package
imports none of its modules: a command loads `run` and never the flows.
"""
