import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from django.urls import reverse

from apps.company.models import Company
from apps.hrms.models import Attendance, BiometricDevice, BiometricLog, Employee


@pytest.fixture
def biometric_company(db):
    return Company.objects.create(name="Biometric Company")


@pytest.fixture
def employee_for_company(db, biometric_company):
    return Employee.objects.create(
        company=biometric_company,
        employee_id="EMP-1001",
        first_name="Jane",
        last_name="Doe",
        joining_date=datetime.now(timezone.utc).date(),
        department=None,
    )


@pytest.fixture
def other_company(db):
    return Company.objects.create(name="Other Company")


@pytest.fixture
def other_employee(db, other_company):
    return Employee.objects.create(
        company=other_company,
        employee_id="EMP-9999",
        first_name="Mallory",
        last_name="Other",
        joining_date=datetime.now(timezone.utc).date(),
    )


def _device_headers(device_id, raw_key):
    return {
        "HTTP_X_DEVICE_ID": device_id,
        "HTTP_X_DEVICE_KEY": raw_key,
    }


@pytest.mark.django_db
def test_biometric_missing_key_is_unauthorized(client, biometric_company):
    response = client.post(
        reverse("hrms:api_biometric_sync"),
        data={"logs": []},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_biometric_wrong_key_is_unauthorized(client, biometric_company):
    raw_key = "correct-house-key"
    device = BiometricDevice.objects.create(
        company=biometric_company,
        device_id="device-001",
        key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
    )

    response = client.post(
        reverse("hrms:api_biometric_sync"),
        data={"logs": [{"employee_id": "EMP-1001", "timestamp": "2025-01-01T08:00:00Z", "punch_type": "in"}]},
        content_type="application/json",
        **_device_headers(device.device_id, "wrong-key"),
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_biometric_inactive_device_is_unauthorized(client, biometric_company):
    raw_key = "inactive-key"
    device = BiometricDevice.objects.create(
        company=biometric_company,
        device_id="device-002",
        key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
        is_active=False,
    )

    response = client.post(
        reverse("hrms:api_biometric_sync"),
        data={"logs": []},
        content_type="application/json",
        **_device_headers(device.device_id, raw_key),
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_biometric_device_cannot_touch_other_company_employee(client, biometric_company, other_company, other_employee):
    raw_key = "tenant-key"
    device = BiometricDevice.objects.create(
        company=biometric_company,
        device_id="device-003",
        key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
    )

    response = client.post(
        reverse("hrms:api_biometric_sync"),
        data={"logs": [{"employee_id": other_employee.employee_id, "timestamp": "2025-01-01T08:00:00Z", "punch_type": "in"}]},
        content_type="application/json",
        **_device_headers(device.device_id, raw_key),
    )

    assert response.status_code == 200
    assert BiometricLog.objects.filter(employee=other_employee).count() == 0


@pytest.mark.django_db
def test_valid_biometric_punch_creates_attendance(client, biometric_company, employee_for_company):
    raw_key = "valid-key"
    device = BiometricDevice.objects.create(
        company=biometric_company,
        device_id="device-004",
        key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
    )

    payload = {
        "logs": [
            {
                "employee_id": employee_for_company.employee_id,
                "timestamp": "2025-01-01T08:15:00Z",
                "punch_type": "in",
            },
            {
                "employee_id": employee_for_company.employee_id,
                "timestamp": "2025-01-01T17:45:00Z",
                "punch_type": "out",
            },
        ]
    }

    response = client.post(
        reverse("hrms:api_biometric_sync"),
        data=payload,
        content_type="application/json",
        **_device_headers(device.device_id, raw_key),
    )

    assert response.status_code == 200
    assert response.json()["processed"] == 2
    attendance = Attendance.objects.get(employee=employee_for_company, company=biometric_company, date="2025-01-01")
    assert attendance.check_in is not None
    assert attendance.check_out is not None
    assert BiometricLog.objects.filter(employee=employee_for_company).count() == 2


@pytest.mark.django_db
def test_biometric_batch_size_is_limited(client, biometric_company):
    raw_key = "oversize-key"
    device = BiometricDevice.objects.create(
        company=biometric_company,
        device_id="device-005",
        key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
    )
    logs = [{"employee_id": "EMP-1001", "timestamp": "2025-01-01T08:00:00Z", "punch_type": "in"} for _ in range(501)]

    response = client.post(
        reverse("hrms:api_biometric_sync"),
        data={"logs": logs},
        content_type="application/json",
        **_device_headers(device.device_id, raw_key),
    )

    assert response.status_code == 400
