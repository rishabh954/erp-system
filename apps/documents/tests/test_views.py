import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.documents.models import Document, DocumentCategory

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
    dummy_file = SimpleUploadedFile("test_doc.txt", b"file_content")
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

    # 3. Read Detail
    detail_url = reverse("documents:detail", kwargs={"pk": doc.pk})
    res = client.get(detail_url)
    assert res.status_code == 200

    # 4. List
    list_url = reverse("documents:list")
    res = client.get(list_url)
    assert res.status_code == 200
    assert doc in res.context["object_list"]
