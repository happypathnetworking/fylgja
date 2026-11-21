# fylgja-core (CONTRIBUTING.md).

.PHONY: all venv test live cluster conformance lint linkcheck wheelcheck wheels image imagecheck infrahub-up \
	infrahub-down infrahub-register infrahub-seed contract netbox-up netbox-down netbox-seed contract-netbox \
	nautobot-up nautobot-down nautobot-seed contract-nautobot

VENV := core/.venv

# local/ is the main checkout's, also when make runs in a worktree: the parent of git's common directory.
MAIN := $(shell dirname "$$(git rev-parse --path-format=absolute --git-common-dir)")
LOCAL ?= $(MAIN)/local

# The development Infrahub (CONTRIBUTING.md): its version, the SDK's for infrahubctl, the ref registered, the
# seeded branch and PURGE=1 (no other value) for an infrahub-down that removes the volumes.
INFRAHUB_VERSION ?= 1.11.11
INFRAHUB_SDK_VERSION ?= 1.23.2
REF ?= $(shell git branch --show-current)
SEED_BRANCH ?= third-link
PURGE ?=

# The development NetBox (CONTRIBUTING.md): NetBox's version, netbox-docker's release and the branching plugin's;
# PURGE=1 above, and no other value, for a netbox-down that removes the volumes.
NETBOX_VERSION ?= 4.7.5
NETBOX_DOCKER_VERSION ?= 5.1.1
NETBOX_BRANCHING_VERSION ?= 1.2.3

# The development Nautobot (CONTRIBUTING.md): Nautobot's version, Golden Config's and the image's Python; PURGE=1
# above, and no other value, for a nautobot-down that removes the volumes.
NAUTOBOT_VERSION ?= 3.2.8
GOLDEN_CONFIG_VERSION ?= 3.0.8
NAUTOBOT_PYTHON ?= 3.14

# The core's image, tagged by the commit it is built at: its first 12 characters, and -dirty
# where `git status --porcelain` prints anything (D-062). Worked out once, as make starts, so
# `image` and `imagecheck` build and check one tag, whatever changes in the tree meanwhile.
IMAGE ?= fylgja-core
TAG := $(shell git rev-parse HEAD 2>/dev/null | cut -c1-12)$(if $(shell git status --porcelain 2>/dev/null),-dirty)
# The same commit in full, which the image's build stage writes into the core's package as the build it answers
# --version with (D-106): `image` passes it, and `imagecheck` holds the image's --version to TAG's twelve characters.
COMMIT := $(shell git rev-parse HEAD 2>/dev/null)$(if $(shell git status --porcelain 2>/dev/null),-dirty)

all: lint test

# The core's venv, core/.venv, a locked sync of the uv workspace (D-108): the four distributions editable with every
# extra, at the versions uv.lock holds, which a pin moved in a pyproject.toml without `uv lock` refuses. The
# interpreter is the PATH's python3, never one uv fetches.
venv:
	UV_PROJECT_ENVIRONMENT=$(abspath $(VENV)) uv sync --locked --all-packages --all-extras --python python3
	printf '*\n' > $(VENV)/.gitignore

# The pure tier: no infrastructure (Constitution, Development).
test:
	cd core && .venv/bin/pytest -q
	cd infrahub && ../core/.venv/bin/pytest -q
	cd netbox && ../core/.venv/bin/pytest -q
	cd nautobot && ../core/.venv/bin/pytest -q
	cd readers/infrahub && ../../core/.venv/bin/pytest -q
	cd readers/netbox && ../../core/.venv/bin/pytest -q
	cd readers/nautobot && ../../core/.venv/bin/pytest -q

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

# mypy runs four times: the core's tests, infrahub/'s, netbox/'s and nautobot/'s would name modules alike in one run.
lint:
	cd core && .venv/bin/ruff check --config pyproject.toml . ../scripts ../readme_links.py ../infrahub ../netbox ../nautobot && .venv/bin/mypy && .venv/bin/mypy ../infrahub/seed ../infrahub/tests ../scripts/infrahub_dev.py && .venv/bin/mypy ../netbox/seed ../netbox/tests ../scripts/netbox_dev.py && .venv/bin/mypy ../nautobot/seed ../nautobot/tests ../scripts/nautobot_dev.py
	cd readers/infrahub && ../../core/.venv/bin/ruff check --config pyproject.toml . && ../../core/.venv/bin/mypy
	cd readers/netbox && ../../core/.venv/bin/ruff check --config pyproject.toml . && ../../core/.venv/bin/mypy
	cd readers/nautobot && ../../core/.venv/bin/ruff check --config pyproject.toml . && ../../core/.venv/bin/mypy

# Every relative link and anchor in the tracked Markdown resolves in a clone.
linkcheck:
	python3 -I scripts/linkcheck.py

