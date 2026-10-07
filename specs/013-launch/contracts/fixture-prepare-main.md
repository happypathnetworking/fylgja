# Contract: `fylgja-fixture -prepare-main`

Test tooling under the `fixture` build tag; the one binary that writes to Infrahub
([D-001](../../../docs/decisions.md#d-001)). FR-040 allows it. Reads `INFRAHUB_ADDRESS`
and `INFRAHUB_API_TOKEN` from the environment, as every flag of the tool does.

## Usage

```
go run -tags fixture ./cmd/fylgja-fixture -prepare-main \
    [-schema-dir schema] \
    [-repository-name fylgja] \
    [-repository-location https://github.com/happypathnetworking/fylgja.git] \
    [-repository-ref main] \
    [-wait 300s]
```

`-prepare-main` acts on `main` alone and takes no `-branch`; given one, it refuses before
any request. It combines with no other flag.

## Steps, in order; each skips what exists

1. **The schema**: `schema/*.yaml` loaded on `main` (`LoadSchema`: `POST
   /api/schema/load?branch=main`, then the wait for the kinds). On a `main` that has it
   the load is a no-op (research §2.4). Prints `schema loaded on main`.
2. **The group**: `CoreStandardGroup` named `fylgja-devices` looked up by name; created
   when absent. Prints `group fylgja-devices present` or `created`.
3. **The registration**: `CoreReadOnlyRepository` named `-repository-name` looked up by
   name; when absent, created with `location`, `ref` and a description naming D-044, and
   **no credential**. Prints `repository fylgja present (…)` or `created (location …,
   ref main, no credential)`.
4. **The wait**, bounded by `-wait`, polling each second, for all of: the repository's
   `internal_status` `active`, its `operational_status` `online`, and `main` holding the
   `CoreGraphQLQuery` `device_config`, the `CoreTransformJinja2` `srlinux_device_config`
   and the `CoreArtifactDefinition` `srlinux_device_config` with artifact name
   `device-config`. Prints `import complete after <s>s: query, transform and definition
   on main`.

## Refusals and failures (exit 1, `fylgja-fixture: …` on stderr)

- `-prepare-main takes no -branch: it prepares main`
- the wait's expiry: `main did not hold <the missing ones> within <wait>; the repository
  is <internal_status>/<operational_status>; a git_repositories_sync run stuck PENDING in
  Infrahub's task manager blocks every import until it is cancelled`
- a repository of that name whose `location` or `ref` differ from the flags: `repository
  fylgja is registered at <location> on <ref>, not <wanted>; remove it or name another
  with -repository-name` (nothing is changed)
- every HTTP or GraphQL error, as the tool reports them today

## Idempotence

A second run on a prepared `main` prints `present` for the group and the repository,
re-loads the schema (a no-op) and passes through the wait at once. Nothing is updated or
deleted by this flag.

## The reworded refusal (FR-028)

`lookupByName` and `groupMemberCount` in `internal/testsupport/infrahub.go`:

```
branch %s holds %d %s named %q, want one; register this repository
(github.com/happypathnetworking/fylgja) on main as a read-only repository with no
credential and wait for its import (docs/development.md, "What Infrahub needs"); a
branch created before the import cannot see it
```
