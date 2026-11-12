# fylgja-core (CONTRIBUTING.md).

.PHONY: all venv test live cluster conformance lint linkcheck wheelcheck image imagecheck infrahub-up infrahub-down \
	infrahub-register infrahub-seed contract orchestrator-env prefect-up prefect-down orchestrator-serve

VENV := core/.venv

# local/ is the main checkout's, also when make runs in a worktree: the parent of git's common directory.
MAIN := $(shell dirname "$$(git rev-parse --path-format=absolute --git-common-dir)")
LOCAL ?= $(MAIN)/local

# The development Infrahub (CONTRIBUTING.md): its version, the SDK's for infrahubctl, the ref registered, the
# seeded branch, PURGE=1 (no other value) for an infrahub-down that removes the volumes, and PROPOSED_CHANGE=1 (no
# other value) for an infrahub-seed that makes the seeded branch's proposed change.
INFRAHUB_VERSION ?= 1.11.11
INFRAHUB_SDK_VERSION ?= 1.23.2
REF ?= $(shell git branch --show-current)
SEED_BRANCH ?= third-link
PURGE ?=
PROPOSED_CHANGE ?=

# The core's image, tagged by the commit it is built at: its first 12 characters, and -dirty
# where `git status --porcelain` prints anything (D-062). Worked out once, as make starts, so
# `image` and `imagecheck` build and check one tag, whatever changes in the tree meanwhile.
IMAGE ?= fylgja-core
TAG := $(shell git rev-parse HEAD 2>/dev/null | cut -c1-12)$(if $(shell git status --porcelain 2>/dev/null),-dirty)

all: lint test

# The core's venv at core/pyproject.toml's pins: the package editable, with its extras server and dev (D-084), and
# the reader's and the example orchestrator's beside it, each editable, with its extra dev.
venv:
	test -x $(VENV)/bin/python || python3 -m venv $(VENV)
	printf '*\n' > $(VENV)/.gitignore
	$(VENV)/bin/pip install -q -e 'core[server,dev]'
	$(VENV)/bin/pip install -q -e 'readers/infrahub[dev]'
	$(VENV)/bin/pip install -q -e 'orchestrator[dev]'

# The pure tier: no infrastructure (Constitution, Development).
test:
	cd core && .venv/bin/pytest -q
	cd infrahub && ../core/.venv/bin/pytest -q
	cd readers/infrahub && ../../core/.venv/bin/pytest -q
	cd orchestrator && ../core/.venv/bin/pytest -q

# The live tier: booted images on the local driver, on demand (CONTRIBUTING.md): tests/live, and the conformance
# suite on the local harness. Load local/.env first.
live:
	cd core && FYLGJA_CONFORMANCE_DRIVER=containerlab .venv/bin/pytest -q -rA -m live tests/live tests/conformance

# The cluster tier: the clabernetes driver's calls on the k3s cluster, on demand (CONTRIBUTING.md). Load local/.env first.
cluster:
	cd core && .venv/bin/pytest -q -rA -m cluster tests/cluster

# The conformance suite alone, on the harness of the driver DRIVER names: containerlab (the default) under the live
# tier's marker on this host, clabernetes under the cluster tier's against the deployed core. Load local/.env first.
DRIVER ?= containerlab
CONFORMANCE_MARKER = $(if $(filter containerlab,$(DRIVER)),live,$(if $(filter clabernetes,$(DRIVER)),cluster))

conformance:
	$(if $(CONFORMANCE_MARKER),,$(error DRIVER is containerlab or clabernetes))
	cd core && FYLGJA_CONFORMANCE_DRIVER=$(DRIVER) .venv/bin/pytest -q -rA -m $(CONFORMANCE_MARKER) tests/conformance

# mypy runs twice: the core's tests and infrahub/'s would name modules alike in one run.
lint:
	cd core && .venv/bin/ruff check --config pyproject.toml . ../scripts ../infrahub && .venv/bin/mypy && .venv/bin/mypy ../infrahub/seed ../infrahub/tests ../scripts/infrahub_dev.py
	cd readers/infrahub && ../../core/.venv/bin/ruff check --config pyproject.toml . && ../../core/.venv/bin/mypy
	cd orchestrator && ../core/.venv/bin/ruff check --config pyproject.toml . && ../core/.venv/bin/mypy

# Every relative link and anchor in the tracked Markdown resolves in a clone.
linkcheck:
	python3 -I scripts/linkcheck.py

# The wheel, built from core/ and formats/ and carrying the core's formats and no other, installed outside the tree
# with the extra server and alone, each base library at the floor of its range (D-066, D-084). Needs the network.
# Then the reader's, built from readers/infrahub/ and formats/ with its one format and its queries, installed beside
# the base alone, where its command answers --help; then the example's, built from orchestrator/ and formats/ with its
# two formats and its change source's queries, installed beside the base and the reader alone, where its command
# answers --help.
wheelcheck:
	python3 -I scripts/wheelcheck.py

# The core's image from the Dockerfile; its build context is .dockerignore's allow-list. Needs Docker and the network.
image:
	docker build -t $(IMAGE):$(TAG) .

# The image built, then run: its user, its entry point's refusal, its formats (those CORE_FORMATS in core/setup.py
# names, each byte for byte its file in formats/), its packages' files against git's; the tag printed last.
imagecheck: image
	python3 -I scripts/imagecheck.py $(IMAGE):$(TAG)

