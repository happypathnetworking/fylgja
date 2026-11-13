# The development NetBox's image: netbox-docker's at NetBox's and netbox-docker's versions, and one layer adding the
# branching plugin at its version (make netbox-up, D-096). Each version is a build argument with no default, which
# scripts/netbox_dev.py sets from the make variables through the override, so a build not given all three fails.
# The build context is netbox/dev/ alone.
ARG NETBOX_VERSION
ARG NETBOX_DOCKER_VERSION
FROM docker.io/netboxcommunity/netbox:v${NETBOX_VERSION}-${NETBOX_DOCKER_VERSION}
ARG NETBOX_BRANCHING_VERSION
RUN uv pip install --python /opt/netbox/venv/bin/python netboxlabs-netbox-branching==${NETBOX_BRANCHING_VERSION}
