import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.authentication.api.serializers import UserUpdateSerializer
from apps.authentication.forms import ProfileUpdateForm, RegisterForm
from apps.authentication.models import User


@pytest.mark.django_db
def test_registration_rejects_whitespace_names_and_weak_password():
    form = RegisterForm(
        data={
            "first_name": " ",
            "last_name": "User",
            "email": "new-user@example.com",
            "phone": "",
            "password1": "12345678",
            "password2": "12345678",
            "tenant_slug": "",
        }
    )

    assert not form.is_valid()
    assert "first_name" in form.errors
    assert "password1" in form.errors
    assert not User.objects.filter(email="new-user@example.com").exists()


@pytest.mark.django_db
def test_profile_form_rejects_invalid_timezone_and_whitespace_names(user):
    form = ProfileUpdateForm(
        instance=user,
        data={
            "first_name": " ",
            "last_name": "User",
            "phone": "",
            "language": user.language,
            "timezone": "Not/A_Timezone",
            "theme": user.theme,
            "date_format": user.date_format,
        },
    )

    assert not form.is_valid()
    assert "first_name" in form.errors
    assert "timezone" in form.errors


@pytest.mark.django_db
def test_user_update_api_rejects_invalid_timezone(user):
    serializer = UserUpdateSerializer(
        user,
        data={"timezone": "Not/A_Timezone"},
        partial=True,
    )

    assert not serializer.is_valid()
    assert "timezone" in serializer.errors


@pytest.mark.django_db
def test_user_update_api_rejects_whitespace_only_name(user):
    serializer = UserUpdateSerializer(
        user,
        data={"first_name": "   "},
        partial=True,
    )

    assert not serializer.is_valid()
    assert "first_name" in serializer.errors


@pytest.mark.parametrize("code", ["12345", "1234567", "12a456", 123456])
def test_two_factor_api_rejects_malformed_codes(code):
    response = APIClient().post(
        reverse("api_auth:2fa-verify"),
        {"partial_token": "unknown", "code": code},
        format="json",
    )

    assert response.status_code == 400
    assert "exactly 6 digits" in response.data["error"]
