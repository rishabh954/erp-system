import pytest
from django.core.exceptions import ImproperlyConfigured

from config import settings


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_testing_flag_accepts_only_explicit_truthy_values(value):
    assert settings._env_flag_enabled(value)


@pytest.mark.parametrize("value", [None, "", "0", "false", "no", "off", "random"])
def test_testing_flag_does_not_treat_arbitrary_nonempty_values_as_true(value):
    assert not settings._env_flag_enabled(value)


def test_production_hosts_must_be_explicit():
    with pytest.raises(ImproperlyConfigured, match="ALLOWED_HOSTS must be explicitly set"):
        settings._validate_production_hosts(None, ["localhost", "127.0.0.1"])

    settings._validate_production_hosts("erp.example.com", ["erp.example.com"])


@pytest.mark.parametrize("password", ["", "redispass", "redis", "password", "secret", "changeme"])
def test_production_redis_password_rejects_missing_or_weak_values(password):
    with pytest.raises(ImproperlyConfigured, match="REDIS_PASSWORD must be set"):
        settings._validate_production_redis_password(password)


def test_production_redis_password_accepts_non_default_value():
    settings._validate_production_redis_password("long-unique-deployment-secret")
