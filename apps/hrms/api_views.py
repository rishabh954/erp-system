import json
import logging

from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import Attendance, BiometricLog, Employee

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class BiometricSyncAPIView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            logs = data.get("logs", [])

            created_count = 0
            for log in logs:
                employee_id = log.get("employee_id")
                timestamp_str = log.get("timestamp")
                punch_type = log.get("punch_type")
                device_id = log.get("device_id", "")

                if not employee_id or not timestamp_str or not punch_type:
                    continue

                timestamp = parse_datetime(timestamp_str)
                if not timestamp:
                    continue

                employee = Employee.objects.filter(employee_id=employee_id).first()
                if not employee:
                    continue

                # Create the log
                b_log = BiometricLog.objects.create(
                    employee=employee,
                    timestamp=timestamp,
                    punch_type=punch_type.lower(),
                    device_id=device_id,
                )

                # Sync to Attendance
                date = timestamp.date()
                attendance, _ = Attendance.objects.get_or_create(
                    employee=employee, date=date, company=employee.company
                )

                if b_log.punch_type == "in":
                    if not attendance.check_in or timestamp < attendance.check_in:
                        attendance.check_in = timestamp
                elif b_log.punch_type == "out":
                    if not attendance.check_out or timestamp > attendance.check_out:
                        attendance.check_out = timestamp

                attendance.save()
                b_log.is_processed = True
                b_log.save(update_fields=["is_processed"])
                created_count += 1

            return JsonResponse({"success": True, "processed": created_count})

        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return JsonResponse({"success": False, "error": "An unexpected error occurred."}, status=500)
