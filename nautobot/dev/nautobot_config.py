from nautobot.core.settings import *  # noqa: F403

ALLOWED_HOSTS = ["*"]

PLUGINS = ["nautobot_plugin_nornir", "nautobot_golden_config"]

PLUGINS_CONFIG = {
    "nautobot_plugin_nornir": {
        "nornir_settings": {
            "credentials": "nautobot_plugin_nornir.plugins.credentials.env_vars.CredentialsEnvVars",
            "runner": {"plugin": "threaded", "options": {"num_workers": 20}},
        },
    },
    "nautobot_golden_config": {
        "enable_backup": False,
        "enable_compliance": False,
        "enable_intended": True,
        "enable_sotagg": True,
        "enable_plan": False,
        "enable_deploy": False,
        "enable_postprocessing": False,
    },
}
