# Feature Specification: The launch

**Feature Branch**: `013-launch`

**Created**: 2026-10-07

**Status**: Draft

**Input**: User description: "SPECIFY_FEATURE_DIRECTORY=specs/013-launch. M14 — Reproducible and visible, the second of its two features: the launch, as docs/roadmap.md's Next section, D-043 and D-044 define it. Read specs/013-launch/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design."

M14 is two features. The cut made this repository's first commit
([D-043](../../docs/decisions.md#d-043)). The launch, this feature, makes the repository
public at its start and ends with a stranger able to stand Fylgja up: one bring-up script
takes a clean Ubuntu 26.04 host to every tier passing, CI runs tier 2 against a real
Infrahub, the development host's Infrahub renders from this repository
([D-044](../../docs/decisions.md#d-044)), and the front page carries a recorded session, a
threat model, a first release and a write-up. Its scope is the roadmap's
[Next section](../../docs/roadmap.md#next), item by item; its settled decisions are the
brief's [Decided](brief.md#decided) list, which this spec restates only where a
requirement needs the sentence. **No product behaviour changes**: every format, command,
workflow, activity, wire type, golden, recorded history and the live fixture id are the
cut's.

Three people appear below. **The operator** owns the repository and the development host,
makes every outward-facing act (the flip to public, the settings, the release, each issue
submitted) and pushes `origin`; a session never pushes. **A stranger** has a clone, an
Ubuntu 26.04 host and, optionally, the cEOS tar from Arista, and has never seen the
private record. **CI** is a hosted runner that runs what the stranger runs.

## Clarifications

### Session 2026-10-07

- Q: When the script runs again on a host it already set up, which has a `local/.env` holding the tokens Infrahub's volumes were created with and an Infrahub already running, what does it do with them? → A: Keep the existing `local/.env` and the running Infrahub; re-verify each part, install only what is missing, and end with the tiers passing as a first run does.
- Q: When tier 3 is narrowed to a platform list and every case it ran passed, what exit status does the run end with, beside its partial-pass line? → A: Exit 0, ending on the distinct partial-pass line; `E2E-OK` is never printed by a narrowed run; a failed case still exits 1 and a leak 99.
- Q: When the script finds a cEOS tar but its checksum differs from the recorded one, does it stop, or go on for SR Linux alone and say so? → A: Stop before importing, naming the file, the checksum found and the one recorded; nothing else of the run proceeds.
- Q: When the script ends on a fresh host, does it leave the Temporal dev server, the worker and the API's server running, or stop them after reading their reports? → A: Leave all three running, detached, logging under `local/`, as development.md's three-process section describes; the last report says they are up and how to stop them.
- Q: What intent does the README's recorded session run against, given that a step needs a twin built from a waypoint series, which the fixture branch does not have? → A: The throwaway `fylgja-test-readme` branch and series seeded by the fixture tool, as the README's stepping walk-through already does, deleted after the recording. The fixture branch gains no series; a persistent stepping series on it is an idea for the order after the launch, not this feature's scope.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The repository goes public first (Priority: P1)

The operator makes the repository public before the script, CI and the registration are
built and proved, so that every registration they make afterwards is the credential-less
one a stranger makes, no token for this repository is ever stored in a secret or on a
host, and nothing has to be dropped and re-proved at the close. The first public view is
the README and the system as cut; the script, CI, the recording and the release arrive in
the open.

**Why this priority**: every other story registers this repository in an Infrahub with no
credential, which only a public repository allows. The flip comes first or the rest is
built twice.

**Independent Test**: a person with no GitHub account clones the repository over HTTPS
and reads its front page; a pull request against it is not taken; `main` cannot be
rewritten; `SECURITY.md` says how to report a vulnerability; a read of the tree finds
nothing private.

**Acceptance Scenarios**:

1. **Given** the tree at the flip, **When** it is read once more for anything private,
   **Then** no credential, no commit hash, path, task number, file name or quotation of
   the private record, and no host's process id or local path is found in any file of
   the tree, this branch's work included.
2. **Given** the settings set and `SECURITY.md` in the tree with its way to report a
   vulnerability, **When** the operator makes the repository public, **Then** a person
   with no account clones it over HTTPS and reads the README, `LICENSE` and
   `SECURITY.md`.
3. **Given** the repository public, **When** someone opens a pull request, **Then** the
   repository's settings refuse it or close it unreviewed, as the README's Contributing
   section says, and `main` can be pushed to by the operator alone and never
   force-pushed or deleted.
4. **Given** the repository public, **When** a stranger registers it in their own Infrahub
   as a read-only repository on `main` with no credential, **Then** the clone, the
   connectivity check and the import succeed and the artifact definition appears on
   `main`.

---

### User Story 2 - A stranger stands Fylgja up with one script (Priority: P1)

A stranger with a fresh Ubuntu 26.04 install, a clone of this repository and the pinned
cEOS tar runs one script. It takes the host through the roadmap's four parts, toolchain,
lab host, Infrahub and Fylgja, and ends with the build, tier 1 and tier 2 passing and the
worker's and the server's start-up reports naming both packages. The hand walk-through in
development.md becomes the script's record. Tier 3 then passes in full on that host, once,
by the operator's hand.

**Why this priority**: it is the roadmap's definition of the launch's close, "a stranger
able to stand Fylgja up", and the one script both consumers run.

**Independent Test**: on a fresh Ubuntu 26.04 VM, from a clone and the tar, one run of the
script ends with tiers 1 and 2 passing and both reports naming both packages; `make
test-e2e` then ends `E2E-OK` with eight cases.

**Acceptance Scenarios**:

1. **Given** a fresh Ubuntu 26.04 install, a clone and the tar at a path the stranger
   gives, or in `local/`, or in the clone's parent directory, **When** the script runs,
   **Then** it ends with `make build`, `make test` and `make test-contract` passed and the
   worker's and the server's start-up reports naming both packages, the dev server, the
   worker and the server left running, and its first and last reports name both platforms
   and where the tar was found.
2. **Given** that host as the script left it, **When** `make test-e2e` runs, **Then** it
   ends `E2E-OK`, all eight cases, case 1 deploying `b9d53ebc…`.
3. **Given** a host on any Ubuntu release but 26.04, **When** the script runs, **Then** it
   refuses before changing anything, naming the release it found and the one it supports.
4. **Given** the cEOS image already present under exactly the reference the EOS package
   names, **When** the script runs, **Then** it skips the import and says so.
5. **Given** a tar found whose checksum differs from the recorded one, **When** the script
   runs, **Then** it imports nothing and stops before any further part, naming the file,
   the checksum it found and the one recorded.
6. **Given** a host the script already set up, with its `local/.env` and its Infrahub
   running, **When** the script runs again, **Then** it keeps that `local/.env` and that
   Infrahub, re-verifies each part, installs only what is missing, and ends the same way,
   with the tiers passing and the reports naming both packages.
7. **Given** the script's run, **When** its output and every file it wrote but `local/.env`
   are read, **Then** no token and no password appears in any of them.
8. **Given** the script's run, **When** `local/.env` is read, **Then** every name that
   `.env.example` documents is present and filled, the tokens made by the script and each
   login its image's published default, but `FYLGJA_PSP_DIR`, left empty on purpose so
   that the embedded packages are used.

---

### User Story 3 - SR Linux alone (Priority: P2)

A stranger without an Arista account runs the script with no tar. It goes on for SR
Linux alone, says so in its first and last reports with where it looked, and ends with
tiers 1 and 2 passing. Tier 3 on that host refuses by default, as it does today, and a
run narrowed to `nokia_srlinux` runs every case that needs no other package and ends on a
partial-pass line naming the two it skipped and why.

**Why this priority**: the cEOS image is account-gated and never vendored, so without this
path half of the audience cannot stand Fylgja up at all. It is the roadmap's one decision
named for the launch, taken in the brief.

**Independent Test**: the script run once without a tar names SR Linux alone and passes
tiers 1 and 2; `make test-e2e` narrowed to `nokia_srlinux` ends on the partial-pass line
naming cases 6 and 8; a default run refuses naming the absent cEOS reference; a tar placed
in the repository root is not found.

**Acceptance Scenarios**:

1. **Given** no tar at the given path, in `local/` or in the parent directory, **When** the
   script runs, **Then** it goes on, its first and last reports name SR Linux as the one
   platform the host can run and the places it looked, and it ends with tiers 1 and 2
   passed.
2. **Given** the pinned tar placed in the repository root and nowhere else, **When** the
   script runs, **Then** it is not found, and the reports name where the script looked.
3. **Given** that host, **When** `make test-e2e` runs with no platform list, **Then** it
   refuses before any case, naming the absent cEOS reference and how to import it.
4. **Given** that host, **When** tier 3 runs narrowed to `nokia_srlinux`, **Then** cases 1
   to 5 and 7 run and pass, cases 6 and 8 are skipped, and the run exits 0 on a line
   distinct from `E2E-OK` naming the platforms it ran and each skipped case with the
   package it needs and that its image is absent.
5. **Given** a host with both images, **When** tier 3 runs narrowed to `nokia_srlinux`,
   **Then** cases 6 and 8 are still skipped, naming the package outside the list: the list
   selects by package, not by image.
6. **Given** a platform list naming a package no shipped package has, **When** tier 3
   runs, **Then** it refuses before any case, naming the packages it knows.
7. **Given** a platform list naming every shipped package, **When** tier 3 runs on a host
   with both images, **Then** it runs as a default run does and ends `E2E-OK`.
8. **Given** a narrowed run, **When** it ends, **Then** the host is as clean as a full run
   leaves it, and the same credential and marker greps have run.

---

### User Story 4 - CI runs tier 2 against a real Infrahub (Priority: P2)

On every push to `main`, CI runs the unit job and then the contract job: the script's
Infrahub part brings up Infrahub 1.11.2 on the runner, gives `main` the schema and the
group, registers this repository with no credential, awaits the import and seeds the
fixture; then the generated client is checked against the live schema and tier 2 runs. A
pull request runs the unit job alone. The README carries the badge.

**Why this priority**: tier 2 has run only on the development host until now; CI with a
real Infrahub is what makes the contract tier the repository's, not the operator's.

**Independent Test**: a push to `main` turns both jobs green, the contract job's log
showing Infrahub brought up, the repository registered, the fixture seeded and tier 2
passed; a pull request runs the unit job alone; the badge in the README shows the last run
on `main`.

**Acceptance Scenarios**:

1. **Given** a push to `main`, **When** CI runs, **Then** the unit job and the contract
   job both pass, and the contract job's log shows the Infrahub part's stages in order,
   the registration with no credential, the seed, the generated-client diff and tier 2.
2. **Given** a pull request, **When** CI runs, **Then** the unit job runs and the contract
   job does not.
3. **Given** the day GitHub moves `ubuntu-latest` to another release, **When** CI runs,
   **Then** nothing changes, because both jobs name `ubuntu-26.04`.
4. **Given** any CI log, **When** it is read, **Then** no token and no password appears
   in it.
5. **Given** the README, **When** it is read on the repository's front page, **Then** the
   badge shows the result of the last run on `main`.
6. **Given** the repository's secrets, **When** they are listed, **Then** none holds a
   credential for this repository.

---

### User Story 5 - Infrahub renders from this repository (Priority: P2)

Once the repository is public, the development host's Infrahub registers it as a
read-only repository on `main` with no credential, in place of the private copy of the
template, which is unregistered. The template's bytes are the same, so no artifact and no
fixture id moves; tier 2 and tier 3 pass on that host afterwards. The fixture tool's
refusal names this repository's registration, and whether Infrahub takes a new commit on
a `ref` update or only on re-creation is verified and recorded.

**Why this priority**: it executes D-044 on the one Infrahub that exists today, and proves
on the development host what the script and CI do on theirs.

**Independent Test**: after the registration, the private copy is absent from Infrahub's
repositories, `make infrahub-seed` passes, the live fixture compiles to `b9d53ebc…`, and
`make test-contract` and `make test-e2e` pass.

**Acceptance Scenarios**:

1. **Given** the repository public and the private copy registered, **When** this
   repository is registered read-only on `main` with no credential and the private copy
   is removed, **Then** the import completes, the artifact definition and the group are
   found by name, the seed passes and the fixture compiles to `b9d53ebc…`.
2. **Given** that registration, **When** tier 2 and tier 3 run on the development host,
   **Then** both pass.
3. **Given** a branch that cannot find the definition or the group, **When** the fixture
   tool refuses, **Then** its message names this repository's read-only registration on
   `main`, not `fylgja-artifacts`.
4. **Given** a new commit on `main` of this repository, **When** the registration's `ref`
   is updated, **Then** whether Infrahub 1.11.2 imports the new commit or only on
   re-creation is recorded in verified-facts.md with the version and date, and
   development.md says which.

---

### User Story 6 - The front page (Priority: P3)

A reader of the repository's front page sees what is built and how to stand it up: the
README with the recorded session, the badge and the script; `SECURITY.md` with the threat
model and how to report a vulnerability; the release `v0.1.0` with its static binary; the
settings and topics; the one-page write-up of how Fylgja was built; and, on Infrahub's
tracker, each verified behaviour of Infrahub 1.11.2 filed or dropped by the operator's
word.

**Why this priority**: it is what makes the repository worth reading, and none of it is a
feature. It follows the script and CI because the README's Tests and What it needs
sections point at them.

**Independent Test**: the operator reads the front page at the close and finds each item:
README, badge, recording, `LICENSE`, `SECURITY.md`, the release, the diagrams.

**Acceptance Scenarios**:

1. **Given** the README, **When** it is read, **Then** it embeds an animated image of one
   recorded session, a create, a step and a verify, made on the development host against
   the throwaway `fylgja-test-readme` branch and series the stepping walk-through seeds,
   with the cast beside it under `docs/`, and no credential is visible in any frame.
2. **Given** `SECURITY.md`, **When** it is read, **Then** it says the API is one bearer
   token sent in the clear, on loopback unless `--listen` says otherwise, that the server
   holds Infrahub's token and both node logins, what a reader on a shared host should
   know, and how to report a vulnerability; and it was in the tree before the flip.
3. **Given** the tag `v0.1.0`, **When** its release is opened, **Then** one static binary
   is attached, `fylgja --version` prints `0.1.0`, and the tagged commit's CI passed.
4. **Given** the repository's settings, **When** they are read, **Then** `main` is
   protected, issues are open, pull requests are not taken, and the topics name Infrahub,
   containerlab, digital twin and network automation.
5. **Given** `docs/how-it-was-built.md`, **When** it is read, **Then** it is one page that
   says what a Spec Kit pass is, what a convergence pass finds and what the hours say
   about AI-assisted engineering with a human deciding; its figures are stated as derived
   from the private record, and it cites no link, path, commit hash, task number, file
   name or wording of that record.
6. **Given** the five Infrahub behaviours verified-facts.md records, **When** each is
   taken through the `infrahub-reporting-issues` skill, **Then** its draft is shown
   before anything is submitted, it is filed as an issue or a discussion or dropped by
   the operator's word, and a filed one's link is in verified-facts.md.

---

### User Story 7 - The records are true at the close (Priority: P3)

A reader of the documents finds the launch recorded: development.md's walk-through is the
script's record; every fact re-verified on Ubuntu 26.04 is in verified-facts.md with its
version and date; the roadmap's Built table carries the launch and Next names what comes
after it; `CLAUDE.md`'s State is rewritten whole and its Environment describes the 26.04
host.

**Why this priority**: the documents are what a reader and the next session act on, and
the milestone closes by rewriting them.

**Independent Test**: each record named in the Functional Requirements says what this
feature made true, and `grep` finds no statement the launch made false (24.04.1 as the
development host, the private copy registered, the contract job disabled, no recording).

**Acceptance Scenarios**:

1. **Given** development.md, **When** it is read, **Then** its Local environment section
   is the script's record, it describes CI's two jobs, the read-only registration and the
   `ref` update answer, and tier 3's platform list.
2. **Given** verified-facts.md, **When** it is read, **Then** every fact the script
   re-verified carries the version and date of its re-verification on 26.04, The host
   describes the 26.04 host, and a fact that no longer held is corrected, never silently
   worked around.
3. **Given** the roadmap, **When** it is read, **Then** the Built table carries the
   launch and Next names the first item after it.
4. **Given** `CLAUDE.md`, **When** it is read, **Then** its State is rewritten whole and
   its Environment describes the 26.04 development host.
5. **Given** the README, **When** its What it needs and Tests sections are read, **Then**
   they point at the script and CI and say what an SR Linux-only host gets: the cEOS
   image needed only for EOS and mixed twins and tier 3's EOS cases, and the
   walk-throughs, all SR Linux, unchanged.
6. **Given** the glossary, **When** it is read, **Then** each new term this feature
   introduced has an entry.

---

### Edge Cases

- **The host is not Ubuntu 26.04.** The script refuses before changing anything, naming
  the release it found and the one it supports.
- **The tar is found but its checksum differs.** Nothing is imported and the script stops
  before any further part, naming the file, the checksum found and the one recorded; it
  does not fall back to SR Linux alone, since the stranger placed the tar on purpose.
- **The tar is in the repository root alone.** Not found; the reports name where the
  script looked. The root is never searched, because `.gitignore` does not cover it and
  the converge loop commits from it.
- **The cEOS reference is already present.** The import is skipped and said so; the same
  image under another tag is absent, as the host check reads it.
- **A second run on a set-up host.** The existing `local/.env` and the running Infrahub are
  kept, since Infrahub's volumes hold the admin token the first run made; each part is
  re-verified, only what is missing is installed, and the run ends the same way.
- **The stranger's user is not yet in `docker` or `clab_admins`.** Group membership takes
  effect at the next login; the script either continues under the new groups or says what
  to do before its next part, and never ends claiming a tier passed that did not run.
- **Infrahub's port is already held, or another Compose project of Infrahub is on the
  host.** The script names what holds the port and stops, rather than bringing a second
  Infrahub up beside it.
- **The repository sync is stuck `PENDING`.** The script's wait for the import is bounded
  and names the stuck sync on expiry; it never waits without end.
- **A `BranchCreate` straight after a `BranchDelete` fails with `graphql: None`.** The seed
  is run again, as development.md says.
- **The runner's time or memory does not hold Infrahub and the import.** The contract job
  fails naming the stage; the spec allows CI to be split out of the one script if the
  runner needs more than the script gives, recorded as a decision.
- **A fork's pull request.** The contract job does not run, because it runs on pushes to
  `main` alone and never under `pull_request_target`.
- **A narrowed tier 3 run names an unknown package.** Refused before any case, naming the
  packages known.
- **A credential in the recording's frame.** The recording is re-made; the cast and the
  rendered image are read before they are committed.
- **The `ref` update does not bring in a new commit.** Recorded as such; a template change
  is then a documented re-registration, and development.md says so.
- **An Infrahub behaviour is a duplicate on the tracker.** The skill's search finds it; it
  is dropped with the existing issue's link recorded instead.
- **The development host moves to 26.04 while the write-up's figures are owed.** The
  private record stays reachable until the figures are read and confirmed by the
  operator.

## Requirements *(mandatory)*

### Functional Requirements

**The bring-up script**

- **FR-001**: One script MUST take a fresh Ubuntu 26.04 install, from a clone of this
  repository, through four parts, toolchain, lab host, Infrahub and Fylgja, and end with
  `make build`, `make test` and `make test-contract` passed and the worker's and the
  server's start-up reports naming both packages, in one run.
- **FR-002**: The script MUST support Ubuntu 26.04 alone, name the release it finds, and
  refuse any other before changing anything.
- **FR-003**: The toolchain part MUST provide `make`, `git`, a Go that lets `go.mod` fetch
  its own toolchain, golangci-lint 2.14.0, the Temporal CLI, `gnmic`, and a Python venv at
  the repository root holding `infrahub-sdk[ctl]` with a `.gitignore` of `*` inside it.
- **FR-004**: The lab host part MUST provide Docker Engine with the user in `docker`,
  containerlab 0.79 with the user in `clab_admins`, the SR Linux image pulled, the AppArmor
  widening for SR Linux's `rsyslogd`, and the cEOS import of FR-005.
- **FR-005**: The script MUST look for the cEOS tar at a path the operator gives, then in
  `local/`, then in the repository's parent directory, and never in the repository root;
  take only the file the EOS package's version names; check it against a recorded
  checksum; import it under exactly the reference the EOS package names; and skip the
  import when that reference is present.
- **FR-006**: Without a tar, the script MUST go on for SR Linux alone, and its first and
  last reports MUST name the platforms the host can run and where it looked.
- **FR-007**: A tar found whose checksum differs from the recorded one MUST NOT be
  imported, and the script MUST stop before any further part, naming the file, the
  checksum it found and the one recorded; it MUST NOT go on for SR Linux alone.
- **FR-008**: The Infrahub part MUST bring up Infrahub 1.11.2 from its published Compose
  with the override that pins the version and caps Neo4j, load the schema on `main`,
  create the group `fylgja-devices`, register this repository as a read-only repository on
  `main` with no credential, await the import, and seed the fixture; every wait MUST be
  bounded and name what it waited for on expiry.
- **FR-009**: The Infrahub part MUST run on its own, as CI's contract job runs it.
- **FR-010**: The script's preamble MUST scaffold `local/.env` from `.env.example` with
  every documented name present and filled (`FYLGJA_PSP_DIR` empty on purpose) when the
  file is absent, before the Infrahub part reads it. The Fylgja part MUST build, run tier
  1 and tier 2, start the dev server, the worker and the server detached, logging under
  `local/`, read each report, and leave all three running when the script ends, so that
  the host is ready for a twin create. What the run ends with is FR-001's; what the last
  report says is FR-012's.
- **FR-011**: The script MUST make every token it needs (Infrahub's initial admin token,
  the API's token) and write each into `local/.env` alone; its output and every other file
  it writes MUST carry no token and no password.
- **FR-012**: The script's first report MUST name what it will do and the platforms the
  host can run; its last report MUST name what it did, the platforms, where the tar was
  looked for and found, each tier's result, and the three processes it left running with
  how to stop them.
- **FR-013**: The script run again on a host it set up MUST keep the existing `local/.env`
  and the running Infrahub, re-verify each part, install only what is missing, and end
  the same way; it MUST NOT re-scaffold `local/.env` or re-create Infrahub's volumes.
- **FR-014**: The script is tooling beside `scripts/e2e.sh`, never part of what Fylgja
  ships: the binary MUST stay one static Go binary with no second runtime in its critical
  path.
- **FR-015**: The script's first run on Ubuntu 26.04 MUST re-verify every fact of
  verified-facts.md it touches; each is recorded in this feature's `research.md`, then in
  verified-facts.md with its version and date, and a fact that no longer holds is a
  finding, never a silent workaround.
- **FR-016**: development.md's hand walk-through MUST become the script's record: it
  describes what the script does, part by part, and no longer asks the reader to do it by
  hand.

**Tier 3 by platform**

- **FR-017**: `scripts/e2e.sh` MUST keep requiring every shipped package's image by
  default, so that a bare `E2E-OK` means all eight cases.
- **FR-018**: An explicit platform list MUST narrow a run: it selects by package, never by
  image; skips each case that needs a package outside the list or whose account-gated
  image is absent; and, when every case it ran passed, exits 0 on a line distinct from
  `E2E-OK` naming the platforms run and each skipped case with why. A narrowed run never
  prints `E2E-OK`; a failed case still exits 1 and a leak 99.
- **FR-019**: Each case MUST declare the packages it needs; today cases 6 and 8 need
  `arista_eos`.
- **FR-020**: A platform list naming a package no shipped package has MUST be refused
  before any case, naming the packages known; a list naming every shipped package runs
  as a default run.
- **FR-021**: A narrowed run MUST leave the host as clean as a full run and run the same
  credential and marker greps.

**CI**

- **FR-022**: The unit job MUST run on every push to `main` and every pull request; the
  contract job MUST run on pushes to `main` alone and never under `pull_request_target`;
  both MUST name `ubuntu-26.04` and never `ubuntu-latest`.
- **FR-023**: The contract job MUST run the script's Infrahub part, then the
  generated-client diff, then tier 2.
- **FR-024**: No credential for this repository MUST be stored in a repository secret or
  on a host, and no CI log MUST carry a token or a password.
- **FR-025**: The README MUST carry a badge showing the last run on `main`.
- **FR-026**: Tier 3 MUST NOT run in CI.

**Infrahub renders from this repository**

- **FR-027**: The development host's Infrahub MUST register this repository as a read-only
  repository on `main` with no credential, in place of the private copy, which MUST no
  longer be registered afterwards; the live fixture MUST still compile to `b9d53ebc…`, and
  tier 2 and tier 3 MUST pass there.
- **FR-028**: The fixture tool's refusal MUST name this repository's read-only
  registration on `main`, not `fylgja-artifacts`; nothing else of the tool's product-facing
  behaviour changes.
- **FR-029**: Whether Infrahub 1.11.2 imports a new commit on a `ref` update or only on
  re-creation MUST be verified and recorded in verified-facts.md with the version and
  date, and development.md MUST say which.

**Public and visible**

- **FR-030**: The repository MUST go public before the script, CI and the registration
  are built and proved, by the operator's act, once the settings refuse pull requests,
  `SECURITY.md` says how to report a vulnerability, and the tree, this branch's work
  included, has been read once more for anything private; the ruleset that protects
  `main` is set in the same sitting as the flip, immediately after it, since GitHub's
  Free plan offers rulesets to public repositories alone, and until then write access is
  the operator's alone.
- **FR-031**: `SECURITY.md` MUST state the threat model (one bearer token sent in the
  clear, on loopback unless `--listen` says otherwise; the server holds Infrahub's token
  and both node logins; what a reader on a shared host should know) and how to report a
  vulnerability.
- **FR-032**: The README MUST embed an animated image rendered from an asciinema recording
  of one create, one step and one verify made on the development host against the
  throwaway `fylgja-test-readme` branch and series the README's stepping walk-through
  seeds with the fixture tool, deleted after the recording; committed under `docs/` with
  the cast beside it, with no credential in any frame. The fixture branch gains no
  series.
- **FR-033**: The tag `v0.1.0` MUST carry a release with one static binary attached,
  stamped so that `fylgja --version` prints the line `fylgja version 0.1.0`, built from a
  commit whose CI passed.
- **FR-034**: The repository's settings MUST protect `main`, keep issues open and refuse
  pull requests, and its topics MUST name Infrahub, containerlab, digital twin and network
  automation.
- **FR-035**: `docs/how-it-was-built.md` MUST be one page saying what a Spec Kit pass is,
  what a convergence pass finds and what the hours say about AI-assisted engineering with
  a human deciding; its figures MUST be derived from the private record and stated as
  such, read by the operator before they are committed, and it MUST cite no link, path,
  commit hash, task number, file name or wording of that record.
- **FR-036**: Each of the five Infrahub 1.11.2 behaviours verified-facts.md records MUST
  be taken through the `infrahub-reporting-issues` skill, its draft shown before anything
  is submitted, and filed as an issue or a discussion or dropped by the operator's word; a
  filed one's link MUST be in verified-facts.md.
- **FR-037**: Every outward-facing act (the flip, the settings and topics, the release,
  each submission) MUST be the operator's or made with the operator's word in the
  session; a session MUST NOT push.

**The records and the boundary**

- **FR-038**: At the close, development.md, verified-facts.md, the glossary, the roadmap,
  `CLAUDE.md` and the README MUST say what this feature made true, as User Story 7 lists,
  and the research log of this feature MUST hold what the script found on 26.04 and the
  write-up's figures with how each was counted.
- **FR-039**: No product behaviour MUST change: bundle `4`, CTM `1`, PSP `0.6`,
  `twin.json` `5`, contract `0.2`, findings `1`, the API `1`, the three goldens, the live
  fixture id, every command, workflow, activity and wire type, and the nine recorded
  histories are the cut's. A product change found necessary is a defect raised before it
  is made.
- **FR-040**: The only test tooling this feature may change is the fixture tool's refusal
  (FR-028), `scripts/e2e.sh` (FR-017 to FR-021), and, if the plan chooses it, the fixture
  tool's or `testsupport`'s ability to prepare `main` (the schema, the group, the
  registration) for the script's Infrahub part.
- **FR-041**: Nothing this feature writes (the script and its output, CI's logs, the
  recording, `SECURITY.md`, `research.md`, the write-up) MUST carry a credential. The
  images' published default logins are the packages' data, not a credential: the script
  carries them as `scripts/e2e.sh` does and writes them into `local/.env` alone, and they
  MUST appear nowhere else this feature writes.
- **FR-042**: Every commit of this feature MUST be authored as the repository's first
  commit is, with the `Co-Authored-By` trailer of the model that made it.

### Key Entities

- **The bring-up script**: the one script both consumers run. Its inputs are the host, the
  clone, and optionally a path to the cEOS tar; its parts are toolchain, lab host,
  Infrahub and Fylgja; its outputs are a set-up host, `local/.env`, and a first and a last
  report. Its Infrahub part stands alone.
- **The platform list**: tier 3's optional narrowing, a list of shipped package names.
  Absent, every package's image is required; present, it selects cases by the packages
  they declare and ends on the partial-pass line.
- **The registration**: this repository as a read-only repository on `main` in an
  Infrahub, with no credential; made by the script, by CI's job and on the development
  host, each the same way a stranger makes it.
- **The recording**: one asciinema cast of a create, a step and a verify against the
  throwaway `fylgja-test-readme` branch and series, and the animated image rendered from
  it, both under `docs/`.
- **The release**: tag `v0.1.0` and one static binary stamped `0.1.0`.
- **The write-up**: `docs/how-it-was-built.md`, one page, its figures derived from the
  private record and uncited.
- **The candidate issues**: the five Infrahub 1.11.2 behaviours of verified-facts.md, each
  filed or dropped.
- **`local/.env`**: the one file holding a value; scaffolded by the script's preamble
  from `.env.example`, every name present and filled but `FYLGJA_PSP_DIR`, empty on
  purpose.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a fresh Ubuntu 26.04 VM, from a clone and the tar, one run of the script
  ends with tiers 1 and 2 passed and both start-up reports naming both packages, with no
  input asked after its start beyond privilege escalation.
- **SC-002**: On that VM, `make test-e2e` ends `E2E-OK` with all eight cases, once, case 1
  deploying `b9d53ebc…`.
- **SC-003**: On a VM without the tar, the script names SR Linux alone in its first and
  last reports and ends with tiers 1 and 2 passed; tier 3 narrowed to `nokia_srlinux`
  ends on the partial-pass line naming cases 6 and 8; a default tier 3 refuses naming
  the absent cEOS reference; a tar in the repository root is not found.
- **SC-004**: A push to `main` turns both CI jobs green, the contract job having brought
  Infrahub up, registered this repository with no credential, seeded the fixture and run
  tier 2 inside the runner's job limit; a pull request runs the unit job alone; the badge
  shows it; the contract job's wall time is recorded in `research.md`.
- **SC-005**: On the development host, the private copy is unregistered, the live fixture
  compiles to `b9d53ebc…`, tier 2 and tier 3 pass, and the `ref` update question has one
  recorded answer.
- **SC-006**: The front page read by the operator at the close shows the README with the
  recording, the badge and the script, `LICENSE`, `SECURITY.md`, the release `v0.1.0` with
  its binary, the diagrams, the settings and the topics; `docs/how-it-was-built.md` is one
  page.
- **SC-007**: A grep of everything this feature wrote, and of CI's logs and the script's
  output, for the API's token and Infrahub's token finds nothing; a grep for both images'
  published default passwords over the recording, CI's logs, the script's output and the
  records finds nothing, the two scripts and `local/.env` being the only places they are
  allowed; a read of the recording finds none in any frame.
- **SC-008**: A grep of the tree for the private record's commit hashes, paths, task
  numbers and file names finds nothing, before the flip and at the close.
- **SC-009**: Every fact of verified-facts.md the script touched carries a 26.04
  re-verification with its version and date, and its The host section describes the
  26.04 host.
- **SC-010**: Each of the five Infrahub behaviours has one recorded outcome: filed, with
  its link in verified-facts.md, or dropped, with the operator's word.
- **SC-011**: `fylgja --version` on the release's binary prints the line `fylgja version
  0.1.0`, and the binary is static.
- **SC-012**: The three goldens, the live fixture id, every format version and every
  recorded history are unchanged from the cut: `make test` passes with no golden
  re-baselined.

## Assumptions

Each is a reasonable default taken where the brief did not decide; the Clarifications
session above settled five questions, now written into the requirements.

- **The release's binary is for Linux on amd64 alone**, the lab host's platform; a client
  on another machine builds from the tree, as development.md says.
- **The script asks nothing after it starts** but privilege escalation; the tar's path and
  any other input are given at the start, so a run is unattended.
- **The fresh VM is sized for tier 3**: memory as verified-facts.md's The host records (a
  twin beside Infrahub's capped Neo4j); its exact size is the plan's.
- **Infrahub's initial admin token and the API's token are the script's to make**, so no
  secret is handed to it; whether CI needs any secret at all is the plan's.
- **The development host moves to 26.04 by a fresh install the script sets up**, as the
  operator verifies the script; the 24.04.1 facts are re-verified there.
- **The operator's acts come in this order**: the settings, `SECURITY.md` and the read of
  the tree; the flip; the registration on the development host; then the script, CI, the
  recording, the write-up, the issues and the release.
- **The write-up's figures are read in one session on the development host**, from a
  location the operator gives in that session and nothing here writes down; the operator
  reads the figures before they are committed.
- **The group-membership re-login** is handled inside the script or stated by it before
  its next part; which is the plan's.
- **The recording's renderer and format** (SVG or GIF) and its size on the README are the
  plan's; the README embeds whichever renders on GitHub's front page.

**Out of scope**: M8 and M9; any product behaviour; a second Ubuntu release; tier 3 in CI;
vendoring or pulling the cEOS image; a `CONTRIBUTING.md`; another platform; a change to
the template's bytes; a persistent waypoint series on the fixture branch (an idea for the
order after the launch: it would reverse the fixture tool's refusal, the test-series
guard and the tiers' "no waypoints" invariant, and could add a tier-3 step of an SR
Linux-only twin, which no case steps today).

**Dependencies**: Infrahub's published Compose file for 1.11.2; GitHub's hosted
`ubuntu-26.04` runner; Arista's cEOS-lab tar for 4.32.0.2F, provided by the operator or
the stranger; asciinema and a renderer to an animated image; the private development
record reachable on the development host for the write-up's figures; the OpsMill
`infrahub-reporting-issues` skill.
