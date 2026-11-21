# The development Nautobot's image: Network to Code's at Nautobot's version and the image's Python, and one layer
# adding Golden Config at its version by uv. Each version is a build argument with no default, so a build not given
# all three fails. The build context is nautobot/dev/ alone.
ARG NAUTOBOT_VERSION
ARG NAUTOBOT_PYTHON
FROM networktocode/nautobot:${NAUTOBOT_VERSION}-py${NAUTOBOT_PYTHON}
ARG NAUTOBOT_VERSION
ARG GOLDEN_CONFIG_VERSION

# uv 0.12.23, from Astral's image: the index's digest, read 2026-11-15, the image built 2026-10-03.
COPY --from=ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 /uv /usr/local/bin/uv

USER root
RUN uv pip install --no-cache --python /usr/local/bin/python nautobot==${NAUTOBOT_VERSION} nautobot-golden-config==${GOLDEN_CONFIG_VERSION}
USER nautobot
