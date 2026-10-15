"""Restore one tenant backup into a prepared, empty tenant database."""

import json
import uuid
from collections import Counter

from django.apps import apps
from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.administration.tasks import SENSITIVE_MODEL_NAMES, _backup_company_path
from apps.authentication.models import User
from apps.company.models import Company
from core.restore_context import restoring


SCHEMA_VERSION = 1


def _identity(model_label, pk):
    return model_label.lower(), str(pk)


def _company_owned(row, rows_by_identity, company_id, seen=None):
    """Verify ownership only through a parent record present in this backup."""
    seen = seen or set()
    model = apps.get_model(row["model"])
    identity = _identity(row["model"], row["pk"])
    if identity in seen:
        return False
    seen.add(identity)
    if model is Company:
        return str(row["pk"]) == str(company_id)
    path = _backup_company_path(model, Company)
    if path is None:
        return False
    if path == "company_id":
        return str(row.get("fields", {}).get("company")) == str(company_id)
    parent = row
    parent_model = model
    for relation_name in path.removesuffix("__company_id").split("__"):
        related_pk = parent.get("fields", {}).get(relation_name)
        if related_pk is None:
            return False
        field = parent_model._meta.get_field(relation_name)
        parent_model = field.related_model
        parent = rows_by_identity.get(_identity(parent_model._meta.label_lower, related_pk))
        if parent is None:
            return False
    return _company_owned(parent, rows_by_identity, company_id, seen)


def _target_queryset(model, company_id):
    qs = model._base_manager.all()
    if model is Company:
        return qs.filter(pk=company_id)
    path = _backup_company_path(model, Company)
    if path:
        return qs.filter(**{path: company_id})
    return qs


def _validate_references(objects, rows_by_identity, company_id):
    for row in objects:
        model = apps.get_model(row["model"])
        fields = row.get("fields", {})
        for field in model._meta.concrete_fields:
            if not field.is_relation or not field.many_to_one or field.name not in fields:
                continue
            ref_pk = fields[field.name]
            if ref_pk is None:
                continue
            related_model = field.related_model
            ref_identity = _identity(related_model._meta.label_lower, ref_pk)
            if ref_identity in rows_by_identity:
                continue
            if related_model is User:
                qs = related_model._base_manager.filter(
                    Q(primary_company_id=company_id)
                    | Q(companies__pk=company_id)
                    | Q(is_superuser=True)
                ).distinct()
            else:
                qs = _target_queryset(related_model, company_id)
            related = qs.filter(pk=ref_pk).first()
            if related is None:
                raise CommandError(
                    f"Cannot restore {row['model']} {row['pk']}: referenced "
                    f"{related_model._meta.label} {ref_pk} is missing from the target."
                )


class Command(BaseCommand):
    help = "Restore a company-only JSON backup into its matching prepared company. Signals and side effects are suppressed during restore."

    def add_arguments(self, parser):
        parser.add_argument("backup_file")
        parser.add_argument("--company", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            company_id = uuid.UUID(str(options["company"]))
        except (ValueError, TypeError) as exc:
            raise CommandError("--company must be a valid company UUID.") from exc
        try:
            with open(options["backup_file"], encoding="utf-8") as backup_file:
                payload = json.load(backup_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Cannot read backup JSON: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("manifest"), dict) or not isinstance(payload.get("objects"), list):
            raise CommandError("Backup must contain manifest and objects entries.")
        manifest = payload["manifest"]
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise CommandError(f"Unsupported backup schema_version: {manifest.get('schema_version')!r}.")
        try:
            manifest_company = uuid.UUID(str(manifest.get("company_id")))
        except (ValueError, TypeError) as exc:
            raise CommandError("Backup manifest has an invalid company_id.") from exc
        if manifest_company != company_id:
            raise CommandError("Backup company_id does not match --company; no data was loaded.")
        company = Company.objects.filter(pk=company_id).first()
        if company is None:
            raise CommandError("The target company must already exist before restore.")

        objects = payload["objects"]
        rows_by_identity = {}
        for row in objects:
            if not isinstance(row, dict) or not {"model", "pk", "fields"}.issubset(row):
                raise CommandError("Backup contains a malformed serialized object.")
            try:
                model = apps.get_model(row["model"])
            except (LookupError, ValueError) as exc:
                raise CommandError(f"Unknown model in backup: {row.get('model')!r}.") from exc
            if model._meta.model_name.lower() in SENSITIVE_MODEL_NAMES:
                raise CommandError(f"Backup must not contain excluded sensitive model {row['model']}.")
            identity = _identity(row["model"], row["pk"])
            if identity in rows_by_identity:
                raise CommandError(f"Backup contains duplicate object {row['model']} {row['pk']}.")
            rows_by_identity[identity] = row

        for row in objects:
            model = apps.get_model(row["model"])
            if model is Company:
                if str(row["pk"]) != str(company_id):
                    raise CommandError("Backup contains a different Company row.")
                continue
            if not _company_owned(row, rows_by_identity, company_id):
                raise CommandError(
                    f"Backup object {row['model']} {row['pk']} is not verifiably owned by the target company."
                )
            if _target_queryset(model, company_id).filter(pk=row["pk"]).exists():
                raise CommandError(
                    f"Target already contains {row['model']} {row['pk']}; restore will not overwrite rows."
                )

        _validate_references(objects, rows_by_identity, company_id)
        counts = Counter(row["model"] for row in objects if apps.get_model(row["model"]) is not Company)
        if options["dry_run"]:
            self.stdout.write("Dry run validated; no rows were written.")
            for model_label, count in sorted(counts.items()):
                self.stdout.write(f"Would load {model_label}: {count}")
            return

        loaded = Counter()
        try:
            with restoring():
                with transaction.atomic():
                    deserialized = []
                    for deserialized_obj in serializers.deserialize(
                        "json", json.dumps(objects), handle_forward_references=True
                    ):
                        if deserialized_obj.object.__class__ is Company:
                            continue
                        deserialized.append(deserialized_obj)
                        deserialized_obj.save()
                        loaded[deserialized_obj.object._meta.label_lower] += 1
                    for deserialized_obj in deserialized:
                        deserialized_obj.save_deferred_fields()
                    expected_counts = manifest.get("model_counts", {})
                    for model_label, expected in expected_counts.items():
                        model = apps.get_model(model_label)
                        if model is Company:
                            continue
                        actual = _target_queryset(model, company_id).count()
                        if actual != expected:
                            raise ValueError(
                                f"Restored count mismatch for {model_label}: expected {expected}, found {actual}."
                            )
        except Exception as exc:
            raise CommandError(f"Restore aborted and rolled back: {exc}") from exc
        self.stdout.write("Restore completed.")
        for model_label, count in sorted(loaded.items()):
            self.stdout.write(f"Loaded {model_label}: {count}")
