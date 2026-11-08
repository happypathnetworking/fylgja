# fylgja-core (CONTRIBUTING.md).

.PHONY: all venv test live cluster conformance lint linkcheck wheelcheck image imagecheck

VENV := core/.venv

# The core's image, tagged by the commit it is built at: its first 12 characters, and -dirty
# where `git status --porcelain` prints anything (D-062). Worked out once, as make starts, so
# `image` and `imagecheck` build and check one tag, whatever changes in the tree meanwhile.
IMAGE ?= fylgja-core
TAG := $(shell git rev-parse HEAD 2>/dev/null | cut -c1-12)$(if $(shell git status --porcelain 2>/dev/null),-dirty)

all: lint test

# The core's venv at core/pyproject.toml's pins, the package editable.
venv:
	test -x $(VENV)/bin/python || python3 -m venv $(VENV)
	printf '*\n' > $(VENV)/.gitignore
	$(VENV)/bin/pip install -q -e 'core[dev]'

# The pure tier: no infrastructure (Constitution, Development).
test:
	cd core && .venv/bin/pytest -q

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

lint:
	cd core && .venv/bin/ruff check --config pyproject.toml . ../scripts && .venv/bin/mypy

# Every relative link and anchor in the tracked Markdown resolves in a clone.
linkcheck:
	python3 -I scripts/linkcheck.py

# The wheel, built from core/ and formats/ and installed outside the tree, validates a fixture (D-066). Needs the network.
wheelcheck:
	python3 -I scripts/wheelcheck.py

# The core's image from the Dockerfile; its build context is .dockerignore's allow-list. Needs Docker and the network.
image:
	docker build -t $(IMAGE):$(TAG) .

# The image built, then run: its user, its entry point's refusal, its formats against formats/'s, its packages'
# files against git's; the tag printed last.
imagecheck: image
	python3 -I scripts/imagecheck.py $(IMAGE):$(TAG)
