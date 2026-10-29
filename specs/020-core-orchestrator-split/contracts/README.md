# contracts/ for 020

What the feature changes on each interface; the repository's `contracts/` is rewritten to
these at implement (data-model.md §12).

## The core's API (`contracts/api.md`, version `1`)

| Operation | Path | `args` | Files in | Interrupt |
|---|---|---|---|---|
| `twin.create` | `/v1/twin/create` | `snapshot`, `dry_run`, `detach` | the snapshot when a path | from `start`, or by identity |
| `twin.provision` | `/v1/twin/provision` | `bundle`, `dry_run`, `detach` | the bundle's files | as above |
| `twin.step` | `/v1/twin/step` | `snapshot`, `allow_restart`, `dry_run`, `wait`, `detach` | the snapshot when a path | as above |
| `twin.destroy` | `/v1/twin/destroy` | `detach` | | by identity alone |
| `run.read` | `/v1/run/read` | `workflow_id`, `run_id` | | no |
| `run.interrupt` | `/v1/run/interrupt` | `workflow_id`, `run_id` | | no |
| `twin.diff` | `/v1/twin/diff` | `from`, `to` | each snapshot sent as a file | no |
| `twin.show`, `twin.verify`, `twin.compile`, `psp.validate` | unchanged | | | |

Lost: `twin.rehearse`, `stage.list`, `stage.plan`, `intent.read`, `schema.check` (`404`,
`API version 1 has no operation at this path; nothing was read or done`). The `run`
frame: `{"run": {"workflow_id", "run_id", "state"?}}`, `state` on `run.read` alone. A
`run.read` of a running run ends by EOF after its events, the one answer with no
`document`. The detached answer: `start`, `run`, `document` (`run.detached`).

## The core's CLI (`contracts/cli.md`)

`fylgja twin create|provision|step|destroy … --detach`; `fylgja run read --workflow
<id> [--run <id>] [--json]`; `fylgja run interrupt --workflow <id> [--run <id>]`; `fylgja
twin diff --from <id|file> --to <id|file> [--json]`. Gone: `twin rehearse`, `stage`,
`intent`, `schema`, and `--branch`, `--at`, `--stage`, `--scope`, `--probes` on `twin
create` and `twin step`. `fylgja serve` reads no `INFRAHUB_*` and no
`FYLGJA_DEFAULT_SCOPE`; its report says what it dials.

## The orchestrator (`contracts/orchestrator.md`, new)

- **`fylgja-cli`**: `intent read --branch <b> [--at <t>] [--stage <b>/<l>] [--scope
  tag:<n>] [--probes <f>] --out <f>`; `stage list [--branch <b>] [--scope]`; `stage plan
  --branch <b> [--scope] [--probes]`; `twin create --branch <b>|--stage <b>/<l>
  [--scope] [--probes] [--dry-run]`; `twin step [--stage <b>/<l>] [--probes]
  [--allow-restart] [--wait <d>] [--dry-run]`; `twin rehearse --branch <b> [--scope]
  [--probes] [--markdown]`; `schema check --branch <b>`; `--json` everywhere. Each prints
  the findings document the core's CLI printed (`findings 1`, operations `intent.read`,
  `stage.list`, `stage.plan`, `twin.create`, `twin.step`, `twin.rehearse`, `schema.check`)
  and exits by its status; its refusals are 014's, 015's, 016's and 017's with their ids
  and wording, plus `record.twin.stale`, `step.target.required`,
  `rehearsal.report.unposted`, `platform.unreachable`.
- **The documents**: the `stages`, `plan` and `rehearsal` blocks and the markdown report,
  unchanged but for `fylgja-cli` in the reproduce lines; `rehearsal.schema.json` and
  `stages.schema.json` move here.
- **The adapter**: `python -m fylgja_orchestrator.adapters.infrahub read|stages|schema-check`,
  the snapshot `2` file byte for byte the Go reader's; environment `INFRAHUB_ADDRESS`,
  `INFRAHUB_API_TOKEN`, `FYLGJA_DEFAULT_SCOPE`, `FYLGJA_PSP_DIR`.
- **The flows and their platform**: six deployments `<flow>/main`; a run's document is
  its artifact `fylgja-findings`; the platform's API at `PREFECT_API_URL` with basic auth
  `PREFECT_API_AUTH_STRING`.
- **The record**: `FYLGJA_ORCHESTRATOR_ROOT/twin.json` (`record_version` `1`) and
  `snapshots/<id>.json`.

## The checks (`contracts/checks.md`, moved from 015)

`fylgja-step` and `fylgja-twin` read `FYLGJA_ORCHESTRATOR_ADDRESS` and
`FYLGJA_ORCHESTRATOR_AUTH`, trigger `stage-plan` and `twin-rehearse` on the platform's
API, wait, read the artifact and conclude from `status` alone; `fylgja-twin` skips a
draft and posts nothing; timeouts 300 and 4,260; the R-15 retry and margins unchanged.
