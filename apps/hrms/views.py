"""
HRMS Views
Employees, Attendance, Leave Management, Payroll
"""

from django.views.generic import ListView, DetailView, CreateView, UpdateView, View, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib import messages
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.db.models import Q, Count, Sum, Avg
from django.utils import timezone
from datetime import date, timedelta

from .models import (
    Employee, Attendance, LeaveRequest, LeaveType, LeaveBalance,
    PayrollPeriod, Payslip, JobTitle
)


class CompanyMixin(LoginRequiredMixin):
    def company(self):
        return self.request.user.primary_company


# ════════════════════════ EMPLOYEES ══════════════════════════════════════════

class EmployeeListView(CompanyMixin, ListView):
    template_name = 'hrms/employees/list.html'
    context_object_name = 'employees'
    paginate_by = 25

    def get_queryset(self):
        qs = Employee.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related('job_title', 'department', 'branch', 'manager').order_by('first_name')

        q = self.request.GET.get('q', '')
        status = self.request.GET.get('status', '')
        dept = self.request.GET.get('department', '')

        if q:
            qs = qs.filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q) |
                Q(employee_id__icontains=q) | Q(email__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        if dept:
            qs = qs.filter(department_id=dept)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.company.models import Department
        ctx['departments'] = Department.objects.filter(
            company=self.company(), is_active=True, is_deleted=False
        )
        ctx['status_choices'] = Employee.Status.choices
        ctx['total_count'] = Employee.objects.filter(company=self.company(), is_deleted=False).count()
        ctx['active_count'] = Employee.objects.filter(company=self.company(), status='active', is_deleted=False).count()
        return ctx


class EmployeeDetailView(CompanyMixin, DetailView):
    template_name = 'hrms/employees/detail.html'
    context_object_name = 'employee'

    def get_object(self):
        return get_object_or_404(Employee, pk=self.kwargs['pk'],
                                  company=self.company(), is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        emp = self.object
        today = date.today()
        ctx['attendance_this_month'] = Attendance.objects.filter(
            employee=emp,
            date__year=today.year, date__month=today.month
        ).order_by('-date')
        ctx['leave_balances'] = LeaveBalance.objects.filter(
            employee=emp, year=today.year
        ).select_related('leave_type')
        ctx['recent_payslips'] = Payslip.objects.filter(
            employee=emp, is_deleted=False
        ).select_related('payroll_period').order_by('-created_at')[:6]
        ctx['skills'] = emp.skills.all()
        ctx['documents'] = emp.documents.filter(is_deleted=False)
        ctx['experience'] = emp.experience_records.all().order_by('-start_date')
        return ctx



class EmployeeUpdateView(CompanyMixin, View):
    template_name = 'hrms/employees/form.html'

    def get(self, request, pk):
        emp = get_object_or_404(Employee, pk=pk, company=self.company())
        ctx = self._ctx()
        ctx['emp'] = emp
        return render(request, self.template_name, ctx)

    def post(self, request, pk):
        emp = get_object_or_404(Employee, pk=pk, company=self.company())
        data = request.POST
        employee_id = data.get('employee_id')
        if employee_id and Employee.objects.filter(company=self.company(), employee_id=employee_id).exclude(pk=pk).exists():
            messages.error(request, f'Employee ID "{employee_id}" is already assigned to another employee.')
            ctx = self._ctx()
            ctx['emp'] = emp
            return render(request, self.template_name, ctx)

        try:
            emp.employee_id = data.get('employee_id', emp.employee_id)
            emp.first_name = data.get('first_name', emp.first_name)
            emp.last_name = data.get('last_name', emp.last_name)
            emp.email = data.get('email', emp.email)
            emp.phone = data.get('phone', emp.phone)
            emp.joining_date = data.get('joining_date', emp.joining_date)
            emp.department_id = data.get('department') or None
            emp.branch_id = data.get('branch') or None
            emp.job_title_id = data.get('job_title') or None
            emp.status = data.get('status', emp.status)
            emp.gender = data.get('gender', emp.gender)
            emp.date_of_birth = data.get('date_of_birth') or None
            emp.address_line1 = data.get('address_line1', emp.address_line1)
            emp.city = data.get('city', emp.city)
            emp.country = data.get('country', emp.country)
            emp.national_id = data.get('national_id', emp.national_id)
            emp.emergency_contact_name = data.get('emergency_contact_name', emp.emergency_contact_name)
            emp.emergency_contact_phone = data.get('emergency_contact_phone', emp.emergency_contact_phone)
            emp.marital_status = data.get('marital_status', emp.marital_status)
            emp.nationality = data.get('nationality', emp.nationality)
            emp.emergency_contact_relation = data.get('emergency_contact_relation', emp.emergency_contact_relation)
            
            if request.FILES.get('profile_photo'):
                emp.profile_photo = request.FILES['profile_photo']
            emp.save()
            self._ensure_user_account(emp, self.company())

            messages.success(request, f'Employee {emp.full_name} updated successfully.')
            return redirect('hrms:employee_detail', pk=emp.pk)
        except Exception as e:
            messages.error(request, f'Error updating employee: {e}')
            ctx = self._ctx()
            ctx['emp'] = emp
            return render(request, self.template_name, ctx)


    def _ensure_user_account(self, emp, company):
        if emp.email and not emp.user_id:
            from apps.authentication.models import User, UserCompany
            user = User.objects.filter(email=emp.email).first()
            if not user:
                user = User.objects.create_user(
                    email=emp.email,
                    username=emp.email,
                    password='Welcome@123',
                    first_name=emp.first_name,
                    last_name=emp.last_name,
                    role=User.Role.EMPLOYEE
                )
            emp.user = user
            emp.save(update_fields=['user'])
            UserCompany.objects.get_or_create(user=user, company=company, defaults={'is_active': True})
            
    def _ctx(self):
        from apps.company.models import Department, Branch
        from apps.administration.models import Designation
        company = self.company()
        return {
            'departments': Department.objects.filter(company=company, is_active=True, is_deleted=False),
            'branches': Branch.objects.filter(company=company, is_active=True, is_deleted=False),
            'job_titles': Designation.objects.filter(company=company, is_active=True, is_deleted=False),
            'managers': Employee.objects.filter(company=company, status=Employee.Status.ACTIVE, is_deleted=False),
            'status_choices': Employee.Status.choices,
            'gender_choices': Employee.Gender.choices,
            'marital_status_choices': Employee.MaritalStatus.choices,
        }

class EmployeeCreateView(CompanyMixin, View):
    template_name = 'hrms/employees/form.html'

    def get(self, request):
        return render(request, self.template_name, self._ctx())

    def post(self, request):
        data = request.POST
        company = self.company()
        employee_id = data.get('employee_id')
        if employee_id and Employee.objects.filter(company=company, employee_id=employee_id).exists():
            messages.error(request, f'Employee ID "{employee_id}" is already assigned to another employee.')
            return render(request, self.template_name, self._ctx())

        try:
            emp = Employee(
                company=company,
                employee_id=data['employee_id'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                email=data.get('email', ''),
                phone=data.get('phone', ''),
                joining_date=data['joining_date'],
                department_id=data.get('department') or None,
                branch_id=data.get('branch') or None,
                job_title_id=data.get('job_title') or None,
                status=data.get('status', 'active'),
                gender=data.get('gender', ''),
                date_of_birth=data.get('date_of_birth') or None,
                address_line1=data.get('address_line1', ''),
                city=data.get('city', ''),
                country=data.get('country', ''),
                national_id=data.get('national_id', ''),
                emergency_contact_name=data.get('emergency_contact_name', ''),
                emergency_contact_phone=data.get('emergency_contact_phone', ''),
                marital_status=data.get('marital_status', ''),
                nationality=data.get('nationality', ''),
                emergency_contact_relation=data.get('emergency_contact_relation', ''),
            )
            if request.FILES.get('profile_photo'):
                emp.profile_photo = request.FILES['profile_photo']
            emp.save()
            self._ensure_user_account(emp, company)

            # Initialize leave balances for the new year
            from .tasks import reset_annual_leave_balances
            reset_annual_leave_balances.delay(company_id=str(company.pk))

            messages.success(request, f'Employee {emp.full_name} created successfully.')
            return redirect('hrms:employee_detail', pk=emp.pk)
        except Exception as e:
            messages.error(request, f'Error creating employee: {e}')
            return render(request, self.template_name, self._ctx())


    def _ensure_user_account(self, emp, company):
        if emp.email and not emp.user_id:
            from apps.authentication.models import User, UserCompany
            user = User.objects.filter(email=emp.email).first()
            if not user:
                user = User.objects.create_user(
                    email=emp.email,
                    username=emp.email,
                    password='Welcome@123',
                    first_name=emp.first_name,
                    last_name=emp.last_name,
                    role=User.Role.EMPLOYEE
                )
            emp.user = user
            emp.save(update_fields=['user'])
            UserCompany.objects.get_or_create(user=user, company=company, defaults={'is_active': True})
            
    def _ctx(self):
        from apps.company.models import Department, Branch
        from apps.administration.models import Designation
        company = self.company()
        return {
            'departments': Department.objects.filter(company=company, is_active=True, is_deleted=False),
            'branches': Branch.objects.filter(company=company, is_active=True, is_deleted=False),
            'job_titles': Designation.objects.filter(company=company, is_active=True, is_deleted=False),
            'managers': Employee.objects.filter(company=company, status=Employee.Status.ACTIVE, is_deleted=False),
            'status_choices': Employee.Status.choices,
            'gender_choices': Employee.Gender.choices,
            'marital_status_choices': Employee.MaritalStatus.choices,
        }


# ════════════════════════ ATTENDANCE ════════════════════════════════════════

class AttendanceView(CompanyMixin, TemplateView):
    template_name = 'hrms/attendance/index.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()
        today = date.today()
        ctx['today'] = today
        ctx['attendance_today'] = Attendance.objects.filter(
            company=company, date=today
        ).select_related('employee').order_by('employee__first_name')
        ctx['present'] = Attendance.objects.filter(company=company, date=today, status='present').count()
        ctx['absent'] = Attendance.objects.filter(company=company, date=today, status='absent').count()
        ctx['on_leave'] = Attendance.objects.filter(company=company, date=today, status='on_leave').count()
        ctx['late'] = Attendance.objects.filter(company=company, date=today, status='late').count()
        return ctx


class CheckInView(CompanyMixin, View):
    def post(self, request):
        try:
            emp = Employee.objects.get(user=request.user, is_deleted=False)
        except Employee.DoesNotExist:
            return JsonResponse({'error': 'Your user account is not linked to an employee profile.'}, status=400)
        
        today = date.today()
        att, created = Attendance.objects.get_or_create(
            company=self.company(), employee=emp, date=today,
            defaults={'status': 'present', 'check_in': timezone.now()}
        )
        if not created and not att.check_in:
            att.check_in = timezone.now()
            att.status = 'present'
            att.save(update_fields=['check_in', 'status'])
        return JsonResponse({'status': 'ok', 'check_in': str(att.check_in)})


class CheckOutView(CompanyMixin, View):
    def post(self, request):
        try:
            emp = Employee.objects.get(user=request.user, is_deleted=False)
        except Employee.DoesNotExist:
            return JsonResponse({'error': 'Your user account is not linked to an employee profile.'}, status=400)
            
        today = date.today()
        try:
            att = Attendance.objects.get(company=self.company(), employee=emp, date=today)
            att.check_out = timezone.now()
            att.save()
            return JsonResponse({'status': 'ok', 'work_hours': float(att.work_hours)})
        except Attendance.DoesNotExist:
            return JsonResponse({'error': 'No check-in found for today'}, status=400)


# ════════════════════════ LEAVE MANAGEMENT ═══════════════════════════════════

class LeaveListView(CompanyMixin, ListView):
    template_name = 'hrms/leaves/list.html'
    context_object_name = 'leaves'
    paginate_by = 25

    def get_queryset(self):
        qs = LeaveRequest.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related('employee', 'leave_type', 'approved_by').order_by('-created_at')

        # Non-HR users only see their own
        if self.request.user.role not in ('hr_manager', 'company_admin', 'super_admin'):
            try:
                emp = Employee.objects.get(user=self.request.user, is_deleted=False)
                qs = qs.filter(employee=emp)
            except Employee.DoesNotExist:
                qs = qs.none()

        status = self.request.GET.get('status', '')
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = LeaveRequest.Status.choices
        ctx['pending_count'] = LeaveRequest.objects.filter(
            company=self.company(), status='pending', is_deleted=False
        ).count()
        return ctx


class LeaveRequestCreateView(CompanyMixin, View):
    template_name = 'hrms/leaves/form.html'

    def get(self, request):
        return render(request, self.template_name, {
            'leave_types': LeaveType.objects.filter(company=self.company(), is_active=True, is_deleted=False),
            'day_type_choices': LeaveRequest.DayType.choices,
        })

    def post(self, request):
        company = self.company()
        try:
            emp = Employee.objects.get(user=request.user, company=company, is_deleted=False)
        except Employee.DoesNotExist:
            messages.error(request, 'No employee profile found for your account.')
            return redirect('hrms:leaves')

        from datetime import datetime
        start = datetime.strptime(request.POST['start_date'], '%Y-%m-%d').date()
        end   = datetime.strptime(request.POST['end_date'],   '%Y-%m-%d').date()
        days  = (end - start).days + 1

        from core.services import BaseService
        leave = LeaveRequest(
            company=company,
            employee=emp,
            leave_type_id=request.POST['leave_type'],
            start_date=start,
            end_date=end,
            day_type=request.POST.get('day_type', 'full'),
            total_days=days,
            reason=request.POST['reason'],
            status='pending',
        )
        leave.number = BaseService.generate_sequence_number('LV', LeaveRequest, company.pk)
        if request.FILES.get('attachment'):
            leave.attachment = request.FILES['attachment']
        leave.save()

        # Trigger approval workflow notification
        from apps.notifications.tasks import send_bulk_notification
        from apps.authentication.models import User
        hr_users = User.objects.filter(
            role='hr_manager', companies=company, is_active=True
        ).values_list('pk', flat=True)
        send_bulk_notification.delay(
            recipient_ids=list(hr_users),
            title=f'Leave Request: {emp.full_name}',
            message=f'{emp.full_name} has submitted a leave request for {days} day(s).',
            notification_type='approval',
            action_url=f'/hrms/leaves/{leave.pk}/',
            company_id=str(company.pk),
        )

        messages.success(request, f'Leave request {leave.number} submitted successfully.')
        return redirect('hrms:leaves')


class LeaveApproveView(CompanyMixin, View):
    def post(self, request, pk):
        leave = get_object_or_404(LeaveRequest, pk=pk, company=self.company(), is_deleted=False)
        action = request.POST.get('action')
        if action == 'approve':
            leave.status = 'approved'
            leave.approved_by = request.user
            leave.approved_at = timezone.now()
            leave.save(update_fields=['status', 'approved_by', 'approved_at'])
            # Update leave balance
            bal = LeaveBalance.objects.filter(
                employee=leave.employee,
                leave_type=leave.leave_type,
                year=date.today().year
            ).first()
            if bal:
                bal.used += leave.total_days
                bal.pending = max(0, bal.pending - leave.total_days)
                bal.save(update_fields=['used', 'pending'])
            messages.success(request, f'Leave request {leave.number} approved.')
        elif action == 'reject':
            leave.status = 'rejected'
            leave.rejection_reason = request.POST.get('rejection_reason', '')
            leave.save(update_fields=['status', 'rejection_reason'])
            messages.warning(request, f'Leave request {leave.number} rejected.')
        return redirect('hrms:leaves')


# ════════════════════════ PAYROLL ═════════════════════════════════════════════

class PayrollListView(CompanyMixin, ListView):
    template_name = 'hrms/payroll/list.html'
    context_object_name = 'periods'
    paginate_by = 12

    def get_queryset(self):
        return PayrollPeriod.objects.filter(
            company=self.company(), is_deleted=False
        ).order_by('-period_start')


class PayrollDetailView(CompanyMixin, DetailView):
    template_name = 'hrms/payroll/detail.html'
    context_object_name = 'period'

    def get_object(self):
        return get_object_or_404(PayrollPeriod, pk=self.kwargs['pk'],
                                  company=self.company(), is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['payslips'] = Payslip.objects.filter(
            payroll_period=self.object, is_deleted=False
        ).select_related('employee').order_by('employee__first_name')
        return ctx


class PayrollProcessView(CompanyMixin, View):
    def post(self, request, pk):
        period = get_object_or_404(PayrollPeriod, pk=pk, company=self.company(), is_deleted=False)
        from .tasks import process_payroll
        process_payroll.delay(str(period.pk))
        messages.success(request, f'Payroll processing started for {period.name}. This may take a few minutes.')
        return redirect('hrms:payroll_detail', pk=pk)


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path

app_name = 'hrms'

urlpatterns = [
    path('employees/', EmployeeListView.as_view(), name='employees'),
    path('employees/create/', EmployeeCreateView.as_view(), name='employee_create'),
    path('employees/<uuid:pk>/', EmployeeDetailView.as_view(), name='employee_detail'),
    path('attendance/', AttendanceView.as_view(), name='attendance'),
    path('attendance/check-in/', CheckInView.as_view(), name='check_in'),
    path('attendance/check-out/', CheckOutView.as_view(), name='check_out'),
    path('leaves/', LeaveListView.as_view(), name='leaves'),
    path('leaves/create/', LeaveRequestCreateView.as_view(), name='leave_request_create'),
    path('leaves/<uuid:pk>/approve/', LeaveApproveView.as_view(), name='leave_approve'),
    path('payroll/', PayrollListView.as_view(), name='payroll'),
    path('payroll/<uuid:pk>/', PayrollDetailView.as_view(), name='payroll_detail'),
    path('payroll/<uuid:pk>/process/', PayrollProcessView.as_view(), name='payroll_process'),
]

# ════════════════════════ RECRUITMENT ═════════════════════════════════════════

from .models import JobPosting, JobApplication, Interview

class JobPostingListView(CompanyMixin, ListView):
    template_name = 'hrms/recruitment/job_postings.html'
    context_object_name = 'jobs'
    
    def get_queryset(self):
        return JobPosting.objects.filter(company=self.company()).select_related('department')

class JobPostingDetailView(CompanyMixin, DetailView):
    template_name = 'hrms/recruitment/job_posting_detail.html'
    context_object_name = 'job'
    
    def get_queryset(self):
        return JobPosting.objects.filter(company=self.company()).select_related('department')
        
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['applications'] = self.object.applications.all()
        return ctx

class JobApplicationListView(CompanyMixin, ListView):
    template_name = 'hrms/recruitment/applications.html'
    context_object_name = 'applications'
    
    def get_queryset(self):
        return JobApplication.objects.filter(company=self.company()).select_related('job_posting')

class JobApplicationDetailView(CompanyMixin, DetailView):
    template_name = 'hrms/recruitment/application_detail.html'
    context_object_name = 'application'
    
    def get_queryset(self):
        return JobApplication.objects.filter(company=self.company()).select_related('job_posting')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['interviews'] = self.object.interviews.select_related('interviewer')
        return ctx

# ════════════════════════ PERFORMANCE APPRAISAL ═══════════════════════════════
from .models import PerformanceAppraisal, TrainingProgram, ExpenseClaim

class PerformanceAppraisalListView(CompanyMixin, ListView):
    template_name = 'hrms/appraisals/list.html'
    context_object_name = 'appraisals'
    
    def get_queryset(self):
        return PerformanceAppraisal.objects.filter(company=self.company()).select_related('employee', 'manager')

class PerformanceAppraisalDetailView(CompanyMixin, DetailView):
    template_name = 'hrms/appraisals/detail.html'
    context_object_name = 'appraisal'
    
    def get_queryset(self):
        return PerformanceAppraisal.objects.filter(company=self.company()).select_related('employee', 'manager')

# ════════════════════════ TRAINING PROGRAM ════════════════════════════════════

class TrainingProgramListView(CompanyMixin, ListView):
    template_name = 'hrms/training/list.html'
    context_object_name = 'programs'
    
    def get_queryset(self):
        return TrainingProgram.objects.filter(company=self.company()).prefetch_related('attendees')

class TrainingProgramDetailView(CompanyMixin, DetailView):
    template_name = 'hrms/training/detail.html'
    context_object_name = 'program'
    
    def get_queryset(self):
        return TrainingProgram.objects.filter(company=self.company()).prefetch_related('attendees')

# ════════════════════════ EXPENSE CLAIMS ══════════════════════════════════════

class ExpenseClaimListView(CompanyMixin, ListView):
    template_name = 'hrms/expenses/list.html'
    context_object_name = 'claims'
    
    def get_queryset(self):
        return ExpenseClaim.objects.filter(company=self.company()).select_related('employee')

class ExpenseClaimDetailView(CompanyMixin, DetailView):
    template_name = 'hrms/expenses/detail.html'
    context_object_name = 'claim'
    
    def get_queryset(self):
        return ExpenseClaim.objects.filter(company=self.company()).select_related('employee', 'approved_by')
