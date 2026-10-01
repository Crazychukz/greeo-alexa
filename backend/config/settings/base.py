"""Settings shared by all Greeo environments.

Values enter the application through environment variables so deployments do
not require code changes. Defaults only support the local Docker workflow.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[2]


def env(name: str, default: str | None = None) -> str:
    """Read one required environment value, optionally with a local default."""
    value = os.getenv(name, default)
    if value is None:
        raise ImproperlyConfigured(f"Set the {name} environment variable.")
    return value


def env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment value strictly to catch configuration typos."""
    value = env(name, str(default)).lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean value.")


def env_int(name: str, default: int) -> int:
    """Read an integer setting and fail clearly on malformed configuration."""
    try:
        return int(env(name, str(default)))
    except ValueError as error:
        raise ImproperlyConfigured(f"{name} must be an integer.") from error


def database_from_url(url: str) -> dict[str, str]:
    """Convert a PostgreSQL URL into Django's database configuration."""
    parsed = urlparse(url)
    if parsed.scheme in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.removeprefix("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or "5432"),
        }
    raise ImproperlyConfigured("DATABASE_URL must use postgresql://.")


INSECURE_DEFAULT_SECRET_KEY = "change-me-for-any-non-local-environment"
SECRET_KEY = env("DJANGO_SECRET_KEY", INSECURE_DEFAULT_SECRET_KEY)
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [
    host.strip() for host in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "corsheaders",
    "apps.core",
    "apps.news",
    "apps.stories",
    "apps.wisdom",
    "apps.memory",
    "apps.llm",
    "apps.mcp_server",
    "apps.simulator",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# No fallback: the models use PostgreSQL-only fields, so a missing URL must fail loudly.
DATABASES = {"default": database_from_url(env("DATABASE_URL"))}

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "greeo-local-cache",
    }
}

AUTH_PASSWORD_VALIDATORS: list[dict[str, str]] = []
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = env_bool("CELERY_TASK_EAGER_PROPAGATES", True)
CELERY_BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    "news-poll-due-feeds": {
        "task": "news.poll_due_feeds",
        "schedule": crontab(minute="*/30"),
    }
}
# Synthetic fixtures stay hidden unless an environment opts in; dev.py enables them.
ALLOW_SYNTHETIC = env_bool("ALLOW_SYNTHETIC", False)
# Demo-only: also serve single-source proverbs. Off by default; the submission must
# disclose it when on. See docs/proverbs/DEMO_CORPUS.md.
DEMO_ALLOW_SINGLE_SOURCE_PROVERBS = env_bool("DEMO_ALLOW_SINGLE_SOURCE_PROVERBS", False)

# RSS ingestion performs only permitted feed requests. No article pages are fetched.
GREEO_CONTACT_EMAIL = env("GREEO_CONTACT_EMAIL", "local@example.invalid")
NEWS_HTTP_TIMEOUT_SECONDS = env_int("NEWS_HTTP_TIMEOUT_SECONDS", 10)
NEWS_MAX_5XX_RETRIES = env_int("NEWS_MAX_5XX_RETRIES", 2)
NEWS_CIRCUIT_OPEN_MINUTES = env_int("NEWS_CIRCUIT_OPEN_MINUTES", 60)
NEWS_MAX_CONSECUTIVE_FAILURES = env_int("NEWS_MAX_CONSECUTIVE_FAILURES", 5)
NEWS_DOMAIN_LOCK_SECONDS = env_int("NEWS_DOMAIN_LOCK_SECONDS", 60)

