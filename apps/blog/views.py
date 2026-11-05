"""
Blog Views — ERP internal UI
All views require authentication and enforce module permissions via CompanyMixin.
"""

import json
import logging

from django.contrib import messages
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import (
    DetailView, ListView, TemplateView, View,
)

from core.mixins import CompanyMixin

from .forms import (
    BlogApprovalForm, BlogCategoryForm, BlogEnquiryForm,
    BlogPostForm, BlogScheduleForm, BlogTagForm,
    SocialMediaPublishForm, WebsiteIntegrationForm,
)
from .models import (
    BlogCategory, BlogEnquiry, BlogPost, BlogTag, PublishingLog, SocialMediaAccount,
    SocialMediaPublication, WebsiteIntegration, WebsitePublication,
)
from .services import BlogService, WebsiteIntegrationService

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

class BlogDashboardView(CompanyMixin, TemplateView):
    template_name = "blog/dashboard.html"
    required_permission = "blog.read"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.company()
        base_qs = BlogPost.objects.filter(company=c, is_deleted=False)

        ctx.update({
            "total_posts": base_qs.count(),
            "draft_count": base_qs.filter(status="draft").count(),
            "pending_count": base_qs.filter(status="pending_approval").count(),
            "approved_count": base_qs.filter(status="approved").count(),
            "scheduled_count": base_qs.filter(status="scheduled").count(),
            "published_count": base_qs.filter(status="published").count(),
            "rejected_count": base_qs.filter(status="rejected").count(),
            "archived_count": base_qs.filter(status="archived").count(),
            "failed_sync_count": base_qs.filter(website_sync_status="failed").count(),
            "recent_posts": base_qs.select_related("author", "category").order_by("-created_at")[:8],
            "pending_approvals": base_qs.filter(status="pending_approval").select_related("author")[:5],
            "recent_enquiries": BlogEnquiry.objects.filter(company=c).order_by("-submitted_at")[:5],
            "total_enquiries": BlogEnquiry.objects.filter(company=c).count(),
            "leads_generated": BlogEnquiry.objects.filter(company=c, status="lead_created").count(),
            "connected_social_accounts": SocialMediaAccount.objects.filter(
                company=c, is_active=True, connection_status="connected"
            ).count(),
            "website_integration": WebsiteIntegration.objects.filter(company=c, is_active=True).first(),
        })
        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# BLOG POSTS
# ═══════════════════════════════════════════════════════════════════════════════

class BlogPostListView(CompanyMixin, ListView):
    template_name = "blog/posts/list.html"
    context_object_name = "posts"
    paginate_by = 25
    required_permission = "blog.read"

    def get_queryset(self):
        c = self.company()
        qs = BlogPost.objects.filter(company=c, is_deleted=False)\
            .select_related("author", "category").order_by("-created_at")

        q = self.request.GET.get("q", "")
        status = self.request.GET.get("status", "")
        category = self.request.GET.get("category", "")

        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(number__icontains=q))
        if status:
            qs = qs.filter(status=status)
        if category:
            qs = qs.filter(category__slug=category)

        # Authors see only their own posts unless they have approve/publish perms
        user = self.request.user
        co = c
        if not user.has_module_permission("blog", "approve", company=co) and \
           not user.has_module_permission("blog", "delete", company=co):
            qs = qs.filter(author=user)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = BlogPost.Status.choices
        ctx["categories"] = BlogCategory.objects.filter(
            company=self.company(), is_active=True, is_deleted=False
        )
        return ctx


