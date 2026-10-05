import hashlib
import hmac
import json
import logging
from typing import Any

from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import Attendance, BiometricDevice, BiometricLog, Employee

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class BiometricSyncAPIView(View):
    """Device-authenticated biometric sync endpoint.

    CSRF is disabled only because this is a machine-to-machine endpoint that
    authenticates using X-Device-Id/X-Device-Key headers instead of cookies or
    session state.
    """

    MAX_BATCH_SIZE = 500
    RATE_LIMIT_PER_DEVICE = 60

    def _device_auth(self, request):
        device_id = request.headers.get("X-Device-Id")
        device_key = request.headers.get("X-Device-Key")
        if not device_id or not device_key:
            return None

        try:
            device = BiometricDevice.objects.select_related("company").get(
                device_id=device_id,
                is_active=True,
            )
        except BiometricDevice.DoesNotExist:
            return None

        key_hash = hashlib.sha256(device_key.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(device.key_hash, key_hash):
            return None

        return device

    def _rate_limited(self, device):
        key = f"biometric:{device.id}:rate_limit"
        current = cache.get(key, 0)
        if current >= self.RATE_LIMIT_PER_DEVICE:
            return False
        cache.set(key, current + 1, timeout=60)
        return True

    def post(self, request):
        device = self._device_auth(request)
        if device is None:
            return JsonResponse({"detail": "Invalid or missing device credentials."}, status=401)

        if not self._rate_limited(device):
            return JsonResponse({"detail": "Rate limit exceeded."}, status=429)

        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"detail": "Malformed JSON payload."}, status=400)

        logs = payload.get("logs", [])
        if len(logs) > self.MAX_BATCH_SIZE:
            return JsonResponse(
                {"detail": f"Batch size exceeds maximum of {self.MAX_BATCH_SIZE}."},
                status=400,
            )

        created_count = 0
        company = device.company

        try:
            with transaction.atomic():
                for log in logs:
                    employee_id = log.get("employee_id")
                    timestamp_str = log.get("timestamp")
                    punch_type = log.get("punch_type")

                    if not employee_id or not timestamp_str or not punch_type:
                        continue

                    timestamp = parse_datetime(timestamp_str)
                    if not timestamp:
                        continue

                    employee = Employee.objects.filter(
                        company=company,
                        employee_id=employee_id,
                    ).select_related("company").first()
                    if not employee:
                        continue

                    punch_value = str(punch_type).lower()
                    if punch_value not in {"in", "out"}:
                        continue

                    b_log = BiometricLog.objects.create(
                        employee=employee,
                        timestamp=timestamp,
                        punch_type=punch_value,
                        device_id=device.device_id,
                    )

                    date = timestamp.date()
                    attendance, _ = Attendance.objects.get_or_create(
                        employee=employee,
                        date=date,
                        company=company,
                    )

                    if b_log.punch_type == "in":
                        if not attendance.check_in or timestamp < attendance.check_in:
                            attendance.check_in = timestamp
                    elif b_log.punch_type == "out":
                        if not attendance.check_out or timestamp > attendance.check_out:
                            attendance.check_out = timestamp

                    attendance.save(update_fields=["check_in", "check_out", "updated_at"])
                    b_log.is_processed = True
                    b_log.save(update_fields=["is_processed"])
                    created_count += 1

            return JsonResponse({"success": True, "processed": created_count})
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Biometric sync failed: %s", exc, exc_info=True)
            return JsonResponse({"success": False, "error": "An unexpected error occurred."}, status=500)
