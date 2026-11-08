# The core's image (D-062): fylgja-core-server, with the platform and probe packages inside, run as
# a user that is not root. `make image` builds it, tagged by its commit, and `make imagecheck` runs
# it. The build context is .dockerignore's allow-list. No containerlab: a core in a pod serves the
# clabernetes driver alone.

# python:3.14.9-slim, Python 3.14.9 on Debian trixie: the index's digest, read 2026-11-06, the
# index built 2026-10-21. Every pin is a release at least two weeks old when chosen (CONTRIBUTING.md,
# D-039): 3.14.9 is the newest Python whose release was, that day.
FROM python:3.14.9-slim@sha256:35caba83af2fe6da9a5d922f9b0156f21d1246a48278c58a08bd253303ba42e8 AS build

# The tree's layout: core/setup.py copies ../formats into the wheel (D-066).
COPY core/pyproject.toml core/setup.py /src/core/
COPY core/src /src/core/src
COPY formats /src/formats
RUN python -m venv /opt/fylgja/venv \
 && /opt/fylgja/venv/bin/pip wheel --no-deps -w /wheels /src/core \
 && /opt/fylgja/venv/bin/pip install --no-cache-dir /wheels/*.whl

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