class BlogPostCreateView(CompanyMixin, View):
    template_name = "blog/posts/create.html"
    required_permission_module = "blog"

    def get(self, request):
        form = BlogPostForm(company=self.company())
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = BlogPostForm(request.POST, request.FILES, company=self.company())
        if form.is_valid():
            svc = BlogService(user=request.user, company=self.company())
            try:
                post = svc.create_post(
                    title=form.cleaned_data["title"],
                    content_raw=form.cleaned_data.get("content_raw", ""),
                    subtitle=form.cleaned_data.get("subtitle", ""),
                    excerpt=form.cleaned_data.get("excerpt", ""),
                    category=form.cleaned_data.get("category"),
                    featured_image=form.cleaned_data.get("featured_image"),
                    featured_image_alt=form.cleaned_data.get("featured_image_alt", ""),
                    og_image=form.cleaned_data.get("og_image"),
                    seo_title=form.cleaned_data.get("seo_title", ""),
                    meta_description=form.cleaned_data.get("meta_description", ""),
                    meta_keywords=form.cleaned_data.get("meta_keywords", ""),
                    canonical_url=form.cleaned_data.get("canonical_url", ""),
                    enable_enquiry_form=form.cleaned_data.get("enable_enquiry_form", True),
                    is_featured=form.cleaned_data.get("is_featured", False),
                    allow_comments=form.cleaned_data.get("allow_comments", False),
                )
                if form.cleaned_data.get("tags"):
                    post.tags.set(form.cleaned_data["tags"])
                messages.success(request, f"Blog post '{post.title}' created.")
                return redirect("blog:post_detail", pk=post.pk)
            except Exception as exc:
                messages.error(request, str(exc))
        return render(request, self.template_name, {"form": form})


class BlogPostDetailView(CompanyMixin, DetailView):
    template_name = "blog/posts/detail.html"
    context_object_name = "post"
    required_permission = "blog.read"

    def get_queryset(self):
        return BlogPost.objects.filter(company=self.company(), is_deleted=False)\
            .select_related("author", "category", "published_by")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        post = self.object
        ctx["revisions"] = post.revisions.all()[:10]
        ctx["approvals"] = post.approvals.all()[:10]
        ctx["website_publication"] = WebsitePublication.objects.filter(post=post).first()
        ctx["social_publications"] = post.social_publications.select_related("account").all()
        ctx["enquiries"] = post.enquiries.all()[:5]
        ctx["publishing_logs"] = post.publishing_logs.all()[:10]
        ctx["approval_form"] = BlogApprovalForm()
        ctx["social_form"] = SocialMediaPublishForm(company=self.company())
        ctx["schedule_form"] = BlogScheduleForm(company=self.company())
        ctx["website_integration"] = WebsiteIntegration.objects.filter(
            company=self.company(), is_active=True
        ).first()
        return ctx


class BlogPostUpdateView(CompanyMixin, View):
    template_name = "blog/posts/edit.html"
    required_permission_module = "blog"

    def get(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company(), is_deleted=False)
        form = BlogPostForm(instance=post, company=self.company())
        return render(request, self.template_name, {"form": form, "post": post})

    def post(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company(), is_deleted=False)
        form = BlogPostForm(request.POST, request.FILES, instance=post, company=self.company())
        if form.is_valid():
            svc = BlogService(user=request.user, company=self.company())
            try:
                update_data = {k: v for k, v in form.cleaned_data.items() if k != "tags"}
                updated = svc.update_post(post, **update_data)
                if form.cleaned_data.get("tags") is not None:
                    updated.tags.set(form.cleaned_data["tags"])
                messages.success(request, "Blog post updated.")
                return redirect("blog:post_detail", pk=updated.pk)
            except Exception as exc:
                messages.error(request, str(exc))
        return render(request, self.template_name, {"form": form, "post": post})


