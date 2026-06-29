from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from core.pagination import StandardResultsSetPagination
from apps.hrms.models import Employee, Attendance, LeaveRequest, PayrollPeriod, Payslip
from apps.hrms.api.serializers import (
    EmployeeSerializer, AttendanceSerializer, LeaveRequestSerializer,
    PayrollPeriodSerializer, PayslipSerializer
)

class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request, 'company') and self.request.company:
            qs = qs.filter(company=self.request.company)
        return qs

    @action(detail=True, methods=['post'])
    def check_in(self, request, pk=None):
        employee = self.get_object()
        today = timezone.now().date()
        attendance, created = Attendance.objects.get_or_create(
            employee=employee,
            date=today,
            defaults={'company': employee.company, 'check_in': timezone.now()}
        )
        if not created and attendance.check_in:
            return Response({'error': 'Already checked in today'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not created:
            attendance.check_in = timezone.now()
            attendance.save(update_fields=['check_in'])
            
        return Response({'status': 'checked_in', 'time': attendance.check_in})

    @action(detail=True, methods=['post'])
    def check_out(self, request, pk=None):
        employee = self.get_object()
        today = timezone.now().date()
        try:
            attendance = Attendance.objects.get(employee=employee, date=today)
        except Attendance.DoesNotExist:
            return Response({'error': 'Not checked in today'}, status=status.HTTP_400_BAD_REQUEST)
            
        if attendance.check_out:
            return Response({'error': 'Already checked out'}, status=status.HTTP_400_BAD_REQUEST)
            
        attendance.check_out = timezone.now()
        attendance.save(update_fields=['check_out'])
        return Response({'status': 'checked_out', 'time': attendance.check_out})

    @action(detail=True, methods=['get'])
    def leave_balance(self, request, pk=None):
        employee = self.get_object()
        balances = employee.leave_balances.all().values('leave_type__name', 'allocated', 'used', 'pending', 'available')
        return Response(balances)

    @action(detail=True, methods=['get'])
    def payslips(self, request, pk=None):
        employee = self.get_object()
        payslips = employee.payslips.all()
        serializer = PayslipSerializer(payslips, many=True)
        return Response(serializer.data)


class AttendanceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Attendance.objects.all()
    serializer_class = AttendanceSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request, 'company') and self.request.company:
            qs = qs.filter(company=self.request.company)
            
        employee_id = self.request.query_params.get('employee')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
            
        date = self.request.query_params.get('date')
        if date:
            qs = qs.filter(date=date)
            
        return qs

    @action(detail=False, methods=['get'])
    def today_summary(self, request):
        today = timezone.now().date()
        qs = self.get_queryset().filter(date=today)
        
        present = qs.filter(status=Attendance.Status.PRESENT).count()
        absent = qs.filter(status=Attendance.Status.ABSENT).count()
        late = qs.filter(status=Attendance.Status.LATE).count()
        on_leave = qs.filter(status=Attendance.Status.ON_LEAVE).count()
        
        return Response({
            'present': present,
            'absent': absent,
            'late': late,
            'on_leave': on_leave,
        })


class LeaveRequestViewSet(viewsets.ModelViewSet):
    queryset = LeaveRequest.objects.all()
    serializer_class = LeaveRequestSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request, 'company') and self.request.company:
            qs = qs.filter(company=self.request.company)
        return qs

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        leave_req = self.get_object()
        if leave_req.status != LeaveRequest.Status.PENDING:
            return Response({'error': 'Can only approve pending requests'}, status=status.HTTP_400_BAD_REQUEST)
            
        leave_req.status = LeaveRequest.Status.APPROVED
        leave_req.approved_by = request.user
        leave_req.save(update_fields=['status', 'approved_by'])
        return Response({'status': 'approved'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        leave_req = self.get_object()
        if leave_req.status != LeaveRequest.Status.PENDING:
            return Response({'error': 'Can only reject pending requests'}, status=status.HTTP_400_BAD_REQUEST)
            
        leave_req.status = LeaveRequest.Status.REJECTED
        leave_req.approved_by = request.user
        leave_req.rejection_reason = request.data.get('reason', '')
        leave_req.save(update_fields=['status', 'approved_by', 'rejection_reason'])
        return Response({'status': 'rejected'})


class PayrollPeriodViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PayrollPeriod.objects.all()
    serializer_class = PayrollPeriodSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request, 'company') and self.request.company:
            qs = qs.filter(company=self.request.company)
        return qs

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        period = self.get_object()
        if period.status != PayrollPeriod.Status.DRAFT:
            return Response({'error': 'Can only process draft periods'}, status=status.HTTP_400_BAD_REQUEST)
            
        # Trigger Celery task here in a real app
        from apps.hrms.tasks import process_payroll
        process_payroll.delay(period.pk)
        
        return Response({'status': 'processing_started'})


class PayslipViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Payslip.objects.all()
    serializer_class = PayslipSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request, 'company') and self.request.company:
            qs = qs.filter(company=self.request.company)
        return qs

    @action(detail=True, methods=['get'])
    def download_pdf(self, request, pk=None):
        payslip = self.get_object()
        # In a real app, generate PDF here using a template and weasyprint or similar
        # For now, just return a mock response
        return Response({'download_url': f'/media/payslips/{payslip.pk}.pdf'})
