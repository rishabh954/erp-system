from django.urls import path

from .views import (
    DocumentApproveView,
    DocumentCategoryCreateView,
    DocumentDetailView,
    DocumentDownloadView,
    DocumentListView,
    DocumentNewVersionView,
    DocumentUploadView,
)

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
