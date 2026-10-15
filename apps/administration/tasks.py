import csv
import io
import json
from collections import deque

from celery import shared_task
from django.apps import apps
from django.core import serializers
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.conf import settings
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
SENSITIVE_FIELD_CLASS_PARTS = (
    "encrypted", "password", "secret", "token", "credential", "apikey", "privatekey", "totp",
)


def _backup_storage():
    return FileSystemStorage(location=settings.PRIVATE_BACKUP_ROOT)


def _safe_backup_fields(model):
    safe = []
    for field in model._meta.concrete_fields:
        lowered = field.name.lower()
        field_class = field.__class__.__name__.lower()
        if any(part in lowered for part in SENSITIVE_FIELD_PARTS):
            continue
        if any(part in field_class for part in SENSITIVE_FIELD_CLASS_PARTS):
            continue
        safe.append(field.name)
    return safe


def _backup_company_path(model, company_model, max_depth=5):
    """Return the shortest FK path from model to a company-owned model."""
    queue = deque([(model, "", frozenset({model}))])
    while queue:
        current, prefix, visited = queue.popleft()
        try:
            company_field = current._meta.get_field("company")
        except Exception:
            company_field = None
        if company_field and company_field.is_relation and company_field.related_model is company_model:
            return f"{prefix}__company_id" if prefix else "company_id"
        depth = prefix.count("__") + (1 if prefix else 0)
        if depth >= max_depth:
            continue
        for field in current._meta.concrete_fields:
            if not field.is_relation or not field.many_to_one or field.related_model in visited:
                continue
            next_prefix = f"{prefix}__{field.name}" if prefix else field.name
            queue.append((field.related_model, next_prefix, visited | {field.related_model}))
    return None


def serialize_company_backup(company_id):
    """Serialize a tenant-only snapshot with sensitive fields removed."""
    from apps.company.models import Company

    objects = []
    model_counts = {}
    excluded = []
    unresolved = []
    company = Company.objects.filter(pk=company_id).first()
    if company is None:
        raise Company.DoesNotExist

    safe_company_fields = _safe_backup_fields(Company)
    company_object = json.loads(serializers.serialize("json", [company], fields=safe_company_fields))
    objects.extend(company_object)
    model_counts[Company._meta.label_lower] = len(company_object)

    for model in apps.get_models():
        if model is Company:
            continue
        if model._meta.model_name.lower() in SENSITIVE_MODEL_NAMES:
            excluded.append({"model": model._meta.label_lower, "reason": "sensitive model"})
            continue
        company_path = _backup_company_path(model, Company)
        if company_path is None:
            unresolved.append(model._meta.label_lower)
            continue
        fields = _safe_backup_fields(model)
        queryset = model._default_manager.filter(**{company_path: company_id}).iterator()
        # Batch materialization bounds memory while preserving Django's serializer format.
        batch = []
        for obj in queryset:
            batch.append(obj)
            if len(batch) == 500:
                rows = json.loads(serializers.serialize("json", batch, fields=fields))
                objects.extend(rows)
                model_counts[model._meta.label_lower] = model_counts.get(model._meta.label_lower, 0) + len(rows)
                batch.clear()
        if batch:
            rows = json.loads(serializers.serialize("json", batch, fields=fields))
            objects.extend(rows)
            model_counts[model._meta.label_lower] = model_counts.get(model._meta.label_lower, 0) + len(rows)
        if model._meta.label_lower not in model_counts:
            model_counts[model._meta.label_lower] = 0
    manifest = {
        "company_id": str(company.pk),
        "created_at": timezone.now().isoformat(),
        "schema_version": 1,
        "django_version": __import__("django").get_version(),
        "erp_version": settings.SPECTACULAR_SETTINGS.get("VERSION", "unknown"),
        "apps": sorted({config.label for config in apps.get_app_configs()}),
        "restore_prerequisites": "Create this company and any referenced user records first, then load the objects array.",
        "model_counts": model_counts,
        "excluded_models": excluded,
        "unresolved_models": sorted(unresolved),
    }
    return json.dumps({"manifest": manifest, "objects": objects}, ensure_ascii=False, separators=(",", ":"))


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
        storage = _backup_storage()
        saved_name = storage.save(name, ContentFile(content))
        with transaction.atomic():
            record = BackupRecord.objects.select_for_update().get(
                pk=record_id, company_id=company_id
            )
            record.file_path = saved_name
            record.file_size = storage.size(saved_name)
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
def _append_import_errors(existing, new_errors):
    current = json.loads(existing) if existing else []
    current.extend(new_errors)
    return json.dumps(current)


