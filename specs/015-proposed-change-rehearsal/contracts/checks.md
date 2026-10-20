# Contract: the two checks, `fylgja-step` and `fylgja-twin`

Infrahub's runtime, as the Jinja template is (Constitution I): Python glue in this
repository, run by Infrahub's task workers on a proposed change at its creation and on a
re-run, reaching Fylgja through the API alone (XI). Everything that decides is behind the
API; the Python finds the proposed change, asks, posts the comment and concludes.

## Registration (`.infrahub.yml`)

```yaml
queries:
  - name: device_config
    file_path: infrahub/queries/device_config.gql
  - name: fylgja_branch
    file_path: infrahub/queries/branch.gql           # { Branch { name } }: the cheap read the SDK requires of a check

check_definitions:
  - name: fylgja-step
    file_path: infrahub/checks/fylgja_step.py
    class_name: FylgjaStep
  - name: fylgja-twin
    file_path: infrahub/checks/fylgja_twin.py
    class_name: FylgjaTwin
```

Global (no `targets`, no `parameters`); the query is the class's `query = "fylgja_branch"`,
never a `query:` key under the definition. `infrahub/checks/fylgja_api.py` is the shared
glue, imported relatively (`from .fylgja_api import …`), which Infrahub's module naming
allows (research §1.2). The definitions reach Infrahub as the template does: on `origin`'s
`main`, imported on request ([D-044](../../../docs/decisions.md#d-044)); a branch created
before the import does not run them until rebased or recreated (research §1.5).

## The environment, and what each check needs

| Variable | From | Unset |
|---|---|---|
| `FYLGJA_API_ADDRESS` | the override: `host.docker.internal:7650` | `log_error` naming the variable, nothing sent, conclusion failure; `fylgja-twin` on a draft reads neither variable and skips it |
| `FYLGJA_API_TOKEN` | the override, from `local/.env` | the same |

Nothing else of Fylgja's, Infrahub's or a node's. The check's own client (`self.client`,
the task worker's) is used for two reads and one write and nothing more: the proposed
change by `source_branch__value = branch_name` and `state__value = open` (its `id`, `name`,
`is_draft`), and `fylgja-twin`'s comment. No token and no configuration line reaches a
message, a comment or a log line, and of the two variables' values only the address does,
which a fault names as the server it tried (Constitution X; US2's scenario 4).

## `fylgja-step` (`timeout = 300`)

1. The variables; the proposed change (none open on the branch: `log_error`).
2. `POST /v1/stage/plan` with `{"render": "text", "args": {"branch": <branch_name>}}`,
   read to its document.
3. Once the answer has ended, `log_info` the plan's text as the `out` frames carried it,
   then the `err` frames' text, each once, then the findings' text.
4. **Conclusion**: `log_error` when the document's findings hold a rejection, **except** a
   branch point (`at_source: branch_point`) whose one rejection is `contract.node.missing`;
   when the plan's status is `error` (`operation.failed`, the stages unlistable); and when
   Fylgja cannot be reached (a dial error, a `401`, a `404` under `Fylgja-Api-Versions`, an
   answer cut before its document), naming the address and never the token. A plan whose
   every other stage compiled passes, `stage.main.moved` and the other warnings included.

Runs on every open proposed change, draft or not.

## `fylgja-twin` (`timeout = 4200`)

1. The proposed change (none open on the branch: `log_error`), then the variables. **A
   draft** (`is_draft`) is decided first, since it needs nothing of Fylgja's (FR-020):
   `log_info` `skipped: proposed change <id> is a draft; mark it ready for review and re-run
   the checks to rehearse it`, conclusion success, neither variable read and nothing asked
   of Fylgja.
2. `POST /v1/twin/rehearse` with `{"render": "markdown", "args": {"branch": <branch_name>}}`
   and `Fylgja-Stream: <16 random bytes in hex>`, streamed, no read timeout, read to its
   document; the `out` frames and then the `err` frames logged once each, when the answer
   ends or is cut (T046), since Infrahub shows every entry as a block of its own.
3. **The host held** (`run.in_flight`, `host.lab.present`, `host.twin.present` before any
   `start`): wait 30 s and ask again, until the check's own deadline (its `timeout` less
   180 s) nears, then `log_error` naming the run or the twin the last answer named. A
   retried refusal is logged and never posted; the comment is the final answer's document,
   once.
4. **The comment**: once the document frame is read, one comment as the proposed change's
   view writes and shows one (research §5.9): a `CoreChangeThread` with `change` the
   proposed change, `label` `Conversation` and `resolved` false, then one
   `CoreThreadComment` with `text` the frame's `markdown` and `thread` that thread, both
   saved on `main`. The view's overview lists a thread through the event its creation
   emits; a `CoreChangeComment` is counted and never shown. A failure to post is
   `log_info` (`the comment could not be posted: <error>`), never `log_error`, and never a
   credential; a thread whose comment could not be saved is deleted, as the view deletes
   its own. A new comment each run; none is edited or deleted.
5. **Conclusion**: the document's `status` alone: `ok` → success; `rejected`, `error`,
   `failed`, `unclean`, `nonconforming` → `log_error` with the document's text (the
   findings as the `text` field carries them) and the report's lines already logged.
   Fylgja unreachable, refusing the token or the version, or the answer cut: `log_error`
   naming the address.
6. **The connection lost mid-rehearsal** (the answer cut after `start`): `log_error` `the
   connection to Fylgja was lost while the rehearsal ran; the run goes on to its destroy
   and no report will be posted; re-run the checks once fylgja twin show reports no twin`.
7. **The check's own deadline** while the answer is still open: the interrupt is sent, the
   answer read on to its document or its cut, and `log_error` says the run was asked to
   cancel. **Cancelled or timed out by Infrahub** (`BaseException` in the handler): the
   interrupt is sent with a blocking call, never an `await` (research §1.4), and the
   exception re-raised; Infrahub leaves the validator `in_progress`, which blocks the merge.

The message is the report's text; the comment is its markdown; the conclusion is the
status's mapping and nothing else ([D-052](../research.md#3-the-decision-entries-drafted)).

## What Infrahub shows

- The check's message under `Message` in the proposed change's checks tab, as plain text
  with its line breaks kept (research §5.9).
- The report in the proposed change's overview, as the thread its creation lists
  ("<account> created a thread"), its one comment rendered as markdown: the table, the
  Mermaid drawing, the stages, the warnings, the baseline findings, the reproduce commands,
  the caveat ([D-053](../../../docs/decisions.md#d-053)).
- The validator `Check: fylgja-twin` `success` or `failure`; a failure blocks the merge
  (every validator but the data one must succeed).

## Timings on the development host

`fylgja-step` answers in about 20 s from a run-check's call (the pipeline's 13 s, the plan's
5–10 s); `fylgja-twin` in the rehearsal's time plus 20 s (research §1.5, §1.7).
