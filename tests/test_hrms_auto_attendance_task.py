from datetime import date

import pytest

from apps.company.models import Company
from apps.hrms.models import Attendance, Employee


def make_employee(company, employee_id, status=Employee.Status.ACTIVE):
    return Employee.objects.create(
        company=company,
        employee_id=employee_id,
        first_name=employee_id,
        last_name="Employee",
        joining_date=date.today(),
        status=status,
    )


@pytest.mark.django_db
def test_auto_mark_attendance_is_tenant_scoped_and_idempotent():
    from apps.hrms.tasks import auto_mark_attendance

    company_a = Company.objects.create(name="Attendance A")
    company_b = Company.objects.create(name="Attendance B")
    employee_a = make_employee(company_a, "A-1")
    employee_b = make_employee(company_b, "B-1")
    inactive = make_employee(company_a, "A-2", status=Employee.Status.INACTIVE)
    today = date.today()
    existing = Attendance.objects.create(
        company=company_a,
        employee=employee_a,
        date=today,
        status=Attendance.Status.PRESENT,
    )

    auto_mark_attendance.run()
    auto_mark_attendance.run()

    existing.refresh_from_db()
    assert existing.status == Attendance.Status.PRESENT
    assert Attendance.objects.filter(company=company_a, employee=employee_a, date=today).count() == 1
    assert Attendance.objects.filter(company=company_b, employee=employee_b, date=today).count() == 1
    assert Attendance.objects.get(company=company_b, employee=employee_b, date=today).status == Attendance.Status.ABSENT
    assert not Attendance.objects.filter(company=company_a, employee=inactive, date=today).exists()
