import hashlib
import hmac
from unittest.mock import Mock, patch

import pytest
import requests
from celery.exceptions import Retry

from apps.administration.models import WebhookDelivery, WebhookEndpoint
from apps.administration.tasks import (
    deliver_webhook,
    dispatch_webhook_event,
    validate_public_webhook_url,
)
from core.factories import CompanyFactory

pytestmark = pytest.mark.django_db


def make_endpoint(company, events):
    return WebhookEndpoint.objects.create(
        company=company,
        name="Events",
        url="https://hooks.example.test/callback",
        secret="webhook-secret",
        events=events,
        status=WebhookEndpoint.Status.ACTIVE,
    )


@patch("socket.getaddrinfo")
@patch("requests.post")
def test_webhook_delivery_is_signed_and_records_success(post, getaddrinfo, company):
    getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 443))]
    post.return_value = Mock(status_code=202)
    endpoint = make_endpoint(company, ["invoice.created"])
    payload = {"id": "inv-1"}
    deliver_webhook.run(str(endpoint.pk), str(company.pk), "invoice.created", payload)
    body = b'{"id":"inv-1"}'
    signature = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
    post.assert_called_once_with(
        endpoint.url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-Event": "invoice.created",
        },
        timeout=5,
        allow_redirects=False,
    )
    delivery = WebhookDelivery.objects.get(endpoint=endpoint)
    assert delivery.status == WebhookDelivery.Status.SUCCEEDED
    assert delivery.status_code == 202


@pytest.mark.django_db
def test_dispatch_only_queues_same_company_subscribed_endpoints(company):
    other = CompanyFactory()
    matching = make_endpoint(company, ["invoice.created"])
    make_endpoint(company, ["invoice.paid"])
    make_endpoint(other, ["invoice.created"])
    with patch("apps.administration.tasks.deliver_webhook.delay") as queue:
        dispatch_webhook_event(str(company.pk), "invoice.created", {"id": "1"})
    queue.assert_called_once_with(
        str(matching.pk), str(company.pk), "invoice.created", {"id": "1"}
    )


@pytest.mark.django_db
def test_webhook_ssrf_private_targets_are_rejected():
    with patch(
        "socket.getaddrinfo",
        return_value=[(None, None, None, None, ("127.0.0.1", 443))],
    ):
        with pytest.raises(ValueError, match="public IP"):
            validate_public_webhook_url("https://localhost/hook")


@pytest.mark.django_db
@patch("socket.getaddrinfo")
@patch("requests.post")
def test_webhook_failure_is_logged_and_retried(post, getaddrinfo, company):
    getaddrinfo.return_value = [(None, None, None, None, ("8.8.8.8", 443))]
    post.side_effect = requests.Timeout("timeout")
    endpoint = make_endpoint(company, ["invoice.created"])
    with patch.object(deliver_webhook, "retry", side_effect=Retry()) as retry:
        with pytest.raises(Retry):
            deliver_webhook.run(str(endpoint.pk), str(company.pk), "invoice.created", {"id": "1"})
        retry.assert_called_once()
    attempt = WebhookDelivery.objects.get(endpoint=endpoint)
    assert attempt.status == WebhookDelivery.Status.FAILED
    assert "timeout" in attempt.error
    assert attempt.attempt_number == 1
