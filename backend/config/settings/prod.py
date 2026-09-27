"""Production settings with unsafe development options disabled."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import INSECURE_DEFAULT_SECRET_KEY, SECRET_KEY

DEBUG = False
# Synthetic fixtures must never reach real listeners, whatever the environment says.
ALLOW_SYNTHETIC = False

if not SECRET_KEY or SECRET_KEY == INSECURE_DEFAULT_SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY to a unique secret value in production.")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
