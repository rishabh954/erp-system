import csv
import io
import json

from celery import shared_task
from django.apps import apps
from django.core import serializers
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

SENSITIVE_MODEL_NAMES = {
    "apikey",
    "integration",
    "webhookendpoint",
    "user",
    "usersession",
    "session",
    "companysettings",
}
SENSITIVE_FIELD_PARTS = (
    "password",
    "secret",
    "token",
    "credential",
    "private_key",
    "api_key",
    "session",
    "totp",
)


def _safe_backup_fields(model):
    safe = []
    for field in model._meta.concrete_fields:
        if field.name == "company":
            safe.append(field.name)
            continue
        if field.is_relation:
            continue
        lowered = field.name.lower()
        if any(part in lowered for part in SENSITIVE_FIELD_PARTS):
            continue
        if field.__class__.__name__.lower().startswith("encrypted"):
            continue
        safe.append(field.name)
    return safe


def serialize_company_backup(company_id):
    """Serialize a tenant-only snapshot with sensitive fields removed."""
    from apps.company.models import Company

    output = []
    company = Company.objects.filter(pk=company_id).first()
    if company is None:
        raise Company.DoesNotExist

    safe_company_fields = _safe_backup_fields(Company)
    output.extend(
        json.loads(serializers.serialize("json", [company], fields=safe_company_fields))
    )

    for model in apps.get_models():
        if model is Company or model._meta.model_name in SENSITIVE_MODEL_NAMES:
            continue
        try:
            company_field = model._meta.get_field("company")
        except Exception:
            continue
        if not company_field.is_relation or company_field.related_model is not Company:
            continue
        fields = _safe_backup_fields(model)
        queryset = model._default_manager.filter(company_id=company_id).iterator()
        # Batch materialization bounds memory while preserving Django's serializer format.
        batch = []
        for obj in queryset:
            batch.append(obj)
            if len(batch) == 500:
                output.extend(json.loads(serializers.serialize("json", batch, fields=fields)))
                batch.clear()
        if batch:
            output.extend(json.loads(serializers.serialize("json", batch, fields=fields)))
    return json.dumps(output, ensure_ascii=False, separators=(",", ":"))


@shared_task
def generate_backup(record_id, company_id):
    from apps.administration.models import BackupRecord

    record = BackupRecord.objects.filter(pk=record_id, company_id=company_id).first()
    if record is None:
        return
    try:
        with transaction.atomic():
            BackupRecord.objects.filter(
                pk=record_id, company_id=company_id
            ).update(status=BackupRecord.Status.IN_PROGRESS)

        content = serialize_company_backup(company_id).encode("utf-8")
        name = f"backups/{company_id}/{record_id}.json"
        saved_name = default_storage.save(name, ContentFile(content))
        with transaction.atomic():
            record = BackupRecord.objects.select_for_update().get(
                pk=record_id, company_id=company_id
            )
            record.file_path = saved_name
            record.file_size = default_storage.size(saved_name)
            record.status = BackupRecord.Status.COMPLETED
            record.save(update_fields=["file_path", "file_size", "status"])
    except Exception as exc:
        with transaction.atomic():
            BackupRecord.objects.filter(pk=record_id, company_id=company_id).update(
                status=BackupRecord.Status.FAILED, notes=str(exc)[:2000]
            )


IMPORT_CONFIG = {
    "customers": ("apps.crm.models", "Customer", ("name", "email", "phone", "address_line1")),
    "vendors": ("apps.purchase.models", "Vendor", ("name", "email", "phone", "address_line1")),
    "products": ("apps.inventory.models", "Product", ("name", "sku", "description", "cost_price", "sale_price", "product_type")),
}
EXPORT_CONFIG = {
    "customers": ("apps.crm.models", "Customer", ("name", "email", "phone", "address_line1")),
    "vendors": ("apps.purchase.models", "Vendor", ("name", "email", "phone", "address_line1")),
    "products": ("apps.inventory.models", "Product", ("name", "sku", "description", "cost_price", "sale_price", "product_type")),
}
IMPORT_BATCH_SIZE = 200
MAX_IMPORT_ERRORS = 100


