import pytest
from datetime import date
from decimal import Decimal
from apps.hrms.services import PayrollService
from apps.hrms.models import EmployeeSalary, PayrollPeriod, SalaryStructure, SalaryComponent, Attendance

pytestmark = pytest.mark.django_db

def test_payroll_service(company, user, employee, currency):
    service = PayrollService(user=user, company=company)
    
    struct = SalaryStructure.objects.create(company=company, name='Standard', is_active=True)
    SalaryComponent.objects.create(
        company=company, salary_structure=struct,
        name='Basic', code='BSC', component_type='earning',
        calc_type='fixed', amount=Decimal('5000.00')
    )
    SalaryComponent.objects.create(
        company=company, salary_structure=struct,
        name='HRA', code='HRA', component_type='earning',
        calc_type='percentage', percentage=Decimal('10.00')
    )
    SalaryComponent.objects.create(
        company=company, salary_structure=struct,
        name='Tax', code='TAX', component_type='tax',
        calc_type='percentage', percentage=Decimal('5.00')
    )
    
    salary = EmployeeSalary.objects.create(
        employee=employee,
        company=company,
        salary_structure=struct,
        basic_salary=Decimal('5000.00'),
        currency=currency,
        effective_from=date(2026, 7, 1),
        is_current=True
    )
    
    period = PayrollPeriod.objects.create(
        company=company,
        name='July 2026',
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        currency=currency,
        status='draft'
    )
    
    # Process payroll
    processed_period = service.process_payroll(period)
    
    assert processed_period.status == 'completed'
    assert processed_period.total_gross > 0
    assert processed_period.total_net > 0
    
    # Check payslip generated
    payslip = processed_period.payslips.filter(employee=employee).first()
    assert payslip is not None
    assert payslip.gross_salary == Decimal('5500.00') # 5000 + 10% (500)
    assert payslip.total_tax == Decimal('250.00') # 5% of 5000
    assert payslip.net_salary == Decimal('5250.00')
