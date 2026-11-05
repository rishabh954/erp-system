"""
Blog Celery Tasks
All long-running publishing, retry, and health-check operations run here.
Views and services dispatch tasks; tasks never block HTTP requests.

Task catalogue:
  publish_post_to_website_task     — publish a single post to the website
  update_post_on_website_task      — update an already-published post
  unpublish_post_from_website_task — remove from website
  publish_post_to_social_task      — publish to a single social account
  publish_scheduled_posts          — beat: poll for due scheduled posts
  retry_failed_website_pubs        — beat: retry PENDING_RETRY website pubs
  retry_failed_social_pubs         — beat: retry PENDING_RETRY social pubs
  check_integration_health         — beat: health-check all active integrations
  process_blog_enquiry_task        — process a new enquiry and create CRM lead
  sync_social_metrics_task         — update engagement metrics from APIs
"""

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


# ─── Website Publishing Tasks ─────────────────────────────────────────────────


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 0},  # service layer manages retries
    name="apps.blog.tasks.publish_post_to_website_task",
)
def publish_post_to_website_task(self, post_id: str, integration_id: str, user_id: str | None = None):
    """Publish a single blog post to the company website."""
    from apps.blog.models import BlogPost, WebsiteIntegration
    from apps.blog.services import WebsiteIntegrationService

    try:
        post = BlogPost.objects.select_related("company").get(pk=post_id, is_deleted=False)
        integration = WebsiteIntegration.objects.get(pk=integration_id, is_active=True)
    except (BlogPost.DoesNotExist, WebsiteIntegration.DoesNotExist) as exc:
        logger.error("publish_post_to_website_task: object not found — %s", exc)
        return {"status": "error", "detail": str(exc)}

    user = _get_user(user_id)
    svc = WebsiteIntegrationService(user=user, company=post.company)
    pub = svc.publish_post(post, integration, user=user)
    self.update_state(state="SUCCESS", meta={"sync_status": pub.sync_status})
    return {"status": pub.sync_status, "public_url": pub.public_url}


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 0},
    name="apps.blog.tasks.update_post_on_website_task",
)
def update_post_on_website_task(self, post_id: str, integration_id: str, user_id: str | None = None):
    """Push updated content for an already-published post."""
    from apps.blog.models import BlogPost, WebsiteIntegration
    from apps.blog.services import WebsiteIntegrationService

    try:
        post = BlogPost.objects.get(pk=post_id, is_deleted=False)
        integration = WebsiteIntegration.objects.get(pk=integration_id, is_active=True)
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}

    user = _get_user(user_id)
    svc = WebsiteIntegrationService(user=user, company=post.company)
    pub = svc.update_post(post, integration, user=user)
    return {"status": pub.sync_status}


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 0},
    name="apps.blog.tasks.unpublish_post_from_website_task",
)
def unpublish_post_from_website_task(self, post_id: str, integration_id: str, user_id: str | None = None):
    """Remove a post from the public website."""
    from apps.blog.models import BlogPost, WebsiteIntegration
    from apps.blog.services import WebsiteIntegrationService

    try:
        post = BlogPost.objects.get(pk=post_id, is_deleted=False)
        integration = WebsiteIntegration.objects.get(pk=integration_id)
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}

    user = _get_user(user_id)
    svc = WebsiteIntegrationService(user=user, company=post.company)
    pub = svc.unpublish_post(post, integration, user=user)
    return {"status": pub.sync_status}


# ─── Social Media Publishing Tasks ───────────────────────────────────────────


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 0},
    name="apps.blog.tasks.publish_post_to_social_task",
)
def publish_post_to_social_task(
    self,
    post_id: str,
    account_id: str,
    caption: str = "",
    hashtags: str = "",
    user_id: str | None = None,
):
    """Publish a blog post to a single social media account."""
    from apps.blog.models import BlogPost, SocialMediaAccount
    from apps.blog.services import SocialMediaService

    try:
        post = BlogPost.objects.get(pk=post_id, is_deleted=False)
        account = SocialMediaAccount.objects.get(pk=account_id, is_active=True)
    except Exception as exc:
        logger.error("publish_post_to_social_task: %s", exc)
        return {"status": "error", "detail": str(exc)}

    user = _get_user(user_id)
    svc = SocialMediaService(user=user, company=post.company)
    pub = svc.publish_to_account(post, account, caption=caption, hashtags=hashtags, user=user)
    return {"status": pub.status, "external_post_url": pub.external_post_url}


# ─── Beat Tasks ───────────────────────────────────────────────────────────────


@shared_task(name="apps.blog.tasks.publish_scheduled_posts")
def publish_scheduled_posts():
    """
    Fires every 5 minutes via beat.
    Finds SCHEDULED posts whose scheduled_publish_at has passed and publishes them.
    """
    from apps.blog.models import BlogPost, WebsiteIntegration

    now = timezone.now()
    due_posts = BlogPost.objects.filter(
        status=BlogPost.Status.SCHEDULED,
        scheduled_publish_at__lte=now,
        is_deleted=False,
    ).select_related("company")

    dispatched = 0
    for post in due_posts:
        integration = WebsiteIntegration.objects.filter(
            company=post.company, is_active=True
        ).first()
        if not integration:
            logger.warning(
                "No active website integration for company %s — skipping post %s",
                post.company_id, post.pk,
            )
            continue

        publish_post_to_website_task.delay(str(post.pk), str(integration.pk))

        # Also publish to scheduled social accounts
        try:
            schedule = post.publishing_schedule
            for account in schedule.social_accounts.filter(is_active=True):
                publish_post_to_social_task.delay(str(post.pk), str(account.pk))
        except Exception:
            pass  # no schedule attached

        dispatched += 1

    return f"Dispatched {dispatched} scheduled post(s)."


