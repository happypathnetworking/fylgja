# Contract: the fixture tool and test support for rehearsals and checks

Test tooling under the `fixture` and `contract` build tags, extending 014's
([014's contract](../../014-proposed-change-stages/contracts/fixture-tool.md)); the one
binary that writes to Infrahub. Every flag and helper below refuses `fylgja-fixture` and a
branch outside `fylgja-test-` before any request, as 014's do.

## The fixture tool

```
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -ready                    # the open proposed change: is_draft false
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -run-checks user          # CoreProposedChangeRunCheck USER; waits for every user validator; prints each check's conclusion
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -run-checks artifact      # as -run-check (kept)
go run -tags fixture ./cmd/fylgja-fixture -branch <b> -add-interface n1:ethernet-1/99   # one uncabled physical interface, enabled; -generate after it is the caller's
```

- **`-ready`** sends `CoreProposedChangeUpdate(data: {id, is_draft: {value: false}})` and
  prints `proposed change <id> on <b> marked ready for review`. It starts nothing
  (research §1.5): re-run the checks after it.
- **`-run-checks user`** sends `CoreProposedChangeRunCheck(data: {id, check_type: USER})`,
  then polls every 5 s until every `CoreUserValidator` of the proposed change is
  `completed`, or 4,500 s pass (the live check's timeout and a margin), and prints one line
  per check: `check fylgja-twin: success (message 2,311 characters)`. A validator still
  `in_progress` at the bound is named in the failure (research §1.4: a timed-out check
  leaves one).
- **`-add-interface`** writes one `NetworkInterface` (`iftype physical`, `enabled true`,
  `mgmt_only false`, no link) on the named device and prints it. The artifacts are not
  regenerated: `-generate` renders the line the node will refuse.
- **`-delete`** is unchanged: deleting a proposed change takes its comments and validators
  (research §1.6).

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
| `RunUserChecks(id string, timeout time.Duration) ([]UserCheckRow, error)` | `USER` run-check; waits for every user validator `completed`; `UserCheckRow{Name, Conclusion, Severity, Message}` |
| `UserChecksOf(id string) ([]UserCheckRow, error)` | each `CoreStandardCheck` under a `CoreUserValidator`, with its validator's state |
| `CommentsOf(id string) ([]CommentRow, error)` | `CommentRow{ID, Text}` through the proposed change's `comments` |
| `AddInterface(branch, device, name string) error` | one uncabled physical interface |
| `ServeRepository(dir string) (location string, stop func(), err error)` | `git init -b main`, commit, bare clone, `update-server-info`, served by `net/http` on `<bridge>:0`; the location is `http://<bridge>:<port>/<name>.git` |
| `BridgeAddress() (string, error)` | `docker network inspect bridge`'s gateway, as the bring-up script reads it; an error when Docker or the network is absent |
| `EnsureReadOnlyRepository(name, location, ref)` (existing), `AwaitImport(name, wait)` (existing) | the registration |
| `DeleteRepository(name string) error` | `CoreReadOnlyRepositoryDelete`; its definitions and query go with it (research §1.6) |
| `CheckDefinitions() ([]string, error)` | the names on `main`, for the test's assertions and its cleanup |

The contract tier's invariant after `make test-contract` gains: `CoreReadOnlyRepository`
holds `fylgja` alone, `CoreCheckDefinition` counts the registered checks and no
`fylgja-test-*` repository remains.
