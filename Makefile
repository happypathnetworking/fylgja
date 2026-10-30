# Fylgja — M2
# CGO is disabled everywhere: lab-host workers ship as static binaries (D-005).
export CGO_ENABLED := 0

BIN  := bin/fylgja
PKGS := ./...

# The binary's own identity, reported by `fylgja --version`. It identifies the binary
# and nothing else: no build stamp reaches a bundle, or every release would change
# bundle_id for unchanged intent (D-024). The default matches cmd/fylgja's own default,
# so an ordinary `make build` is reproducible from the source alone; a release stamps
# its own, e.g. `make build VERSION=0.2.0`.
VERSION ?= 0.1.0-dev
LDFLAGS := -X main.version=$(VERSION)

.PHONY: all build test test-contract test-e2e lint lint-python linkcheck diagrams clean \
        temporal-dev worker serve infrahub-schema infrahub-seed infrahub-clean command-log \
        orchestrator-venv prefect-server orchestrator-serve

# The orchestrator's venv (research R-02), made by `make orchestrator-venv`.
ORCH_VENV := orchestrator/.venv

all: build

build:
	go build -ldflags '$(LDFLAGS)' -o $(BIN) ./cmd/fylgja

# Tier 1: the Go packages, then the orchestrator's tests that need no Infrahub. The venv is
# made by `make orchestrator-venv`.
test:
	go test $(PKGS)
	$(ORCH_VENV)/bin/pytest -q orchestrator -m 'not contract'

# Contract tier: real Infrahub, never a fake (D-017). Needs INFRAHUB_ADDRESS and
# INFRAHUB_API_TOKEN in the environment (local/.env; see docs/development.md). Never
# cached: Go's cache keys a test on its binary, environment and files, never on what
# Infrahub answers. The packages run beside each other against one Infrahub, which works
# their branches, proposed changes and rebases in turn, so a package takes up to three
# times as long as it does alone: internal/stages, about four and a half minutes alone,
# outlasted go test's default ten-minute timeout here (014's research §8.10) until 020
# removed it with the reader (T035), which left internal/checks the Go tier's one package
# with contract tests; the rest run their tier-1 tests again under the tag.
# internal/checks runs after the rest, alone. Its registration on main makes every proposed
# change opened while it lives run its two checks, the other packages' with them, and its
# waits are those of an Infrahub with nothing else to do: beside the rest, its draft's
# pipeline took 260 s against 58 s alone and a link's render outlasted its 90 s (015's
# research §5.5). The orchestrator's tier 2 runs last, alone against the same Infrahub. Each
# run goes on whatever the one before answers, so one tier reports all three.
CHECKS_PKG     := github.com/happypathnetworking/fylgja/internal/checks
CONTRACT_PKGS   = $(filter-out $(CHECKS_PKG),$(shell go list -tags contract $(PKGS)))
test-contract:
	rc=0; \
	go test -count=1 -timeout 30m -tags contract $(CONTRACT_PKGS) || rc=1; \
	go test -count=1 -timeout 30m -tags contract $(CHECKS_PKG) || rc=1; \
	$(ORCH_VENV)/bin/pytest -q orchestrator -m contract || rc=1; \
	exit $$rc

# End-to-end tier: a booted NOS through Temporal. Needs the dev server (make
# temporal-dev), a worker (make worker), Docker, containerlab, both images (SR Linux and
# cEOS) and Infrahub. It never runs in CI and never gates a PR.
test-e2e: build
	scripts/e2e.sh

# golangci-lint, then ruff over the orchestrator and the checks, both with the orchestrator's
# configuration (orchestrator/pyproject.toml). CI's lint job runs golangci-lint by its action
# and lint-python on its own.
lint:
	golangci-lint run
	$(MAKE) --no-print-directory lint-python

lint-python:
	$(ORCH_VENV)/bin/ruff check --config orchestrator/pyproject.toml orchestrator infrahub/checks

# The tracked Markdown's relative links and anchors (scripts/linkcheck.py). A hand tool;
# not a CI step.
linkcheck:
	python3 -I scripts/linkcheck.py

# Publishes the Spec Kit command log the hooks keep in local/command-log/ into each
# commands/ directory (docs/development.md). The directories are git-ignored, so nothing is
# committed; the hooks write no tracked file, so a session leaves the tree clean.
command-log:
	python3 .claude/hooks/command-log.py flush --commit

# The Python scripts' tests: the loop's planner, the tasks.md merge driver, the command-log
# hook (scripts/tests/). A hand tool; not a CI step.
test-scripts:
	python3 -I -m unittest discover -s scripts/tests -p 'test_*.py'

STRUCTURIZR_IMAGE := structurizr/structurizr@sha256:721136283c2f9cf1ba69037bc9de136c579d66fdcb2d771cb60546ec68def1a5
PLANTUML_IMAGE    := plantuml/plantuml@sha256:d08610df482510844382caa4e016ba2bf7e3231f630f02ee12f250f3416c62b1

