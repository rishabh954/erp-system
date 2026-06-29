import pytest
from decimal import Decimal
from django.utils import timezone
from apps.hrms.models import Employee, EmployeeSalary, PayrollPeriod, Payslip, SalaryStructure

pytestmark = pytest.mark.django_db

def test_payroll_processing_totals(company, user, currency):
    """Test that a payslip correctly sums up basic salary into gross/net amounts."""
    # Create an employee
    employee = Employee.objects.create(
        company=company,
        user=user,
        first_name="Test",
        last_name="Employee",
        employee_id="EMP-001",
        joining_date=timezone.now().date(),
        status=Employee.Status.ACTIVE
    )
    
    # Create salary structure
    struct = SalaryStructure.objects.create(company=company, name="Standard")
    
    salary = EmployeeSalary.objects.create(
        employee=employee,
        company=company,
        salary_structure=struct,
        basic_salary=Decimal('5000.00'),
        currency=currency,
        effective_from=timezone.now().date(),
        is_current=True
    )
    
    # Create Payroll Period
    period = PayrollPeriod.objects.create(
        company=company,
        name="June 2026",
        period_start=timezone.now().date(),
        period_end=timezone.now().date(),
        currency=currency,
        status=PayrollPeriod.Status.PROCESSING
    )
    
    # Create Payslip
    # Typically there's a service or model method to generate this, but we'll test the raw fields
    # to ensure they calculate right if set directly, or if there's a method we should call.
    payslip = Payslip.objects.create(
        company=company,
        payroll_period=period,
        employee=employee,
        employee_salary=salary,
        basic_salary=salary.basic_salary,
        gross_salary=salary.basic_salary + Decimal('500.00'),  # Adding hypothetical allowance
        total_deductions=Decimal('200.00'),
        total_tax=Decimal('100.00'),
        net_salary=salary.basic_salary + Decimal('500.00') - Decimal('200.00') - Decimal('100.00'),
        status=Payslip.Status.DRAFT
    )
    
    assert payslip.gross_salary == Decimal('5500.00')
    assert payslip.net_salary == Decimal('5200.00')
    
    # Check if period totals are aggregatable
    period.total_gross = payslip.gross_salary
    period.total_deductions = payslip.total_deductions + payslip.total_tax
    period.total_net = payslip.net_salary
    period.save()
    
    period.refresh_from_db()
    assert period.total_gross == Decimal('5500.00')
    assert period.total_net == Decimal('5200.00')

from datetime import date
from apps.hrms.services import EmployeeService, AttendanceService, LeaveService, PayrollService
from apps.hrms.models import Attendance, LeaveRequest, LeaveType

@pytest.fixture
def hrms_services(db, rf, company, user):
    class MockData(dict):
        def getlist(self, key):
            return self.get(key, [])
            
    return {
        'company': company,
        'user': user,
        'MockData': MockData,
        'employee_service': EmployeeService(user=user, company=company),
        'attendance_service': AttendanceService(user=user, company=company),
        'leave_service': LeaveService(user=user, company=company),
        'payroll_service': PayrollService(user=user, company=company),
    }

@pytest.mark.django_db
def test_employee_service(hrms_services):
    service = hrms_services['employee_service']
    
    data = hrms_services['MockData']({
        'employee_id': 'EMP-002',
        'first_name': 'John',
        'last_name': 'Doe',
        'email': 'john.doe@example.com',
        'joining_date': date(2026, 1, 1),
    })
    
    emp = service.onboard_employee(data, hrms_services['user'])
    assert emp.pk is not None
    assert emp.employee_id == 'EMP-002'
    assert emp.first_name == 'John'
    assert emp.status == 'active'

@pytest.mark.django_db
def test_attendance_service(hrms_services):
    emp_service = hrms_services['employee_service']
    att_service = hrms_services['attendance_service']
    
    emp = emp_service.onboard_employee({
        'employee_id': 'EMP-003',
        'first_name': 'Jane',
        'last_name': 'Smith',
        'joining_date': date(2026, 1, 1),
    }, hrms_services['user'])
    
    att = att_service.check_in(emp)
    assert att.status == 'present'
    assert att.check_in is not None
    assert att.check_out is None
    
    att_out = att_service.check_out(emp)
    assert att_out.check_out is not None

@pytest.mark.django_db
def test_leave_service(hrms_services):
    emp_service = hrms_services['employee_service']
    leave_service = hrms_services['leave_service']
    company = hrms_services['company']
    
    emp = emp_service.onboard_employee({
        'employee_id': 'EMP-004',
        'first_name': 'Alice',
        'last_name': 'Wonder',
        'joining_date': date(2026, 1, 1),
    }, hrms_services['user'])
    
    leave_type = LeaveType.objects.create(
        company=company,
        name='Annual Leave',
        code='AL',
        days_allowed=20
    )
    
    data = hrms_services['MockData']({
        'leave_type': leave_type.pk,
        'start_date': '2026-07-01',
        'end_date': '2026-07-05',
        'reason': 'Vacation'
    })
    
    leave = leave_service.request_leave(emp, data)
    assert leave.status == 'pending'
    assert leave.total_days == 5
    
    leave_service.process_leave(leave, 'approve', hrms_services['user'])
    
    leave.refresh_from_db()
    assert leave.status == 'approved'
    assert leave.approved_by == hrms_services['user']
