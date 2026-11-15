# The core's image (D-062): fylgja-core-server, with the platform and probe packages inside, run as
# a user that is not root. `make image` builds it, tagged by its commit, and `make imagecheck` runs
# it. The build context is .dockerignore's allow-list. No containerlab: a core in a pod serves the
# clabernetes driver alone.

# python:3.14.9-slim, Python 3.14.9 on Debian trixie: the index's digest, read 2026-11-06, the
# index built 2026-10-21. Every pin is a release at least two weeks old when chosen (CONTRIBUTING.md,
# D-039): 3.14.9 is the newest Python whose release was, that day.
FROM python:3.14.9-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8 AS build

# uv 0.12.23, from Astral's image: the index's digest, read 2026-11-15, the image built 2026-10-03.
# It is copied into this stage alone: no uv in the image, and no pip in the venv; the base image's
# own pip under /usr/local is untouched. The version is the root pyproject.toml's
# required-version, which a test holds equal (D-108).
COPY --from=ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 /uv /usr/local/bin/uv

# The tree's layout: core/setup.py copies into the wheel the formats its CORE_FORMATS names, each
# byte for byte its file in ../formats (D-066, D-084), and reads the version from ../VERSION (D-106).
COPY core/pyproject.toml core/setup.py /src/core/
COPY core/src /src/core/src
COPY formats /src/formats
COPY VERSION /src/VERSION
# The commit the image is built at, which the wheel's build writes into the package (core/setup.py): an argument, since
# the context holds no .git. `make image` gives it; with none the build says unknown. In this stage alone, so the final
# image's environment never holds it.
ARG FYLGJA_BUILD_COMMIT
# The wheel built, then installed with its server extra, the server's libraries at their pins
# (D-084): resolved as an integrator's install is, not from the lock. The interpreter is the
# image's, never a uv-managed one. Bytecode is compiled at install: uv compiles none by default,
# and the venv is read-only to the user the server runs as, so every start would compile the
# server in memory. The glob is expanded alone: a bare /wheels/*.whl[server] is a glob with a
# character class and matches nothing.
RUN uv venv --no-python-downloads --python /usr/local/bin/python3 /opt/fylgja/venv \
 && uv build --no-cache --no-python-downloads --python /usr/local/bin/python3 --wheel --out-dir /wheels /src/core \
 && uv pip install --no-cache --compile-bytecode --python /opt/fylgja/venv/bin/python "$(echo /wheels/*.whl)[server]"

# The same base, by the same digest.
FROM python:3.14.9-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8

COPY --from=build /opt/fylgja/venv /opt/fylgja/venv
COPY psp /opt/fylgja/psp
COPY probes /opt/fylgja/probes
ENV FYLGJA_PACKAGES=/opt/fylgja/psp:/opt/fylgja/probes \
    PATH=/opt/fylgja/venv/bin:$PATH
USER 10001:10001
# Never optimised, no -O and no PYTHONOPTIMIZE: the server refuses to start so (server.optimised).
ENTRYPOINT ["fylgja-core-server"]
