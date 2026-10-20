# Contract: the fixture tool and test support for rehearsals and checks

Test tooling under the `fixture` and `contract` build tags, extending 014's
([014's contract](../../014-proposed-change-stages/contracts/fixture-tool.md)); the one
binary that writes to Infrahub. Every flag below refuses `fylgja-fixture` and a branch
outside `fylgja-test-` before any request, as 014's do. A helper given a branch refuses it
before any request too; one given a proposed change's id reads that proposed change's
source branch first and refuses it before any write (`testProposedChange`).

## The fixture tool

```
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -ready                    # the open proposed change: is_draft false
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -run-checks user          # CoreProposedChangeRunCheck USER; waits for each definition the branch sees to run again; prints each check's conclusion
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -run-checks artifact      # as -run-check (kept)
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -add-interface n1:ethernet-1/99   # one uncabled physical interface, enabled; -generate after it is the caller's
```

- **`-ready`** sends `CoreProposedChangeUpdate(data: {id, is_draft: {value: false}})` and
  prints `proposed change <id> on <b> marked ready for review`. It starts nothing
  (research §1.5): re-run the checks after it.
- **`-run-checks user`** sends `CoreProposedChangeRunCheck(data: {id, check_type: USER})`,
  then polls every 5 s until the validator of each check definition Infrahub runs on the
  source branch, those of a registered repository the branch sees, has been restarted by
  this run and reads `completed` (research §5.5), or 4,500 s pass (the live check's timeout
  and a margin), and prints one line per check: `check fylgja-twin: success (message 2,311
  characters)`. A validator not restarted, or still `in_progress`, at the bound is named in
  the failure (research §1.4: a timed-out check leaves one). A branch that sees no
  definition returns at once.
- **`-add-interface`** writes one `NetworkInterface` (`iftype physical`, `enabled true`,
  `mgmt_only false`, no link) on the named device and prints it. The artifacts are not
  regenerated: `-generate` renders the line the node will refuse.
- **`-delete`** is unchanged: deleting a proposed change takes its threads, their comments,
  and its validators (research §1.6, §5.9).

## Composing a rehearsal for a test

```
fixture -branch $B                                   # seed
fixture -branch $B -propose                          # the draft; both checks run: fylgja-twin skips it
fixture -branch $B -stage seeded -description seeded
fixture -branch $B -add-link                         # wait for n1's and n3's checksums (e2e: await_checksums_moved)
fixture -branch $B -stage third-link
fylgja twin rehearse --branch $B                     # by hand: baseline seeded, third-link passed, head passed
fixture -branch $B -ready
fixture -branch $B -run-checks user                  # fylgja-twin rehearses; one comment
fixture -branch $B -add-interface n1:ethernet-1/99
fixture -branch $B -generate                         # wait for n1's checksum
fixture -branch $B -stage bad-port
fixture -branch $B -run-checks user                  # bad-port fails at push; a second comment
fixture -branch $B -delete
```

## Test support (`internal/testsupport`)

| Helper | Does |
|---|---|
| `MarkReady(id string) error` | `is_draft` false |
| `RunUserChecks(id string, timeout time.Duration) ([]UserCheckRow, error)` | `USER` run-check; waits until each definition's validator the source branch sees has been restarted and reads `completed` (research §5.5); `UserCheckRow{Name, Conclusion, Severity, Message, ValidatorState}` |
| `AwaitUserChecks(id string, timeout time.Duration) ([]UserCheckRow, error)` | sends nothing; waits until each definition the source branch sees has a validator reading `completed`, the run a creation began (T065, research §5.6); returns at once when the branch sees none |
| `UserChecksOf(id string) ([]UserCheckRow, error)` | each `CoreStandardCheck` under a `CoreUserValidator`, with its validator's state |
| `CommentsOf(id string) ([]CommentRow, error)` | `CommentRow{ID, Thread, Text}`: each comment of each of the proposed change's threads, through its `threads`; no `CoreChangeComment`, which the overview never shows (research §5.9, D-053) |
| `OverviewThreads(id string) ([]string, error)` | the threads the overview shows, oldest first: each `infrahub.proposed_change_thread.created` event whose primary node is the proposed change, by its first related node (research §5.9) |
| `AddInterface(branch, device, name string) error` | one uncabled physical interface |
| `ServeRepository(dir string) (location string, stop func(), err error)` | `git init -b main`, commit, bare clone, `update-server-info`, served by `net/http` on `<bridge>:0`; the location is `http://<bridge>:<port>/<name>.git` |
| `BridgeAddress() (string, error)` | `docker network inspect bridge`'s gateway, as the bring-up script reads it; an error when Docker or the network is absent |
| `EnsureReadOnlyRepository(name, location, ref)` (existing), `AwaitImport(name, wait)` (existing) | the registration |
| `DeleteRepository(name string) error` | `CoreReadOnlyRepositoryDelete`; its definitions and query go with it (research §1.6) |
| `CheckDefinitions() ([]CheckDefinitionRow, error)` | each definition on `main`, `CheckDefinitionRow{Name, Timeout}`, for the tests' assertions and their cleanup; tier 3's precondition reads the same by GraphQL |

The contract tier's invariant after `make test-contract` gains: `CoreReadOnlyRepository`
holds `fylgja` alone, `CoreCheckDefinition` counts the registered checks and no
`fylgja-test-*` repository remains.