# MCP server (separate process: manage.py run_mcp_server). Origins and hosts are the
# DNS-rebinding allowlists required by the MCP Streamable HTTP transport.
MCP_HOST = env("MCP_HOST", "127.0.0.1")
MCP_PORT = env_int("MCP_PORT", 8001)
MCP_ALLOWED_HOSTS = [
    h.strip()
    for h in env("MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,mcp:*").split(",")
    if h.strip()
]
MCP_ALLOWED_ORIGINS = [
    o.strip()
    for o in env("MCP_ALLOWED_ORIGINS", "http://localhost:*,http://127.0.0.1:*").split(",")
    if o.strip()
]
# The X-Greeo-User development header lets a caller name any identity, so it is only
# honoured when DEBUG is also on; the MCP server refuses to start otherwise.
MCP_ALLOW_DEV_IDENTITY = env_bool("MCP_ALLOW_DEV_IDENTITY", DEBUG)
# Light abuse protection for a public demo: requests per minute per token (or per
# client address for guests). 0 turns it off.
MCP_RATE_LIMIT_PER_MINUTE = env_int("MCP_RATE_LIMIT_PER_MINUTE", 240)
# Amazon's payload guidance: "no third-party tracking parameters, or upstream deep links".
INCLUDE_SOURCE_URLS = env_bool("INCLUDE_SOURCE_URLS", False)

# Simulator host API: our stand-in for Alexa+. It reaches Greeo only through MCP.
SIMULATOR_MCP_URL = env("SIMULATOR_MCP_URL", "http://127.0.0.1:8001/mcp")
SIMULATOR_MAX_TOOL_ITERATIONS = env_int("SIMULATOR_MAX_TOOL_ITERATIONS", 4)
SIMULATOR_SESSION_SECONDS = env_int("SIMULATOR_SESSION_SECONDS", 1800)
# Browser origins allowed to call the simulator API (the separate front end).
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in env("CORS_ALLOWED_ORIGINS", "http://localhost:4200,http://localhost:5173").split(",")
    if o.strip()
]
CORS_URLS_REGEX = r"^/api/simulator/.*$"
CORS_ALLOW_HEADERS = ["accept", "authorization", "content-type", "x-greeo-user"]
REST_FRAMEWORK = {
    # The simulator API is a local demo surface; identity is the dev header in DEBUG.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
}

# Simulator speech. Mock means no audio (the front end uses browser speech); Polly is
# opt-in, like Bedrock, so a clean clone needs no AWS credentials.
SPEECH_BACKEND = env("SPEECH_BACKEND", "mock")
POLLY_VOICE_ID = env("POLLY_VOICE_ID", "Ayanda")
POLLY_ENGINE = env("POLLY_ENGINE", "neural")
SPEECH_RETRIES = env_int("SPEECH_RETRIES", 2)
SPEECH_CACHE_SECONDS = env_int("SPEECH_CACHE_SECONDS", 86400)

# Structured logs: one JSON object per line, with credentials redacted before output.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact": {"()": "apps.core.logging.RedactSecrets"}},
    "formatters": {"json": {"()": "apps.core.logging.JsonFormatter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["redact"],
            "formatter": "json",
        }
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        # The HTTP client logs one line per request at INFO; keep tool logs readable.
        "httpx": {"level": "WARNING"},
        "httpx2": {"level": "WARNING"},
        # The stateless transport logs a line for every request it closes.
        "mcp.server.streamable_http": {"level": "WARNING"},
    },
}

# LLM calls are permitted only through apps.llm.client. Mock is intentionally
# the default so a clean local setup never requires cloud credentials.
LLM_BACKEND = env("LLM_BACKEND", "mock")
AWS_REGION = env("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = env("BEDROCK_MODEL_ID", "")
LLM_MAX_TOKENS = env_int("LLM_MAX_TOKENS", 1000)
LLM_TIMEOUT_SECONDS = env_int("LLM_TIMEOUT_SECONDS", 30)
LLM_PROVIDER_RETRIES = env_int("LLM_PROVIDER_RETRIES", 2)
LLM_MAX_CALLS_PER_RUN = env_int("LLM_MAX_CALLS_PER_RUN", 300)
LLM_DAILY_TOKEN_BUDGET = env_int("LLM_DAILY_TOKEN_BUDGET", 500000)
LLM_INPUT_PRICE_PER_MILLION_USD = env("LLM_INPUT_PRICE_PER_MILLION_USD", "0")
LLM_OUTPUT_PRICE_PER_MILLION_USD = env("LLM_OUTPUT_PRICE_PER_MILLION_USD", "0")