def _import_unique_keys(model, module):
    if module == "products":
        return [("sku",)]
    keys = []
    for constraint in model._meta.constraints:
        fields = tuple(getattr(constraint, "fields", ()) or ())
        if fields and "company" in fields:
            keys.append(tuple(field for field in fields if field != "company"))
    for fields in model._meta.unique_together:
        fields = tuple(fields)
        if "company" in fields:
            keys.append(tuple(field for field in fields if field != "company"))
    return [key for key in keys if key]


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
        seen = {key: {} for key in _import_unique_keys(model, job.module)}
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
                duplicate = None
                for key_fields in seen:
                    if any(not getattr(obj, field, None) for field in key_fields):
                        continue
                    key = tuple(getattr(obj, field) for field in key_fields)
                    label = key_fields[0]
                    value = getattr(obj, label)
                    existing = model.objects.filter(company_id=company_id)
                    for field, item in zip(key_fields, key):
                        existing = existing.filter(**{field: item})
                    if existing.exists():
                        duplicate = f"duplicate {label} '{value}' already exists for this company"
                        break
                    if key in seen[key_fields]:
                        duplicate = f"duplicate {label} '{value}' also on row {seen[key_fields][key]}"
                        break
                    seen[key_fields][key] = row_number
                if duplicate:
                    raise ValueError(duplicate)
                obj.full_clean()
                batch.append((row_number, obj))
            except Exception as exc:
                job.failed_rows += 1
                errors.append({"row": row_number, "message": str(exc)[:500]})
            if len(batch) + len(errors) >= IMPORT_BATCH_SIZE:
                with transaction.atomic():
                    for batch_row, obj in batch:
                        try:
                            with transaction.atomic():
                                obj.save(force_insert=True)
                            job.imported_rows += 1
                        except Exception as exc:
                            job.failed_rows += 1
                            errors.append({"row": batch_row, "message": str(exc)[:500]})
                    job.error_log = _append_import_errors(job.error_log, errors)
                    job.save(update_fields=["total_rows", "imported_rows", "failed_rows", "error_log"])
                batch, errors = [], []
        with transaction.atomic():
            for batch_row, obj in batch:
                try:
                    with transaction.atomic():
                        obj.save(force_insert=True)
                    job.imported_rows += 1
                except Exception as exc:
                    job.failed_rows += 1
                    errors.append({"row": batch_row, "message": str(exc)[:500]})
            job.error_log = _append_import_errors(job.error_log, errors)
            job.save(update_fields=["total_rows", "imported_rows", "failed_rows", "error_log"])
        job.status = ImportJob.Status.DONE
    except Exception as exc:
        job.status = ImportJob.Status.FAILED
        job.error_log = _append_import_errors(
            job.error_log, [{"row": 1, "message": str(exc)[:500]}]
        )
    finally:
        recorded_errors = json.loads(job.error_log or "[]")
        job.failed_rows = len(recorded_errors)
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


def _parse_and_resolve_public_webhook_url(url):
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
    addresses = tuple(dict.fromkeys(entry[4][0].split("%", 1)[0] for entry in results))
    if not addresses or any(
        (parsed_ip := ipaddress.ip_address(address)).version == 6
        and parsed_ip.ipv4_mapped is not None
        or not ipaddress.ip_address(address).is_global
        for address in addresses
    ):
        raise ValueError("Webhook targets must resolve only to public IP addresses.")
    return parsed, addresses


def validate_public_webhook_url(url):
    return _parse_and_resolve_public_webhook_url(url)[0]


def _resolve_validated_webhook_url(url):
    """Resolve and validate once so delivery uses the exact address checked here."""
    return _parse_and_resolve_public_webhook_url(url)


def _pinned_webhook_post(parsed, address, body, headers, timeout=5):
    import http.client
    import socket
    import ssl

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    host_header = parsed.hostname if parsed.port is None else f"{parsed.hostname}:{parsed.port}"

    if parsed.scheme == "https":
        class PinnedHTTPSConnection(http.client.HTTPSConnection):
            def connect(self):
                raw = socket.create_connection((address, port), self.timeout)
                self.sock = self._context.wrap_socket(raw, server_hostname=parsed.hostname)

        connection = PinnedHTTPSConnection(parsed.hostname, port, timeout=timeout, context=ssl.create_default_context())
    else:
        class PinnedHTTPConnection(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.create_connection((address, port), self.timeout)

        connection = PinnedHTTPConnection(parsed.hostname, port, timeout=timeout)
    request_headers = dict(headers)
    request_headers["Host"] = host_header
    try:
        connection.request("POST", path, body=body, headers=request_headers)
        response = connection.getresponse()
        status = response.status
        response.read()
        return status
    finally:
        connection.close()


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
        parsed, addresses = _resolve_validated_webhook_url(endpoint.url)
        signature = hmac.new(
            endpoint.secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        headers = {
                "Content-Type": "application/json",
                "X-Webhook-Signature": f"sha256={signature}",
                "X-Webhook-Event": event,
            }
        # Every returned address was validated; use one of those exact IPs while
        # retaining the original hostname for Host, certificate validation and SNI.
        status_code = _pinned_webhook_post(parsed, addresses[0], body, headers, timeout=5)
        delivery.status_code = status_code
        if 200 <= status_code < 300:
            delivery.status = WebhookDelivery.Status.SUCCEEDED
            delivery.completed_at = timezone.now()
            delivery.save(update_fields=["status_code", "status", "completed_at"])
            return
        raise RuntimeError(f"Webhook returned HTTP {status_code}.")
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
