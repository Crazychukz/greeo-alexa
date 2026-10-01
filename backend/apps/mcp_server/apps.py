from django.apps import AppConfig
from django.core.checks import Error, register


class McpServerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mcp_server"

    def ready(self) -> None:
        register(dev_identity_check)


def dev_identity_check(app_configs, **kwargs) -> list[Error]:
    """Fail every management command and server start if dev identity leaks out of DEBUG."""
    from django.conf import settings

    if settings.MCP_ALLOW_DEV_IDENTITY and not settings.DEBUG:
        return [
            Error(
                "MCP_ALLOW_DEV_IDENTITY is on while DEBUG is off.",
                hint="The X-Greeo-User header lets anyone claim any identity. Set "
                "MCP_ALLOW_DEV_IDENTITY=false, or DJANGO_DEBUG=true for local work.",
                id="greeo.E001",
            )
        ]
    return []
