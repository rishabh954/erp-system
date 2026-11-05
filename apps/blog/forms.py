"""
Blog Forms
All forms validate on the server side, regardless of frontend validation.
"""

from django import forms
from django.utils import timezone

from apps.blog.models import (
    BlogCategory,
    BlogEnquiry,
    BlogPost,
    BlogTag,
    SocialMediaAccount,
    WebsiteIntegration,
)


class BlogPostForm(forms.ModelForm):
    """Create and edit blog posts."""

    tags = forms.ModelMultipleChoiceField(
        queryset=BlogTag.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = BlogPost
        fields = [
            "title", "subtitle", "content_raw", "excerpt",
            "category", "tags",
            "featured_image", "featured_image_alt", "og_image",
            "seo_title", "meta_description", "meta_keywords", "canonical_url",
            "enable_enquiry_form", "is_featured", "allow_comments",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Blog title"}),
            "subtitle": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional subtitle"}),
            "content_raw": forms.Textarea(attrs={"id": "blog-content-editor", "class": "form-control d-none"}),
            "excerpt": forms.Textarea(attrs={"class": "form-control", "rows": 3, "maxlength": 500}),
            "featured_image_alt": forms.TextInput(attrs={"class": "form-control"}),
            "seo_title": forms.TextInput(attrs={"class": "form-control", "maxlength": 70}),
            "meta_description": forms.Textarea(attrs={"class": "form-control", "rows": 2, "maxlength": 160}),
            "meta_keywords": forms.TextInput(attrs={"class": "form-control"}),
            "canonical_url": forms.URLInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            self.fields["category"].queryset = BlogCategory.objects.filter(
                company=company, is_active=True, is_deleted=False
            )
            self.fields["tags"].queryset = BlogTag.objects.filter(
                company=company, is_active=True, is_deleted=False
            )

    def clean_featured_image(self):
        image = self.cleaned_data.get("featured_image")
        if image and hasattr(image, "size"):
            max_size_mb = 5
            if image.size > max_size_mb * 1024 * 1024:
                raise forms.ValidationError(f"Featured image must be smaller than {max_size_mb} MB.")
        return image

    def clean_seo_title(self):
        val = self.cleaned_data.get("seo_title", "")
        if val and len(val) > 70:
            raise forms.ValidationError("SEO title must be 70 characters or fewer.")
        return val

    def clean_meta_description(self):
        val = self.cleaned_data.get("meta_description", "")
        if val and len(val) > 160:
            raise forms.ValidationError("Meta description must be 160 characters or fewer.")
        return val


class BlogScheduleForm(forms.Form):
    """Schedule a post for future publishing."""

    publish_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
        help_text="Select a future date and time to publish (uses your company timezone).",
    )
    publish_to_website = forms.BooleanField(required=False, initial=True)
    social_account_ids = forms.MultipleChoiceField(choices=[], required=False)

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            accounts = SocialMediaAccount.objects.filter(
                company=company,
                is_active=True,
                connection_status=SocialMediaAccount.ConnectionStatus.CONNECTED,
                is_deleted=False,
            )
            self.fields["social_account_ids"].choices = [
                (str(a.pk), f"{a.get_platform_display()} — {a.account_name}")
                for a in accounts
            ]

    def clean_publish_at(self):
        dt = self.cleaned_data.get("publish_at")
        if dt and dt <= timezone.now():
            raise forms.ValidationError("Scheduled time must be in the future.")
        return dt


class BlogApprovalForm(forms.Form):
    """Approve or reject a blog post."""

    comment = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        required=False,
        label="Comment / Reason",
    )

    def clean_comment(self):
        return self.cleaned_data.get("comment", "").strip()


