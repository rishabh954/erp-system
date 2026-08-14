from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.hrms.api.views import (
    AttendanceViewSet,
    EmployeeViewSet,
    LeaveRequestViewSet,
    PayrollPeriodViewSet,
    PayslipViewSet,
)

app_name = "api_hrms"
router = DefaultRouter()
router.register(r"employees", EmployeeViewSet, basename="employee")
router.register(r"attendance", AttendanceViewSet, basename="attendance")
router.register(r"leave-requests", LeaveRequestViewSet, basename="leave-request")
router.register(r"payroll-periods", PayrollPeriodViewSet, basename="payroll-period")
router.register(r"payslips", PayslipViewSet, basename="payslip")

urlpatterns = [path("", include(router.urls))]