class BlogPostDeleteView(CompanyMixin, View):
    required_permission = "blog.delete"

    def post(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company(), is_deleted=False)
        svc = BlogService(user=request.user, company=self.company())
        try:
            svc.delete_post(post)
            messages.success(request, f"Post '{post.title}' deleted.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("blog:posts")


class BlogPostDuplicateView(CompanyMixin, View):
    required_permission = "blog.create"

    def post(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company(), is_deleted=False)
        svc = BlogService(user=request.user, company=self.company())
        new_post = svc.duplicate_post(post)
        messages.success(request, f"Duplicated as '{new_post.title}'.")
        return redirect("blog:post_detail", pk=new_post.pk)


class BlogPostArchiveView(CompanyMixin, View):
    required_permission = "blog.update"

    def post(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company(), is_deleted=False)
        svc = BlogService(user=request.user, company=self.company())
        svc.archive_post(post)
        messages.success(request, "Post archived.")
        return redirect("blog:post_detail", pk=post.pk)


# ═══════════════════════════════════════════════════════════════════════════════
# APPROVAL WORKFLOW
# ═══════════════════════════════════════════════════════════════════════════════

class SubmitForApprovalView(CompanyMixin, View):
    required_permission = "blog.update"

    def post(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company(), is_deleted=False)
        svc = BlogService(user=request.user, company=self.company())
        try:
            svc.submit_for_approval(post)
            messages.success(request, "Post submitted for approval.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("blog:post_detail", pk=post.pk)


class ApprovalQueueView(CompanyMixin, ListView):
    template_name = "blog/approval_queue.html"
    context_object_name = "posts"
    paginate_by = 20
    required_permission = "blog.approve"

    def get_queryset(self):
        return BlogPost.objects.filter(
            company=self.company(), status="pending_approval", is_deleted=False
        ).select_related("author", "category").order_by("-created_at")


class ApprovePostView(CompanyMixin, View):
    required_permission = "blog.approve"

    def post(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company())
        form = BlogApprovalForm(request.POST)
        if form.is_valid():
            svc = BlogService(user=request.user, company=self.company())
            try:
                svc.approve_post(post, comment=form.cleaned_data.get("comment", ""))
                messages.success(request, f"Post '{post.title}' approved.")
            except ValueError as exc:
                messages.error(request, str(exc))
        return redirect("blog:post_detail", pk=post.pk)


class RejectPostView(CompanyMixin, View):
    required_permission = "blog.approve"

    def post(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company())
        form = BlogApprovalForm(request.POST)
        if form.is_valid():
            reason = form.cleaned_data.get("comment", "")
            if not reason:
                messages.error(request, "Rejection reason is required.")
                return redirect("blog:post_detail", pk=post.pk)
            svc = BlogService(user=request.user, company=self.company())
            try:
                svc.reject_post(post, reason=reason)
                messages.warning(request, "Post rejected.")
            except ValueError as exc:
                messages.error(request, str(exc))
        return redirect("blog:post_detail", pk=post.pk)


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULING & PUBLISHING
# ═══════════════════════════════════════════════════════════════════════════════

class SchedulePostView(CompanyMixin, View):
    required_permission = "blog.create"

    def post(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company())
        form = BlogScheduleForm(request.POST, company=self.company())
        if form.is_valid():
            svc = BlogService(user=request.user, company=self.company())
            try:
                social_ids = form.cleaned_data.get("social_account_ids", [])
                svc.schedule_post(post, form.cleaned_data["publish_at"], social_account_ids=social_ids)
                messages.success(request, "Post scheduled.")
            except ValueError as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, "Invalid schedule data.")
        return redirect("blog:post_detail", pk=post.pk)


class PublishNowView(CompanyMixin, View):
    """Publish an approved post immediately to the website."""
    required_permission = "blog.create"

    def post(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company())
        integration = WebsiteIntegration.objects.filter(
            company=self.company(), is_active=True
        ).first()
        if not integration:
            messages.error(request, "No active website integration configured.")
            return redirect("blog:post_detail", pk=post.pk)

        from .tasks import publish_post_to_website_task
        publish_post_to_website_task.delay(str(post.pk), str(integration.pk), str(request.user.pk))
        messages.success(request, "Publishing started. The page will update when complete.")
        return redirect("blog:post_detail", pk=post.pk)


class UnpublishPostView(CompanyMixin, View):
    required_permission = "blog.delete"

    def post(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company())
        integration = WebsiteIntegration.objects.filter(company=self.company(), is_active=True).first()
        if not integration:
            messages.error(request, "No website integration configured.")
            return redirect("blog:post_detail", pk=post.pk)
        from .tasks import unpublish_post_from_website_task
        unpublish_post_from_website_task.delay(str(post.pk), str(integration.pk), str(request.user.pk))
        messages.success(request, "Unpublishing started.")
        return redirect("blog:post_detail", pk=post.pk)


class PublishCalendarView(CompanyMixin, TemplateView):
    template_name = "blog/publishing_calendar.html"
    required_permission = "blog.read"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.company()
        scheduled = BlogPost.objects.filter(
            company=c, status__in=["scheduled", "published"], is_deleted=False
        ).values("pk", "title", "scheduled_publish_at", "published_at", "status")
        ctx["calendar_posts"] = json.dumps([
            {
                "id": str(p["pk"]),
                "title": p["title"],
                "date": (
                    p["scheduled_publish_at"] or p["published_at"]
                ).isoformat() if (p["scheduled_publish_at"] or p["published_at"]) else None,
                "status": p["status"],
            }
            for p in scheduled
            if (p["scheduled_publish_at"] or p["published_at"])
        ], default=str)
        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# SOCIAL MEDIA
# ═══════════════════════════════════════════════════════════════════════════════

class SocialAccountListView(CompanyMixin, ListView):
    template_name = "blog/social/accounts.html"
    context_object_name = "accounts"
    required_permission = "blog.read"

    def get_queryset(self):
        return SocialMediaAccount.objects.filter(
            company=self.company(), is_deleted=False
        ).order_by("platform", "account_name")


class SocialAccountConnectView(CompanyMixin, View):
    """Initiates the OAuth flow for a social platform."""
    required_permission = "blog.create"

    def get(self, request, platform):
        from .oauth_helpers import get_oauth_redirect_url
        try:
            redirect_url = get_oauth_redirect_url(platform, request, self.company())
            return redirect(redirect_url)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("blog:social_accounts")


class SocialOAuthCallbackView(CompanyMixin, View):
    """Handles the OAuth callback from the social platform."""

    def get(self, request, platform):
        from .oauth_helpers import handle_oauth_callback
        try:
            account = handle_oauth_callback(platform, request, self.company())
            messages.success(request, f"{account.get_platform_display()} connected: {account.account_name}.")
        except Exception as exc:
            messages.error(request, f"OAuth error: {exc}")
        return redirect("blog:social_accounts")


class SocialAccountDisconnectView(CompanyMixin, View):
    required_permission = "blog.create"

    def post(self, request, pk):
        account = get_object_or_404(SocialMediaAccount, pk=pk, company=self.company())
        account.connection_status = SocialMediaAccount.ConnectionStatus.DISCONNECTED
        account.access_token = ""
        account.refresh_token = ""
        account.page_access_token = ""
        account.is_active = False
        account.save()
        messages.success(request, f"{account.account_name} disconnected.")
        return redirect("blog:social_accounts")


class PublishToSocialView(CompanyMixin, View):
    required_permission = "blog.create"

    def post(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk, company=self.company())
        form = SocialMediaPublishForm(request.POST, company=self.company())
        if form.is_valid():
            from .tasks import publish_post_to_social_task
            account_ids = form.cleaned_data["account_ids"]
            caption = form.cleaned_data.get("caption", "")
            hashtags = form.cleaned_data.get("hashtags", "")
            for account_id in account_ids:
                publish_post_to_social_task.delay(
                    str(post.pk), account_id, caption, hashtags, str(request.user.pk)
                )
            messages.success(request, f"Publishing to {len(account_ids)} platform(s) started.")
        else:
            messages.error(request, "Please select at least one social account.")
        return redirect("blog:post_detail", pk=post.pk)


class SocialPublishingQueueView(CompanyMixin, ListView):
    template_name = "blog/social/publishing_queue.html"
    context_object_name = "publications"
    paginate_by = 25
    required_permission = "blog.read"

    def get_queryset(self):
        return SocialMediaPublication.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related("post", "account").order_by("-created_at")


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSITE INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════

class WebsiteIntegrationView(CompanyMixin, View):
    template_name = "blog/website_integration.html"
    required_permission_module = "blog"

    def get(self, request):
        integration = WebsiteIntegration.objects.filter(
            company=self.company(), is_deleted=False
        ).first()
        form = WebsiteIntegrationForm(instance=integration)
        return render(request, self.template_name, {
            "form": form, "integration": integration,
            "publications": WebsitePublication.objects.filter(
                company=self.company(), is_deleted=False
            ).select_related("post").order_by("-created_at")[:20],
        })

    def post(self, request):
        integration = WebsiteIntegration.objects.filter(
            company=self.company(), is_deleted=False
        ).first()
        form = WebsiteIntegrationForm(request.POST, instance=integration)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = self.company()
            obj.updated_by = request.user
            if not integration:
                obj.created_by = request.user
            # Only update credentials if a new value was provided
            for cred_field in ["api_key", "api_secret", "webhook_secret"]:
                if not form.cleaned_data.get(cred_field):
                    setattr(obj, cred_field, getattr(integration, cred_field, "") if integration else "")
            obj.save()
            messages.success(request, "Website integration settings saved.")
            return redirect("blog:website_integration")
        return render(request, self.template_name, {"form": form, "integration": integration})


class WebsiteHealthCheckView(CompanyMixin, View):
    required_permission = "blog.read"

    def post(self, request, pk):
        integration = get_object_or_404(WebsiteIntegration, pk=pk, company=self.company())
        svc = WebsiteIntegrationService(user=request.user, company=self.company())
        ok = svc.check_health(integration)
        if ok:
            messages.success(request, "Website integration is connected and healthy.")
        else:
            messages.error(request, f"Health check failed: {integration.error_message}")
        return redirect("blog:website_integration")


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLISHING HISTORY
# ═══════════════════════════════════════════════════════════════════════════════

class PublishingHistoryView(CompanyMixin, ListView):
    template_name = "blog/publishing_history.html"
    context_object_name = "logs"
    paginate_by = 50
    required_permission = "blog.read"

    def get_queryset(self):
        return PublishingLog.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related("post", "triggered_by").order_by("-triggered_at")


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORIES & TAGS
# ═══════════════════════════════════════════════════════════════════════════════

class BlogCategoryListView(CompanyMixin, ListView):
    template_name = "blog/categories/list.html"
    context_object_name = "categories"
    required_permission = "blog.read"

    def get_queryset(self):
        return BlogCategory.objects.filter(company=self.company(), is_deleted=False)\
            .annotate(post_count=Count("posts")).order_by("order", "name")


class BlogCategoryCreateView(CompanyMixin, View):
    template_name = "blog/categories/form.html"
    required_permission = "blog.create"

    def get(self, request):
        return render(request, self.template_name, {"form": BlogCategoryForm(company=self.company())})

    def post(self, request):
        form = BlogCategoryForm(request.POST, request.FILES, company=self.company())
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = self.company()
            obj.created_by = request.user
            obj.save()
            messages.success(request, "Category created.")
            return redirect("blog:categories")
        return render(request, self.template_name, {"form": form})


class BlogTagListView(CompanyMixin, ListView):
    template_name = "blog/tags/list.html"
    context_object_name = "tags"
    required_permission = "blog.read"

    def get_queryset(self):
        return BlogTag.objects.filter(company=self.company(), is_deleted=False)\
            .annotate(post_count=Count("posts")).order_by("name")


class BlogTagCreateView(CompanyMixin, View):
    template_name = "blog/tags/form.html"
    required_permission = "blog.create"

    def get(self, request):
        return render(request, self.template_name, {"form": BlogTagForm()})

    def post(self, request):
        form = BlogTagForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = self.company()
            obj.created_by = request.user
            obj.save()
            messages.success(request, "Tag created.")
            return redirect("blog:tags")
        return render(request, self.template_name, {"form": form})


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════

class BlogAnalyticsView(CompanyMixin, TemplateView):
    template_name = "blog/analytics.html"
    required_permission = "blog.read"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.company()

        posts_qs = BlogPost.objects.filter(company=c, is_deleted=False)
        enquiries_qs = BlogEnquiry.objects.filter(company=c)
        social_qs = SocialMediaPublication.objects.filter(company=c, is_deleted=False)

        # Top posts by enquiry count
        top_posts = posts_qs.annotate(
            enq_count=Count("enquiries")
        ).filter(enq_count__gt=0).order_by("-enq_count")[:10]

        # Social stats by platform
        social_stats = {}
        for pub in social_qs.filter(status="published").select_related("account"):
            p = pub.account.get_platform_display()
            social_stats.setdefault(p, {"count": 0, "likes": 0, "comments": 0, "shares": 0})
            social_stats[p]["count"] += 1
            social_stats[p]["likes"] += pub.likes_count
            social_stats[p]["comments"] += pub.comments_count
            social_stats[p]["shares"] += pub.shares_count

        # Publishing log summary
        log_qs = PublishingLog.objects.filter(company=c)

        ctx.update({
            "total_posts": posts_qs.count(),
            "published_posts": posts_qs.filter(status="published").count(),
            "scheduled_posts": posts_qs.filter(status="scheduled").count(),
            "failed_pubs": posts_qs.filter(website_sync_status="failed").count(),
            "total_enquiries": enquiries_qs.count(),
            "leads_generated": enquiries_qs.filter(status="lead_created").count(),
            "conversion_rate": _safe_pct(
                enquiries_qs.filter(status="lead_created").count(),
                enquiries_qs.count()
            ),
            "top_posts": top_posts,
            "social_stats": social_stats,
            "total_social_published": social_qs.filter(status="published").count(),
            "failed_social": social_qs.filter(status="failed").count(),
            "publish_success_rate": _safe_pct(
                log_qs.filter(result="success").count(),
                log_qs.count()
            ),
        })
        return ctx


def _safe_pct(numerator, denominator) -> float:
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# BLOG ENQUIRY (public-facing — no login required)
# ═══════════════════════════════════════════════════════════════════════════════

class BlogEnquirySubmitView(View):
    """
    Public enquiry form endpoint.
    Rate-limited per IP. No authentication required.
    """

    def post(self, request, post_pk):
        from apps.blog.models import BlogEnquiry, BlogPost

        # Identify the company from the post
        try:
            post = BlogPost.objects.get(pk=post_pk, status="published", is_deleted=False)
        except BlogPost.DoesNotExist:
            return JsonResponse({"error": "Post not found."}, status=404)

        form = BlogEnquiryForm(request.POST)
        if not form.is_valid():
            return JsonResponse({"errors": form.errors}, status=400)

        # Spam protection: rate limit by IP
        ip = _get_client_ip(request)
        from django.core.cache import cache
        cache_key = f"blog_enquiry_ip:{ip}"
        count = cache.get(cache_key, 0)
        if count >= 5:
            return JsonResponse({"error": "Too many enquiries. Please try again later."}, status=429)
        cache.set(cache_key, count + 1, timeout=3600)

        enquiry = BlogEnquiry(
            company=post.company,
            post=post,
            public_url_submitted_from=request.META.get("HTTP_REFERER", ""),
            ip_address=ip,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            utm_source=request.GET.get("utm_source", ""),
            utm_medium=request.GET.get("utm_medium", ""),
            utm_campaign=request.GET.get("utm_campaign", ""),
            referrer=request.META.get("HTTP_REFERER", ""),
            **{k: v for k, v in form.cleaned_data.items()},
        )
        enquiry.save()
        return JsonResponse({"success": True, "message": "Thank you! We will be in touch shortly."})


def _get_client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


# ═══════════════════════════════════════════════════════════════════════════════
# BLOG ENQUIRIES LIST (internal)
# ═══════════════════════════════════════════════════════════════════════════════

class BlogEnquiryListView(CompanyMixin, ListView):
    template_name = "blog/enquiries/list.html"
    context_object_name = "enquiries"
    paginate_by = 25
    required_permission = "blog.read"

    def get_queryset(self):
        return BlogEnquiry.objects.filter(company=self.company())\
            .select_related("post", "crm_lead").order_by("-submitted_at")
