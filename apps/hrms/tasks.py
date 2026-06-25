"""
HRMS Celery Tasks
Payroll processing, attendance automation, leave balance reset
"""

from celery import shared_task
from django.utils import timezone
from datetime import date
import logging

logger = logging.getLogger(__name__)


@shared_task
def process_payroll(payroll_period_id):
    """Process payroll for all employees in a period."""
    from apps.hrms.models import (
        PayrollPeriod, Payslip, Employee, EmployeeSalary,
        Attendance, LeaveRequest
    )
    from decimal import Decimal

    try:
        period = PayrollPeriod.objects.get(pk=payroll_period_id)
        period.status = 'processing'
        period.save(update_fields=['status'])

        employees = Employee.objects.filter(
            company=period.company, status__in=['active', 'probation'], is_deleted=False
        ).select_related('salary_structure')

        total_gross = Decimal('0')
        total_deductions = Decimal('0')
        total_net = Decimal('0')

        for emp in employees:
            try:
                salary = EmployeeSalary.objects.filter(
                    employee=emp, is_current=True, is_deleted=False
                ).select_related('salary_structure').first()

                if not salary:
                    continue

                # Count working days in period
                working_days = _count_working_days(period.period_start, period.period_end)
                present_days = Attendance.objects.filter(
                    employee=emp,
                    date__range=(period.period_start, period.period_end),
                    status__in=['present', 'late', 'half_day'],
                ).count()

                absent_days = working_days - present_days

                # Calculate components
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
                        amount = Decimal('0')  # Formula evaluation would go here

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

                # Create or update payslip
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

                # Set sequence number
                if not payslip.number:
                    prefix = period.company.settings.filter(key='PAYSLIP_PREFIX').first()
                    prefix = prefix.value if prefix else 'PAY'
                    payslip.number = f"{prefix}-{period.period_start.strftime('%Y%m')}-{emp.employee_id}"
                    payslip.save(update_fields=['number'])

                total_gross += gross
                total_deductions += deductions
                total_net += net

            except Exception as e:
                logger.error(f'Payslip error for {emp.full_name}: {e}')

        period.total_gross = total_gross
        period.total_deductions = total_deductions
        period.total_net = total_net
        period.status = 'completed'
        period.save(update_fields=['total_gross', 'total_deductions', 'total_net', 'status'])

        logger.info(f'Payroll completed for period {period.name}: {employees.count()} employees')

    except Exception as e:
        logger.error(f'Payroll processing failed for {payroll_period_id}: {e}')
        PayrollPeriod.objects.filter(pk=payroll_period_id).update(status='draft')


@shared_task
def auto_mark_attendance():
    """Mark absent for employees who didn't check in today."""
    from apps.hrms.models import Employee, Attendance, WorkSchedule
    from apps.company.models import Company

    today = date.today()
    weekday = today.weekday()  # 0=Mon

    for company in Company.objects.filter(status='active', is_deleted=False):
        employees = Employee.objects.filter(
            company=company, status='active', is_deleted=False
        )
        for emp in employees:
            if not Attendance.objects.filter(employee=emp, date=today).exists():
                Attendance.objects.create(
                    company=company,
                    employee=emp,
                    date=today,
                    status='absent',
                )


@shared_task
def reset_annual_leave_balances(company_id=None):
    """Reset leave balances at start of fiscal year."""
    from apps.hrms.models import Employee, LeaveType, LeaveBalance

    from apps.company.models import Company
    companies = Company.objects.filter(status='active', is_deleted=False)
    if company_id:
        companies = companies.filter(pk=company_id)

    year = date.today().year
    for company in companies:
        leave_types = LeaveType.objects.filter(company=company, is_active=True, is_deleted=False)
        employees = Employee.objects.filter(company=company, status='active', is_deleted=False)

        for emp in employees:
            for lt in leave_types:
                # Carry forward from previous year
                prev = LeaveBalance.objects.filter(
                    employee=emp, leave_type=lt, year=year - 1
                ).first()

                carry = Decimal('0')
                if prev and lt.carry_forward:
                    carry = min(prev.available, lt.max_carry_forward_days)

                LeaveBalance.objects.get_or_create(
                    employee=emp, leave_type=lt, year=year,
                    defaults={
                        'allocated': lt.days_allowed,
                        'carried_forward': carry,
                        'used': Decimal('0'),
                        'pending': Decimal('0'),
                    }
                )


@shared_task
def send_payslip_emails(payroll_period_id):
    """Email payslips to all employees after payroll approval."""
    from apps.hrms.models import Payslip
    from apps.notifications.tasks import send_email_task

    payslips = Payslip.objects.filter(
        payroll_period_id=payroll_period_id,
        status='approved',
        employee__user__isnull=False,
    ).select_related('employee__user', 'payroll_period')

    for slip in payslips:
        if slip.employee.user and slip.employee.user.email:
            send_email_task.delay(
                to_email=slip.employee.user.email,
                to_name=slip.employee.full_name,
                subject=f'Your Payslip for {slip.payroll_period.name}',
                template='payslip',
                context={
                    'employee': slip.employee.full_name,
                    'period': slip.payroll_period.name,
                    'net_salary': float(slip.net_salary),
                    'payslip_number': slip.number,
                },
                company_id=str(slip.company_id),
            )


def _count_working_days(start, end):
    """Count weekdays between two dates (Mon-Fri)."""
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timezone.timedelta(days=1)
    return count


from decimal import Decimal
