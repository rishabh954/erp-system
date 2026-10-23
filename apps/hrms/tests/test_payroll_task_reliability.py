from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.company.models import Company
from apps.hrms.models import (
    EmployeeSalary,
    PayrollPeriod,
    Payslip,
    SalaryComponent,
    SalaryStructure,
)


def make_period(company, currency):
    return PayrollPeriod.objects.create(
        company=company,
        name="May 2026",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        currency=currency,
        status=PayrollPeriod.Status.DRAFT,
    )


@pytest.mark.django_db
def test_payroll_task_is_tenant_scoped_and_skips_completed_retries(
    company, user, employee, currency
):
    from apps.hrms.tasks import process_payroll_task

    structure = SalaryStructure.objects.create(company=company, name="Monthly")
    SalaryComponent.objects.create(
        company=company,
        salary_structure=structure,
        name="Basic",
        code="BASIC",
        component_type=SalaryComponent.ComponentType.EARNING,
        calc_type=SalaryComponent.CalcType.FIXED,
        amount=Decimal("5000.00"),
    )
    EmployeeSalary.objects.create(
        company=company,
        employee=employee,
        salary_structure=structure,
        basic_salary=Decimal("5000.00"),
        currency=currency,
        effective_from=date(2026, 1, 1),
    )
    period = make_period(company, currency)

    assert process_payroll_task.run(str(period.pk), str(user.pk), str(company.pk)) == (
        "Payroll completed for period May 2026."
    )
    assert process_payroll_task.run(str(period.pk), str(user.pk), str(company.pk)) == (
        "Payroll period May 2026 is already finalized."
    )
    assert Payslip.objects.filter(company=company, payroll_period=period).count() == 1


@pytest.mark.django_db
def test_payroll_task_rejects_wrong_company_and_preserves_state_on_failure(
    company, user, currency
):
    from apps.hrms.services import PayrollService
    from apps.hrms.tasks import process_payroll_task

    period = make_period(company, currency)
    other_company = Company.objects.create(name="Other payroll company")

    assert process_payroll_task.run(
        str(period.pk), str(user.pk), str(other_company.pk)
    ) == "Payroll period not found."
    period.refresh_from_db()
    assert period.status == PayrollPeriod.Status.DRAFT

    failure = RuntimeError("payroll backend failed")
    with patch.object(PayrollService, "process_payroll", side_effect=failure):
        with patch.object(process_payroll_task, "retry", side_effect=failure) as retry:
            with pytest.raises(RuntimeError, match="payroll backend failed"):
                process_payroll_task.run(
                    str(period.pk), str(user.pk), str(company.pk)
                )
    retry.assert_called_once()
    period.refresh_from_db()
    assert period.status == PayrollPeriod.Status.DRAFT


@pytest.mark.django_db
def test_payroll_service_ignores_salary_data_owned_by_another_company(
    company, employee, currency
):
    from apps.hrms.tasks import process_payroll_task

    foreign_company = Company.objects.create(name="Foreign salary company")
    foreign_structure = SalaryStructure.objects.create(
        company=foreign_company, name="Foreign Structure"
    )
    SalaryComponent.objects.create(
        company=foreign_company,
        salary_structure=foreign_structure,
        name="Foreign Basic",
        code="FOREIGN",
        component_type=SalaryComponent.ComponentType.EARNING,
        calc_type=SalaryComponent.CalcType.FIXED,
        amount=Decimal("90000.00"),
    )
    EmployeeSalary.objects.create(
        company=foreign_company,
        employee=employee,
        salary_structure=foreign_structure,
        basic_salary=Decimal("90000.00"),
        currency=currency,
        effective_from=date(2026, 1, 1),
    )
    period = make_period(company, currency)

    process_payroll_task.run(str(period.pk), company_id=str(company.pk))

    period.refresh_from_db()
    assert period.status == PayrollPeriod.Status.COMPLETED
    assert period.total_gross == Decimal("0")
    assert not Payslip.objects.filter(company=company, payroll_period=period).exists()