def _append_import_errors(existing, new_errors):
    current = json.loads(existing) if existing else []
    current.extend(new_errors)
    return json.dumps(current[:MAX_IMPORT_ERRORS])


@shared_task
def process_import_job(job_id, company_id):
    from apps.administration.models import ImportJob

    job = ImportJob.objects.filter(pk=job_id, company_id=company_id).first()
    if not job:
        return
    job.status = ImportJob.Status.RUNNING
    job.started_at = timezone.now()
    job.error_log = ""
    job.total_rows = job.imported_rows = job.failed_rows = 0
    job.save(update_fields=[
        "status", "started_at", "error_log", "total_rows", "imported_rows", "failed_rows"
    ])
    try:
        config = IMPORT_CONFIG.get(job.module)
        if not config:
            raise ValueError("Unsupported import module.")
        module_path, model_name, allowed_fields = config
        model = getattr(__import__(module_path, fromlist=[model_name]), model_name)
        job.file.open("rb")
        try:
            raw = job.file.read()
        finally:
            job.file.close()
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or any(not name for name in reader.fieldnames):
            raise ValueError("CSV must contain a valid header row.")
        mapping = job.column_mapping or {
            field: field for field in allowed_fields if field in reader.fieldnames
        }
        if not isinstance(mapping, dict) or any(
            destination not in allowed_fields or source not in reader.fieldnames
            for destination, source in mapping.items()
        ):
            raise ValueError("Column mapping must use allowed fields and existing CSV headers.")
        required = {"name"} | ({"sku"} if job.module == "products" else set())
        if not required.issubset(mapping):
            raise ValueError(f"Column mapping must include: {', '.join(sorted(required))}.")

        batch = []
        errors = []
        batch_errors = []
        row_number = 1
        for row_number, row in enumerate(reader, start=2):
            job.total_rows += 1
            try:
                if None in row:
                    raise ValueError("row has more values than the header")
                values = {
                    destination: (row.get(source) or "").strip()
                    for destination, source in mapping.items()
                    if (row.get(source) or "").strip()
                }
                if any(not values.get(field) for field in required):
                    raise ValueError(f"required value missing: {', '.join(sorted(required))}")
                obj = model(company_id=company_id, **values)
                obj.full_clean()
                batch.append(obj)
            except Exception as exc:
                job.failed_rows += 1
                errors.append({"row": row_number, "message": str(exc)[:500]})
            if len(batch) + len(errors) >= IMPORT_BATCH_SIZE:
                batch_errors = errors
                with transaction.atomic():
                    model.objects.bulk_create(batch)
                    job.imported_rows += len(batch)
                    job.error_log = _append_import_errors(job.error_log, batch_errors)
                    job.save(update_fields=["total_rows", "imported_rows", "failed_rows", "error_log"])
                batch, errors = [], []
        with transaction.atomic():
            if batch:
                model.objects.bulk_create(batch)
                job.imported_rows += len(batch)
            job.error_log = _append_import_errors(job.error_log, errors)
            job.save(update_fields=["total_rows", "imported_rows", "failed_rows", "error_log"])
        job.status = ImportJob.Status.DONE
    except Exception as exc:
        job.status = ImportJob.Status.FAILED
        job.error_log = _append_import_errors(
            job.error_log, [{"row": 1, "message": str(exc)[:500]}]
        )
    finally:
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "error_log", "completed_at", "total_rows", "imported_rows", "failed_rows"])


def _safe_csv_cell(value):
    value = "" if value is None else str(value)
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


