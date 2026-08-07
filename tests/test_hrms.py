"""
Tests for HRMS Services in ERP system.
"""
import pytest
from datetime import date
from decimal import Decimal
from django.utils import timezone

from apps.hrms.models import Employee, Attendance, LeaveType, LeaveBalance, LeaveRequest, SalaryStructure, SalaryComponent, EmployeeSalary, PayrollPeriod, Payslip
from apps.hrms.services import EmployeeService, AttendanceService, LeaveService, PayrollService
from apps.company.models import Department
from apps.authentication.models import User

@pytest.fixture
def hrms_data(company, user):
    dept = Department.objects.create(company=company, name="Engineering", code="ENG")
    
    leave_type = LeaveType.objects.create(company=company, name="Annual Leave", code="AL", days_allowed=20)
    
    return {
        "dept": dept,
        "leave_type": leave_type,
    }

@pytest.mark.django_db
class TestHRMSServices:
    def test_employee_creation_with_department(self, company, hrms_data, user):
        """Test: Employee creation with department"""
        service = EmployeeService(company=company, user=user)
        emp = service.onboard_employee({
            "employee_id": "EMP002",
            "first_name": "Jane",
            "last_name": "Doe",
            "department": hrms_data["dept"].id,
            "joining_date": date.today(),
            "status": "active"
        }, user)
        
        assert emp.first_name == "Jane"
        assert emp.department == hrms_data["dept"]
        assert Employee.objects.filter(employee_id="EMP002").exists()

    def test_leave_request_workflow(self, company, employee, hrms_data, user):
        """Test: leave request workflow (apply -> approve -> balance decreases)"""
        LeaveBalance.objects.create(
            employee=employee, leave_type=hrms_data["leave_type"], year=date.today().year, allocated=Decimal("20.0"), pending=Decimal("0.0"), used=Decimal("0.0")
        )
        
        service = LeaveService(company=company, user=user)
        leave = service.request_leave(employee, {
            "leave_type": hrms_data["leave_type"].id,
            "start_date": date.today().strftime("%Y-%m-%d"),
            "end_date": date.today().strftime("%Y-%m-%d"),
            "reason": "Vacation"
        })
        assert leave.status == "pending"
        
        service.process_leave(leave, "approve", user)
        assert leave.status == "approved"
        
        bal = LeaveBalance.objects.get(employee=employee, leave_type=hrms_data["leave_type"], year=date.today().year)
        assert bal.used == Decimal("1.0")

    def test_payroll_calculation_net_pay(self, company, employee, currency):
        """Test: payroll calculation produces correct net pay (gross - deductions)"""
        struct = SalaryStructure.objects.create(company=company, name="Standard")
        SalaryComponent.objects.create(
            company=company, salary_structure=struct, name="Basic", code="BASIC", component_type="earning", calc_type="fixed", amount=Decimal("5000.00")
        )
        SalaryComponent.objects.create(
            company=company, salary_structure=struct, name="Tax", code="TAX", component_type="deduction", calc_type="fixed", amount=Decimal("500.00")
        )
        
        EmployeeSalary.objects.create(
            company=company, employee=employee, salary_structure=struct, basic_salary=Decimal("5000.00"), effective_from=date.today(), currency=currency
        )
        
        period = PayrollPeriod.objects.create(
            company=company, name="Jan 2023", period_start=date(2023, 1, 1), period_end=date(2023, 1, 31)
        )
        
        service = PayrollService(company=company)
        service.process_payroll(period)
        
        payslip = Payslip.objects.get(payroll_period=period, employee=employee)
        assert payslip.gross_salary == Decimal("5000.00")
        assert payslip.total_deductions == Decimal("500.00")
        assert payslip.net_salary == Decimal("4500.00")

    def test_attendance_mark_present_absent(self, company, employee):
        """Test: attendance mark present"""
        service = AttendanceService(company=company)
        att = service.check_in(employee)
        assert att.status == "present"
        assert att.check_in is not None
        
        att_out = service.check_out(employee)
        assert att_out.check_out is not None
        assert att_out.work_hours >= 0
