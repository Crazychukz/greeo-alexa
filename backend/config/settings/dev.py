"""Local development settings."""

from .base import *  # noqa: F403
from .base import env_bool

# Local development and tests use visibly synthetic fixtures, so show them by default.
ALLOW_SYNTHETIC = env_bool("ALLOW_SYNTHETIC", True)
