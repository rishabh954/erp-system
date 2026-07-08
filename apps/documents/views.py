"""
Document Management Views
Upload, Categories, Version Control, Approval Workflow
"""

import os

from core.permissions import PermissionRequiredMixin
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, View

from core.services import BaseService

from .models import Document, DocumentCategory, DocumentVersion


class CompanyMixin(PermissionRequiredMixin):
    def company(self):
        return self.request.user.primary_company


class DocumentListView(CompanyMixin, ListView):
    required_permission = "documents.read"
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
    required_permission = "documents.read"
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
        data = request.POST
        company = self.company()
        file = request.FILES.get("file")

        if not file:
            messages.error(request, "Please select a file to upload.")
            return redirect("documents:upload")

        try:
            doc = Document(
                company=company,
                title=data.get("title") or file.name,
                category_id=data.get("category") or None,
                description=data.get("description", ""),
                file=file,
                file_size=file.size,
                file_type=file.content_type or "",
                version=data.get("version", "1.0"),
                status=data.get("status", "draft"),
                is_public=data.get("is_public") == "on",
                expiry_date=data.get("expiry_date") or None,
                notes=data.get("notes", ""),
                tags=[t.strip() for t in data.get("tags", "").split(",") if t.strip()],
                created_by=request.user,
            )
            doc.number = BaseService.generate_sequence_number(
                "DOC", Document, company.pk
            )
            doc.save()

            # Create first version record
            DocumentVersion.objects.create(
                company=company,
                document=doc,
                version=doc.version,
                file=file,
                file_size=file.size,
                change_notes="Initial upload",
                uploaded_by=request.user,
            )

            messages.success(request, f'Document "{doc.title}" uploaded successfully.')
            return redirect("documents:detail", pk=doc.pk)
        except Exception as e:
            messages.error(request, f"Upload failed: {e}")
            return redirect("documents:upload")


class DocumentNewVersionView(CompanyMixin, View):
    required_permission = "documents.create"
    def post(self, request, pk):
        doc = get_object_or_404(
            Document, pk=pk, company=self.company(), is_deleted=False
        )
        file = request.FILES.get("file")

        if not file:
            messages.error(request, "Please select a file.")
            return redirect("documents:detail", pk=pk)

        try:
            # Bump version
            parts = doc.version.split(".")
            parts[-1] = str(int(parts[-1]) + 1)
            new_version = ".".join(parts)

            DocumentVersion.objects.create(
                company=self.company(),
                document=doc,
                version=new_version,
                file=file,
                file_size=file.size,
                change_notes=request.POST.get("change_notes", ""),
                uploaded_by=request.user,
            )

            doc.file = file
            doc.version = new_version
            doc.file_size = file.size
            doc.save(update_fields=["file", "version", "file_size"])

            messages.success(request, f"Version {new_version} uploaded.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
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
        return redirect("documents:detail", pk=pk)


class DocumentDownloadView(CompanyMixin, View):
    required_permission = "documents.read"
    def get(self, request, pk):
        doc = get_object_or_404(
            Document, pk=pk, company=self.company(), is_deleted=False
        )
        if not doc.is_public and doc.created_by != request.user:
            if request.user.role not in ("company_admin", "super_admin"):
                raise Http404

        if not doc.file:
            raise Http404

        try:
            response = FileResponse(doc.file.open("rb"))
            response["Content-Disposition"] = (
                f'attachment; filename="{os.path.basename(doc.file.name)}"'
            )
            return response
        except FileNotFoundError:
            raise Http404


class DocumentCategoryCreateView(CompanyMixin, View):
    required_permission = "documents.create"
    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            DocumentCategory.objects.create(
                company=company,
                name=data["name"],
                parent_id=data.get("parent") or None,
                description=data.get("description", ""),
            )
            messages.success(request, "Category created.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect("documents:list")


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path

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
