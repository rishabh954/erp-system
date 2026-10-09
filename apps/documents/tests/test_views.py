import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.documents.models import Document, DocumentCategory
from apps.documents.validators import (
    MAX_DOCUMENT_FILE_SIZE,
    get_document_file_type,
)

pytestmark = pytest.mark.django_db


def test_document_crud(client, user, company):
    client.force_login(user)

    # 1. Create Category
    cat_url = reverse("documents:category_create")
    res = client.post(
        cat_url,
        {
            "name": "Test Category",
        },
    )
    assert res.status_code == 302
    category = DocumentCategory.objects.filter(name="Test Category").first()
    assert category is not None

    # 2. Upload Document
    upload_url = reverse("documents:upload")
    dummy_file = SimpleUploadedFile(
        "test_doc.txt", b"file_content", content_type="application/pdf"
    )
    res = client.post(
        upload_url,
        {
            "title": "Test Document",
            "category": category.pk,
            "file": dummy_file,
        },
    )
    assert res.status_code == 302
    doc = Document.objects.filter(title="Test Document").first()
    assert doc is not None
    assert doc.file_type == "text/plain"

    # 3. Read Detail
    detail_url = reverse("documents:detail", kwargs={"pk": doc.pk})
    res = client.get(detail_url)
    assert res.status_code == 200

    # 4. List
    list_url = reverse("documents:list")
    res = client.get(list_url)
    assert res.status_code == 200
    assert doc in res.context["object_list"]


def test_document_upload_rejects_mismatched_file_content(client, user, company):
    client.force_login(user)
    upload = SimpleUploadedFile(
        "spoofed.pdf", b"not a PDF", content_type="application/pdf"
    )

    response = client.post(
        reverse("documents:upload"),
        {"title": "Spoofed upload", "file": upload},
    )

    assert response.status_code == 302
    assert not Document.objects.filter(title="Spoofed upload").exists()


def test_document_upload_rejects_files_over_size_limit():
    upload = SimpleUploadedFile(
        "large.txt", b"x" * (MAX_DOCUMENT_FILE_SIZE + 1)
    )

    with pytest.raises(ValidationError, match="10 MB"):
        get_document_file_type(upload)


def test_document_download_uses_internal_nginx_redirect(client, user, company):
    client.force_login(user)
    document = Document.objects.create(
        company=company,
        title="Private document",
        file=SimpleUploadedFile("private.txt", b"private content"),
        created_by=user,
    )

    response = client.get(reverse("documents:download", kwargs={"pk": document.pk}))

    assert response.status_code == 200
    assert response["X-Accel-Redirect"].startswith("/_protected_media/documents/")
    assert response["Content-Type"] == "application/octet-stream"


def test_document_download_is_scoped_to_active_company(client, user, company):
    from apps.authentication.models import UserCompany
    from core.factories import CompanyFactory, UserFactory

    other_company = CompanyFactory()
    other_user = UserFactory(primary_company=other_company)
    UserCompany.objects.create(
        user=other_user, company=other_company, role="company_admin"
    )
    document = Document.objects.create(
        company=company,
        title="Tenant private document",
        file=SimpleUploadedFile("tenant.txt", b"private content"),
        created_by=user,
    )
    client.force_login(other_user)

    response = client.get(reverse("documents:download", kwargs={"pk": document.pk}))

    assert response.status_code == 404
