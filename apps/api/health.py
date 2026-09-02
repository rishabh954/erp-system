import logging
from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.views import View
from django.core.cache import cache

logger = logging.getLogger(__name__)

class HealthCheckView(View):
    def get(self, request, *args, **kwargs):
        status = "ok"
        components = {}

        # Check DB
        try:
            connections["default"].cursor()
            components["database"] = "up"
        except OperationalError:
            components["database"] = "down"
            status = "error"
            logger.error("Health check failed: Database connection error")
        except Exception as e:
            components["database"] = "down"
            status = "error"
            logger.error(f"Health check failed: DB error {str(e)}")

        # Check Cache/Redis
        try:
            cache.set("health_check", "ok", timeout=5)
            if cache.get("health_check") == "ok":
                components["redis"] = "up"
            else:
                components["redis"] = "down"
                status = "error"
                logger.error("Health check failed: Cache did not return stored value")
        except Exception as e:
            components["redis"] = "down"
            status = "error"
            logger.error(f"Health check failed: Redis/Cache error {str(e)}")

        status_code = 200 if status == "ok" else 503
        return JsonResponse({"status": status, "components": components}, status=status_code)

class LiveCheckView(View):
    def get(self, request, *args, **kwargs):
        """Liveness probe: Just returns 200 OK to indicate the process is running."""
        return JsonResponse({"status": "ok"})

class ReadyCheckView(HealthCheckView):
    """Readiness probe: Same as health check, ensures dependencies are up."""
    pass