# The development Infrahub, the Compose project fylgja-core-infrahub: local/.env's missing names written, never
# printed; the published Compose file fetched once; started, and waited for until /api/info answers the version.
infrahub-up:
	python3 -I scripts/infrahub_dev.py up --local $(LOCAL) --version $(INFRAHUB_VERSION) --override infrahub/dev/compose.override.yml --repo $(MAIN)/.git

# Stopped, its containers, network and volumes kept; PURGE=1, and no other value, removes them and
# local/infrahub/seed.json.
infrahub-down:
	python3 -I scripts/infrahub_dev.py down --local $(LOCAL) --version $(INFRAHUB_VERSION) --override infrahub/dev/compose.override.yml --repo $(MAIN)/.git $(if $(filter 1,$(PURGE)),--purge)

# infrahubctl, in a venv of its own under local/infrahub/, so that the SDK meets nothing else (D-083).
$(LOCAL)/infrahub/.venv/bin/infrahubctl:
	python3 -m venv $(LOCAL)/infrahub/.venv
	printf '*\n' > $(LOCAL)/infrahub/.venv/.gitignore
	$(LOCAL)/infrahub/.venv/bin/pip install -q 'infrahub-sdk[ctl]==$(INFRAHUB_SDK_VERSION)'

# The schema library, the group fylgja-devices and this repository's registration on main, at REF, the branch checked
# out, and its commit (CONTRIBUTING.md); a detached head names no branch and is refused. Load local/.env first.
infrahub-register: $(LOCAL)/infrahub/.venv/bin/infrahubctl
	$(if $(REF),,$(error REF is empty: a detached head names no branch to register; give REF=<branch>))
	$(VENV)/bin/python infrahub/seed/register.py --ref $(REF) --commit $$(git rev-parse --verify '$(REF)^{commit}') --schema infrahub/schema/dcim --ctl $(LOCAL)/infrahub/.venv/bin/infrahubctl

# The reader's FylgjaProbe kind and the example's FylgjaStage on main where main lacks them; the fixture network on
# main from infrahub/seed/main/'s object files, loaded by infrahubctl, and its configurations generated and waited
# for; then an earlier seed's marks and open proposed change of SEED_BRANCH removed, and the branch made anew with
# infrahub/seed/stages/'s two edits, each generated, waited for, timed by the reader's head and marked on main; with
# PROPOSED_CHANGE=1, last, its proposed change into main. Into local/infrahub/seed.json (CONTRIBUTING.md). Load
# local/.env first.
infrahub-seed: $(LOCAL)/infrahub/.venv/bin/infrahubctl
	$(VENV)/bin/python infrahub/seed/seed.py --branch $(SEED_BRANCH) --files infrahub/seed --out $(LOCAL)/infrahub/seed.json --ctl $(LOCAL)/infrahub/.venv/bin/infrahubctl --schema readers/infrahub/schema/fylgja-probe.yml --schema infrahub/schema/fylgja-stage.yml $(if $(filter 1,$(PROPOSED_CHANGE)),--proposed-change)

# The example orchestrator's lines in local/.env, generated and never printed: the basic auth the edge's Prefect and the
# task workers share, the runner's token of the core's, listed in the token file FYLGJA_TOKENS names, the scope, the
# reader document and the records' directory; then its Infrahub account and that account's token, checked where the
# line is there (CONTRIBUTING.md, "Running the example orchestrator"). Load local/.env first.
orchestrator-env: $(LOCAL)/infrahub/.venv/bin/infrahubctl
	python3 -I scripts/edge_dev.py env --local $(LOCAL) --main $(MAIN)
	$(VENV)/bin/python infrahub/seed/account.py --env $(LOCAL)/.env --ctl $(LOCAL)/infrahub/.venv/bin/infrahubctl

# The edge's Prefect server on port 4200 of the Docker bridge's gateway (PREFECT_BIND over it), under local/prefect/,
# waited for until it answers; refused, with nothing started or stopped, where anything else listens on the port.
# Load local/.env first.
prefect-up:
	python3 -I scripts/edge_dev.py prefect-up --local $(LOCAL) --main $(MAIN)

# The server prefect-up started ended, and no other process.
prefect-down:
	python3 -I scripts/edge_dev.py prefect-down --local $(LOCAL) --main $(MAIN)

# The runner, fylgja-orchestrator serve, in the foreground until it is stopped, given its own tokens and no other.
# Load local/.env first.
orchestrator-serve:
	python3 -I scripts/edge_dev.py serve --local $(LOCAL) --main $(MAIN)

# The contract tier: infrahub/'s code, then the reader's, then the example orchestrator's, against the running
# development Infrahub, the last with a Prefect server of its own on loopback (CONTRIBUTING.md). Load local/.env first.
contract:
	cd infrahub && FYLGJA_INFRAHUB_SEED=$(LOCAL)/infrahub/seed.json FYLGJA_INFRAHUB_CTL=$(LOCAL)/infrahub/.venv/bin/infrahubctl ../core/.venv/bin/pytest -q -rA -m contract tests/contract
	cd readers/infrahub && FYLGJA_INFRAHUB_SEED=$(LOCAL)/infrahub/seed.json FYLGJA_INFRAHUB_CTL=$(LOCAL)/infrahub/.venv/bin/infrahubctl ../../core/.venv/bin/pytest -q -rA -m contract tests/contract
	cd orchestrator && FYLGJA_INFRAHUB_SEED=$(LOCAL)/infrahub/seed.json FYLGJA_INFRAHUB_CTL=$(LOCAL)/infrahub/.venv/bin/infrahubctl ../core/.venv/bin/pytest -q -rA -m contract tests/contract
