from rest_framework import serializers

from core.api.fields import TenantModelSerializer
from apps.hrms.models import Attendance, Employee, LeaveRequest, PayrollPeriod, Payslip


class EmployeeSerializer(TenantModelSerializer):
    class Meta:
        model = Employee
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class AttendanceSerializer(TenantModelSerializer):
    class Meta:
        model = Attendance
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class LeaveRequestSerializer(TenantModelSerializer):
    class Meta:
        model = LeaveRequest
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "status",
        ]


class PayrollPeriodSerializer(TenantModelSerializer):
    class Meta:
        model = PayrollPeriod
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class PayslipSerializer(TenantModelSerializer):
    class Meta:
        model = Payslip
        fields = "__all__"
        read_only_fields = [
            "company",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
