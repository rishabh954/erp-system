from datetime import date
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, F

from core.services import BaseService
from apps.hrms.models import (
    Employee, Attendance, LeaveRequest, LeaveBalance, LeaveType,
    PayrollPeriod, Payslip, EmployeeSalary
)


class EmployeeService(BaseService):
    @transaction.atomic
    def onboard_employee(self, data, user, files=None):
        employee_id = data.get('employee_id')
        if employee_id and Employee.objects.filter(company=self.company, employee_id=employee_id).exists():
            raise ValueError(f'Employee ID "{employee_id}" is already assigned to another employee.')

        emp = Employee(
            company=self.company,
            employee_id=employee_id,
            first_name=data.get('first_name'),
            last_name=data.get('last_name'),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            joining_date=data.get('joining_date'),
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
        if files and files.get('profile_photo'):
            emp.profile_photo = files['profile_photo']
        emp.save()

        # Try to link user account
        self._ensure_user_account(emp)

        # Initialize leave balances for the new year
        from apps.hrms.tasks import reset_annual_leave_balances
        reset_annual_leave_balances.delay(company_id=str(self.company.pk))

        self.log_activity(
            action='created',
            module='hrms',
            resource_type='Employee',
            resource_id=emp.pk,
            description=f"Onboarded new employee: {emp.full_name}"
        )
        return emp

    def _ensure_user_account(self, emp):
        if emp.email and not emp.user_id:
            from apps.authentication.models import User
            user = User.objects.filter(email=emp.email).first()
            if user:
                emp.user = user
                emp.save(update_fields=['user'])


class AttendanceService(BaseService):
    def check_in(self, employee):
        today = timezone.localdate()
        att, created = Attendance.objects.get_or_create(
            company=self.company, employee=employee, date=today,
            defaults={'status': 'present', 'check_in': timezone.now()}
        )
        if not created and not att.check_in:
            att.check_in = timezone.now()
            att.status = 'present'
            att.save(update_fields=['check_in', 'status'])
        return att

    def check_out(self, employee):
        today = timezone.localdate()
        try:
            att = Attendance.objects.get(company=self.company, employee=employee, date=today)
            att.check_out = timezone.now()
            att.save(update_fields=['check_out'])
            return att
        except Attendance.DoesNotExist:
            raise ValueError('No check-in found for today')


class LeaveService(BaseService):
    @transaction.atomic
    def request_leave(self, employee, data, files=None):
        from datetime import datetime
        start = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        end   = datetime.strptime(data['end_date'],   '%Y-%m-%d').date()
        days  = (end - start).days + 1

        leave = LeaveRequest(
            company=self.company,
            employee=employee,
            leave_type_id=data['leave_type'],
            start_date=start,
            end_date=end,
            day_type=data.get('day_type', 'full'),
            total_days=days,
            reason=data['reason'],
            status='pending',
        )
        leave.number = BaseService.generate_sequence_number('LV', LeaveRequest, self.company.pk)
        
        if files and files.get('attachment'):
            leave.attachment = files['attachment']
        leave.save()

        # Trigger approval workflow notification
        from apps.notifications.tasks import send_bulk_notification
        from apps.authentication.models import User
        hr_users = User.objects.filter(
            role='hr_manager', companies=self.company, is_active=True
        ).values_list('pk', flat=True)
        
        send_bulk_notification.delay(
            recipient_ids=list(hr_users),
            title=f'Leave Request: {employee.full_name}',
            message=f'{employee.full_name} has submitted a leave request for {days} day(s).',
            notification_type='approval',
            action_url=f'/hrms/leaves/{leave.pk}/',
            company_id=str(self.company.pk),
        )
        
        self.log_activity(
            action='created',
            module='hrms',
            resource_type='LeaveRequest',
            resource_id=leave.pk,
            description=f"Leave request created for {employee.full_name}"
        )
        return leave

    @transaction.atomic
    def process_leave(self, leave, action, user, data=None):
        if action == 'approve':
            leave.status = 'approved'
            leave.approved_by = user
            leave.approved_at = timezone.now()
            leave.save(update_fields=['status', 'approved_by', 'approved_at'])
            
            # Update leave balance
            bal = LeaveBalance.objects.filter(
                employee=leave.employee,
                leave_type=leave.leave_type,
                year=timezone.localdate().year
            ).first()
            if bal:
                bal.used += leave.total_days
                bal.pending = max(0, bal.pending - leave.total_days)
                bal.save(update_fields=['used', 'pending'])
                
            self.log_activity(
                action='approved',
                module='hrms',
                resource_type='LeaveRequest',
                resource_id=leave.pk,
                description=f"Approved leave request for {leave.employee.full_name}"
            )
            
        elif action == 'reject':
            leave.status = 'rejected'
            leave.rejection_reason = data.get('rejection_reason', '') if data else ''
            leave.save(update_fields=['status', 'rejection_reason'])
            
            self.log_activity(
                action='rejected',
                module='hrms',
                resource_type='LeaveRequest',
                resource_id=leave.pk,
                description=f"Rejected leave request for {leave.employee.full_name}"
            )
        return leave


class PayrollService(BaseService):
    
    def _count_working_days(self, start, end):
        count = 0
        current = start
        while current <= end:
            if current.weekday() < 5:
                count += 1
            current += timezone.timedelta(days=1)
        return count
        
    @transaction.atomic
    def process_payroll(self, period):
        period.status = 'processing'
        period.save(update_fields=['status'])

        employees = Employee.objects.filter(
            company=period.company, status__in=['active', 'probation'], is_deleted=False
        ).select_related('salary_structure')

        total_gross = Decimal('0')
        total_deductions = Decimal('0')
        total_net = Decimal('0')

        for emp in employees:
            salary = EmployeeSalary.objects.filter(
                employee=emp, is_current=True, is_deleted=False
            ).select_related('salary_structure').first()

            if not salary:
                continue

            working_days = self._count_working_days(period.period_start, period.period_end)
            present_days = Attendance.objects.filter(
                employee=emp,
                date__range=(period.period_start, period.period_end),
                status__in=['present', 'late', 'half_day'],
            ).count()

            absent_days = working_days - present_days

            basic = salary.basic_salary
            components = []
            gross = Decimal('0')
            deductions = Decimal('0')
            tax = Decimal('0')

            for comp in salary.salary_structure.components.filter(is_deleted=False):
                if comp.calc_type == 'fixed':
                    amount = comp.amount
                elif comp.calc_type == 'percentage':
                    amount = basic * comp.percentage / 100
                else:
                    amount = Decimal('0')

                components.append({
                    'name': comp.name,
                    'code': comp.code,
                    'type': comp.component_type,
                    'amount': float(amount),
                })

                if comp.component_type == 'earning':
                    gross += amount
                elif comp.component_type == 'deduction':
                    deductions += amount
                elif comp.component_type == 'tax':
                    tax += amount

            net = gross - deductions - tax

            payslip, created = Payslip.objects.get_or_create(
                payroll_period=period,
                employee=emp,
                defaults={
                    'company': period.company,
                    'employee_salary': salary,
                    'working_days': working_days,
                    'present_days': present_days,
                    'absent_days': absent_days,
                    'basic_salary': basic,
                    'gross_salary': gross,
                    'total_deductions': deductions,
                    'total_tax': tax,
                    'net_salary': net,
                    'status': 'generated',
                    'components': components,
                }
            )

            if not created:
                Payslip.objects.filter(pk=payslip.pk).update(
                    working_days=working_days, present_days=present_days,
                    absent_days=absent_days, basic_salary=basic,
                    gross_salary=gross, total_deductions=deductions,
                    total_tax=tax, net_salary=net, status='generated',
                    components=components,
                )

            if not payslip.number:
                prefix = period.company.settings.filter(key='PAYSLIP_PREFIX').first()
                prefix = prefix.value if prefix else 'PAY'
                payslip.number = f"{prefix}-{period.period_start.strftime('%Y%m')}-{emp.employee_id}"
                payslip.save(update_fields=['number'])

            total_gross += gross
            total_deductions += deductions
            total_net += net

        period.total_gross = total_gross
        period.total_deductions = total_deductions
        period.total_net = total_net
        period.status = 'completed'
        period.save(update_fields=['total_gross', 'total_deductions', 'total_net', 'status'])
        
        self.log_activity(
            action='processed',
            module='hrms',
            resource_type='PayrollPeriod',
            resource_id=period.pk,
            description=f"Processed payroll for period {period.name}"
        )
        return period