@shared_task(name="apps.blog.tasks.retry_failed_website_pubs")
def retry_failed_website_pubs():
    """
    Fires every 10 minutes via beat.
    Retries PENDING_RETRY website publications whose next_retry_at has passed.
    """
    from apps.blog.models import WebsitePublication

    now = timezone.now()
    pending = WebsitePublication.objects.filter(
        sync_status=WebsitePublication.SyncStatus.PENDING_RETRY,
        next_retry_at__lte=now,
        is_deleted=False,
    ).select_related("post", "integration")

    retried = 0
    for pub in pending:
        publish_post_to_website_task.delay(
            str(pub.post_id), str(pub.integration_id)
        )
        retried += 1

    return f"Queued {retried} website publication retry/retries."


@shared_task(name="apps.blog.tasks.retry_failed_social_pubs")
def retry_failed_social_pubs():
    """
    Fires every 10 minutes via beat.
    Retries FAILED social publications within retry limits.
    """
    from apps.blog.models import SocialMediaPublication

    now = timezone.now()
    pending = SocialMediaPublication.objects.filter(
        status=SocialMediaPublication.PublishStatus.FAILED,
        next_retry_at__lte=now,
        retry_count__lt=models_max_retries_expr(),
        is_deleted=False,
    ).select_related("post", "account")

    retried = 0
    for pub in pending:
        if pub.retry_count >= pub.max_retries:
            continue
        publish_post_to_social_task.delay(str(pub.post_id), str(pub.account_id))
        retried += 1

    return f"Queued {retried} social publication retry/retries."


@shared_task(name="apps.blog.tasks.check_integration_health")
def check_integration_health():
    """
    Fires every 30 minutes via beat.
    Pings all active website integrations and updates their status.
    """
    from apps.blog.models import WebsiteIntegration
    from apps.blog.services import WebsiteIntegrationService

    integrations = WebsiteIntegration.objects.filter(is_active=True, is_deleted=False)
    results = {}
    for integration in integrations:
        svc = WebsiteIntegrationService(company=integration.company)
        ok = svc.check_health(integration)
        results[str(integration.pk)] = "ok" if ok else "error"

    return results


@shared_task(name="apps.blog.tasks.process_blog_enquiry_task")
def process_blog_enquiry_task(enquiry_id: str):
    """Process a new blog enquiry and create a CRM lead."""
    from apps.blog.models import BlogEnquiry
    from apps.blog.services import BlogEnquiryService

    try:
        enquiry = BlogEnquiry.objects.select_related("company", "post").get(pk=enquiry_id)
    except BlogEnquiry.DoesNotExist:
        logger.error("process_blog_enquiry_task: BlogEnquiry %s not found", enquiry_id)
        return {"status": "not_found"}

    svc = BlogEnquiryService(company=enquiry.company)
    enquiry = svc.process_enquiry(enquiry)
    return {"status": enquiry.status, "lead_id": str(enquiry.crm_lead_id) if enquiry.crm_lead_id else None}


@shared_task(name="apps.blog.tasks.sync_social_metrics_task")
def sync_social_metrics_task():
    """
    Fires daily via beat.
    Fetches updated engagement metrics from social platform APIs for published posts.
    Only runs where platform APIs support metric endpoints (Facebook/Instagram Insights).
    """
    from apps.blog.models import SocialMediaPublication

    published = SocialMediaPublication.objects.filter(
        status=SocialMediaPublication.PublishStatus.PUBLISHED,
        account__platform__in=["facebook", "instagram"],
        external_post_id__isnull=False,
        is_deleted=False,
    ).exclude(external_post_id="").select_related("account", "post")

    updated = 0
    for pub in published:
        try:
            _sync_metrics_for_pub(pub)
            updated += 1
        except Exception as exc:
            logger.warning("Metrics sync failed for pub %s: %s", pub.pk, exc)

    return f"Synced metrics for {updated} publication(s)."


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _get_user(user_id: str | None):
    if not user_id:
        return None
    try:
        from apps.authentication.models import User
        return User.objects.get(pk=user_id)
    except Exception:
        return None


def models_max_retries_expr():
    """Return a raw value used in filter; Django ORM F-expression not needed here."""
    return 3  # default max retries; compared against pub.max_retries at Python level


def _sync_metrics_for_pub(pub):
    """Fetch metrics from Facebook/Instagram Graph API for a single publication."""

    account = pub.account
    if not account.page_access_token or not pub.external_post_id:
        return

    platform = account.platform
    if platform == "facebook":
        url = (
            f"https://graph.facebook.com/v19.0/{pub.external_post_id}"
            f"?fields=likes.summary(true),comments.summary(true),shares"
            f"&access_token={account.page_access_token}"
        )
    elif platform == "instagram":
        url = (
            f"https://graph.facebook.com/v19.0/{pub.external_post_id}"
            f"?fields=like_count,comments_count"
            f"&access_token={account.page_access_token}"
        )
    else:
        return

    import requests as req
    response = req.get(url, timeout=15)
    if not response.ok:
        return

    data = response.json()
    if platform == "facebook":
        pub.likes_count = data.get("likes", {}).get("summary", {}).get("total_count", pub.likes_count)
        pub.comments_count = data.get("comments", {}).get("summary", {}).get("total_count", pub.comments_count)
        pub.shares_count = data.get("shares", {}).get("count", pub.shares_count)
    elif platform == "instagram":
        pub.likes_count = data.get("like_count", pub.likes_count)
        pub.comments_count = data.get("comments_count", pub.comments_count)

    pub.metrics_updated_at = timezone.now()
    pub.save(update_fields=["likes_count", "comments_count", "shares_count", "metrics_updated_at", "updated_at"])