# The wheel, built from core/ and formats/ and carrying the core's formats and no other, installed outside the tree
# with the extra server and alone, each base library at the floor of its range (D-066, D-084). Needs the network.
# Then the reader's, built from readers/infrahub/ and formats/ with its one format and its queries, installed beside
# the base alone, where its command answers --help; then the NetBox reader's, with its one format, beside the base
# alone, where it answers --help and refuses a missing token; then the Nautobot reader's, checked the same way.
# Each wheel is built at the tree's commit and holds it, and each installed command's --version names the tree's
# version and that commit.
wheelcheck:
	python3 -I scripts/wheelcheck.py

# The four published wheels (D-106, D-121), core, readers/infrahub, readers/netbox and readers/nautobot, and no other,
# built by uv into dist/ (git-ignored), emptied first, each at COMMIT, the tree's commit, which each wheel holds. Each
# member's build/ is removed first, so that no file since removed from the tree rides along from an earlier build. The
# backend is the setuptools build-constraints.txt names, not whatever the index holds that day. scripts/publish.py
# check holds them, the tag, VERSION and CHANGELOG.md to one another. uv writes dist/.gitignore, which is removed: the check refuses any
# file but the four wheels. Needs the network.
wheels:
	rm -rf dist core/build readers/infrahub/build readers/netbox/build readers/nautobot/build
	mkdir dist
	for member in core readers/infrahub readers/netbox readers/nautobot; do \
		FYLGJA_BUILD_COMMIT=$(COMMIT) uv build --wheel --no-python-downloads --python python3 --build-constraints build-constraints.txt --out-dir dist $$member || exit 1; \
	done
	rm -f dist/.gitignore

# The core's image from the Dockerfile; its build context is .dockerignore's allow-list. The commit it is built at,
# COMMIT, is given as the build stage's one argument. Needs Docker and the network.
image:
	docker build --build-arg FYLGJA_BUILD_COMMIT=$(COMMIT) -t $(IMAGE):$(TAG) .

# The image built, then run: its user, its entry point's refusal, its formats (those CORE_FORMATS in core/setup.py
# names, each byte for byte its file in formats/), its wheel's packages (the YAML git tracks in psp/ and probes/, no
# copy of its own and no FYLGJA_PACKAGES), and the build its two commands
# answer --version with, which names the commit in TAG; the tag printed last.
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

# The development NetBox, the Compose project fylgja-core-netbox: local/.env's missing names written, never printed;
# netbox-docker's release fetched once; a project network of another subnet than the override's recreated, its
# containers removed and its volumes kept; the plugin's image built, started, and waited for until Docker calls netbox
# healthy, its worker started, and /api/status/ names both versions and a running worker, read with the superuser's
# token, provisioned into local/.env where it lacks one or NetBox refuses it.
netbox-up:
	python3 -I scripts/netbox_dev.py up --local $(LOCAL) --netbox $(NETBOX_VERSION) --docker $(NETBOX_DOCKER_VERSION) --branching $(NETBOX_BRANCHING_VERSION) --override netbox/dev/compose.override.yml

# Stopped, its containers, network and volumes kept; PURGE=1, and no other value, removes them. local/.env, the
# release and the image stay.
netbox-down:
	python3 -I scripts/netbox_dev.py down --local $(LOCAL) --netbox $(NETBOX_VERSION) --docker $(NETBOX_DOCKER_VERSION) --branching $(NETBOX_BRANCHING_VERSION) --override netbox/dev/compose.override.yml $(if $(filter 1,$(PURGE)),--purge)

# The development Nautobot, the Compose project fylgja-core-nautobot: local/.env's missing names written, never
# printed; local/nautobot/git made, the directory the git service serves; the image built from nautobot/dev/, started,
# and waited for until /health/ answers 200 from the host (Docker's word is not asked), then /api/status/ names both
# versions and a running worker, read with the superuser's token, the line local/.env holds, which the image takes at
# each start.
nautobot-up:
	python3 -I scripts/nautobot_dev.py up --local $(LOCAL) --nautobot $(NAUTOBOT_VERSION) --golden-config $(GOLDEN_CONFIG_VERSION) --python $(NAUTOBOT_PYTHON)

# Stopped, its containers, network and volumes kept; PURGE=1, and no other value, removes them. local/.env,
# local/nautobot/git and the image stay.
nautobot-down:
	python3 -I scripts/nautobot_dev.py down --local $(LOCAL) --nautobot $(NAUTOBOT_VERSION) --golden-config $(GOLDEN_CONFIG_VERSION) --python $(NAUTOBOT_PYTHON) $(if $(filter 1,$(PURGE)),--purge)

