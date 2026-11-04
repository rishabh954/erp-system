import re

from django import forms

from .models import Document, DocumentCategory
from .validators import get_document_file_type


class DocumentUploadForm(forms.Form):
    title = forms.CharField(max_length=500, required=False)
    category = forms.ModelChoiceField(
        queryset=DocumentCategory.objects.none(), required=False
    )
    description = forms.CharField(required=False, widget=forms.Textarea)
    file = forms.FileField()
    version = forms.CharField(max_length=20, required=False, initial="1.0")
    status = forms.ChoiceField(
        choices=Document.Status.choices,
        required=False,
        initial=Document.Status.DRAFT,
    )
    is_public = forms.BooleanField(required=False)
    expiry_date = forms.DateField(required=False)
    tags = forms.CharField(required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea)

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["category"].queryset = DocumentCategory.objects.filter(
                company=company, is_deleted=False
            )

    def clean_version(self):
        version = self.cleaned_data["version"].strip() or "1.0"
        if not re.fullmatch(r"\d+(?:\.\d+)*", version):
            raise forms.ValidationError("Enter a version such as 1.0.")
        return version

    def clean_file(self):
        upload = self.cleaned_data["file"]
        get_document_file_type(upload)
        return upload

    def clean_tags(self):
        return [
            tag.strip()
            for tag in self.cleaned_data.get("tags", "").split(",")
            if tag.strip()
        ]


class DocumentVersionForm(forms.Form):
    file = forms.FileField()
    change_notes = forms.CharField(required=False, widget=forms.Textarea)

    def clean_file(self):
        upload = self.cleaned_data["file"]
        get_document_file_type(upload)
        return upload


class DocumentCategoryForm(forms.Form):
    name = forms.CharField(max_length=200)
    parent = forms.ModelChoiceField(
        queryset=DocumentCategory.objects.none(), required=False
    )
    description = forms.CharField(required=False, widget=forms.Textarea)

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["parent"].queryset = DocumentCategory.objects.filter(
                company=company, is_deleted=False
            )
