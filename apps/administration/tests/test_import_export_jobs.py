
import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse

from apps.administration.models import ExportJob, ImportJob
from apps.crm.models import Customer
from core.factories import CompanyFactory

pytestmark = pytest.mark.django_db


def _import_job(company, user, content, mapping=None):
    return ImportJob.objects.create(
        company=company,
        module="customers",
        file=ContentFile(content.encode(), name="customers.csv"),
        column_mapping=mapping or {},
        imported_by=user,
    )


def test_import_task_imports_valid_rows_and_ignores_company_column(company, user):
    from apps.administration.tasks import process_import_job

    job = _import_job(
        company,
        user,
        "name,email,company_id\nSafe Customer,safe@example.test,foreign-id\n",
    )
    process_import_job.run(str(job.pk), str(company.pk))
    job.refresh_from_db()
    assert job.status == ImportJob.Status.DONE, job.error_log
    assert job.total_rows == job.imported_rows == 1
    assert job.failed_rows == 0
    customer = Customer.objects.get(company=company, email="safe@example.test")
    assert customer.company_id == company.pk


def test_bad_import_rows_are_skipped_and_reported(company, user):
    from apps.administration.tasks import process_import_job

    job = _import_job(
        company,
        user,
        "name,email\nGood Customer,good@example.test\n,missing@example.test\n",
    )
    process_import_job.run(str(job.pk), str(company.pk))
    job.refresh_from_db()
    assert job.status == ImportJob.Status.DONE, job.error_log
    assert job.total_rows == 2
    assert job.imported_rows == 1
    assert job.failed_rows == 1
    assert '"row": 3' in job.error_log
    assert Customer.objects.filter(company=company).count() == 1


def test_export_is_tenant_scoped_escaped_and_download_scoped(
    client, company, user, tmp_path
):

    other = CompanyFactory(name="Other tenant")
    Customer.objects.create(company=company, name="=SUM(1,1)", email="a@example.test")
    Customer.objects.create(company=other, name="Other Customer", email="b@example.test")
    job = ExportJob.objects.create(
        company=company,
        module="customers",
        format="csv",
        requested_by=user,
    )
    from apps.administration.tasks import process_export_job

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        process_export_job.run(str(job.pk), str(company.pk))
        job.refresh_from_db()
        assert job.status == ExportJob.Status.DONE
        content = default_storage.open(job.output_file.name).read().decode()
        assert "'=SUM(1,1)" in content
        assert "Other Customer" not in content

        client.force_login(user)
        response = client.get(reverse("administration:export_download", kwargs={"pk": job.pk}))
        assert response.status_code == 200

        foreign_job = ExportJob.objects.create(
            company=other,
            module="customers",
            format="csv",
            status=ExportJob.Status.DONE,
            requested_by=None,
        )
        foreign_job.output_file.save("foreign.csv", ContentFile(b"secret"))
        response = client.get(
            reverse("administration:export_download", kwargs={"pk": foreign_job.pk})
        )
        assert response.status_code == 404
