# Contract: tier 3's platform list (`scripts/e2e.sh`)

Test tooling, no product change. Everything not named here is as `docs/development.md`,
"Tier 3, as `scripts/e2e.sh` runs it", describes.

## The variable

```
PLATFORMS=<list> make test-e2e          # or: PLATFORMS=<list> scripts/e2e.sh
```

`<list>` is one or more shipped package names separated by commas or spaces. A shipped
package name is its `platform.id`, which is the stem of its file under `psp/`:
`nokia_srlinux`, `arista_eos`. Unset or
empty: the run is a default run, which requires every shipped package's image before any
case, as now.

## What each case needs

Declared in one table at the top of the script, read by nothing else:

| Case | Packages |
|---|---|
| 1, 2, 3, 4, 5, 7 | `nokia_srlinux` |
| 6, 8 | `nokia_srlinux arista_eos` |

## Refusals before any case (exit 1, through `fail`)

- `e2e: FAILED: PLATFORMS names <name>, which no shipped package has; known: arista_eos nokia_srlinux`
- `e2e: FAILED: PLATFORMS=<list> selects no case: every case needs nokia_srlinux`
- a default run on a host without `ceos:4.32.0.2F`: unchanged,
  `e2e: FAILED: image ceos:4.32.0.2F is absent: import it as docs/development.md says; it is never pulled`

## Selection, with a list

A case runs when every package it needs is in the list and, for a package whose
`image.acquisition` is `account_gated`, its `image.ref` is present (`docker image
inspect`). Otherwise it is skipped, and the skip is printed where the case would start:

```
e2e: case 6: skipped (needs arista_eos: not in PLATFORMS)
e2e: case 6: skipped (needs arista_eos: image ceos:4.32.0.2F absent)
e2e: case 6: skipped (needs arista_eos: not in PLATFORMS; image ceos:4.32.0.2F absent)
```

The third form is printed when both hold, so that on an SR Linux-only host narrowed to
`nokia_srlinux` the reason names the package outside the list and that its image is
absent, as US3 scenario 4 asks.

The list selects by package, never by image: on a host with both images,
`PLATFORMS=nokia_srlinux` still skips cases 6 and 8. A list naming every shipped package
on a host with every image runs as a default run and ends `E2E-OK`.

## The end of the run

| End | Line | Exit |
|---|---|---|
| default run, every case passed | `E2E-OK` | 0 |
| a list, no case skipped, every case passed | `E2E-OK` | 0 |
| a list, at least one case skipped, every case run passed | `E2E-PARTIAL: platforms <list>; ran <cases>; skipped <case> (<reason>) [<case> (<reason>)]…`, each reason one of the three forms above | 0 |
| a failed check | `e2e: FAILED: …` | 1 |
| a lab, a twin directory or the Schedule left behind | `e2e: LEAK: …` | 99 |

Example: `E2E-PARTIAL: platforms nokia_srlinux; ran 1 2 3 4 5 7; skipped 6 (needs
arista_eos: not in PLATFORMS) 8 (needs arista_eos: not in PLATFORMS)` on a host with both
images; on an SR Linux-only host each reason reads `needs arista_eos: not in PLATFORMS;
image ceos:4.32.0.2F absent`. A narrowed run never prints `E2E-OK` when it skipped a
case.

## Unchanged

The trap's destroy and branch deletion, the leak checks, the credential and marker greps
over everything the run produced, the API's server the script starts, and every case's
checks. The closing timing lines print for the cases that ran alone.