class SocialMediaPublishForm(forms.Form):
    """Customise per-platform captions before publishing to social media."""

    account_ids = forms.MultipleChoiceField(
        choices=[],
        required=True,
        widget=forms.CheckboxSelectMultiple,
        label="Publish to",
    )
    caption = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        required=False,
        label="Caption (leave blank to auto-generate)",
    )
    hashtags = forms.CharField(
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "#Blog #SvapasWorld"}),
        required=False,
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            accounts = SocialMediaAccount.objects.filter(
                company=company,
                is_active=True,
                connection_status=SocialMediaAccount.ConnectionStatus.CONNECTED,
                is_deleted=False,
            )
            self.fields["account_ids"].choices = [
                (str(a.pk), f"{a.get_platform_display()} — {a.account_name}")
                for a in accounts
            ]


class SocialMediaAccountForm(forms.ModelForm):
    """Add/edit a social media account (OAuth config is handled separately)."""

    class Meta:
        model = SocialMediaAccount
        fields = ["platform", "account_name", "account_id", "account_username", "account_url", "is_active"]
        widgets = {
            "account_name": forms.TextInput(attrs={"class": "form-control"}),
            "account_id": forms.TextInput(attrs={"class": "form-control"}),
            "account_username": forms.TextInput(attrs={"class": "form-control"}),
            "account_url": forms.URLInput(attrs={"class": "form-control"}),
        }


class WebsiteIntegrationForm(forms.ModelForm):
    """Configure the website CMS integration."""

    class Meta:
        model = WebsiteIntegration
        fields = [
            "name", "website_url", "integration_type",
            "api_endpoint", "api_key", "api_secret", "webhook_secret",
            "field_mapping", "max_retries", "retry_backoff_seconds", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "website_url": forms.URLInput(attrs={"class": "form-control"}),
            "api_endpoint": forms.URLInput(attrs={"class": "form-control"}),
            "api_key": forms.PasswordInput(
                attrs={"class": "form-control"},
                render_value=False,
            ),
            "api_secret": forms.PasswordInput(
                attrs={"class": "form-control"},
                render_value=False,
            ),
            "webhook_secret": forms.PasswordInput(
                attrs={"class": "form-control"},
                render_value=False,
            ),
            "field_mapping": forms.Textarea(attrs={"class": "form-control font-monospace", "rows": 4}),
            "max_retries": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 10}),
            "retry_backoff_seconds": forms.NumberInput(attrs={"class": "form-control", "min": 10}),
        }
        help_texts = {
            "api_key": "Enter a new value to update. Leave blank to keep the existing credential.",
            "api_secret": "Enter a new value to update. Leave blank to keep the existing credential.",
            "webhook_secret": "Enter a new value to update. Leave blank to keep the existing credential.",
        }


class BlogCategoryForm(forms.ModelForm):
    class Meta:
        model = BlogCategory
        fields = ["name", "description", "parent", "image", "is_active", "order"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            self.fields["parent"].queryset = BlogCategory.objects.filter(
                company=company, is_active=True, parent__isnull=True
            ).exclude(pk=self.instance.pk if self.instance.pk else None)


class BlogTagForm(forms.ModelForm):
    class Meta:
        model = BlogTag
        fields = ["name", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
        }


class BlogEnquiryForm(forms.ModelForm):
    """Public-facing enquiry form embedded in blog pages."""

    class Meta:
        model = BlogEnquiry
        fields = [
            "contact_name", "contact_email", "contact_phone",
            "contact_company", "message", "consent_given",
        ]
        widgets = {
            "contact_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Your Name *"}),
            "contact_email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Email Address *"}),
            "contact_phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Phone Number"}),
            "contact_company": forms.TextInput(attrs={"class": "form-control", "placeholder": "Company Name"}),
            "message": forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "How can we help you?"}),
            "consent_given": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_consent_given(self):
        val = self.cleaned_data.get("consent_given")
        if not val:
            raise forms.ValidationError("You must consent to be contacted before submitting.")
        return val

    def clean_message(self):
        msg = self.cleaned_data.get("message", "").strip()
        if len(msg) < 10:
            raise forms.ValidationError("Please provide a more detailed message (at least 10 characters).")
        return msg
