"""
Blog API Serializers
"""

from rest_framework import serializers

from core.api.fields import TenantModelSerializer

from apps.blog.models import (
    BlogApproval,
    BlogCategory,
    BlogEnquiry,
    BlogPost,
    BlogRevision,
    BlogTag,
    PublishingLog,
    SocialMediaAccount,
    SocialMediaPublication,
    WebsiteIntegration,
    WebsitePublication,
)


class BlogCategorySerializer(TenantModelSerializer):
    post_count = serializers.SerializerMethodField()

    class Meta:
        model = BlogCategory
        fields = ["id", "name", "slug", "description", "parent", "is_active", "order", "post_count"]
        read_only_fields = ["id", "slug", "company", "created_at", "updated_at"]

    def get_post_count(self, obj):
        return obj.posts.filter(is_deleted=False).count()


class BlogTagSerializer(TenantModelSerializer):
    class Meta:
        model = BlogTag
        fields = ["id", "name", "slug", "is_active"]
        read_only_fields = ["id", "slug", "company", "created_at", "updated_at"]


class BlogPostListSerializer(TenantModelSerializer):
    """Lightweight serializer for list views."""
    author_name = serializers.CharField(source="author.full_name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    tag_list = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = [
            "id", "number", "title", "subtitle", "slug", "excerpt",
            "status", "website_sync_status", "is_featured",
            "author_name", "category_name", "tag_list",
            "published_at", "scheduled_publish_at", "website_url",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_tag_list(self, obj):
        return list(obj.tags.values_list("name", flat=True))


class BlogPostDetailSerializer(TenantModelSerializer):
    tags = BlogTagSerializer(many=True, read_only=True)
    category = BlogCategorySerializer(read_only=True)
    author_name = serializers.CharField(source="author.full_name", read_only=True)
    is_live = serializers.BooleanField(read_only=True)
    public_url = serializers.CharField(read_only=True)
    effective_seo_title = serializers.CharField(read_only=True)

    class Meta:
        model = BlogPost
        fields = "__all__"
        read_only_fields = [
            "id", "number", "slug", "company", "created_by", "updated_by",
            "created_at", "updated_at", "website_idempotency_key",
            "revision_count", "website_post_id", "website_url",
            "website_sync_status", "website_synced_at", "website_sync_error",
        ]


class BlogRevisionSerializer(serializers.ModelSerializer):
    revised_by_name = serializers.CharField(source="revised_by.full_name", read_only=True, default="")

    class Meta:
        model = BlogRevision
        fields = "__all__"
        read_only_fields = ["id", "post", "version", "revised_by", "created_at"]


class BlogApprovalSerializer(TenantModelSerializer):
    decided_by_name = serializers.CharField(source="decided_by.full_name", read_only=True, default="")

    class Meta:
        model = BlogApproval
        fields = ["id", "post", "decision", "decided_by", "decided_by_name", "comment", "decided_at"]
        read_only_fields = ["id", "decided_at", "company", "created_at", "updated_at"]


class WebsiteIntegrationSerializer(TenantModelSerializer):
    class Meta:
        model = WebsiteIntegration
        fields = [
            "id", "name", "website_url", "integration_type",
            "api_endpoint", "status", "last_health_check",
            "last_sync_at", "error_message", "max_retries",
            "retry_backoff_seconds", "is_active",
        ]
        # Credentials are NEVER exposed via API
        read_only_fields = ["id", "status", "last_health_check", "last_sync_at", "error_message"]


class WebsitePublicationSerializer(TenantModelSerializer):
    class Meta:
        model = WebsitePublication
        fields = [
            "id", "post", "integration", "sync_status",
            "external_post_id", "public_url", "published_at",
            "retry_count", "next_retry_at", "error_detail",
        ]
        read_only_fields = fields


class SocialMediaAccountSerializer(TenantModelSerializer):
    is_token_expired = serializers.BooleanField(read_only=True)
    needs_reauth = serializers.BooleanField(read_only=True)

    class Meta:
        model = SocialMediaAccount
        fields = [
            "id", "platform", "account_name", "account_id", "account_username",
            "account_url", "account_avatar_url", "connection_status",
            "granted_permissions", "connected_at", "last_used_at", "is_active",
            "is_token_expired", "needs_reauth",
        ]
        # access_token / refresh_token / page_access_token NEVER in API output
        read_only_fields = [
            "id", "connection_status", "granted_permissions", "connected_at", "last_used_at",
            "is_token_expired", "needs_reauth",
        ]


class SocialMediaPublicationSerializer(TenantModelSerializer):
    platform = serializers.CharField(source="account.get_platform_display", read_only=True)
    account_name = serializers.CharField(source="account.account_name", read_only=True)

    class Meta:
        model = SocialMediaPublication
        fields = [
            "id", "post", "account", "platform", "account_name",
            "status", "caption", "hashtags", "scheduled_at",
            "external_post_id", "external_post_url", "published_at",
            "retry_count", "error_detail",
            "likes_count", "comments_count", "shares_count",
            "reach", "impressions", "metrics_updated_at",
        ]
        read_only_fields = [
            "id", "status", "external_post_id", "external_post_url",
            "published_at", "retry_count", "error_detail",
            "likes_count", "comments_count", "shares_count", "reach",
            "impressions", "metrics_updated_at",
        ]


class PublishingLogSerializer(serializers.ModelSerializer):
    triggered_by_name = serializers.CharField(
        source="triggered_by.full_name", read_only=True, default=""
    )

    class Meta:
        model = PublishingLog
        fields = [
            "id", "post", "operation", "result", "platform",
            "triggered_by", "triggered_by_name", "triggered_at",
            "duration_ms", "detail", "http_status_code", "external_id",
        ]
        read_only_fields = fields


class BlogEnquirySerializer(TenantModelSerializer):
    post_title = serializers.CharField(source="post.title", read_only=True, default="")
    lead_number = serializers.CharField(source="crm_lead.number", read_only=True, default="")

    class Meta:
        model = BlogEnquiry
        fields = [
            "id", "post", "post_title", "contact_name", "contact_email",
            "contact_phone", "contact_company", "message", "consent_given",
            "utm_source", "utm_medium", "utm_campaign",
            "status", "crm_lead", "lead_number", "submitted_at",
        ]
        read_only_fields = [
            "id", "status", "crm_lead", "lead_number", "submitted_at",
            "company", "created_at", "updated_at",
        ]