# Validates the C4 model and regenerates every committed diagram: the five views as
# C4-PlantUML and SVG under docs/c4/, the import graph in docs/development.md and the
# fixture topologies in docs/diagrams/topologies.md. Needs Docker and go; no test tier
# needs it. A second run changes nothing.
diagrams:
	docker run --rm -u "$$(id -u):$$(id -g)" -v "$(CURDIR)/docs/c4":/w $(STRUCTURIZR_IMAGE) validate -w /w/workspace.dsl
	docker run --rm -u "$$(id -u):$$(id -g)" -v "$(CURDIR)/docs/c4":/w $(STRUCTURIZR_IMAGE) export -w /w/workspace.dsl -f plantuml/c4plantuml -o /w
	docker run --rm -u "$$(id -u):$$(id -g)" -v "$(CURDIR)/docs/c4":/w $(PLANTUML_IMAGE) -tsvg /w/*.puml
	scripts/diagrams.sh

clean:
	rm -rf bin/

# The Temporal dev server, file-backed so run history survives a restart
# (docs/development.md). UI at http://localhost:8233. The CLI is the one on the PATH, or
# else where its installer, run by scripts/bring-up.sh, puts it and leaves it off the PATH.
TEMPORAL ?= $(or $(shell command -v temporal),$(HOME)/.temporalio/bin/temporal)
temporal-dev:
	$(TEMPORAL) server start-dev --db-filename local/temporal.db

# The lab-host worker on queue fylgja. The state root is made absolute here so the
# worker and the API's server, each started from wherever, agree on it.
worker: build
	FYLGJA_STATE_ROOT=$(CURDIR)/local $(BIN) worker run

# The API's server, beside the worker on the lab host: every other command is a request to
# it (D-040, D-041). It needs FYLGJA_API_TOKEN, which it refuses to start without, and the
# worker's environment (Infrahub's variables, both node logins, docker and containerlab on
# its PATH), which it reads at each request; load local/.env in its shell first. The state
# root is the worker's, made absolute the same way.
serve: build
	FYLGJA_STATE_ROOT=$(CURDIR)/local $(BIN) serve

# The orchestrator's venv: Prefect, the SDK, pytest and ruff at orchestrator/pyproject.toml's
# pins, the package installed editable. A .gitignore of * inside keeps the tree clean, as
# the root .venv's does. A second run reinstalls nothing that is current.
orchestrator-venv:
	test -x $(ORCH_VENV)/bin/python || python3 -m venv $(ORCH_VENV)
	printf '*\n' > $(ORCH_VENV)/.gitignore
	$(ORCH_VENV)/bin/pip install -q -e 'orchestrator[dev]'

# The orchestrator's Prefect server and its runner (research R-01, R-17), beside the worker
# and the API's server on the lab host. Both read PREFECT_API_URL (http://<bridge>:4200/api,
# where the server listens: the host's processes and Infrahub's task workers reach it there)
# and PREFECT_API_AUTH_STRING (<user>:<password>, the server's basic authentication) from
# the environment and refuse to start without them; load local/.env in their shell first.
# PREFECT_HOME is local/orchestrator/prefect (the server's SQLite database), made absolute
# as the state root is, and the runner's state root is local/orchestrator.
PREFECT_HOME_DIR := $(CURDIR)/local/orchestrator/prefect
prefect-server:
	: "$${PREFECT_API_URL:?load local/.env first}" "$${PREFECT_API_AUTH_STRING:?load local/.env first}"; \
	set -- $$(python3 -I -c 'import sys, urllib.parse as u; p = u.urlsplit(sys.argv[1]); print(p.hostname, p.port)' "$$PREFECT_API_URL"); \
	mkdir -p $(PREFECT_HOME_DIR) && \
	PREFECT_HOME=$(PREFECT_HOME_DIR) PREFECT_SERVER_API_AUTH_STRING="$$PREFECT_API_AUTH_STRING" \
		$(ORCH_VENV)/bin/prefect server start --host "$$1" --port "$$2" --no-ui

orchestrator-serve:
	: "$${PREFECT_API_URL:?load local/.env first}" "$${PREFECT_API_AUTH_STRING:?load local/.env first}"; \
	mkdir -p $(PREFECT_HOME_DIR) && \
	PREFECT_HOME=$(PREFECT_HOME_DIR) FYLGJA_ORCHESTRATOR_ROOT=$(CURDIR)/local/orchestrator \
		$(ORCH_VENV)/bin/fylgja-orchestrator serve

# Infrahub is operator-provided: bring your own instance and point INFRAHUB_ADDRESS /
# INFRAHUB_API_TOKEN at it (see .env.example). Fylgja neither vendors nor starts it.
#
# Loads the schema library (schema/dcim/) and the stage kind onto the fixture branch and
# seeds the three-node topology in the library's kinds.
# Build-tagged: this is the one place Fylgja code writes to Infrahub.
infrahub-schema:
	go run -tags fixture ./cmd/fylgja-fixture -schema-only

infrahub-seed:
	go run -tags fixture ./cmd/fylgja-fixture

infrahub-clean:
	go run -tags fixture ./cmd/fylgja-fixture -delete
