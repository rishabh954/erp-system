from unittest.mock import patch

import pytest
from django.test import Client


@pytest.mark.django_db
def test_readiness_succeeds_when_database_and_cache_are_available():
    response = Client().get("/health/ready/")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "components": {"database": "up", "redis": "up"},
    }


@pytest.mark.django_db
def test_readiness_fails_safely_without_database_or_cache(caplog):
    with (
        patch("apps.api.health.connections") as connections,
        patch("apps.api.health.cache") as cache,
    ):
        cursor = connections.__getitem__.return_value.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = RuntimeError("db-password-secret")
        cache.set.side_effect = RuntimeError("redis-password-secret")
        response = Client().get("/health/ready/")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "components": {"database": "down", "redis": "down"},
    }
    assert "db-password-secret" not in response.content.decode()
    assert "redis-password-secret" not in response.content.decode()
    assert "db-password-secret" not in caplog.text
    assert "redis-password-secret" not in caplog.text


def test_liveness_does_not_depend_on_external_services():
    response = Client().get("/health/live/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
