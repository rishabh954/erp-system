"""
Blog & Content Management Models
Covers: Blog Posts, Categories, Tags, Approvals, Revisions,
        Website Integration, Social Media Accounts & Publications,
        Publishing Schedules, Publishing Logs, Blog Enquiries (CRM leads).

All models are company-scoped (multi-tenant) via CompanyScoped base class.
Sensitive credentials (OAuth tokens) are encrypted at rest via EncryptedCharField.
"""

import uuid

import bleach
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core.fields import EncryptedCharField
from core.models import CompanyScoped, NotesMixin, TimeStampedModel

# ---------------------------------------------------------------------------
# Bleach allowed HTML config for blog content sanitisation
# ---------------------------------------------------------------------------
BLOG_ALLOWED_TAGS = [
    "p", "br", "strong", "b", "em", "i", "u", "s", "del",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "blockquote", "pre", "code",
    "a", "img", "figure", "figcaption",
    "table", "thead", "tbody", "tr", "th", "td",
    "div", "span", "hr",
    "sub", "sup", "mark",
]

BLOG_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "width", "height", "loading", "class"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
    "div": ["class", "id", "style"],
    "span": ["class", "style"],
    "p": ["class"],
    "pre": ["class"],
    "code": ["class"],
    "blockquote": ["class"],
}

BLOG_ALLOWED_STYLES = [
    "color", "background-color", "font-size", "text-align",
    "padding", "margin", "border", "border-radius",
]


def sanitize_blog_html(html_content: str) -> str:
    """Sanitise user-supplied HTML to prevent XSS. Preserves blog formatting."""
    if not html_content:
        return ""
    return bleach.clean(
        html_content,
        tags=BLOG_ALLOWED_TAGS,
        attributes=BLOG_ALLOWED_ATTRIBUTES,
        strip=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAXONOMY
# ═══════════════════════════════════════════════════════════════════════════════


class BlogCategory(CompanyScoped, NotesMixin):
    """Hierarchical blog categories (up to 2 levels deep)."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True, db_index=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    image = models.ImageField(upload_to="blog/categories/", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0, db_index=True)

    class Meta:
        db_table = "blog_categories"
        ordering = ["order", "name"]
        unique_together = [("company", "slug")]
        verbose_name = _("Blog Category")
        verbose_name_plural = _("Blog Categories")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:210] or "category"
            candidate = base
            n = 2
            while BlogCategory.objects.filter(
                company_id=self.company_id, slug=candidate
            ).exclude(pk=self.pk).exists():
                candidate = f"{base[:209]}-{n}"
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class BlogTag(CompanyScoped):
    """Flat tags for blog posts."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "blog_tags"
        ordering = ["name"]
        unique_together = [("company", "slug")]
        verbose_name = _("Blog Tag")
        verbose_name_plural = _("Blog Tags")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:110] or "tag"
            candidate = base
            n = 2
            while BlogTag.objects.filter(
                company_id=self.company_id, slug=candidate
            ).exclude(pk=self.pk).exists():
                candidate = f"{base[:109]}-{n}"
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# BLOG POST
# ═══════════════════════════════════════════════════════════════════════════════