@shared_task
def process_export_job(job_id, company_id):
    from apps.administration.models import ExportJob

    job = ExportJob.objects.filter(pk=job_id, company_id=company_id).first()
    if not job:
        return
    job.status = ExportJob.Status.RUNNING
    job.save(update_fields=["status"])
    try:
        if job.format != "csv" or job.module not in EXPORT_CONFIG:
            raise ValueError("CSV export is available for customers, vendors and products.")
        module_path, model_name, fields = EXPORT_CONFIG[job.module]
        model = getattr(__import__(module_path, fromlist=[model_name]), model_name)
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(fields)
        rows = model.objects.filter(company_id=company_id).values_list(*fields).iterator()
        for row in rows:
            writer.writerow([_safe_csv_cell(value) for value in row])
        with transaction.atomic():
            job = ExportJob.objects.select_for_update().get(pk=job_id, company_id=company_id)
            job.output_file.save(
                f"{job.module}-{job.pk}.csv",
                ContentFile(buffer.getvalue().encode("utf-8")),
                save=False,
            )
            job.status = ExportJob.Status.DONE
            job.completed_at = timezone.now()
            job.save(update_fields=["output_file", "status", "completed_at"])
    except Exception:
        ExportJob.objects.filter(pk=job_id, company_id=company_id).update(
            status=ExportJob.Status.FAILED
        )


def validate_public_webhook_url(url):
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Webhook URL must use HTTP or HTTPS and include a hostname.")
    if parsed.username or parsed.password:
        raise ValueError("Webhook URLs cannot include credentials.")
    try:
        results = socket.getaddrinfo(
            parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ValueError("Webhook hostname could not be resolved.") from exc
    addresses = {entry[4][0].split("%", 1)[0] for entry in results}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Webhook targets must resolve only to public IP addresses.")
    return parsed


def dispatch_webhook_event(company_id, event, payload):
    from apps.administration.models import WebhookEndpoint

    endpoints = WebhookEndpoint.objects.filter(
        company_id=company_id, status=WebhookEndpoint.Status.ACTIVE
    ).only("pk", "company_id", "events")
    for endpoint in endpoints.iterator():
        if "*" in endpoint.events or event in endpoint.events:
            deliver_webhook.delay(
                str(endpoint.pk), str(company_id), event, payload
            )


@shared_task(bind=True, max_retries=5)
def deliver_webhook(self, endpoint_id, company_id, event, payload):
    import hashlib
    import hmac

    import requests
    from django.utils import timezone

    from apps.administration.models import WebhookDelivery, WebhookEndpoint

    endpoint = WebhookEndpoint.objects.filter(
        pk=endpoint_id, company_id=company_id, status=WebhookEndpoint.Status.ACTIVE
    ).first()
    if endpoint is None or ("*" not in endpoint.events and event not in endpoint.events):
        return

    delivery = WebhookDelivery.objects.create(
        company_id=company_id,
        endpoint=endpoint,
        event=event,
        attempt_number=self.request.retries + 1,
    )
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    try:
        validate_public_webhook_url(endpoint.url)
        signature = hmac.new(
            endpoint.secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        response = requests.post(
            endpoint.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": f"sha256={signature}",
                "X-Webhook-Event": event,
            },
            timeout=5,
            allow_redirects=False,
        )
        delivery.status_code = response.status_code
        if 200 <= response.status_code < 300:
            delivery.status = WebhookDelivery.Status.SUCCEEDED
            delivery.completed_at = timezone.now()
            delivery.save(update_fields=["status_code", "status", "completed_at"])
            return
        raise RuntimeError(f"Webhook returned HTTP {response.status_code}.")
    except Exception as exc:
        delivery.status = WebhookDelivery.Status.FAILED
        delivery.error = str(exc)[:2000]
        delivery.completed_at = timezone.now()
        delivery.save(update_fields=["status_code", "status", "error", "completed_at"])
        if self.request.retries < self.max_retries:
            raise self.retry(
                exc=exc, countdown=min(2 ** self.request.retries, 60)
            ) from exc
        raise
