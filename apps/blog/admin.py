"""
Blog admin — basic registration so models appear in Django admin.
"""

from django.contrib import admin

from .models import (
    BlogApproval,
    BlogCategory,
    BlogEnquiry,
    BlogPost,
    BlogRevision,
    BlogTag,
    PublishingLog,
    PublishingSchedule,
    SocialMediaAccount,
    SocialMediaPublication,
    WebsiteIntegration,
    WebsitePublication,
)


@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "is_active", "order"]
    list_filter = ["company", "is_active"]
    search_fields = ["name"]


@admin.register(BlogTag)
class BlogTagAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "slug", "is_active"]
    list_filter = ["company", "is_active"]
    search_fields = ["name"]


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ["number", "title", "status", "author", "company", "created_at"]
    list_filter = ["company", "status", "website_sync_status"]
    search_fields = ["title", "number", "slug"]
    readonly_fields = ["number", "slug", "revision_count", "website_idempotency_key"]
    date_hierarchy = "created_at"


@admin.register(BlogRevision)
class BlogRevisionAdmin(admin.ModelAdmin):
    list_display = ["post", "version", "revised_by", "created_at"]
    list_filter = ["post__company"]
    readonly_fields = ["post", "version", "content", "title"]


@admin.register(BlogApproval)
class BlogApprovalAdmin(admin.ModelAdmin):
    list_display = ["post", "decision", "decided_by", "decided_at"]
    list_filter = ["company", "decision"]
    readonly_fields = ["decided_at"]


@admin.register(WebsiteIntegration)
class WebsiteIntegrationAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "integration_type", "status", "is_active"]
    list_filter = ["company", "status", "integration_type"]
    readonly_fields = ["last_health_check", "last_sync_at"]


@admin.register(WebsitePublication)
class WebsitePublicationAdmin(admin.ModelAdmin):
    list_display = ["post", "integration", "sync_status", "published_at"]
    list_filter = ["company", "sync_status"]
    readonly_fields = ["idempotency_key", "retry_count"]


@admin.register(SocialMediaAccount)
class SocialMediaAccountAdmin(admin.ModelAdmin):
    list_display = ["account_name", "platform", "company", "connection_status", "is_active"]
    list_filter = ["company", "platform", "connection_status"]
    # NEVER display raw tokens in list_display
    exclude = ["access_token", "refresh_token", "page_access_token", "oauth_state"]


@admin.register(SocialMediaPublication)
class SocialMediaPublicationAdmin(admin.ModelAdmin):
    list_display = ["post", "account", "status", "published_at"]
    list_filter = ["company", "status", "account__platform"]
    readonly_fields = ["retry_count", "next_retry_at"]


@admin.register(PublishingSchedule)
class PublishingScheduleAdmin(admin.ModelAdmin):
    list_display = ["post", "status", "website_scheduled_at", "social_scheduled_at", "scheduled_by"]
    list_filter = ["company", "status"]


@admin.register(PublishingLog)
class PublishingLogAdmin(admin.ModelAdmin):
    list_display = ["post", "operation", "result", "platform", "triggered_at", "duration_ms"]
    list_filter = ["company", "operation", "result"]
    readonly_fields = ["triggered_at", "duration_ms"]


@admin.register(BlogEnquiry)
class BlogEnquiryAdmin(admin.ModelAdmin):
    list_display = ["contact_email", "contact_name", "post", "status", "submitted_at"]
    list_filter = ["company", "status"]
    readonly_fields = ["ip_address", "user_agent", "submitted_at", "crm_lead"]
