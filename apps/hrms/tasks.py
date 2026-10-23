"""
HRMS Celery Tasks
Payroll processing, attendance automation, leave balance reset
"""

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def process_payroll_task(self, payroll_period_id, user_id=None, company_id=None):
    """Process payroll for all employees in a period using the PayrollService."""
    from apps.authentication.models import UserCompany
    from apps.hrms.models import PayrollPeriod
    from apps.hrms.services import PayrollService

    if not company_id:
        logger.error("Payroll processing requires an explicit company ID.")
        return "Company ID is required."

    try:
        with transaction.atomic():
            period = (
                PayrollPeriod.objects.select_for_update()
                .filter(
                    pk=payroll_period_id,
                    company_id=company_id,
                    is_deleted=False,
                )
                .first()
            )
            if period is None:
                logger.warning(
                    "Payroll period %s not found for company %s",
                    payroll_period_id,
                    company_id,
                )
                return "Payroll period not found."

            if period.status in (
                PayrollPeriod.Status.COMPLETED,
                PayrollPeriod.Status.APPROVED,
                PayrollPeriod.Status.PAID,
            ):
                return f"Payroll period {period.name} is already finalized."

            user_membership = None
            if user_id:
                user_membership = (
                    UserCompany.objects.filter(
                        company_id=company_id,
                        user_id=user_id,
                        is_active=True,
                        user__is_active=True,
                    )
                    .select_related("user")
                    .first()
                )
                if user_membership is None:
                    logger.warning(
                        "Payroll requester %s is not an active member of company %s",
                        user_id,
                        company_id,
                    )
                    return "Payroll requester is not an active company member."

            service = PayrollService(
                user=user_membership.user if user_membership else None,
                company=period.company,
            )
            service.process_payroll(period)

        logger.info("Payroll completed for period %s", period.name)
        return f"Payroll completed for period {period.name}."
    except Exception as exc:
        logger.exception("Payroll processing failed for period %s", payroll_period_id)
        raise self.retry(exc=exc)


@shared_task
def auto_mark_attendance():
    """Mark absent for employees who didn't check in today."""
    from apps.company.models import Company
    from apps.hrms.models import Attendance, Employee

    today = timezone.localdate()
    for company in Company.objects.filter(status="active", is_deleted=False):
        with transaction.atomic():
            employees = Employee.objects.filter(
                company=company, status="active", is_deleted=False
            )
            for emp in employees:
                # The employee/date unique constraint makes this safe when
                # multiple scheduled workers run at the same time. Include
                # company explicitly to keep the lookup tenant-scoped.
                Attendance.objects.get_or_create(
                    company=company,
                    employee=emp,
                    date=today,
                    defaults={"status": "absent"},
                )


@shared_task
def reset_annual_leave_balances(company_id=None):
    """Reset leave balances at start of fiscal year."""
    from apps.company.models import Company
    from apps.hrms.models import Employee, LeaveBalance, LeaveType

    companies = Company.objects.filter(status="active", is_deleted=False)
    if company_id:
        companies = companies.filter(pk=company_id)

    year = timezone.localdate().year
    for company in companies:
        leave_types = LeaveType.objects.filter(
            company=company, is_active=True, is_deleted=False
        )
        employees = Employee.objects.filter(
            company=company, status="active", is_deleted=False
        )

        for emp in employees:
            for lt in leave_types:
                # Carry forward from previous year
                prev = LeaveBalance.objects.filter(
                    employee=emp, leave_type=lt, year=year - 1
                ).first()

                carry = Decimal("0")
                if prev and lt.carry_forward:
                    carry = min(prev.available, lt.max_carry_forward_days)

                LeaveBalance.objects.get_or_create(
                    employee=emp,
                    leave_type=lt,
                    year=year,
                    defaults={
                        "allocated": lt.days_allowed,
                        "carried_forward": carry,
                        "used": Decimal("0"),
                        "pending": Decimal("0"),
                    },
                )


@shared_task
def send_payslip_emails(payroll_period_id):
    """Email payslips to all employees after payroll approval."""
    from apps.hrms.models import PayrollPeriod, Payslip
    from apps.notifications.tasks import send_email_task

    period = PayrollPeriod.objects.filter(pk=payroll_period_id, is_deleted=False).first()
    if period is None:
        logger.warning("Payroll period %s not found for payslip email", payroll_period_id)
        return 0

    payslips = Payslip.objects.filter(
        payroll_period_id=payroll_period_id,
        company=period.company,
        status="approved",
        employee__user__isnull=False,
    ).select_related("employee__user", "payroll_period")

    for slip in payslips:
        if slip.employee.user and slip.employee.user.email:
            send_email_task.delay(
                to_email=slip.employee.user.email,
                to_name=slip.employee.full_name,
                subject=f"Your Payslip for {slip.payroll_period.name}",
                template="payslip",
                context={
                    "employee": slip.employee.full_name,
                    "period": slip.payroll_period.name,
                    "net_salary": float(slip.net_salary),
                    "payslip_number": slip.number,
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


from decimal import Decimal  # noqa: E402
