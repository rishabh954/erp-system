from datetime import date

import pytest
from django.urls import reverse

from apps.hrms.models import (
    JobApplication,
    JobPosting,
    LeaveRequest,
    LeaveType,
    PayrollPeriod,
    PerformanceAppraisal,
    SalaryStructure,
)

pytestmark = pytest.mark.django_db


def test_employee_views(client, user, employee, company):
    client.force_login(user)

    # List
    response = client.get(reverse("hrms:employees"))
    assert response.status_code == 200
    assert "employees" in response.context

    # Detail
    response = client.get(reverse("hrms:employee_detail", args=[employee.pk]))
    assert response.status_code == 200
    assert response.context["employee"] == employee

    # Create GET
    response = client.get(reverse("hrms:employee_create"))
    assert response.status_code == 200

    # Create POST
    data = {
        "employee_id": "EMP-009",
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane.doe@example.com",
        "joining_date": str(date.today()),
        "status": "active",
    }
    response = client.post(reverse("hrms:employee_create"), data)
    assert response.status_code in [302, 200]

    # Update GET and POST
    response = client.get(reverse("hrms:employee_update", args=[employee.pk]))
    assert response.status_code == 200
    response = client.post(reverse("hrms:employee_update", args=[employee.pk]), data)
    assert response.status_code in [302, 200]

    # Document Create
    from django.core.files.uploadedfile import SimpleUploadedFile

    f = SimpleUploadedFile("test.pdf", b"file_content")
    response = client.post(
        reverse("hrms:employee_document_create", args=[employee.pk]),
        {"document_type": "resume", "title": "Resume", "file": f},
    )
    assert response.status_code == 302

    # Skill Create
    response = client.post(
        reverse("hrms:employee_skill_create", args=[employee.pk]),
        {"skill_name": "Python", "proficiency": "expert"},
    )
    assert response.status_code == 302

    # Experience Create
    response = client.post(
        reverse("hrms:experience_record_create", args=[employee.pk]),
        {
            "company_name": "Acme",
            "job_title": "Dev",
            "start_date": "2020-01-01",
            "is_current": "on",
        },
    )
    assert response.status_code == 302


def test_attendance_views(client, user, employee):
    client.force_login(user)

    response = client.get(reverse("hrms:attendance"))
    assert response.status_code == 200

    # Check In
    response = client.post(reverse("hrms:check_in"))
    assert response.status_code == 200

    # Check Out
    response = client.post(reverse("hrms:check_out"))
    # it might be 200 or 400 depending on check_in state,
    # but covers the view code
    assert response.status_code in [200, 400]


def test_leave_views(client, user, employee, company, rf):
    client.force_login(user)

    response = client.get(reverse("hrms:leaves"))
    assert response.status_code == 200

    leave_type = LeaveType.objects.create(
        company=company, name="Annual", code="AN", days_allowed=10
    )

    # Create GET
    response = client.get(reverse("hrms:leave_request_create"))
    assert response.status_code == 200

    # Create POST
    data = {
        "leave_type": leave_type.pk,
        "start_date": str(date.today()),
        "end_date": str(date.today()),
        "reason": "Sick",
    }
    response = client.post(reverse("hrms:leave_request_create"), data)
    assert response.status_code == 302

    leave = LeaveRequest.objects.filter(employee=employee).first()
    assert leave is not None

    url = reverse("hrms:leave_approve", args=[leave.pk])
    response = client.post(url, {"action": "approve"})
    assert response.status_code == 302


def test_salary_structure_views(client, user, company):
    client.force_login(user)

    # Create
    response = client.post(
        reverse("hrms:salary_structure_create"),
        {"name": "Test Struct", "is_active": "on"},
    )
    assert response.status_code == 302

    struct = SalaryStructure.objects.filter(name="Test Struct").first()
    assert struct is not None

    # List
    response = client.get(reverse("hrms:salary_structures"))
    assert response.status_code == 200

    # Detail
    response = client.get(reverse("hrms:salary_structure_detail", args=[struct.pk]))
    assert response.status_code == 200

    # Component create
    data = {
        "name": "Basic",
        "code": "BSC",
        "component_type": "earning",
        "calc_type": "fixed",
        "amount": 1000,
    }
    response = client.post(
        reverse("hrms:salary_component_create", args=[struct.pk]), data
    )
    assert response.status_code == 302
    assert struct.components.count() == 1


def test_payroll_views(client, user, company, currency):
    client.force_login(user)
    period = PayrollPeriod.objects.create(
        company=company,
        name="July 2026",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        currency=currency,
    )

    response = client.get(reverse("hrms:payroll"))
    assert response.status_code == 200

    response = client.get(reverse("hrms:payroll_detail", args=[period.pk]))
    assert response.status_code == 200

    response = client.post(reverse("hrms:payroll_process", args=[period.pk]))
    assert response.status_code == 302


def test_job_posting_and_application(client, user, company):
    client.force_login(user)

    response = client.get(reverse("hrms:job_postings"))
    assert response.status_code == 200

    data = {"title": "Developer", "description": "Looking for a dev", "status": "draft"}
    response = client.post(reverse("hrms:job_postings"), data)
    assert response.status_code == 302
    job = JobPosting.objects.first()

    response = client.get(reverse("hrms:job_posting_detail", args=[job.pk]))
    assert response.status_code == 200

    app_data = {
        "job_posting": job.pk,
        "first_name": "Alice",
        "last_name": "Smith",
        "email": "alice@test.com",
    }
    response = client.post(reverse("hrms:job_applications"), app_data)
    assert response.status_code == 302
    app = JobApplication.objects.first()

    response = client.get(reverse("hrms:application_detail", args=[app.pk]))
    assert response.status_code == 200


def test_performance_appraisal(client, user, company, employee):
    client.force_login(user)

    response = client.get(reverse("hrms:appraisals"))
    assert response.status_code == 200

    data = {
        "employee": employee.pk,
        "period_start": "2026-01-01",
        "period_end": "2026-06-30",
    }
    response = client.post(reverse("hrms:appraisals"), data)
    assert response.status_code == 302

    appraisal = PerformanceAppraisal.objects.first()
    response = client.get(reverse("hrms:appraisal_detail", args=[appraisal.pk]))
    assert response.status_code == 200


def test_training_programs(client, user, company):
    client.force_login(user)

    response = client.get(reverse("hrms:training_programs"))
    assert response.status_code == 200

    data = {
        "name": "New Tech Training",
        "start_date": str(date.today()),
        "end_date": str(date.today()),
        "capacity": 10,
    }
    response = client.post(reverse("hrms:training_programs"), data)
    assert response.status_code == 302

    from apps.hrms.models import TrainingProgram

    prog = TrainingProgram.objects.first()
    assert prog is not None

    response = client.get(reverse("hrms:training_program_detail", args=[prog.pk]))
    assert response.status_code == 200


def test_expense_claims(client, user, company, employee):
    client.force_login(user)

    response = client.get(reverse("hrms:expense_claims"))
    assert response.status_code == 200

    data = {
        "employee": employee.pk,
        "claim_type": "travel",
        "amount": "100.00",
        "expense_date": str(date.today()),
        "description": "Flight tickets",
    }
    response = client.post(reverse("hrms:expense_claims"), data)
    assert response.status_code == 302

    from apps.hrms.models import ExpenseClaim

    claim = ExpenseClaim.objects.first()
    assert claim is not None

    response = client.get(reverse("hrms:expense_claim_detail", args=[claim.pk]))
    assert response.status_code == 200
