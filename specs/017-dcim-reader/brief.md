# Specify brief: 0.3 spec 1 of 4: the Infrahub reader reads the schema library's DCIM (F-011)

This is what `/speckit-specify` reads for roadmap F-011, the feature that opens
[Release 0.3](../../docs/roadmap.md#release-03). It was written on 2026-10-25 from a
design session with the operator that set 0.3's direction: **exploratory coding that
informs the refactor of Fylgja into a production system**, a core that builds, updates and
destroys a twin from a snapshot, under an orchestrator that owns stages, rehearsals and
anything that reads a report. 0.3 is four specs, in this order: this one; snapshots as the
core's one input; probes, `ping` only ([016's brief](../016-probes/brief.md), re-read
against this spec's close); and a reader of NetBox, with its branching plugin, as a second
source of truth read directly. The session read the schema library's current files
([As read](#as-read)), ran one validation-only schema check, and verified nothing else
live; the plan verifies each point before relying on it. Specify what the operator gets,
not a new design. [References](#references) names every file to read.

The prompt:

```
SPECIFY_FEATURE_DIRECTORY=specs/017-dcim-reader GIT_BRANCH_NAME=017-dcim-reader. 0.3, the first of its four specs: the Infrahub reader reads the schema library's DCIM directly, the CTM becoming the contract in place of the generics, as docs/roadmap.md's F-011 and Release 0.3 section define it. Read specs/017-dcim-reader/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design.
```

## Why

- **The generics were the contract while Infrahub was the only source of truth.** They let
  any Infrahub schema implement Fylgja's four kinds and had Infrahub resolve the query
  across them ([D-002](../../docs/decisions.md#d-002)). With NetBox as the second source,
  read directly (0.3's fourth spec), a reader that maps a fixed, DCIM-shaped model onto the
  CTM is unavoidable, and once one reader works that way the generics make the Infrahub
  reader the odd one out. **The contract moves to the CTM**, and to the snapshot the
  second spec builds around it; each reader is an adapter for one source, with one
  documented mapping.
- **The generics never met a model somebody else wrote until they conflicted with one.**
  Probed on 2026-10-16 against OpsMill's [schema library](https://github.com/opsmill/schema-library),
  the DCIM kinds could inherit them only after adaptation on one side or the other
  ([Verified facts](../../docs/verified-facts.md), Infrahub 1.11.2, "Inheriting from two
  generics"): `role`, `platform`, `interfaces` and the Parent `device` each refused in
  turn. The session first thinned the contract to layer 1 and designed an overlay to carry
  it, then chose to carry nothing: read the library's kinds as they are.
- **Layer 1 is all Fylgja reads.** Nothing in the compiler, the bootstrap or verify
  consumes an address, a VLAN, a sub-interface, a loopback, a role or a site; the
  configuration Infrahub renders carries all of that, as it always did the work. The
  reader maps ports, their admin state, their management flag and their cables, and
  nothing else.

## Where the shape is fixed

- **The roadmap's [F-011](../../docs/roadmap.md#f-011)** and the
  [Release 0.3 section](../../docs/roadmap.md#release-03), rewritten to this brief on
  2026-10-25.
- **[D-002](../../docs/decisions.md#d-002), [D-003](../../docs/decisions.md#d-003) and
  [D-004](../../docs/decisions.md#d-004)** are superseded whole by this feature's decision
  entry: there is no generics contract, no `iftype`, no reserved structure. What survives
  of them is their rules, carried into the entry: never claim a meaning the source does not
  carry, and derive wiring in the compiler from what the reader mapped, never from a
  declaration.
- **[D-009](../../docs/decisions.md#d-009), [D-028](../../docs/decisions.md#d-028)** and
  Constitution IV: Infrahub renders every device's configuration, and it enters the bundle
  at read time, through `CoreArtifactTarget`, which the library's `DcimDevice` inherits.
  Unchanged.
- **[D-010](../../docs/decisions.md#d-010)**, the thin CTM with provenance, now the
  contract. **[D-011](../../docs/decisions.md#d-011)**, the pure compiler. The CTM thins;
  the compiler loses a case.
- **[D-016](../../docs/decisions.md#d-016), [D-031](../../docs/decisions.md#d-031)** and
  Constitution II: a platform is data. The package now also declares which of the source's
  platforms it is, so no field is added to anyone's model to key it.
- **[D-044](../../docs/decisions.md#d-044)**: the artifacts template lives here and reaches
  Infrahub only when imported from `origin`'s `main`; it changes, so the install's
  migration has an order ([Left to the plan](#left-to-the-plan)).
- **[D-045](../../docs/decisions.md#d-045)**: `FylgjaStage` is Fylgja's own kind beside
  the contract, branch-agnostic, on `main`. It was never the contract and is untouched; so
  is the stage reader.
- **[Constitution 1.3.0](../../.specify/memory/constitution.md)**:
  - **III** is rewritten, citing the entry, with a major version bump: the CTM is the
    contract; a reader maps one source's model onto it, documents the mapping, names the
    model's version it reads, records every approximation in the fidelity manifest, and
    reads nothing the mapping does not name; the read-only test holds the list of kinds
    read. "Demand the least possible" becomes "read the least possible". Conformance and
    completeness stay separate, all findings in one pass, no CTM on failure.
  - **II**: budgets and readiness from the package; now also the package's match.
  - **V**: the compiler stays pure; the goldens move and are re-baselined on their own
    commit.
  - **X**: every approximation and omission recorded. A management flag read from a role,
    an admin state read from a status, a cable omitted for its ends, each is a row.
- **The verified facts of 2026-10-16** on two generics no longer bear on the design; they
  stay true and recorded.

<a id="as-read"></a>
## As read, 2026-10-25 (the schema library at `26336e9`, Apache 2.0; unverified live)

- **`DcimGenericDevice`** (generic): `name` (unique, required), `description` (optional);
  `interfaces` (Component, many, peer `DcimInterface`, identifier `device__interface`),
  `platform` (Attribute, one, optional, peer `DcimPlatform`), `primary_address`, `tags`.
- **`DcimDevice`** (node) inherits `CoreArtifactTarget`, `DcimGenericDevice` and
  `DcimPhysicalDevice`; adds `status` (active, reserved, provisioning, maintenance,
  deprecated) and a `role` Dropdown. `DcimPhysicalDevice.location` is required, peer
  `LocationHosting`, whose concrete kinds are in `extensions/location_minimal`
  (`LocationSite` among them), so a device needs a location and the fixture seeds one.
- **The interface is split into generics**: `DcimInterface` (`name`, `description`,
  `status` with `disabled` among its values, `role` with `management` among its values,
  `mtu`; `device` as Parent), `InterfaceLayer2`, `InterfaceLayer3` (`ip_addresses`),
  `InterfaceHasSubInterface`, and `DcimEndpoint` (`connector`, one, peer `DcimConnector`,
  identifier `connector__endpoint`). The nodes are **`InterfacePhysical`**, inheriting all
  five, and **`InterfaceVirtual`**, inheriting the first three with a `parent_interface`.
  There is no `enabled` and no `mgmt_only`.
- **The cable is an extension**, `extensions/cable`: `DcimCable` inherits `DcimConnector`,
  whose `connected_endpoints` is Attribute, many, peer `DcimEndpoint`, identifier
  `connector__endpoint`, with no `min_count` or `max_count`; it adds `status` and
  `cable_type`.
- **`DcimPlatform`** (node): `name`, `description`, `manufacturer` (one, peer
  `OrganizationManufacturer`, from `base/organization.yml`), `devices`. No version, no key.
- **`base/ipam.yml`** must load even though nothing in it is read: the DCIM base peers on
  `IpamIPAddress`.
- The library's README calls it "a collection of examples", and its files begin "a
  starting point, not a finished production model". The last change to `base/dcim.yml`
  was on 2026-09-04.
- **Checked live**: an attribute named `package` passes `POST /api/schema/check` on `main`
  (validation only, `202`, nothing written). The design no longer adds it anywhere, but
  the name is known safe.

<a id="the-mapping"></a>
## The mapping

What the reader reads, and what each thing becomes. Everything else on the branch is
invisible to Fylgja.

| CTM | Read from | Rule | Fidelity |
|---|---|---|---|
| the scope | a tag, `BuiltinTag`, named by the request | every device carrying it is in the twin, whatever its `status`; everything else on the branch is outside the scope and not read | — |
| device | `DcimDevice` | every one carrying the scope's tag; `name` is the node name | exact |
| device's artifact | the device's artifacts, through `CoreArtifactTarget` | as now: the one named by its package, `Ready`, bytes verified against Infrahub's checksum | exact |
| platform | the device's `platform`, a `DcimPlatform`, with its `manufacturer` | the package whose declared match names the manufacturer's and the platform's `name`; inside the scope, no platform or no match refuses the read | exact |
| platform `version` | nothing | the library carries none; absent | omitted, recorded |
| port | the device's `interfaces` that are `InterfacePhysical` | `name`; an `InterfaceVirtual` is never read | exact |
| `mgmt_only` | the port's `role` | `management` is the one management port; a second is omitted as now | approximated |
| `enabled` | the port's `status` | `disabled` is disabled; every other value is enabled | approximated |
| link | the port's `connector`, a `DcimCable`, with its `connected_endpoints` | exactly two ends that are physical ports of devices in the scope; a cable with an end outside the scope, with other than two ends, or on anything but a physical port is omitted and recorded, a finding beside the CTM and a manifest row. A cable on a management port is carried, and the compiler omits and records it as it does today, so the CTM stays a faithful seam | exact, or omitted |
| the marker and the artifact-only change | the device's `description` | written by the fixture tool, rendered by the template, read by nobody else | — |

**The scope is a tag.** The operator tags each device the twin is of, with a tag of their
naming; ports and cables follow their devices. The request names it (`--scope tag:<name>`),
the server carries a default, and the twin record, the snapshot and the manifest's
provenance record which scope was read, so a twin says what it is a twin of. Inside the
scope the read is strict: an unmatched platform or incomplete data refuses it. At the
boundary a cable is omitted and recorded, which is where a later boundary device attaches.
The NetBox reader will use the same tag. On Infrahub the artifact definition still targets
the group `fylgja-devices`, since Infrahub renders for a group and not a tag, so a tagged
device outside the group has no artifact and is refused as today; the DCIM guide says so.

**The package declares its platforms.** Each support package gains a `matches` list of
manufacturer and platform names, data under Constitution II, so `nokia_srlinux` names
`Nokia` and `SR Linux` and the fixture's platform is found by them. The NetBox reader will
match the same way, on NetBox's manufacturer and platform. Nothing is added to the library
or to anyone's model to key a package.

## What changes, and nothing else

1. **The reader** (`internal/intent`) is rewritten against the library's kinds at a pinned
   commit, by [the mapping](#the-mapping). Its queries name `DcimDevice`, `DcimPlatform`,
   `InterfacePhysical` and `DcimCable` and nothing else of the operator's model. The stage
   reader's Infrahub-owned roots (`CoreProposedChange`, `Branch`, `CoreArtifactValidator`,
   `InfrahubEvent`) are untouched, but **its stamps query and its event mapper are
   rewritten too**, since both read the generics today: a device's intent stamp is the
   latest write on the device, on any of its interfaces (virtual ones included, since a
   user's transform may render them), on its platform and its manufacturer, and on any
   cable one of its ports is an end of; an event counts for a device when its node is one of
   those, or a peer of one. Broader than the old fixed field list, on purpose: the artifact
   may render any of them, and a stage reported fresh after a write the template read is
   what Constitution X forbids. Over-reporting staleness costs a regenerate; under-reporting
   costs a wrong rehearsal. **Conformance** becomes: the branch's
   schema holds those kinds with the fields the mapping reads (`GET /api/schema`), reported
   per kind and field, with the library version the reader was written against named in
   the finding. **Completeness** stays, inside the scope: a device with no platform, or one no package
   matches, is refused with a finding ([Open](#open) decides where). `fylgja schema check`
   runs the conformance half, as now. `FylgjaContract` and its version compare go.
2. **The scope.** `twin create`, `twin rehearse`, `intent read` and `stage plan` take
   `--scope tag:<name>`, the API's operations carry it, and the server has a default
   (configured as its other settings are; the plan names it). It is recorded in
   `twin.json`, whose format moves, in the snapshot's envelope and in the manifest's
   provenance. The checks pass none and so rehearse under the server's default.
3. **The support packages** gain `matches`, and the PSP format moves (`0.6` to `0.7`), with
   its schema and the conformance suite's pure half checking that every package names at
   least one match and no two packages share one.
4. **The CTM** drops `role`, `site`, `iftype`, `parent` and `addresses`; its platform
   becomes `package` and `version`; its envelope records the mapping's approximations and
   omissions so that the compiler can carry them into the manifest ([Open](#open) decides
   the form). The fixture CTMs under `testdata/ctm/` lose their loopbacks and their
   platforms change shape.
5. **The compiler** loses its loopback case: every interface is a port, cabled unless
   `mgmt_only`. The mapping rows and the manifest lose `iftype`; the manifest gains the
   reader's approximation rows. The breakout rule, which derives parentage from port names,
   is unchanged. All three goldens move, re-baselined on their own commit.
6. **The artifact query and template** (`infrahub/queries/device_config.gql`,
   `infrahub/templates/`) read `DcimDevice` with its platform's manufacturer and name, its
   physical interfaces with their role, status and cable, and its `description`; they lose
   the loopback branch and write the manufacturer, the platform and the description into the
   header comment. Every artifact moves, and with them the fixture's compiled id.
7. **The schema directory.** `fylgja-generics.yaml` and `reference.yaml` are removed.
   **`schema/dcim/`** holds the library's `base/dcim.yml`, `ipam.yml`, `location.yml` and
   `organization.yml`, and `extensions/cable/cable.yml` and
   `extensions/location_minimal/location_minimal.yml`, vendored verbatim at commit
   `26336e9` with the library's `LICENSE.txt`, and a note naming the commit.
   `fylgja-stage.yaml` stays. `schema/README.md` is rewritten: what the reader reads and at
   which library version, when a DCIM user is already conformant (the kinds and fields the mapping reads present
   as the pinned commit has them, which `schema check` reports), what a diverged schema
   costs (a reader of its own, which the production shape makes a seam), and the paragraph
   F-010 left: the shipped template as a reference transform that renders ports, and a
   user's own transform rendering their layer 2 and 3 from their own kinds.
8. **`main` and the fixtures.** `fylgja-fixture -prepare-main` loads `schema/dcim/` on
   `main` beside the stage kind, where the generics were, since the library is the model
   every branch shares. It is the development host's and CI's tool, not an install path: it
   loads the vendored files only when `main` holds none of the library's kinds, and refuses
   when it holds any, naming this. A DCIM user loads nothing of Fylgja's but the stage
   kind, and `fylgja schema check` tells them whether their kinds and fields are the ones
   the mapping reads, as the pinned commit has them. `fylgja-fixture` and the mixed fixture are re-seeded in the
   library's kinds: a site, a manufacturer per vendor, a platform per package, the same
   three nodes tagged `fylgja`, the server's default scope, their ports and cables,
   artifacts generated. `-set-role` and `-set-site` become
   `-set-description`, the artifact-only change, and the tier-3 marker moves to
   `description`. No second fixture branch: every twin is DCIM-modelled now.
9. **Tier 3** gains no case; its nine cases run over the re-seeded fixtures.
10. **The records**: `contracts/ctm.schema.json`, `manifest.schema.json`, `twin.schema.json`,
   `api.md`, `cli.md` and `psp/psp.schema.json`; the decision entry and the constitution's rewrite of III;
   `docs/architecture.md` §4.1 rewritten, §4.2, §4.3 and §4.7; the C4 model, since the
   schema component changes meaning; the schema README; `psp/README.md`;
   `docs/development.md` (the fixtures, the migration); `docs/verified-facts.md`; the
   glossary (mapping, approximation, the library); the README's walk-through; `CLAUDE.md`'s
   Environment (`main`'s schema and hash, the fixture's id), Formats and State; and the
   roadmap, already rewritten.

<a id="decided"></a>
## Decided

- **The CTM is the contract; the generics go.** With two sources of truth every reader is
  an adapter, and an adapter that reads the source's own kinds costs its users nothing.
  The operator chose this on 2026-10-25 over a layer-1 generics contract carried into the
  library by an overlay, which the session had designed first.
- **Layer 1 only.** Nothing above it is consumed; the configuration carries the rest.
- **A port is `InterfacePhysical`**, and `InterfaceVirtual` is never read.
- **`mgmt_only` is `role: management` and `enabled` is `status` not `disabled`**, each
  recorded as approximated, since the library's meanings are near Fylgja's and not
  identical.
- **The scope is a tag on each device, and nothing else.** A real DCIM branch holds
  console servers, PDUs and OOB switches no package will match, so a twin needs saying what
  it is of. Both sources carry tags natively; a group is Infrahub's alone and a location
  cannot say "half this site". The operator chose the tag alone, over the tag beside
  Infrahub's existing group, on 2026-10-25. `status` does not filter: a tagged device is the
  operator's intent.
- **Inside the scope the read is strict.** A device no package matches, or with no
  platform, refuses the read, as incomplete data always has; a twin that silently thinned
  on a typo would be wrong rather than refused.
- **A cable the read cannot place is omitted and recorded, never a refusal of the read.**
  A console cable, a patch panel, a cable to a device outside the scope: refusing the read
  on the first of them would defeat the feature. Constitution X's rule applies.
- **The package declares its platforms** by manufacturer and platform name. Keying by a
  field would add one to the library and to NetBox alike; the package is Fylgja's own data
  and the right home. The platform's `version` is absent from this reader.
- **The library is vendored verbatim at a pinned commit**, under its licence, and the
  reader names the commit it was written against. The library calls itself experimental,
  so the coupling is explicit, as a package's `versions` is to its image.
- **The library loads on `main`** by `-prepare-main`, as the generics did, since it is the
  model every branch shares ([D-028](../../docs/decisions.md#d-028)'s reasoning holds).
- **One fixture branch, re-seeded in the library's kinds.** The fixture's loopbacks go;
  they showed the template rendering a loopback, which the reader no longer sees.
- **`description` is the marker's home.** The library has it natively; nothing is added.
- **A device's intent is every write on it and on what it owns**: its interfaces, its
  platform and manufacturer, its cables. The reviewer's question, settled for Constitution
  X: a user's transform may render any of them.
- **A cable on a management port reaches the CTM**, and the compiler omits and records it
  as it does today. The reader does not pre-empt the compiler's rule, so the NetBox reader
  sees the same seam.
- **`-prepare-main` refuses an install that already holds the library**, since loading the
  pinned files over a user's later library would migrate their `main`. The reviewer's
  question, settled: the tool is the development host's.
- **Nothing Infrahub-shaped lives outside the reader.** The reader is the one component
  that knows the library's kinds; the CTM is the seam the NetBox reader fills in 0.3's
  fourth spec, and the snapshot spec wraps.
- **Out of this feature**: snapshots (the second spec), probes (the third), the NetBox
  reader (the fourth), the agent skill and `infrahub-sync` (left the release), and the
  refactor itself.

<a id="open"></a>
## Open, for clarify

1. **Where a missing or unmatched platform is refused.** At the read, as a completeness
   finding that produces no CTM (Constitution III's rule for required data), or at compile,
   as a finding against a CTM whose device carries no package.
2. **The CTM's version.** `1`, with the fields dropped and a CTM carrying them still
   accepted, or `2`, refusing one. The precedent (M5's `artifact`) kept `1` when a field
   was added; this change also reshapes the platform.
3. **How the reader's approximations reach the manifest.** A per-field fidelity list in
   the CTM's envelope that the compiler copies, or a provenance tag on each mapped field
   as D-010's per-object tag does, or the compiler asserting them from the reader's name
   alone, as `production_forwarding` is asserted per package.
4. **The server's default scope.** A setting of the server (an environment name beside
   its others), or no default, every request naming its scope and the checks carrying a
   fixed one. A default keeps the checks and the fixture simple; none keeps every twin
   record explicit.

<a id="left-to-the-plan"></a>
## Left to the plan

- **Live verification of the reads**, on a throwaway branch seeded in the library's kinds,
  recorded in research.md and then verified-facts.md: filtering a device's `interfaces` to
  `InterfacePhysical` in one query (`__typename` or a kind filter); reading a port's
  `connector` as the generic `DcimConnector` and the cable's `connected_endpoints` through
  it; the cable's ends' devices; and how `GET /api/schema` reports each kind and field the
  conformance half checks.
- **How the reader names the library version it reads**, and what conformance says when a
  branch's kinds differ from it: the kinds and fields present, since a schema hash is per
  install.
- **The install's migration, in order.** `main`'s four generics and `FylgjaContract` are
  removed with `state: absent`, the library is loaded on `main`, `fylgja-fixture` is
  deleted and re-seeded (it is never rebased, and its schema is its own), and the template
  is imported. Until the template on `origin`'s `main` is imported, Infrahub renders with a
  query that names `FylgjaDevice`, which the branch no longer has, so no artifact
  regenerates; and a session never pushes. The plan says how tier 2 runs on this host in
  the window: a throwaway registration from the tree, as `TestChecksInsideInfrahub` makes
  one, or the operator's push and import as a gate before tier 2. The new `main` hash and
  the fixture's compiled id are recorded in `CLAUDE.md` after.
- **The decision entry** superseding D-002, D-003 and D-004, and the constitution's
  rewrite of III, with the read-only test's new form: the list of kinds the reader queries.
- **The frozen copies** older tests read, and which formats move: the CTM, the manifest,
  `twin.json` (the scope), the PSP (`0.7`), the mapping profile's schema if it names
  `iftype`.
- **Load OpsMill's skill `infrahub-managing-objects`** before the fixture tool's seed of
  the library's kinds, and `infrahub-managing-transforms` before the query and template;
  the plugin `infrahub@opsmill` is installed. Their start-up rules yield to `CLAUDE.md`
  where it decides otherwise.
- **The marker's exact form** in `description`, and the mixed fixture's second
  manufacturer and platform.
- **The C4 redraw**: the schema component becomes the vendored library and the stage kind;
  the reader's description changes.

<a id="exit"></a>
## Exit

- **Tier 1**: the compiler without `iftype`, every interface a port; the CTM's validation
  as clarify decides; the three goldens re-baselined on their own commit; the conformance
  suite's pure half over the new CTMs and the packages' `matches`; the mapping's rules
  under test against recorded Infrahub answers.
- **Tier 2**: `fylgja-fixture`, re-seeded in the library's kinds, reads to the CTM
  `testdata/ctm/three-node.json` holds, and the mixed fixture to its own; `fylgja schema
  check` passes on both and refuses a branch without the library's kinds, naming each;
  the artifacts render through the rewritten template; a cable with a third end on a
  throwaway branch is omitted and recorded, as is a cable to an untagged device, which is
  not read; a tagged device whose platform no package matches refuses the read; `internal/stages` and `internal/checks` pass
  unchanged.
- **Tier 3**: the nine cases pass over the re-seeded fixtures, with the marker in
  `description`.
- **Owed before the work starts**: the roadmap rewritten (done 2026-10-25); the operator
  aware that the template change needs their push and import before tier 3, that `main`'s
  schema is migrated, and that both fixtures are re-seeded.

<a id="references"></a>
## References

Read in this order, after `CLAUDE.md`'s list.

| Record | What it gives |
|---|---|
| [docs/roadmap.md](../../docs/roadmap.md): [Release 0.3](../../docs/roadmap.md#release-03), [F-011](../../docs/roadmap.md#f-011), [F-025](../../docs/roadmap.md#f-025), [Decisions the order needs](../../docs/roadmap.md#decisions-the-order-needs) | the scope, and the second reader this one sets the shape for |
| [docs/decisions.md](../../docs/decisions.md): D-002, D-003, D-004, D-009, D-010, D-011, D-016, D-028, D-031, D-044, D-045 | what this feature builds on and supersedes |
| [.specify/memory/constitution.md](../../.specify/memory/constitution.md) 1.3.0: II, III, IV, V, X | the Constitution Check, and the principle rewritten |
| [docs/verified-facts.md](../../docs/verified-facts.md): Infrahub 1.11.2 | the schema and artifact facts the reads rest on |
| [schema/](../../schema/): `fylgja-generics.yaml`, `reference.yaml`, `fylgja-stage.yaml`, `README.md` | the contract as it was, and the kind that stays |
| [the schema library](https://github.com/opsmill/schema-library) at `26336e9`: `base/dcim.yml`, `ipam.yml`, `location.yml`, `organization.yml`, `extensions/cable`, `extensions/location_minimal` | the model the reader reads |
| [docs/architecture.md](../../docs/architecture.md) §4.1, §4.2, §4.3, §4.7 | the reader, the CTM, the compiler and the packages that move |
| [contracts/ctm.schema.json](../../contracts/ctm.schema.json), [contracts/manifest.schema.json](../../contracts/manifest.schema.json), [psp/psp.schema.json](../../psp/psp.schema.json), [psp/README.md](../../psp/README.md) | the documents that move |
| [infrahub/queries/device_config.gql](../../infrahub/queries/device_config.gql), [infrahub/templates/](../../infrahub/templates/) | the template that renders what the reader reads |
| [internal/intent](../../internal/intent) (`queries.graphql`, `project.go`, `conformance.go`, `readonly_test.go`), [internal/ctm](../../internal/ctm), [internal/compiler](../../internal/compiler) (`mapping.go`), [internal/psp](../../internal/psp) | what reads, carries, compiles and matches |
| [cmd/fylgja-fixture](../../cmd/fylgja-fixture), [internal/testsupport](../../internal/testsupport), [scripts/e2e.sh](../../scripts/e2e.sh) | the fixtures, the marker and the cases that move |
| [016's brief](../016-probes/brief.md) | the third spec, whose probe declaration carries its own gateway address now that the CTM has none |