# The fixture network on the development Nautobot from nautobot/seed/main.yaml, found by its names or made, with
# the probes' inactive configuration context; nautobot/seed/templates/ committed into local/nautobot/git's
# templates.git, the repository the git service serves, where its tree is not main's; the repository, the GraphQL query
# nautobot/seed/sotagg.graphql and Golden Config's installed Default Settings pointed at both, its group saved where
# its stored members are not the tagged devices; Nautobot read back and refused, naming each difference and deleting
# nothing, where it is not the fixture; and last each device rendered once, held to three-node.json's configuration
# (CONTRIBUTING.md). Then the reader's account fylgja-reader at its least view grants, under which a render is the
# superuser's, and its write-disabled token's line FYLGJA_NAUTOBOT_TOKEN in local/.env, kept where Nautobot still
# takes it (nautobot/seed/account.py). Load local/.env first, and again after.
nautobot-seed:
	$(VENV)/bin/python nautobot/seed/seed.py --files nautobot/seed --git $(LOCAL)/nautobot/git
	$(VENV)/bin/python nautobot/seed/account.py --env $(LOCAL)/.env

# The fixture network on the development NetBox's main from netbox/seed/main.yaml, found by its names or made, with
# the configuration template that renders it and the probes' inactive configuration context; main read back and
# refused, naming each difference and deleting nothing, where it is not the fixture (CONTRIBUTING.md). Then the
# reader's account at its least permissions, and its token's line in local/.env, kept where NetBox holds the token as
# the account's and made again where it does not. Load local/.env first, and again after for the line.
netbox-seed:
	$(VENV)/bin/python netbox/seed/seed.py --files netbox/seed
	$(VENV)/bin/python netbox/seed/account.py --env $(LOCAL)/.env

# infrahubctl, in a venv of its own under local/infrahub/, so that the SDK meets nothing else (D-083): made by uv, at
# the SDK's pin, and no part of the workspace.
$(LOCAL)/infrahub/.venv/bin/infrahubctl:
	uv venv --no-project --clear --python python3 $(LOCAL)/infrahub/.venv
	printf '*\n' > $(LOCAL)/infrahub/.venv/.gitignore
	uv pip install -q --python $(LOCAL)/infrahub/.venv/bin/python 'infrahub-sdk[ctl]==$(INFRAHUB_SDK_VERSION)'

# The schema library, the group fylgja-devices and this repository's registration on main, at REF, the branch checked
# out, and its commit (CONTRIBUTING.md); a detached head names no branch and is refused. Load local/.env first.
infrahub-register: $(LOCAL)/infrahub/.venv/bin/infrahubctl
	$(if $(REF),,$(error REF is empty: a detached head names no branch to register; give REF=<branch>))
	$(VENV)/bin/python infrahub/seed/register.py --ref $(REF) --commit $$(git rev-parse --verify '$(REF)^{commit}') --schema infrahub/schema/dcim --ctl $(LOCAL)/infrahub/.venv/bin/infrahubctl

# The reader's FylgjaProbe kind on main where main lacks it; the fixture network on main from infrahub/seed/main/'s
# object files, loaded by infrahubctl, and its configurations generated and waited for; then the branch SEED_BRANCH
# made anew with infrahub/seed/stages/'s two edits, each generated, waited for and timed by the reader's head. Into
# local/infrahub/seed.json (CONTRIBUTING.md). Load local/.env first.
infrahub-seed: $(LOCAL)/infrahub/.venv/bin/infrahubctl
	$(VENV)/bin/python infrahub/seed/seed.py --branch $(SEED_BRANCH) --files infrahub/seed --out $(LOCAL)/infrahub/seed.json --ctl $(LOCAL)/infrahub/.venv/bin/infrahubctl --schema readers/infrahub/schema/fylgja-probe.yml

# The contract tier: infrahub/'s code, then the reader's, against the running development Infrahub (CONTRIBUTING.md).
# Load local/.env first.
contract:
	cd infrahub && FYLGJA_INFRAHUB_SEED=$(LOCAL)/infrahub/seed.json FYLGJA_INFRAHUB_CTL=$(LOCAL)/infrahub/.venv/bin/infrahubctl ../core/.venv/bin/pytest -q -rA -m contract tests/contract
	cd readers/infrahub && FYLGJA_INFRAHUB_SEED=$(LOCAL)/infrahub/seed.json FYLGJA_INFRAHUB_CTL=$(LOCAL)/infrahub/.venv/bin/infrahubctl ../../core/.venv/bin/pytest -q -rA -m contract tests/contract

# The NetBox contract tier: netbox/'s code, then the NetBox reader's, against the running development NetBox
# (CONTRIBUTING.md). Load local/.env first.
contract-netbox:
	cd netbox && ../core/.venv/bin/pytest -q -rA -m contract_netbox tests/contract
	cd readers/netbox && ../../core/.venv/bin/pytest -q -rA -m contract_netbox tests/contract

# The Nautobot contract tier: nautobot/'s code, then the Nautobot reader's, against the running development Nautobot
# (CONTRIBUTING.md). Load local/.env first.
contract-nautobot:
	cd nautobot && ../core/.venv/bin/pytest -q -rA -m contract_nautobot tests/contract
	cd readers/nautobot && ../../core/.venv/bin/pytest -q -rA -m contract_nautobot tests/contract
