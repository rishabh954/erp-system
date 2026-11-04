"""
Document Management Views
Upload, Categories, Version Control, Approval Workflow
"""

from pathlib import PurePosixPath
from urllib.parse import quote

from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import content_disposition_header
from django.views.generic import DetailView, ListView, View

from core.mixins import CompanyMixin
from core.services import BaseService

from .forms import DocumentCategoryForm, DocumentUploadForm, DocumentVersionForm
from .models import Document, DocumentCategory, DocumentVersion
from .validators import get_document_file_type


class DocumentListView(CompanyMixin, ListView):
    required_permission = "documents.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "documents.create"
            elif request.method in ["PUT", "PATCH"]:
                return "documents.update"
            elif request.method == "DELETE":
                return "documents.delete"
        return self.required_permission
    template_name = "documents/list.html"
    context_object_name = "documents"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Document.objects.filter(company=self.company(), is_deleted=False)
            .select_related("category", "created_by")
            .order_by("-created_at")
        )

        q = self.request.GET.get("q", "")
        category = self.request.GET.get("category", "")
        status = self.request.GET.get("status", "")

        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(number__icontains=q))
        if category:
            qs = qs.filter(category_id=category)
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = DocumentCategory.objects.filter(
            company=self.company(), is_deleted=False
        )
        ctx["status_choices"] = Document.Status.choices
        return ctx


class DocumentDetailView(CompanyMixin, DetailView):
    required_permission = "documents.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "documents.create"
            elif request.method in ["PUT", "PATCH"]:
                return "documents.update"
            elif request.method == "DELETE":
                return "documents.delete"
        return self.required_permission
    template_name = "documents/detail.html"
    context_object_name = "document"

    def get_object(self):
        return get_object_or_404(
            Document, pk=self.kwargs["pk"], company=self.company(), is_deleted=False
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["versions"] = (
            self.object.versions.filter(is_deleted=False)
            .select_related("uploaded_by")
            .order_by("-created_at")
        )
        return ctx


class DocumentUploadView(CompanyMixin, View):
    required_permission = "documents.create"
    template_name = "documents/upload.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "categories": DocumentCategory.objects.filter(
                    company=self.company(), is_deleted=False
                ),
                "status_choices": Document.Status.choices,
            },
        )

    def post(self, request):
        company = self.company()
        form = DocumentUploadForm(request.POST, request.FILES, company=company)
        if not form.is_valid():
            messages.error(request, "Please provide valid document details and file.")
            return redirect("documents:upload")

        cleaned = form.cleaned_data
        file = cleaned["file"]
        file_type = get_document_file_type(file)
        try:
            with transaction.atomic():
                doc = Document(
                    company=company,
                    title=cleaned["title"] or file.name,
                    category=cleaned["category"],
                    description=cleaned["description"],
                    file=file,
                    file_size=file.size,
                    file_type=file_type,
                    version=cleaned["version"],
                    status=cleaned["status"] or Document.Status.DRAFT,
                    is_public=cleaned["is_public"],
                    expiry_date=cleaned["expiry_date"],
                    notes=cleaned["notes"],
                    tags=cleaned["tags"],
                    created_by=request.user,
                )
                doc.number = BaseService.generate_sequence_number(
                    "DOC", Document, company.pk
                )
                doc.save()

                DocumentVersion.objects.create(
                    company=company,
                    document=doc,
                    version=doc.version,
                    file=file,
                    file_size=file.size,
                    change_notes="Initial upload",
                    uploaded_by=request.user,
                )

                messages.success(
                    request, f'Document "{doc.title}" uploaded successfully.'
                )
                return redirect("documents:detail", pk=doc.pk)
        except Exception:
            messages.error(request, "Document upload failed.")
            return redirect("documents:upload")


