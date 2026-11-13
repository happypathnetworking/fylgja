"""netbox-branching's settings, loaded by netbox-docker after its own `configuration.py`."""

from os import environ

from netbox_branching.utilities import DynamicSchemaDict

PLUGINS = ["netbox_branching"]

DATABASES = DynamicSchemaDict(
    {
        "default": {
            "NAME": environ.get("DB_NAME", "netbox"),
            "USER": environ.get("DB_USER", ""),
            "PASSWORD": environ.get("DB_PASSWORD", ""),
            "HOST": environ.get("DB_HOST", "localhost"),
            "PORT": environ.get("DB_PORT", ""),
            "CONN_MAX_AGE": int(environ.get("DB_CONN_MAX_AGE", "300")),
        }
    }
)

DATABASE_ROUTERS = ["netbox_branching.database.BranchAwareRouter"]

EVENTS_PIPELINE = [
    "netbox_branching.events.add_branch_context",
    "extras.events.process_event_queue",
]
