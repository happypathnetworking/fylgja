# Contract: CI, the pull-request workflow, the release, the settings

## `.github/workflows/ci.yml`

```yaml
on:
  push: { branches: [main] }
  pull_request:
jobs:
  unit:                      # every push to main and every pull request
    runs-on: ubuntu-26.04
    steps: checkout@v5; setup-go@v6 (go-version-file: go.mod); make build; make test;
           golangci-lint-action@v9; shellcheck scripts/bring-up.sh
  contract:                  # pushes to main alone; never pull_request_target
    runs-on: ubuntu-26.04
    if: github.event_name == 'push'
    steps: checkout@v5; setup-go@v6;
           scripts/bring-up.sh --part infrahub;
           go generate ./... && git diff --exit-code;
           set -a; . local/.env; set +a; make test-contract
```

- Both jobs name `ubuntu-26.04`, never `ubuntu-latest`.
- No `secrets.*` anywhere: the script makes Infrahub's admin token on the runner and
  writes it to the job's `local/.env`; nothing prints it. The `env:` block that read
  `secrets.INFRAHUB_API_TOKEN` is removed.
- The `go generate` step's comment says it checks the committed client against the
  committed SDL and needs no Infrahub (research §2.9).
- The badge in the README: `https://github.com/happypathnetworking/fylgja/actions/workflows/ci.yml/badge.svg?branch=main`,
  linked to the workflow's page.
- Tier 3 is not in any workflow (FR-026).

## `.github/workflows/pull-requests.yml`

```yaml
on:
  pull_request_target: { types: [opened, reopened] }
permissions: { pull-requests: write }
jobs:
  close:
    runs-on: ubuntu-26.04
    steps: gh pr comment "$NUMBER" --body "<the README's Contributing sentence>"; gh pr close "$NUMBER"
```

No checkout, no code of the fork, no secret but the job's token. The one
`pull_request_target` in the repository; the contract job never uses it (FR-022). The
comment: *This repository is read-only: issues are welcome, pull requests are not taken
(README, Contributing). Closing.*

## `.github/workflows/release.yml`

```yaml
on:
  push: { tags: ['v*'] }
permissions: { contents: write }
jobs:
  release:
    runs-on: ubuntu-26.04
    steps:
      checkout@v5; setup-go@v6
      VERSION="${GITHUB_REF_NAME#v}"; make build VERSION="$VERSION"
      test "$(bin/fylgja --version)" = "fylgja version $VERSION"      # the exact line the binary prints (fylgja version 0.1.0-dev today)
      file bin/fylgja | grep -q 'statically linked'
      make test
      gh run list --commit "$GITHUB_SHA" --workflow ci --json conclusion --jq '.[0].conclusion' | grep -qx success
      cp bin/fylgja fylgja-linux-amd64; sha256sum fylgja-linux-amd64 > SHA256SUMS
      gh release create "$GITHUB_REF_NAME" --draft --verify-tag --title "$GITHUB_REF_NAME" --notes-file <notes> fylgja-linux-amd64 SHA256SUMS
```

The operator pushes the tag and publishes the draft; the workflow publishes nothing. The
notes name what the release is (the launch; M1–M7 and M10–M14 built), the binary's
platform (Linux amd64) and that a client on another machine builds from the tree.

## The ruleset on `main` (after the flip, the same sitting)

```json
{"name": "main", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
 "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
 "bypass_actors": []}
```

`gh api -X POST repos/happypathnetworking/fylgja/rulesets --input ruleset.json`. No
bypass: the operator cannot force-push or delete `main` either. Available only once the
repository is public on the Free plan (research §2.7).

## The other settings

| Setting | Value | Command |
|---|---|---|
| visibility | public | `gh repo edit --visibility public --accept-visibility-change-consequences` |
| issues | on | (already) |
| projects, wiki | off | `gh repo edit --enable-projects=false --enable-wiki=false` |
| private vulnerability reporting | on | `gh api -X PUT repos/happypathnetworking/fylgja/private-vulnerability-reporting` |
| topics | `infrahub`, `containerlab`, `digital-twin`, `network-automation`, `temporal`, `srlinux`, `arista-eos`, `go` | `gh repo edit --add-topic …` |

Every command above is the operator's, or run with the operator's word in the session
(FR-037).
