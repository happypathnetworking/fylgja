# Data model: The launch

**Feature**: `013-launch` · **Plan**: [plan.md](plan.md) · **Research**: [research.md](research.md)

Nothing here is a product format: bundle `4`, CTM `1`, PSP `0.6`, `twin.json` `5`,
contract `0.2`, findings `1` and the API `1` are untouched (FR-039). The entities are the
script's, the test tooling's, Infrahub's objects on `main`, and the repository's own
settings. Each names the contract that fixes its wire form.

## 1. The bring-up script's run

Contract: [contracts/bring-up-script.md](contracts/bring-up-script.md).

| Field | Values | Notes |
|---|---|---|
| host | the machine the script runs on | must report `VERSION_ID=26.04` in `/etc/os-release`; anything else is refused before a change |
| clone | the repository root, the script's working directory | the script is run as `scripts/bring-up.sh` from the root; `local/` and `.venv/` are written under it |
| `--ceos-tar PATH` | optional | the first place the tar is looked for |
| `--part NAME` | `toolchain`, `lab`, `infrahub`, `fylgja`; repeatable | absent: all four, in that order |
| tar search | the given path, `local/`, the clone's parent directory; never the root | the file is `cEOS-lab-4.32.0.2F.tar` or `.tar.xz`, sha256 `89a567d5…` (R-12) |
| platforms | `nokia_srlinux` always; `arista_eos` when the tar is found or `ceos:4.32.0.2F` is present | printed in the first and last reports |
| `local/.env` | scaffolded in the preamble when absent; kept when present | §2 |
| `local/infrahub/` | `docker-compose.yml` (fetched by version) and `docker-compose.override.yml` (copied from `scripts/infrahub/`) | the Compose project directory; git-ignored under `local/` |
| processes left running | `temporal server start-dev`, `fylgja worker run`, `fylgja serve` | detached, logging to `local/temporal.log`, `local/worker.log`, `local/server.log`; the Fylgja part alone starts them |
| exit | `0` done; `1` a part or a tier failed; `2` refused before any change | §1.1 |

### 1.1 States

```
preamble ─► toolchain ─► lab ─► infrahub ─► fylgja ─► last report (exit 0)
   │           │          │        │           │
   │ refused   └──────────┴────────┴───────────┴─► FAILED <part>: <item> (exit 1)
   ▼
REFUSED (exit 2): release ≠ 26.04 · unknown flag · tar checksum mismatch ·
                  port 8000 held by something not fylgja-infrahub
```

The preamble's checks run in that order and change nothing. The lab part may re-execute
the script once through a fresh login session after it added the user to `docker` and
`clab_admins` (R-02); the re-executed run carries the remaining parts and is otherwise
the same run.

Each item of a part has one of three outcomes, printed as one line: `present <version>`
(verified, nothing done), `installed <version>` (installed, then verified), `skipped
(<why>)` (the cEOS import without a tar, the seed when the fixture is complete). A
wait prints `waiting for <what> (up to <N>s)` and, on expiry, fails naming it.

## 2. `local/.env`

The one file that holds a value; `.env.example` documents every name and no value.
Scaffolded once by the preamble; a present file is never rewritten (FR-013).