class DocumentNewVersionView(CompanyMixin, View):
    required_permission = "documents.create"
    def post(self, request, pk):
        doc = get_object_or_404(
            Document, pk=pk, company=self.company(), is_deleted=False
        )
        form = DocumentVersionForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "Please provide a valid file.")
            return redirect("documents:detail", pk=pk)

        file = form.cleaned_data["file"]
        file_type = get_document_file_type(file)
        try:
            parts = doc.version.split(".")
            if not parts or any(not part.isdigit() for part in parts):
                raise ValueError("Invalid stored version")
            parts[-1] = str(int(parts[-1]) + 1)
            new_version = ".".join(parts)

            with transaction.atomic():
                doc.file = file
                doc.version = new_version
                doc.file_size = file.size
                doc.file_type = file_type
                doc.save(update_fields=["file", "version", "file_size", "file_type"])

                DocumentVersion.objects.create(
                    company=self.company(),
                    document=doc,
                    version=new_version,
                    file=file,
                    file_size=file.size,
                    change_notes=form.cleaned_data["change_notes"],
                    uploaded_by=request.user,
                )

            messages.success(request, f"Version {new_version} uploaded.")
        except Exception:
            messages.error(request, "Document version upload failed.")
        return redirect("documents:detail", pk=pk)


class DocumentApproveView(CompanyMixin, View):
    required_permission = "documents.approve"
    def post(self, request, pk):
        doc = get_object_or_404(
            Document, pk=pk, company=self.company(), is_deleted=False
        )
        action = request.POST.get("action")
        if action == "approve":
            doc.status = "approved"
            doc.save(update_fields=["status"])
            messages.success(request, f'Document "{doc.title}" approved.')
        elif action == "publish":
            doc.status = "published"
            doc.save(update_fields=["status"])
            messages.success(request, f'Document "{doc.title}" published.')
        elif action == "archive":
            doc.status = "archived"
            doc.save(update_fields=["status"])
            messages.success(request, f'Document "{doc.title}" archived.')
        else:
            messages.error(request, "Select a valid document action.")
        return redirect("documents:detail", pk=pk)


class DocumentDownloadView(CompanyMixin, View):
    required_permission = "documents.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "documents.create"
            elif request.method in ["PUT", "PATCH"]:
                return "documents.update"
            elif request.method == "DELETE":
                return "documents.delete"
        return self.required_permission
    def get(self, request, pk):
        doc = get_object_or_404(
            Document, pk=pk, company=self.company(), is_deleted=False
        )
        if not doc.is_public and doc.created_by != request.user:
            role = request.user.get_role_for_company(self.company())
            if not request.user.is_superuser and role not in (
                "company_admin",
                "super_admin",
            ):
                raise Http404

        if not doc.file:
            raise Http404

        file_name = doc.file.name
        path_parts = PurePosixPath(file_name).parts
        if (
            "\\" in file_name
            or not path_parts
            or any(part in ("", ".", "..") for part in path_parts)
        ):
            raise Http404
        response = HttpResponse()
        response["X-Accel-Redirect"] = (
            f"/_protected_media/{quote(file_name, safe='/')}"
        )
        response["Content-Disposition"] = content_disposition_header(
            True, PurePosixPath(file_name).name
        )
        response["Content-Type"] = "application/octet-stream"
        return response


class DocumentCategoryCreateView(CompanyMixin, View):
    required_permission = "documents.create"
    def post(self, request):
        company = self.company()
        form = DocumentCategoryForm(request.POST, company=company)
        if not form.is_valid():
            messages.error(request, "Please provide valid category details.")
            return redirect("documents:list")
        try:
            cleaned = form.cleaned_data
            DocumentCategory.objects.create(
                company=company,
                name=cleaned["name"],
                parent=cleaned["parent"],
                description=cleaned["description"],
            )
            messages.success(request, "Category created.")
        except Exception:
            messages.error(request, "Category creation failed.")
        return redirect("documents:list")


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path  # noqa: E402

app_name = "documents"

urlpatterns = [
    path("", DocumentListView.as_view(), name="list"),
    path("upload/", DocumentUploadView.as_view(), name="upload"),
    path("<uuid:pk>/", DocumentDetailView.as_view(), name="detail"),
    path("<uuid:pk>/download/", DocumentDownloadView.as_view(), name="download"),
    path("<uuid:pk>/version/", DocumentNewVersionView.as_view(), name="new_version"),
    path("<uuid:pk>/approve/", DocumentApproveView.as_view(), name="approve"),
    path(
        "categories/create/",
        DocumentCategoryCreateView.as_view(),
        name="category_create",
    ),
]
