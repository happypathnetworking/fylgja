# fylgja-core (CONTRIBUTING.md).

.PHONY: all venv test lint linkcheck

VENV := core/.venv

all: lint test

# The core's venv at core/pyproject.toml's pins, the package editable.
venv:
	test -x $(VENV)/bin/python || python3 -m venv $(VENV)
	printf '*\n' > $(VENV)/.gitignore
	$(VENV)/bin/pip install -q -e 'core[dev]'

# The pure tier: no infrastructure (Constitution, Development).
test:
	cd core && .venv/bin/pytest -q

lint:
	cd core && .venv/bin/ruff check --config pyproject.toml . ../scripts && .venv/bin/mypy

# Every relative link and anchor in the tracked Markdown resolves in a clone.
linkcheck:
	python3 -I scripts/linkcheck.py
