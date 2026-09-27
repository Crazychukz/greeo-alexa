"""HTTP endpoints owned by the core application."""

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .services import get_health_report


@require_GET
def healthz(request: object) -> JsonResponse:
    """Report whether the two required runtime dependencies are reachable."""
    report = get_health_report()
    status_code = 200 if report["status"] == "ok" else 503
    return JsonResponse(report, status=status_code)
