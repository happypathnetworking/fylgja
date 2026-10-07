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

.PHONY: all build test test-contract test-e2e lint sdl generate diagrams clean \
        temporal-dev worker serve infrahub-schema infrahub-seed infrahub-clean command-log

all: build

build:
	go build -ldflags '$(LDFLAGS)' -o $(BIN) ./cmd/fylgja

test:
	go test $(PKGS)

# Contract tier: real Infrahub, never a fake (D-017). Needs INFRAHUB_ADDRESS and
# INFRAHUB_API_TOKEN in the environment (local/.env; see docs/development.md). Never
# cached: Go's cache keys a test on its binary, environment and files, never on what
# Infrahub answers.
test-contract:
	go test -count=1 -tags contract $(PKGS)

# End-to-end tier: a booted NOS through Temporal. Needs the dev server (make
# temporal-dev), a worker (make worker), Docker, containerlab, both images (SR Linux and
# cEOS) and Infrahub. It never runs in CI and never gates a PR.
test-e2e: build
	scripts/e2e.sh

lint:
	golangci-lint run

# Publishes the Spec Kit command log the hooks keep in local/command-log/ and commits each
# commands/ directory it touches (docs/development.md). The hooks write no tracked file, so
# a session leaves the tree clean; this is when its log reaches git.
command-log:
	python3 .claude/hooks/command-log.py flush --commit

# Fetches the GraphQL SDL from a live Infrahub. The SDL is committed
# so the build never needs Infrahub; only regeneration does. From the default branch
# since M10: the waypoint kind lives there, and a branch created before the kind was
# loaded does not carry it. The file's header is kept by hand.
sdl:
	go run -tags fixture ./cmd/fylgja-fixture -branch main -sdl schema/infrahub.graphql

# Regenerates the typed client from the committed SDL.
generate:
	cd internal/intent && go run github.com/Khan/genqlient

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

# Infrahub is operator-provided: bring your own instance and point INFRAHUB_ADDRESS /
# INFRAHUB_API_TOKEN at it (see .env.example). Fylgja neither vendors nor starts it.
#
# Loads schema/*.yaml onto the fixture branch and seeds the three-node topology.
# Build-tagged: this is the one place Fylgja code writes to Infrahub.
infrahub-schema:
	go run -tags fixture ./cmd/fylgja-fixture -schema-only

infrahub-seed:
	go run -tags fixture ./cmd/fylgja-fixture

infrahub-clean:
	go run -tags fixture ./cmd/fylgja-fixture -delete
