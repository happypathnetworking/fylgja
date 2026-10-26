# The schema library's DCIM, vendored

The six schema files Fylgja's Infrahub reader reads, and the library's licence, copied
byte for byte from [opsmill/schema-library](https://github.com/opsmill/schema-library) at
commit **`26336e9026dff1907f2c58e81dd6ae7b5c3f763e`** (the merge of its pull request #98,
2026-10-09). The reader maps this commit's DCIM onto the CTM, and conformance checks a
branch against what this commit's kinds report ([D-057](../../docs/decisions.md#d-057)).

| Library path | Vendored as | SHA-256 |
|---|---|---|
| `base/dcim.yml` | `dcim.yml` | `81df2eb8cc0a58c496c3292c6349591695048bf1a036b1ccef5190842bc16c9e` |
| `base/ipam.yml` | `ipam.yml` | `6d31dc0307f9053c334e028b57c2d6fca1fa51741a18cfebfbfd3ac35a9fe588` |
| `base/location.yml` | `location.yml` | `afef7a770c05a8110295bd8e6d7f12348cf260851b9f3da828edb6ae8c53f926` |
| `base/organization.yml` | `organization.yml` | `082e8536f389d5ad971f2808068234a3dab6c48249230db9ec1aa308124e5fff` |
| `extensions/cable/cable.yml` | `cable.yml` | `3196073cdd490350e514c2bc777e27a647b1e7dbaf6c29fa9e3abc524e943041` |
| `extensions/location_minimal/location_minimal.yml` | `location_minimal.yml` | `cf148227aa191f13a77e2758aa9639e8312c61fae9538762d3b63bfb044b15c3` |
| `LICENSE.txt` | `LICENSE.txt` | `71d4aed1ad1acd6b90246d50984276bf0d5a3a27c2bb06feb91b96058c67399d` |

**The files are never reformatted or edited**, not by `infrahubctl schema format` nor by
hand: they are the library's bytes, so that a branch that loaded the library from its own
clone at this commit holds what Fylgja's conformance table expects. The binary embeds them
(`embed.go`), and `TestVendoredLibraryIsThePinnedCommit` (`embed_test.go`) holds each
embedded file's SHA-256 to this table and this file to the commit. Moving to another
commit is a decision of its own, which moves the commit, the table, the reader's mapping
and the CTM's `envelope.mapping.version` together.

**Licence.** The library is the Apache License 2.0's, as Fylgja is; its text is
`LICENSE.txt` here, the library's own file, and it ships in the binary beside the files it
covers. The library has no `NOTICE` file.

**How they are loaded.** `go run -tags fixture ./cmd/fylgja-fixture -prepare-main` loads
the six files in one request, and only onto a `main` that holds none of the library's
kinds: a `main` that holds any is refused, loading nothing, since a `main` that already
holds the library is its operator's, and `fylgja schema check` says whether it is the one
the reader reads ([R-13](../../specs/017-dcim-reader/research.md#r-13)). Test support loads
them the same way onto a throwaway branch, then the stage kind (`../fylgja-stage.yaml`)
in a second request. The library's root README calls it "a collection of examples … in an
experimental phase": Fylgja reads it at this commit alone.
