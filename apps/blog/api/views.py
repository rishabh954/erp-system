"""
Blog API ViewSets (DRF)
All endpoints are tenant-scoped and permission-gated.
"""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.api.mixins import TenantScopedViewSetMixin
from core.pagination import StandardResultsSetPagination
from core.tenancy import get_active_company

from apps.blog.models import (
    BlogCategory, BlogEnquiry, BlogPost, BlogTag,
    PublishingLog, SocialMediaAccount, SocialMediaPublication,
    WebsiteIntegration,
)
from apps.blog.api.serializers import (
    BlogCategorySerializer, BlogEnquirySerializer, BlogPostDetailSerializer,
    BlogPostListSerializer, BlogRevisionSerializer, BlogTagSerializer,
    PublishingLogSerializer, SocialMediaAccountSerializer,
    SocialMediaPublicationSerializer, WebsiteIntegrationSerializer,
)


class BlogCategoryViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "blog.read"
    queryset = BlogCategory.objects.all()
    serializer_class = BlogCategorySerializer
    pagination_class = StandardResultsSetPagination

    def get_required_permission(self, request=None):
        if request and request.method in ("POST",):
            return "blog.create"
        if request and request.method in ("PUT", "PATCH"):
            return "blog.update"
        if request and request.method == "DELETE":
            return "blog.delete"
        return self.required_permission

    def perform_create(self, serializer):
        company = get_active_company(self.request)
        serializer.save(company=company, created_by=self.request.user)


class BlogTagViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "blog.read"
    queryset = BlogTag.objects.all()
    serializer_class = BlogTagSerializer
    pagination_class = StandardResultsSetPagination

    def get_required_permission(self, request=None):
        if request and request.method == "POST":
            return "blog.create"
        if request and request.method in ("PUT", "PATCH"):
            return "blog.update"
        if request and request.method == "DELETE":
            return "blog.delete"
        return self.required_permission

    def perform_create(self, serializer):
        company = get_active_company(self.request)
        serializer.save(company=company, created_by=self.request.user)


class BlogPostViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "blog.read"
    queryset = BlogPost.objects.all()
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.action == "list":
            return BlogPostListSerializer
        return BlogPostDetailSerializer

    def get_required_permission(self, request=None):
        action = getattr(self, "action", None)
        if action in ("submit_for_approval", "schedule"):
            return "blog.update"
        if action in ("approve", "reject"):
            return "blog.approve"
        if action in ("publish_website", "publish_social"):
            return "blog.create"
        if action == "unpublish":
            return "blog.delete"
        if request and request.method == "POST":
            return "blog.create"
        if request and request.method in ("PUT", "PATCH"):
            return "blog.update"
        if request and request.method == "DELETE":
            return "blog.delete"
        return self.required_permission

    def perform_create(self, serializer):
        company = get_active_company(self.request)
        self.request.company = company
        post = serializer.save(
            company=company,
            author=self.request.user,
            created_by=self.request.user,
        )

    @action(detail=True, methods=["post"])
    def submit_for_approval(self, request, pk=None):
        post = self.get_object()
        from apps.blog.services import BlogService
        svc = BlogService(user=request.user, company=post.company)
        post = svc.submit_for_approval(post)
        return Response({"status": post.status})

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        post = self.get_object()
        from apps.blog.services import BlogService
        svc = BlogService(user=request.user, company=post.company)
        post = svc.approve_post(post, comment=request.data.get("comment", ""))
        return Response({"status": post.status})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        post = self.get_object()
        reason = request.data.get("reason", "")
        if not reason:
            return Response({"error": "reason is required"}, status=status.HTTP_400_BAD_REQUEST)
        from apps.blog.services import BlogService
        svc = BlogService(user=request.user, company=post.company)
        post = svc.reject_post(post, reason=reason)
        return Response({"status": post.status})

    @action(detail=True, methods=["post"])
    def publish_website(self, request, pk=None):
        post = self.get_object()
        integration_id = request.data.get("integration_id")
        try:
            integration = WebsiteIntegration.objects.get(
                pk=integration_id or "", company=post.company, is_active=True
            )
        except WebsiteIntegration.DoesNotExist:
            integration = WebsiteIntegration.objects.filter(
                company=post.company, is_active=True
            ).first()
        if not integration:
            return Response({"error": "No active website integration."}, status=400)
        from apps.blog.tasks import publish_post_to_website_task
        task = publish_post_to_website_task.delay(str(post.pk), str(integration.pk), str(request.user.pk))
        return Response({"task_id": task.id, "status": "queued"})

    @action(detail=True, methods=["post"])
    def publish_social(self, request, pk=None):
        post = self.get_object()
        account_ids = request.data.get("account_ids", [])
        if not account_ids:
            return Response({"error": "account_ids required"}, status=400)
        from apps.blog.tasks import publish_post_to_social_task
        tasks = []
        for aid in account_ids:
            t = publish_post_to_social_task.delay(
                str(post.pk), aid,
                request.data.get("caption", ""),
                request.data.get("hashtags", ""),
                str(request.user.pk),
            )
            tasks.append(t.id)
        return Response({"task_ids": tasks, "status": "queued"})

    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        post = self.get_object()
        integration = WebsiteIntegration.objects.filter(
            company=post.company, is_active=True
        ).first()
        if not integration:
            return Response({"error": "No website integration."}, status=400)
        from apps.blog.tasks import unpublish_post_from_website_task
        task = unpublish_post_from_website_task.delay(str(post.pk), str(integration.pk), str(request.user.pk))
        return Response({"task_id": task.id, "status": "queued"})

    @action(detail=True, methods=["get"])
    def revisions(self, request, pk=None):
        post = self.get_object()
        revisions = post.revisions.all()
        serializer = BlogRevisionSerializer(revisions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def publishing_logs(self, request, pk=None):
        post = self.get_object()
        logs = post.publishing_logs.all()[:50]
        serializer = PublishingLogSerializer(logs, many=True)
        return Response(serializer.data)


class WebsiteIntegrationViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "blog.read"
    queryset = WebsiteIntegration.objects.all()
    serializer_class = WebsiteIntegrationSerializer

    def get_required_permission(self, request=None):
        if request and request.method in ("POST", "PUT", "PATCH"):
            return "blog.update"
        if request and request.method == "DELETE":
            return "blog.delete"
        return self.required_permission

    @action(detail=True, methods=["post"])
    def health_check(self, request, pk=None):
        integration = self.get_object()
        from apps.blog.services import WebsiteIntegrationService
        svc = WebsiteIntegrationService(user=request.user, company=integration.company)
        ok = svc.check_health(integration)
        return Response({"status": "connected" if ok else "error", "ok": ok})


class SocialMediaAccountViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    required_permission = "blog.read"
    queryset = SocialMediaAccount.objects.all()
    serializer_class = SocialMediaAccountSerializer

    @action(detail=True, methods=["post"])
    def disconnect(self, request, pk=None):
        account = self.get_object()
        account.connection_status = SocialMediaAccount.ConnectionStatus.DISCONNECTED
        account.access_token = ""
        account.refresh_token = ""
        account.page_access_token = ""
        account.is_active = False
        account.save()
        return Response({"status": "disconnected"})


class SocialMediaPublicationViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    required_permission = "blog.read"
    queryset = SocialMediaPublication.objects.all()
    serializer_class = SocialMediaPublicationSerializer


class PublishingLogViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    required_permission = "blog.read"
    queryset = PublishingLog.objects.all()
    serializer_class = PublishingLogSerializer


class BlogEnquiryViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    required_permission = "blog.read"
    queryset = BlogEnquiry.objects.all()
    serializer_class = BlogEnquirySerializer
