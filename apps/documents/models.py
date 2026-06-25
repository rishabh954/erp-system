import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from core.models import CompanyScoped, SequenceMixin, NotesMixin


# ═══════════════════════════════ DOCUMENT MANAGEMENT ══════════════════════════

class DocumentCategory(CompanyScoped):
    name = models.CharField(max_length=200)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='children')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'documents_categories'

    def __str__(self):
        return self.name


class Document(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        REVIEW = 'review', _('Under Review')
        APPROVED = 'approved', _('Approved')
        PUBLISHED = 'published', _('Published')
        ARCHIVED = 'archived', _('Archived')

    title = models.CharField(max_length=500)
    category = models.ForeignKey(DocumentCategory, null=True, blank=True, on_delete=models.SET_NULL)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    file = models.FileField(upload_to='documents/%Y/%m/')
    file_size = models.PositiveIntegerField(default=0)
    file_type = models.CharField(max_length=50, blank=True)
    version = models.CharField(max_length=20, default='1.0')
    tags = models.JSONField(default=list)
    is_public = models.BooleanField(default=False)
    expiry_date = models.DateField(null=True, blank=True)
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=100, blank=True)
    related_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        db_table = 'documents_documents'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} v{self.version}"


class DocumentVersion(CompanyScoped):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='versions')
    version = models.CharField(max_length=20)
    file = models.FileField(upload_to='documents/versions/%Y/%m/')
    change_notes = models.TextField(blank=True)
    file_size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey('authentication.User', on_delete=models.PROTECT)

    class Meta:
        db_table = 'documents_versions'
        ordering = ['-created_at']