| Name | Value the script writes | Who reads it |
|---|---|---|
| `FYLGJA_API_ADDRESS` | `127.0.0.1:7650` (the default, written out) | a client |
| `FYLGJA_API_TOKEN` | 24 random bytes, base64 | a client and the server |
| `INFRAHUB_ADDRESS` | `http://localhost:8000` | the server, the worker, the fixture tool, `e2e.sh` |
| `INFRAHUB_API_TOKEN` | the value of `INFRAHUB_INITIAL_ADMIN_TOKEN` | the same |
| `FYLGJA_PSP_DIR` | empty: the embedded packages (an override directory that does not exist would refuse the roles' start) | the server and the worker |
| `FYLGJA_TEMPORAL_ADDRESS` | `localhost:7233` | the server and the worker |
| `FYLGJA_TEMPORAL_NAMESPACE` | `default` | the same |
| `FYLGJA_STATE_ROOT` | `<clone>/local`, absolute | the same |
| `FYLGJA_HOST_MEMORY_MB` | the host's `MemTotal` in MiB less 8192 (Infrahub idles at about 5 GiB) | the host check |
| `FYLGJA_SRLINUX_USERNAME` / `_PASSWORD` | the SR Linux image's published default login | the worker and the server |
| `FYLGJA_EOS_USERNAME` / `_PASSWORD` | the cEOS image's published default login | the same |
| **Compose block (new in `.env.example`)** | | |
| `COMPOSE_PROJECT_NAME` | `fylgja-infrahub` | Compose |
| `INFRAHUB_INITIAL_ADMIN_TOKEN` | a UUID the script makes | Compose → Infrahub |
| `INFRAHUB_INITIAL_ADMIN_PASSWORD` | random | the same |
| `INFRAHUB_INITIAL_AGENT_TOKEN` | a UUID the script makes | the same (the task worker's token) |
| `INFRAHUB_SECURITY_SECRET_KEY` | random | the same |

Every name `.env.example` documents is present; `FYLGJA_PSP_DIR` alone is empty on
purpose (US2 scenario 8 and FR-010 say so, reworded by `analyze`). The file
is written `0600`. No value is ever printed: the script's output, CI's log and every file
it writes but this one carry none (FR-011).

## 3. The platform list (tier 3)

Contract: [contracts/e2e-platform-list.md](contracts/e2e-platform-list.md).

| Field | Values |
|---|---|
| `PLATFORMS` | unset, or a comma- or space-separated list of shipped package names: each package's `platform.id`, the stem of its `psp/*.yaml` (`nokia_srlinux`, `arista_eos`) |
| case → packages | 1, 2, 3, 4, 5, 7: `nokia_srlinux`; 6, 8: `nokia_srlinux arista_eos`; declared in one table at the top of `scripts/e2e.sh` |
| case outcome | `ran` (passed, or the run failed at it: exit 1), `skipped (needs <pkg>: not in PLATFORMS)`, `skipped (needs <pkg>: image <ref> absent)` |
| run end | unset list: `E2E-OK` (every image required first, as now); a list: `E2E-PARTIAL: …` exit 0 when every case it ran passed and at least one was skipped, `E2E-OK` when none was skipped; `e2e: FAILED:` exit 1; `e2e: LEAK:` exit 99 |
| refusals before any case | a name no package has (naming the known ones); a list that selects no case |

## 4. The registration on `main`

Contract: [contracts/fixture-prepare-main.md](contracts/fixture-prepare-main.md).
Made the same way by the script, by CI's job and on the development host.

| Object | Kind | Fields | Made by |
|---|---|---|---|
| the schema | `schema/*.yaml` loaded on `main` | hash per install (`4d5b37aa…` on the development host) | `LoadSchema`, a no-op when `main` has it (research §2.4) |
| the group | `CoreStandardGroup` | `name: fylgja-devices`, no members | created when absent |
| the registration | `CoreReadOnlyRepository` | `name: fylgja` (default; `-repository-name`), `location: https://github.com/happypathnetworking/fylgja.git` (`-repository-location`), `ref: main` (`-repository-ref`), no `credential`, `description` naming D-044 | created when absent |
| what the import makes | `CoreGraphQLQuery device_config`, `CoreTransformJinja2 srlinux_device_config`, `CoreArtifactDefinition srlinux_device_config` (artifact `device-config`, `text/plain`, targets `fylgja-devices`) | each with `repository → fylgja` | Infrahub's import of `.infrahub.yml` |

### 4.1 The registration's states, and the wait

```
created ──► internal_status: staging → active     (the clone; D-044 measured 14.5s)
        ──► operational_status: unknown → online  (the connectivity check; 34.8s)
        ──► the import: query, transform and definition appear on main
```

`-prepare-main` waits for all three, polling every second, bounded (300 s by default,
`-wait`), and on expiry names which of the three did not arrive and that a
`git_repositories_sync` run stuck `PENDING` in Infrahub's task manager blocks every
import until it is cancelled (verified-facts). A second run finds everything by name
and writes nothing.

### 4.2 The development host's swap (R-15)

```
fylgja-artifacts (CoreRepository + CorePasswordCredential)  ──delete──►  absent
                                                              ↓ record: do the three objects survive?
fylgja (CoreReadOnlyRepository, no credential)              ──create──►  active, online, imported
                                                              ↓ record: the three objects' repository, and their ids
fylgja-fixture                                              ──clean, seed──►  3 artifacts Ready, compiles to b9d53ebc…
```

## 5. The fixture tool's refusal (FR-028)

`lookupByName` and `groupMemberCount` word one message. Before: `… the fylgja-artifacts
repository must be connected and in-sync on main`. After: `… register this repository
(github.com/happypathnetworking/fylgja) on main as a read-only repository with no
credential and wait for its import (docs/development.md, "What Infrahub needs"); a branch
created before the import cannot see it`. Nothing else of the tool's product-facing
behaviour changes.

## 6. The recording

| Field | Value |
|---|---|
| cast | `docs/recording/session.cast`, asciinema 3.2.1, `--cols 100 --rows 30` |
| image | `docs/recording/session.gif`, `agg` 1.9.0, `--idle-time-limit 2 --fps-cap 15 --font-size 14`, under 3 MB |
| intent | the throwaway branch and series `fylgja-test-readme`, seeded and written before the recording as the README's stepping walk-through does; deleted after |
| frames | `twin create --waypoint fylgja-test-readme/1`, `twin step`, `twin verify`, in a shell holding `FYLGJA_API_TOKEN` alone |
| hygiene | the cast and the GIF grepped for the API's token, Infrahub's token and both passwords; every frame read; a credential in a frame means a new recording |
| README | `![…](docs/recording/session.gif)` near the top, after the first paragraph |

## 7. The release

| Field | Value |
|---|---|
| tag | `v0.1.0`, annotated, pushed by the operator |
| workflow | `.github/workflows/release.yml` on `push` of `v*` ([contracts/ci-and-release.md](contracts/ci-and-release.md)) |
| binary | `fylgja-linux-amd64`, `make build VERSION=0.1.0`, static (`file`: statically linked), `fylgja --version` → `0.1.0` |
| beside it | `SHA256SUMS` |
| gate | the tagged commit's `ci` run concluded `success`; `make test` passes on the runner |
| state | draft, created by the workflow → published by the operator |

## 8. The write-up: `docs/how-it-was-built.md`

One page. Sections: what Fylgja is (a paragraph); what a Spec Kit pass is
(specify → clarify → plan → tasks → analyze → implement → converge, each in a fresh
context, with a human deciding); what a convergence pass finds (the kinds of task it
appends, with the tags); the figures (a table: milestone, features, hours, passes,
model time by model), each derived from the private record (R-09's definitions), uncited;
what the hours say; what stays private and why ([D-043](../../docs/decisions.md#d-043)).
Its figures also live in [research.md §5](research.md#5-the-write-ups-figures).

## 9. The candidate issues

| # | Fact | Draft shown | Outcome | Recorded |
|---|---|---|---|---|
| 1–5 | research R-11's rows | by the `infrahub-reporting-issues` skill, before anything is submitted | `filed` (issue or discussion, with its link) or `dropped` (the operator's word, or a duplicate found, with the existing link) | verified-facts.md, beside the fact |

## 10. The repository's settings

Ordered as the operator makes them (the spec's assumption, with R-08's correction).

| Step | Setting | How (the operator, or with the operator's word in the session) |
|---|---|---|
| before the flip | `SECURITY.md` in the tree; the pull-request workflow in the tree; the tree read once more (research R-14) | commits on `013-launch`, merged to `main` and pushed by the operator |
| the flip | visibility `public` | `gh repo edit --visibility public --accept-visibility-change-consequences` |
| the same sitting | ruleset `main`: `deletion`, `non_fast_forward`, no bypass; private vulnerability reporting on; projects off; topics `infrahub`, `containerlab`, `digital-twin`, `network-automation` (and `temporal`, `srlinux`, `arista-eos`, `go`) | `gh api … /rulesets`, `gh api -X PUT … /private-vulnerability-reporting`, `gh repo edit --enable-projects=false --add-topic …` |
| after the script and CI | the badge in the README; `v0.1.0` published | a commit; `git tag -a v0.1.0 && git push origin v0.1.0`; publish the draft |