class BlogPost(CompanyScoped, NotesMixin):
    """
    Core blog post.
    Lifecycle: DRAFT → PENDING_APPROVAL → APPROVED → (SCHEDULED | PUBLISHED)
               or REJECTED → (edit) → PENDING_APPROVAL
               or ARCHIVED at any time by admin.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING_APPROVAL = "pending_approval", _("Pending Approval")
        APPROVED = "approved", _("Approved")
        SCHEDULED = "scheduled", _("Scheduled")
        PUBLISHED = "published", _("Published")
        REJECTED = "rejected", _("Rejected")
        ARCHIVED = "archived", _("Archived")

    class WebsiteSyncStatus(models.TextChoices):
        NOT_SYNCED = "not_synced", _("Not Synced")
        SYNCING = "syncing", _("Syncing")
        SYNCED = "synced", _("Synced")
        FAILED = "failed", _("Failed")
        PENDING_RETRY = "pending_retry", _("Pending Retry")

    # ── Identity ──────────────────────────────────────────────────────────────
    number = models.CharField(max_length=30, blank=True, db_index=True)
    title = models.CharField(max_length=500)
    subtitle = models.CharField(max_length=500, blank=True)
    slug = models.SlugField(max_length=520, blank=True, db_index=True)
    excerpt = models.TextField(
        blank=True, max_length=500, help_text="Short summary shown in listings."
    )
    content = models.TextField(blank=True, help_text="Sanitised HTML content.")
    content_raw = models.TextField(
        blank=True, help_text="Raw HTML before sanitisation (stored for editor round-trip)."
    )

    # ── Taxonomy ──────────────────────────────────────────────────────────────
    category = models.ForeignKey(
        BlogCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posts",
    )
    tags = models.ManyToManyField(BlogTag, blank=True, related_name="posts")

    # ── Media ─────────────────────────────────────────────────────────────────
    featured_image = models.ImageField(
        upload_to="blog/posts/%Y/%m/", null=True, blank=True
    )
    featured_image_alt = models.CharField(max_length=255, blank=True)
    og_image = models.ImageField(
        upload_to="blog/og/%Y/%m/",
        null=True,
        blank=True,
        help_text="Open Graph / social sharing image (1200×630 px recommended).",
    )

    # ── Authorship ────────────────────────────────────────────────────────────
    author = models.ForeignKey(
        "authentication.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="blog_posts_authored",
    )
    contributors = models.ManyToManyField(
        "authentication.User",
        blank=True,
        related_name="blog_posts_contributed",
    )

    # ── Status & Scheduling ───────────────────────────────────────────────────
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    scheduled_publish_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="UTC datetime to automatically publish. Requires status=SCHEDULED.",
    )
    published_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="blog_posts_published",
    )

    # ── SEO ───────────────────────────────────────────────────────────────────
    seo_title = models.CharField(
        max_length=70,
        blank=True,
        help_text="SEO title (max 70 chars). Falls back to title if blank.",
    )
    meta_description = models.CharField(
        max_length=160,
        blank=True,
        help_text="Meta description (max 160 chars).",
    )
    meta_keywords = models.CharField(
        max_length=300,
        blank=True,
        help_text="Comma-separated keywords.",
    )
    canonical_url = models.URLField(
        blank=True,
        help_text="Override canonical URL if post is syndicated.",
    )

    # ── Website publishing ────────────────────────────────────────────────────
    website_sync_status = models.CharField(
        max_length=20,
        choices=WebsiteSyncStatus.choices,
        default=WebsiteSyncStatus.NOT_SYNCED,
        db_index=True,
    )
    website_post_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="External post ID returned by the website CMS API.",
    )
    website_url = models.URLField(
        blank=True, help_text="Public URL of the published article on the website."
    )
    website_synced_at = models.DateTimeField(null=True, blank=True)
    website_sync_error = models.TextField(blank=True)
    website_idempotency_key = models.CharField(
        max_length=100,
        blank=True,
        unique=True,
        null=True,
        help_text="UUID used to prevent duplicate website articles during retries.",
    )

    # ── Flags ─────────────────────────────────────────────────────────────────
    enable_enquiry_form = models.BooleanField(
        default=True,
        help_text="Show CTA enquiry form on the public blog page.",
    )
    is_featured = models.BooleanField(default=False, db_index=True)
    allow_comments = models.BooleanField(default=False)

    # ── Revision tracking ─────────────────────────────────────────────────────
    revision_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "blog_posts"
        ordering = ["-created_at"]
        unique_together = [("company", "slug")]
        indexes = [
            models.Index(fields=["company", "status", "published_at"]),
            models.Index(fields=["company", "website_sync_status"]),
            models.Index(fields=["scheduled_publish_at", "status"]),
        ]
        verbose_name = _("Blog Post")
        verbose_name_plural = _("Blog Posts")

    def __str__(self):
        return f"{self.number} | {self.title}" if self.number else self.title

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def effective_seo_title(self) -> str:
        return self.seo_title or self.title

    @property
    def is_live(self) -> bool:
        return self.status == self.Status.PUBLISHED and bool(self.website_url)

    @property
    def public_url(self) -> str:
        return self.website_url or self.canonical_url

    # ── Save hooks ────────────────────────────────────────────────────────────
    def save(self, *args, **kwargs):
        # Generate slug from title
        if not self.slug and self.title:
            base = slugify(self.title)[:510] or "post"
            candidate = base
            n = 2
            while BlogPost.objects.filter(
                company_id=self.company_id, slug=candidate
            ).exclude(pk=self.pk).exists():
                candidate = f"{base[:509]}-{n}"
                n += 1
            self.slug = candidate

        # Generate post number
        if not self.number:
            from core.services import BaseService
            self.number = BaseService.generate_sequence_number(
                "POST", type(self), self.company_id
            )

        # Assign idempotency key for website publishing
        if not self.website_idempotency_key:
            self.website_idempotency_key = uuid.uuid4().hex

        # Sanitise HTML content
        if self.content_raw:
            self.content = sanitize_blog_html(self.content_raw)

        super().save(*args, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# BLOG REVISION  (version history)
# ═══════════════════════════════════════════════════════════════════════════════


class BlogRevision(TimeStampedModel):
    """Immutable snapshot of a blog post at a point in time."""

    post = models.ForeignKey(
        BlogPost, on_delete=models.CASCADE, related_name="revisions"
    )
    version = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=500)
    subtitle = models.CharField(max_length=500, blank=True)
    content = models.TextField(blank=True)
    excerpt = models.TextField(blank=True, max_length=500)
    seo_title = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)
    meta_keywords = models.CharField(max_length=300, blank=True)
    revised_by = models.ForeignKey(
        "authentication.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="blog_revisions",
    )
    change_summary = models.CharField(
        max_length=500, blank=True, help_text="Short description of what changed."
    )

    class Meta:
        db_table = "blog_revisions"
        ordering = ["-version"]
        unique_together = [("post", "version")]
        verbose_name = _("Blog Revision")
        verbose_name_plural = _("Blog Revisions")

    def __str__(self):
        return f"{self.post.number} v{self.version}"


# ═══════════════════════════════════════════════════════════════════════════════
# APPROVAL WORKFLOW
# ═══════════════════════════════════════════════════════════════════════════════


class BlogApproval(CompanyScoped):
    """
    One record per approval action taken on a blog post.
    Multiple records per post build the full approval history.
    """

    class Decision(models.TextChoices):
        SUBMITTED = "submitted", _("Submitted for Approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        REVISION_REQUESTED = "revision_requested", _("Revision Requested")
        RESUBMITTED = "resubmitted", _("Resubmitted")

    post = models.ForeignKey(
        BlogPost, on_delete=models.CASCADE, related_name="approvals"
    )
    decision = models.CharField(max_length=25, choices=Decision.choices)
    decided_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="blog_approval_decisions",
    )
    comment = models.TextField(
        blank=True, help_text="Approval comment or rejection reason."
    )
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "blog_approvals"
        ordering = ["-decided_at"]
        verbose_name = _("Blog Approval")
        verbose_name_plural = _("Blog Approvals")

    def __str__(self):
        return f"{self.post.number} — {self.get_decision_display()}"


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSITE INTEGRATION  (CMS connector config, per-company)
# ═══════════════════════════════════════════════════════════════════════════════


class WebsiteIntegration(CompanyScoped):
    """
    Configuration for connecting the ERP to the company's public website CMS.
    Supports REST API, webhook, and custom connector approaches.
    Credentials are stored encrypted via EncryptedCharField.
    """

    class IntegrationType(models.TextChoices):
        REST_API = "rest_api", _("REST API")
        WEBHOOK = "webhook", _("Webhook (Push)")
        HEADLESS_CMS = "headless_cms", _("Headless CMS")
        CUSTOM = "custom", _("Custom Connector")

    class Status(models.TextChoices):
        CONNECTED = "connected", _("Connected")
        DISCONNECTED = "disconnected", _("Disconnected")
        ERROR = "error", _("Error")
        PENDING = "pending", _("Pending Setup")

    name = models.CharField(
        max_length=200, default="Primary Website", help_text="Display name."
    )
    website_url = models.URLField(
        help_text="Base URL of the public website (e.g. https://svapasworld.com)."
    )
    integration_type = models.CharField(
        max_length=20,
        choices=IntegrationType.choices,
        default=IntegrationType.REST_API,
    )

    # API connection details — encrypted at rest
    api_endpoint = models.URLField(
        blank=True,
        help_text="Full URL to the blog publishing API endpoint on the website.",
    )
    api_key = EncryptedCharField(
        max_length=500,
        blank=True,
        help_text="API key or bearer token for authenticating with the website.",
    )
    api_secret = EncryptedCharField(max_length=500, blank=True)
    webhook_secret = EncryptedCharField(
        max_length=500,
        blank=True,
        help_text="HMAC secret for verifying incoming webhook payloads.",
    )

    # Optional per-field mappings (JSON) — e.g. {"title": "post_title", "content": "post_content"}
    field_mapping = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional field-name mapping between ERP and website CMS.",
    )

    # Connection health
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.DISCONNECTED,
        db_index=True,
    )
    last_health_check = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    # Retry config
    max_retries = models.PositiveSmallIntegerField(default=3)
    retry_backoff_seconds = models.PositiveSmallIntegerField(
        default=60, help_text="Initial backoff in seconds (doubles on each retry)."
    )

    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "blog_website_integrations"
        verbose_name = _("Website Integration")
        verbose_name_plural = _("Website Integrations")

    def __str__(self):
        return f"{self.name} ({self.website_url})"


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSITE PUBLICATION  (per-post sync record)
# ═══════════════════════════════════════════════════════════════════════════════


class WebsitePublication(CompanyScoped):
    """
    Tracks the lifecycle of publishing a specific BlogPost to the website.
    One record per post per integration (posts can be syndicated to multiple sites).
    """

    class SyncStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        SYNCING = "syncing", _("Syncing")
        PUBLISHED = "published", _("Published")
        UPDATED = "updated", _("Updated")
        UNPUBLISHED = "unpublished", _("Unpublished")
        FAILED = "failed", _("Failed")
        PENDING_RETRY = "pending_retry", _("Pending Retry")

    post = models.ForeignKey(
        BlogPost, on_delete=models.CASCADE, related_name="website_publications"
    )
    integration = models.ForeignKey(
        WebsiteIntegration, on_delete=models.CASCADE, related_name="publications"
    )
    sync_status = models.CharField(
        max_length=20,
        choices=SyncStatus.choices,
        default=SyncStatus.PENDING,
        db_index=True,
    )
    external_post_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Post ID returned by the website CMS.",
    )
    public_url = models.URLField(blank=True)
    idempotency_key = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="UUID used to prevent duplicate articles on the website.",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    updated_at_website = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="website_publications",
    )
    retry_count = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    error_detail = models.TextField(blank=True)
    request_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Last request payload sent (for debugging; no secrets stored).",
    )
    response_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Last response from website (for debugging).",
    )

    class Meta:
        db_table = "blog_website_publications"
        ordering = ["-created_at"]
        unique_together = [("post", "integration")]
        indexes = [
            models.Index(fields=["sync_status", "next_retry_at"]),
        ]
        verbose_name = _("Website Publication")
        verbose_name_plural = _("Website Publications")

    def __str__(self):
        return f"{self.post.number} → {self.integration.name} ({self.sync_status})"


# ═══════════════════════════════════════════════════════════════════════════════
# SOCIAL MEDIA ACCOUNTS
# ═══════════════════════════════════════════════════════════════════════════════


class SocialMediaAccount(CompanyScoped):
    """
    Connected social media account (Facebook Page, Instagram Business, LinkedIn Company).
    OAuth tokens are stored encrypted. Raw tokens are never displayed in UI or logs.
    """

    class Platform(models.TextChoices):
        FACEBOOK = "facebook", _("Facebook Page")
        INSTAGRAM = "instagram", _("Instagram Business")
        LINKEDIN = "linkedin", _("LinkedIn Company Page")
        TWITTER_X = "twitter_x", _("Twitter / X")

    class ConnectionStatus(models.TextChoices):
        CONNECTED = "connected", _("Connected")
        DISCONNECTED = "disconnected", _("Disconnected")
        EXPIRED = "expired", _("Token Expired")
        REQUIRES_REAUTH = "requires_reauth", _("Requires Re-authorisation")
        ERROR = "error", _("Error")
        PENDING = "pending", _("Pending OAuth")

    platform = models.CharField(
        max_length=20, choices=Platform.choices, db_index=True
    )
    account_name = models.CharField(
        max_length=255, help_text="Display name of the page/account (e.g. Svapas World)."
    )
    account_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Platform-specific account/page ID.",
    )
    account_username = models.CharField(max_length=255, blank=True)
    account_url = models.URLField(blank=True)
    account_avatar_url = models.URLField(blank=True)

    # OAuth credentials — encrypted at rest
    access_token = EncryptedCharField(
        max_length=2000,
        blank=True,
        help_text="OAuth access token. Encrypted at rest.",
    )
    refresh_token = EncryptedCharField(
        max_length=2000,
        blank=True,
        help_text="OAuth refresh token. Encrypted at rest.",
    )
    token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the access token expires. Null = non-expiring.",
    )

    # Platform page / page token (Facebook/Instagram use page-level tokens)
    page_id = models.CharField(max_length=255, blank=True)
    page_name = models.CharField(max_length=255, blank=True)
    page_access_token = EncryptedCharField(max_length=2000, blank=True)

    # OAuth state (stored transiently during the OAuth flow)
    oauth_state = models.CharField(
        max_length=255,
        blank=True,
        help_text="CSRF state token for OAuth callback validation.",
    )

    # Available publishing permissions (stored as JSON list)
    granted_permissions = models.JSONField(
        default=list,
        blank=True,
        help_text="Permissions granted during OAuth (e.g. ['pages_manage_posts']).",
    )

    connection_status = models.CharField(
        max_length=25,
        choices=ConnectionStatus.choices,
        default=ConnectionStatus.PENDING,
        db_index=True,
    )
    connected_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="social_accounts_connected",
    )
    connected_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "blog_social_accounts"
        ordering = ["platform", "account_name"]
        unique_together = [("company", "platform", "account_id")]
        verbose_name = _("Social Media Account")
        verbose_name_plural = _("Social Media Accounts")

    def __str__(self):
        return f"{self.get_platform_display()} — {self.account_name}"

    @property
    def is_token_expired(self) -> bool:
        if not self.token_expires_at:
            return False
        return timezone.now() >= self.token_expires_at

    @property
    def needs_reauth(self) -> bool:
        return self.connection_status in (
            self.ConnectionStatus.EXPIRED,
            self.ConnectionStatus.REQUIRES_REAUTH,
        ) or self.is_token_expired


# ═══════════════════════════════════════════════════════════════════════════════
# SOCIAL MEDIA PUBLICATION  (per-post per-platform)
# ═══════════════════════════════════════════════════════════════════════════════


class SocialMediaPublication(CompanyScoped):
    """
    Tracks the state of publishing a BlogPost to a specific social media account.
    One record per post per account.
    """

    class PublishStatus(models.TextChoices):
        NOT_SCHEDULED = "not_scheduled", _("Not Scheduled")
        SCHEDULED = "scheduled", _("Scheduled")
        PUBLISHING = "publishing", _("Publishing")
        PUBLISHED = "published", _("Published")
        FAILED = "failed", _("Failed")
        REQUIRES_REAUTH = "requires_reauth", _("Requires Re-authorisation")
        CANCELLED = "cancelled", _("Cancelled")

    post = models.ForeignKey(
        BlogPost, on_delete=models.CASCADE, related_name="social_publications"
    )
    account = models.ForeignKey(
        SocialMediaAccount, on_delete=models.CASCADE, related_name="publications"
    )
    status = models.CharField(
        max_length=25,
        choices=PublishStatus.choices,
        default=PublishStatus.NOT_SCHEDULED,
        db_index=True,
    )

    # Caption / post content (customisable per platform)
    caption = models.TextField(
        blank=True,
        help_text="Platform-specific caption. Auto-generated if blank.",
    )
    hashtags = models.CharField(
        max_length=500,
        blank=True,
        help_text="Space-separated hashtags (e.g. #Tech #AI).",
    )
    include_featured_image = models.BooleanField(default=True)

    # Scheduling
    scheduled_at = models.DateTimeField(null=True, blank=True)

    # Results
    external_post_id = models.CharField(max_length=255, blank=True)
    external_post_url = models.URLField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="social_publications",
    )

    # Retry
    retry_count = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    max_retries = models.PositiveSmallIntegerField(default=3)
    error_detail = models.TextField(blank=True)

    # Engagement metrics (populated by periodic sync where supported by platform API)
    likes_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    shares_count = models.PositiveIntegerField(default=0)
    reach = models.PositiveIntegerField(default=0)
    impressions = models.PositiveIntegerField(default=0)
    metrics_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "blog_social_publications"
        ordering = ["-created_at"]
        unique_together = [("post", "account")]
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
            models.Index(fields=["status", "next_retry_at"]),
        ]
        verbose_name = _("Social Media Publication")
        verbose_name_plural = _("Social Media Publications")

    def __str__(self):
        return (
            f"{self.post.number} → {self.account.get_platform_display()} "
            f"({self.get_status_display()})"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLISHING SCHEDULE
# ═══════════════════════════════════════════════════════════════════════════════


class PublishingSchedule(CompanyScoped):
    """
    Aggregate scheduling record for a BlogPost.
    Links the post to its planned website and social media publication times.
    """

    class ScheduleStatus(models.TextChoices):
        DRAFT = "draft", _("Draft")
        QUEUED = "queued", _("Queued")
        PROCESSING = "processing", _("Processing")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed / Partial")
        CANCELLED = "cancelled", _("Cancelled")

    post = models.OneToOneField(
        BlogPost, on_delete=models.CASCADE, related_name="publishing_schedule"
    )
    status = models.CharField(
        max_length=20,
        choices=ScheduleStatus.choices,
        default=ScheduleStatus.DRAFT,
        db_index=True,
    )
    publish_to_website = models.BooleanField(default=True)
    website_scheduled_at = models.DateTimeField(null=True, blank=True)

    # Social platforms to publish to (FK to specific SocialMediaAccount pks)
    social_accounts = models.ManyToManyField(
        SocialMediaAccount,
        blank=True,
        related_name="scheduled_posts",
    )
    social_scheduled_at = models.DateTimeField(null=True, blank=True)

    scheduled_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="publishing_schedules",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Celery task ID for cancellation / deduplication.",
    )

    class Meta:
        db_table = "blog_publishing_schedules"
        verbose_name = _("Publishing Schedule")
        verbose_name_plural = _("Publishing Schedules")

    def __str__(self):
        return f"Schedule: {self.post.number} ({self.status})"


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLISHING LOG  (immutable audit trail for every publishing operation)
# ═══════════════════════════════════════════════════════════════════════════════


class PublishingLog(CompanyScoped):
    """
    Append-only log of every publishing operation attempt.
    Used for debugging, retries, and the publishing history view.
    """

    class Operation(models.TextChoices):
        PUBLISH_WEBSITE = "publish_website", _("Publish to Website")
        UPDATE_WEBSITE = "update_website", _("Update on Website")
        UNPUBLISH_WEBSITE = "unpublish_website", _("Unpublish from Website")
        PUBLISH_SOCIAL = "publish_social", _("Publish to Social")
        RETRY_WEBSITE = "retry_website", _("Retry Website Publish")
        RETRY_SOCIAL = "retry_social", _("Retry Social Publish")
        HEALTH_CHECK = "health_check", _("Integration Health Check")

    class Result(models.TextChoices):
        SUCCESS = "success", _("Success")
        FAILED = "failed", _("Failed")
        SKIPPED = "skipped", _("Skipped")
        PARTIAL = "partial", _("Partial Success")

    post = models.ForeignKey(
        BlogPost,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="publishing_logs",
    )
    operation = models.CharField(max_length=25, choices=Operation.choices, db_index=True)
    result = models.CharField(
        max_length=10, choices=Result.choices, default=Result.SUCCESS, db_index=True
    )
    platform = models.CharField(
        max_length=50,
        blank=True,
        help_text="Website or social platform name.",
    )
    triggered_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="publishing_log_entries",
    )
    triggered_at = models.DateTimeField(auto_now_add=True)
    duration_ms = models.PositiveIntegerField(
        default=0, help_text="How long the operation took in milliseconds."
    )
    detail = models.TextField(
        blank=True, help_text="Sanitised error detail or success summary."
    )
    http_status_code = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="HTTP status code from the remote API."
    )
    external_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="External post ID returned on success.",
    )
    celery_task_id = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "blog_publishing_logs"
        ordering = ["-triggered_at"]
        indexes = [
            models.Index(fields=["post", "triggered_at"]),
            models.Index(fields=["operation", "result"]),
        ]
        verbose_name = _("Publishing Log")
        verbose_name_plural = _("Publishing Logs")

    def __str__(self):
        post_ref = self.post.number if self.post else "—"
        return f"{post_ref} | {self.get_operation_display()} | {self.get_result_display()}"


# ═══════════════════════════════════════════════════════════════════════════════
# BLOG ENQUIRY  (CRM lead source)
# ═══════════════════════════════════════════════════════════════════════════════


class BlogEnquiry(CompanyScoped):
    """
    Enquiry submitted through the public blog CTA form.
    Automatically generates a CRM Lead on save (via signal/service).
    Rate-limited and spam-protected at the view layer.
    """

    class Status(models.TextChoices):
        NEW = "new", _("New")
        PROCESSING = "processing", _("Processing")
        LEAD_CREATED = "lead_created", _("Lead Created")
        DUPLICATE = "duplicate", _("Duplicate — Merged")
        SPAM = "spam", _("Marked as Spam")
        FAILED = "failed", _("Lead Creation Failed")

    # Enquiry source
    post = models.ForeignKey(
        BlogPost,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="enquiries",
    )
    public_url_submitted_from = models.URLField(
        blank=True,
        help_text="The public blog URL the visitor was on when they submitted.",
    )

    # Contact details (from the public form)
    contact_name = models.CharField(max_length=255)
    contact_email = models.EmailField(db_index=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    contact_company = models.CharField(max_length=255, blank=True)
    message = models.TextField(help_text="Enquiry / requirement message from visitor.")
    consent_given = models.BooleanField(
        default=False,
        help_text="Visitor confirmed consent to be contacted.",
    )

    # UTM / referral attribution
    utm_source = models.CharField(max_length=100, blank=True)
    utm_medium = models.CharField(max_length=100, blank=True)
    utm_campaign = models.CharField(max_length=100, blank=True)
    referrer = models.URLField(blank=True)

    # Submission metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    # CRM integration
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    crm_lead = models.ForeignKey(
        "crm.Lead",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="blog_enquiries",
    )
    processing_error = models.TextField(blank=True)

    class Meta:
        db_table = "blog_enquiries"
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["contact_email", "submitted_at"]),
            models.Index(fields=["status", "submitted_at"]),
        ]
        verbose_name = _("Blog Enquiry")
        verbose_name_plural = _("Blog Enquiries")

    def __str__(self):
        post_ref = self.post.number if self.post else "general"
        return f"Enquiry from {self.contact_email} ({post_ref})"
