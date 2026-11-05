"""
Blog Services Layer
Separates all business logic from views and Celery tasks.

Services:
  BlogService              — CRUD, approval workflow, versioning, scheduling
  WebsiteIntegrationService — publish / update / unpublish to the company website
  SocialMediaService        — per-platform publish / retry
  BlogEnquiryService        — CRM lead creation from public enquiry forms
"""

import logging
import time
import uuid as uuid_lib
from datetime import timedelta

import requests
from django.db import transaction
from django.utils import timezone

from apps.blog.models import (
    BlogApproval,
    BlogEnquiry,
    BlogPost,
    PublishingLog,
    SocialMediaAccount,
    SocialMediaPublication,
    WebsiteIntegration,
    WebsitePublication,
)
from core.services import BaseService

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# BLOG SERVICE
# ═══════════════════════════════════════════════════════════════════════════════


class BlogService(BaseService):
    """All blog post lifecycle operations."""

    MODULE = "blog"

    # ── Create / Edit ─────────────────────────────────────────────────────────

    def create_post(self, *, title: str, content_raw: str, **kwargs) -> BlogPost:
        """Create a new DRAFT blog post owned by the current user/company."""
        self.check_permission(self.MODULE, "create")
        post = BlogPost(
            company=self.company,
            title=title,
            content_raw=content_raw,
            author=self.user,
            created_by=self.user,
            status=BlogPost.Status.DRAFT,
            **kwargs,
        )
        post.save()
        self.log_activity("create", self.MODULE, "BlogPost", post.pk, f"Created blog post {post.number}")
        return post

    def update_post(self, post: BlogPost, **kwargs) -> BlogPost:
        """Update fields on a blog post that is not yet published."""
        self.check_permission(self.MODULE, "update")
        if post.company_id != self.company.pk:
            raise PermissionError("Cross-company update not allowed.")

        # Mark user for revision snapshot signal
        post._current_user = self.user

        for field, value in kwargs.items():
            setattr(post, field, value)
        post.updated_by = self.user
        post.save()
        self.log_activity("update", self.MODULE, "BlogPost", post.pk, f"Updated blog post {post.number}")
        return post

    def duplicate_post(self, post: BlogPost) -> BlogPost:
        """Create a draft copy of an existing post."""
        self.check_permission(self.MODULE, "create")
        new_post = BlogPost(
            company=self.company,
            title=f"Copy of {post.title}",
            subtitle=post.subtitle,
            content_raw=post.content_raw,
            excerpt=post.excerpt,
            category=post.category,
            seo_title=post.seo_title,
            meta_description=post.meta_description,
            meta_keywords=post.meta_keywords,
            author=self.user,
            created_by=self.user,
            status=BlogPost.Status.DRAFT,
        )
        new_post.save()
        new_post.tags.set(post.tags.all())
        self.log_activity("create", self.MODULE, "BlogPost", new_post.pk, f"Duplicated from {post.number}")
        return new_post

    def delete_post(self, post: BlogPost) -> None:
        """Soft-delete. Cannot delete a published post without unpublishing first."""
        self.check_permission(self.MODULE, "delete")
        if post.status == BlogPost.Status.PUBLISHED:
            raise ValueError("Unpublish the post before deleting it.")
        post.delete(deleted_by=self.user)
        self.log_activity("delete", self.MODULE, "BlogPost", post.pk, f"Deleted {post.number}")

    def archive_post(self, post: BlogPost) -> BlogPost:
        """Move post to Archived status."""
        self.check_permission(self.MODULE, "update")
        post.status = BlogPost.Status.ARCHIVED
        post.updated_by = self.user
        post.save(update_fields=["status", "updated_by", "updated_at"])
        self.log_activity("update", self.MODULE, "BlogPost", post.pk, f"Archived {post.number}")
        return post

    # ── Approval Workflow ─────────────────────────────────────────────────────

    def submit_for_approval(self, post: BlogPost) -> BlogPost:
        """Employee submits a DRAFT/REJECTED post for manager approval."""
        self.check_permission(self.MODULE, "update")
        if post.status not in (BlogPost.Status.DRAFT, BlogPost.Status.REJECTED):
            raise ValueError(f"Cannot submit a post with status '{post.status}'.")
        if not post.title or not post.content_raw:
            raise ValueError("A title and content are required before submitting.")

        with transaction.atomic():
            post.status = BlogPost.Status.PENDING_APPROVAL
            post.updated_by = self.user
            post.save(update_fields=["status", "updated_by", "updated_at"])

            BlogApproval.objects.create(
                company=self.company,
                post=post,
                decision=BlogApproval.Decision.SUBMITTED,
                decided_by=self.user,
                created_by=self.user,
                comment="Submitted for approval.",
            )

        self._notify_approvers(post, "Blog Post Pending Approval",
                               f"'{post.title}' has been submitted for approval by {self.user.full_name}.")
        self.log_activity("approve", self.MODULE, "BlogPost", post.pk, f"Submitted {post.number} for approval")
        return post

    def approve_post(self, post: BlogPost, comment: str = "") -> BlogPost:
        """Manager approves a pending post."""
        self.check_permission(self.MODULE, "approve")
        if post.status != BlogPost.Status.PENDING_APPROVAL:
            raise ValueError("Only posts with status PENDING_APPROVAL can be approved.")

        with transaction.atomic():
            post.status = BlogPost.Status.APPROVED
            post.updated_by = self.user
            post.save(update_fields=["status", "updated_by", "updated_at"])

            BlogApproval.objects.create(
                company=self.company,
                post=post,
                decision=BlogApproval.Decision.APPROVED,
                decided_by=self.user,
                created_by=self.user,
                comment=comment,
            )

        self.send_notification(
            recipient=post.author,
            title="Blog Post Approved",
            message=f"Your post '{post.title}' has been approved and is ready to publish.",
            notification_type="success",
            action_url=f"/blog/posts/{post.pk}/",
            company=self.company,
        )
        self.log_activity("approve", self.MODULE, "BlogPost", post.pk, f"Approved {post.number}")
        return post

    def reject_post(self, post: BlogPost, reason: str) -> BlogPost:
        """Manager rejects a pending post with a reason."""
        self.check_permission(self.MODULE, "approve")
        if post.status != BlogPost.Status.PENDING_APPROVAL:
            raise ValueError("Only posts with status PENDING_APPROVAL can be rejected.")
        if not reason:
            raise ValueError("A rejection reason is required.")

        with transaction.atomic():
            post.status = BlogPost.Status.REJECTED
            post.updated_by = self.user
            post.save(update_fields=["status", "updated_by", "updated_at"])

            BlogApproval.objects.create(
                company=self.company,
                post=post,
                decision=BlogApproval.Decision.REJECTED,
                decided_by=self.user,
                created_by=self.user,
                comment=reason,
            )

        self.send_notification(
            recipient=post.author,
            title="Blog Post Rejected",
            message=f"Your post '{post.title}' was rejected. Reason: {reason}",
            notification_type="warning",
            action_url=f"/blog/posts/{post.pk}/",
            company=self.company,
        )
        self.log_activity("approve", self.MODULE, "BlogPost", post.pk, f"Rejected {post.number}: {reason}")
        return post

    def schedule_post(self, post: BlogPost, publish_at, social_account_ids=None) -> BlogPost:
        """
        Schedule an APPROVED post for future publishing.
        publish_at must be a timezone-aware datetime in the future.
        """
        self.check_permission(self.MODULE, "create")  # 'schedule' maps to create permission
        if post.status != BlogPost.Status.APPROVED:
            raise ValueError("Only APPROVED posts can be scheduled.")
        if not publish_at or publish_at <= timezone.now():
            raise ValueError("Scheduled time must be in the future.")

        with transaction.atomic():
            post.status = BlogPost.Status.SCHEDULED
            post.scheduled_publish_at = publish_at
            post.updated_by = self.user
            post.save(update_fields=["status", "scheduled_publish_at", "updated_by", "updated_at"])

            schedule, _ = post.publishing_schedule if hasattr(post, "publishing_schedule") else (None, None)
            from apps.blog.models import PublishingSchedule
            schedule, _ = PublishingSchedule.objects.get_or_create(
                post=post,
                defaults={"company": self.company, "created_by": self.user},
            )
            schedule.status = PublishingSchedule.ScheduleStatus.QUEUED
            schedule.website_scheduled_at = publish_at
            schedule.scheduled_by = self.user
            if social_account_ids:
                schedule.social_accounts.set(
                    SocialMediaAccount.objects.filter(
                        company=self.company, pk__in=social_account_ids, is_active=True
                    )
                )
            schedule.save()

        self.log_activity("create", self.MODULE, "BlogPost", post.pk,
                          f"Scheduled {post.number} for {publish_at.isoformat()}")
        return post

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _notify_approvers(self, post: BlogPost, title: str, message: str):
        """Notify all users who have blog.approve permission in this company."""
        from apps.authentication.models import ModulePermission, UserCompany
        approver_roles = ModulePermission.objects.filter(
            module=self.MODULE, can_approve=True
        ).values_list("role", flat=True)

        approver_users = list(
            UserCompany.objects.filter(
                company=self.company, is_active=True, role__in=approver_roles
            ).select_related("user").values_list("user", flat=True).distinct()
        )

        from apps.authentication.models import User
        for user_pk in approver_users:
            try:
                user = User.objects.get(pk=user_pk)
                self.send_notification(
                    recipient=user,
                    title=title,
                    message=message,
                    notification_type="info",
                    action_url="/blog/approval-queue/",
                    company=self.company,
                )
            except Exception as exc:
                logger.warning("Failed to notify approver %s: %s", user_pk, exc)


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSITE INTEGRATION SERVICE
# ═══════════════════════════════════════════════════════════════════════════════


class WebsiteIntegrationService(BaseService):
    """
    Handles all communication between the ERP and the company website.
    Uses idempotency keys to prevent duplicate articles.
    All external calls are wrapped with timeout, retry logic, and detailed logging.
    """

    MODULE = "blog"
    DEFAULT_TIMEOUT = 30  # seconds

    def publish_post(self, post: BlogPost, integration: WebsiteIntegration, user=None) -> WebsitePublication:
        """
        Publish a blog post to the website. Idempotent — safe to retry.
        Does NOT mark the post as published until the website confirms success.
        """
        self.check_permission(self.MODULE, "create")

        if post.status not in (BlogPost.Status.APPROVED, BlogPost.Status.SCHEDULED):
            raise ValueError("Post must be APPROVED or SCHEDULED before publishing.")

        # Ensure idempotency key exists
        if not post.website_idempotency_key:
            post.website_idempotency_key = uuid_lib.uuid4().hex
            post.save(update_fields=["website_idempotency_key"])

        pub, _ = WebsitePublication.objects.get_or_create(
            post=post,
            integration=integration,
            defaults={
                "company": post.company,
                "idempotency_key": post.website_idempotency_key,
                "created_by": user or self.user,
            },
        )

        # Already successfully published — return early
        if pub.sync_status == WebsitePublication.SyncStatus.PUBLISHED:
            return pub

        pub.sync_status = WebsitePublication.SyncStatus.SYNCING
        pub.save(update_fields=["sync_status", "updated_at"])
        post.website_sync_status = BlogPost.WebsiteSyncStatus.SYNCING
        post.save(update_fields=["website_sync_status", "updated_at"])

        start_ms = int(time.time() * 1000)
        payload = self._build_payload(post, integration)
        result_status = PublishingLog.Result.FAILED
        external_id = ""
        public_url = ""
        error_detail = ""
        http_code = None

        try:
            response = requests.post(
                integration.api_endpoint,
                json=payload,
                headers=self._build_headers(integration),
                timeout=self.DEFAULT_TIMEOUT,
            )
            http_code = response.status_code

            if response.ok:
                data = response.json()
                external_id = str(data.get("id", data.get("post_id", "")))
                public_url = data.get("url", data.get("link", ""))

                pub.sync_status = WebsitePublication.SyncStatus.PUBLISHED
                pub.external_post_id = external_id
                pub.public_url = public_url
                pub.published_at = timezone.now()
                pub.published_by = user or self.user
                pub.retry_count = pub.retry_count  # no change
                pub.response_data = data
                pub.save()

                post.website_sync_status = BlogPost.WebsiteSyncStatus.SYNCED
                post.website_post_id = external_id
                post.website_url = public_url
                post.website_synced_at = timezone.now()
                post.website_sync_error = ""
                post.status = BlogPost.Status.PUBLISHED
                post.published_at = timezone.now()
                post.published_by = user or self.user
                post.save()

                result_status = PublishingLog.Result.SUCCESS
            else:
                error_detail = f"HTTP {http_code}: {response.text[:500]}"
                self._handle_publish_failure(post, pub, error_detail, integration)

        except requests.exceptions.Timeout:
            error_detail = "Request timed out."
            self._handle_publish_failure(post, pub, error_detail, integration)
        except requests.exceptions.ConnectionError as exc:
            error_detail = f"Connection error: {str(exc)[:300]}"
            self._handle_publish_failure(post, pub, error_detail, integration)
        except Exception as exc:
            error_detail = f"Unexpected error: {str(exc)[:300]}"
            self._handle_publish_failure(post, pub, error_detail, integration)
        finally:
            duration_ms = int(time.time() * 1000) - start_ms
            PublishingLog.objects.create(
                company=post.company,
                post=post,
                operation=PublishingLog.Operation.PUBLISH_WEBSITE,
                result=result_status,
                platform=integration.name,
                triggered_by=user or self.user,
                duration_ms=duration_ms,
                detail=error_detail or "Published successfully.",
                http_status_code=http_code,
                external_id=external_id,
                created_by=user or self.user,
            )

        return pub

    def update_post(self, post: BlogPost, integration: WebsiteIntegration, user=None) -> WebsitePublication:
        """Push updates to an already-published article on the website."""
        self.check_permission(self.MODULE, "update")
        try:
            pub = WebsitePublication.objects.get(post=post, integration=integration)
        except WebsitePublication.DoesNotExist:
            return self.publish_post(post, integration, user)

        if not pub.external_post_id:
            return self.publish_post(post, integration, user)

        payload = self._build_payload(post, integration)
        payload["idempotency_key"] = pub.idempotency_key

        start_ms = int(time.time() * 1000)
        result_status = PublishingLog.Result.FAILED
        error_detail = ""
        http_code = None

        try:
            url = f"{integration.api_endpoint.rstrip('/')}/{pub.external_post_id}/"
            response = requests.put(
                url,
                json=payload,
                headers=self._build_headers(integration),
                timeout=self.DEFAULT_TIMEOUT,
            )
            http_code = response.status_code
            if response.ok:
                data = response.json()
                pub.sync_status = WebsitePublication.SyncStatus.UPDATED
                pub.updated_at_website = timezone.now()
                pub.response_data = data
                pub.save()
                post.website_sync_status = BlogPost.WebsiteSyncStatus.SYNCED
                post.website_synced_at = timezone.now()
                post.website_sync_error = ""
                post.save(update_fields=["website_sync_status", "website_synced_at", "website_sync_error", "updated_at"])
                result_status = PublishingLog.Result.SUCCESS
            else:
                error_detail = f"HTTP {http_code}: {response.text[:500]}"
                pub.error_detail = error_detail
                pub.save(update_fields=["error_detail", "updated_at"])
        except Exception as exc:
            error_detail = str(exc)[:300]
            pub.error_detail = error_detail
            pub.save(update_fields=["error_detail", "updated_at"])
        finally:
            duration_ms = int(time.time() * 1000) - start_ms
            PublishingLog.objects.create(
                company=post.company,
                post=post,
                operation=PublishingLog.Operation.UPDATE_WEBSITE,
                result=result_status,
                platform=integration.name,
                triggered_by=user or self.user,
                duration_ms=duration_ms,
                detail=error_detail or "Updated successfully.",
                http_status_code=http_code,
                created_by=user or self.user,
            )
        return pub

    def unpublish_post(self, post: BlogPost, integration: WebsiteIntegration, user=None) -> WebsitePublication:
        """Remove the article from the public website."""
        self.check_permission(self.MODULE, "delete")
        try:
            pub = WebsitePublication.objects.get(post=post, integration=integration)
        except WebsitePublication.DoesNotExist:
            raise ValueError("No website publication record found for this post.")

        if not pub.external_post_id:
            raise ValueError("Post has no external article ID — cannot unpublish.")

        start_ms = int(time.time() * 1000)
        result_status = PublishingLog.Result.FAILED
        error_detail = ""
        http_code = None

        try:
            url = f"{integration.api_endpoint.rstrip('/')}/{pub.external_post_id}/"
            response = requests.delete(
                url,
                headers=self._build_headers(integration),
                timeout=self.DEFAULT_TIMEOUT,
            )
            http_code = response.status_code
            if response.ok or http_code == 404:
                pub.sync_status = WebsitePublication.SyncStatus.UNPUBLISHED
                pub.save(update_fields=["sync_status", "updated_at"])
                post.website_sync_status = BlogPost.WebsiteSyncStatus.NOT_SYNCED
                post.status = BlogPost.Status.APPROVED  # revert to approved, not deleted
                post.website_url = ""
                post.save(update_fields=["website_sync_status", "status", "website_url", "updated_at"])
                result_status = PublishingLog.Result.SUCCESS
            else:
                error_detail = f"HTTP {http_code}: {response.text[:500]}"
        except Exception as exc:
            error_detail = str(exc)[:300]
        finally:
            duration_ms = int(time.time() * 1000) - start_ms
            PublishingLog.objects.create(
                company=post.company,
                post=post,
                operation=PublishingLog.Operation.UNPUBLISH_WEBSITE,
                result=result_status,
                platform=integration.name,
                triggered_by=user or self.user,
                duration_ms=duration_ms,
                detail=error_detail or "Unpublished successfully.",
                http_status_code=http_code,
                created_by=user or self.user,
            )
        return pub

    def check_health(self, integration: WebsiteIntegration) -> bool:
        """Ping the integration endpoint and update status."""
        try:
            health_url = f"{integration.api_endpoint.rstrip('/')}/health/"
            response = requests.get(
                health_url,
                headers=self._build_headers(integration),
                timeout=10,
            )
            is_ok = response.ok
        except Exception:
            is_ok = False

        integration.status = (
            WebsiteIntegration.Status.CONNECTED if is_ok
            else WebsiteIntegration.Status.ERROR
        )
        integration.last_health_check = timezone.now()
        if not is_ok:
            integration.error_message = "Health check failed."
        else:
            integration.error_message = ""
        integration.save(update_fields=["status", "last_health_check", "error_message", "updated_at"])
        return is_ok

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_headers(self, integration: WebsiteIntegration) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if integration.api_key:
            headers["Authorization"] = f"Bearer {integration.api_key}"
        return headers

    def _build_payload(self, post: BlogPost, integration: WebsiteIntegration) -> dict:
        """Build the request payload, applying any field_mapping from the integration config."""
        default_payload = {
            "idempotency_key": post.website_idempotency_key,
            "title": post.title,
            "subtitle": post.subtitle,
            "slug": post.slug,
            "content": post.content,
            "excerpt": post.excerpt,
            "seo_title": post.effective_seo_title,
            "meta_description": post.meta_description,
            "meta_keywords": post.meta_keywords,
            "featured_image_url": (
                post.featured_image.url if post.featured_image else None
            ),
            "og_image_url": post.og_image.url if post.og_image else None,
            "author_name": post.author.full_name if post.author else "",
            "category": post.category.name if post.category else "",
            "tags": list(post.tags.values_list("name", flat=True)),
            "published_at": post.published_at.isoformat() if post.published_at else None,
            "enable_enquiry_form": post.enable_enquiry_form,
        }

        if integration.field_mapping:
            mapped = {}
            for erp_field, cms_field in integration.field_mapping.items():
                if erp_field in default_payload:
                    mapped[cms_field] = default_payload.pop(erp_field)
            default_payload.update(mapped)

        return default_payload

    def _handle_publish_failure(
        self,
        post: BlogPost,
        pub: WebsitePublication,
        error_detail: str,
        integration: WebsiteIntegration,
    ):
        pub.retry_count += 1
        backoff = integration.retry_backoff_seconds * (2 ** min(pub.retry_count - 1, 5))
        if pub.retry_count < integration.max_retries:
            pub.sync_status = WebsitePublication.SyncStatus.PENDING_RETRY
            pub.next_retry_at = timezone.now() + timedelta(seconds=backoff)
        else:
            pub.sync_status = WebsitePublication.SyncStatus.FAILED
            pub.next_retry_at = None
        pub.error_detail = error_detail
        pub.save()
        post.website_sync_status = BlogPost.WebsiteSyncStatus.FAILED
        post.website_sync_error = error_detail
        post.save(update_fields=["website_sync_status", "website_sync_error", "updated_at"])


# ═══════════════════════════════════════════════════════════════════════════════
# SOCIAL MEDIA SERVICE
# ═══════════════════════════════════════════════════════════════════════════════


class SocialMediaService(BaseService):
    """
    Routes social media publish calls to platform-specific adapters.
    Adapters live in apps/blog/social_adapters.py (built in Phase 6/7).
    """

    MODULE = "blog"

    def publish_to_account(
        self,
        post: BlogPost,
        account: SocialMediaAccount,
        caption: str = "",
        hashtags: str = "",
        user=None,
    ) -> SocialMediaPublication:
        """Publish a post to a single connected social media account."""
        self.check_permission(self.MODULE, "create")

        if not account.is_active:
            raise ValueError(f"Account '{account.account_name}' is not active.")
        if account.needs_reauth:
            raise ValueError(
                f"Account '{account.account_name}' requires re-authorisation before publishing."
            )

        pub, _ = SocialMediaPublication.objects.get_or_create(
            post=post,
            account=account,
            defaults={
                "company": post.company,
                "caption": caption,
                "hashtags": hashtags,
                "created_by": user or self.user,
            },
        )

        # Already published — idempotent
        if pub.status == SocialMediaPublication.PublishStatus.PUBLISHED:
            return pub

        if not caption:
            caption = self._auto_caption(post, account)
        pub.caption = caption
        pub.hashtags = hashtags
        pub.status = SocialMediaPublication.PublishStatus.PUBLISHING
        pub.save(update_fields=["caption", "hashtags", "status", "updated_at"])

        from apps.blog import social_adapters
        adapter = social_adapters.get_adapter(account.platform)

        start_ms = int(time.time() * 1000)
        result_status = PublishingLog.Result.FAILED
        error_detail = ""
        external_id = ""

        try:
            result = adapter.publish(post=post, account=account, publication=pub)
            external_id = result.get("id", "")
            external_url = result.get("url", result.get("permalink", ""))

            pub.status = SocialMediaPublication.PublishStatus.PUBLISHED
            pub.external_post_id = external_id
            pub.external_post_url = external_url
            pub.published_at = timezone.now()
            pub.published_by = user or self.user
            pub.error_detail = ""
            pub.save()
            result_status = PublishingLog.Result.SUCCESS

            account.last_used_at = timezone.now()
            account.save(update_fields=["last_used_at", "updated_at"])

        except ValueError as exc:
            # Platform limitation or capability error
            error_detail = str(exc)[:500]
            pub.status = SocialMediaPublication.PublishStatus.FAILED
            pub.error_detail = error_detail
            pub.retry_count += 1
            pub.save()

        except Exception as exc:
            error_detail = str(exc)[:500]
            pub.retry_count += 1
            if pub.retry_count < pub.max_retries:
                backoff = 60 * (2 ** min(pub.retry_count - 1, 5))
                pub.status = SocialMediaPublication.PublishStatus.FAILED
                pub.next_retry_at = timezone.now() + timedelta(seconds=backoff)
            else:
                pub.status = SocialMediaPublication.PublishStatus.FAILED
                pub.next_retry_at = None
            pub.error_detail = error_detail
            pub.save()

            # Check if it's a token expiry
            if "expired" in error_detail.lower() or "unauthorized" in error_detail.lower():
                account.connection_status = SocialMediaAccount.ConnectionStatus.REQUIRES_REAUTH
                account.save(update_fields=["connection_status", "updated_at"])
                pub.status = SocialMediaPublication.PublishStatus.REQUIRES_REAUTH
                pub.save(update_fields=["status", "updated_at"])

        finally:
            duration_ms = int(time.time() * 1000) - start_ms
            PublishingLog.objects.create(
                company=post.company,
                post=post,
                operation=PublishingLog.Operation.PUBLISH_SOCIAL,
                result=result_status,
                platform=account.get_platform_display(),
                triggered_by=user or self.user,
                duration_ms=duration_ms,
                detail=error_detail or f"Published to {account.account_name}.",
                external_id=external_id,
                created_by=user or self.user,
            )

        return pub

    def _auto_caption(self, post: BlogPost, account: SocialMediaAccount) -> str:
        """Generate a default caption from the blog post content."""
        excerpt = post.excerpt or post.title
        if len(excerpt) > 280:
            excerpt = excerpt[:277] + "..."
        url = post.public_url or ""
        caption = f"{excerpt}\n\n{url}" if url else excerpt
        return caption


# ═══════════════════════════════════════════════════════════════════════════════
# BLOG ENQUIRY SERVICE  (CRM Lead generation)
# ═══════════════════════════════════════════════════════════════════════════════


class BlogEnquiryService(BaseService):
    """
    Processes public blog enquiry form submissions.
    Creates CRM leads, prevents duplicates, notifies the assigned sales user.
    """

    MODULE = "blog"
    DUPLICATE_WINDOW_HOURS = 24  # same email + same company within 24h = duplicate

    @transaction.atomic
    def process_enquiry(self, enquiry: BlogEnquiry) -> BlogEnquiry:
        """
        Main entry point. Called by the Celery task after an enquiry is saved.
        1. Check for recent duplicate
        2. Create/merge CRM Lead
        3. Notify sales team
        4. Update enquiry status
        """
        if enquiry.status != BlogEnquiry.Status.NEW:
            return enquiry

        enquiry.status = BlogEnquiry.Status.PROCESSING
        enquiry.save(update_fields=["status", "updated_at"])

        try:
            lead = self._get_or_create_lead(enquiry)
            enquiry.crm_lead = lead
            enquiry.status = BlogEnquiry.Status.LEAD_CREATED
            enquiry.save(update_fields=["crm_lead", "status", "updated_at"])

            self._notify_sales_team(enquiry, lead)
            self.log_activity(
                "create", self.MODULE, "BlogEnquiry", enquiry.pk,
                f"CRM Lead {lead.number} created from blog enquiry by {enquiry.contact_email}"
            )

        except Exception as exc:
            logger.error("BlogEnquiry processing failed for %s: %s", enquiry.pk, exc)
            enquiry.status = BlogEnquiry.Status.FAILED
            enquiry.processing_error = str(exc)[:500]
            enquiry.save(update_fields=["status", "processing_error", "updated_at"])

        return enquiry

    def _get_or_create_lead(self, enquiry: BlogEnquiry):
        """
        Reuse an existing lead for the same email within the duplicate window.
        Otherwise create a new CRM Lead with source=BLOG.
        """
        from apps.crm.models import Lead

        cutoff = timezone.now() - timedelta(hours=self.DUPLICATE_WINDOW_HOURS)
        existing = (
            Lead.objects.select_for_update()
            .filter(
                company=enquiry.company,
                email__iexact=enquiry.contact_email,
                created_at__gte=cutoff,
                is_deleted=False,
            )
            .order_by("-created_at")
            .first()
        )

        if existing:
            # Merge: add the message as a note activity
            from apps.crm.models import LeadActivity
            LeadActivity.objects.create(
                company=enquiry.company,
                lead=existing,
                activity_type=LeadActivity.ActivityType.NOTE,
                subject=f"Blog enquiry via {enquiry.post.title if enquiry.post else 'website'}",
                description=enquiry.message,
                assigned_to=existing.assigned_to,
                created_by=None,
            )
            enquiry.status = BlogEnquiry.Status.DUPLICATE
            enquiry.save(update_fields=["status", "updated_at"])
            return existing

        # Build source — prefer UTM source if available
        source = Lead.Source.WEB
        if enquiry.utm_source:
            utm = enquiry.utm_source.lower()
            if "facebook" in utm or "instagram" in utm or "linkedin" in utm:
                source = Lead.Source.SOCIAL
            elif "email" in utm:
                source = Lead.Source.EMAIL

        post_title = enquiry.post.title if enquiry.post else "Blog"
        lead = Lead(
            company=enquiry.company,
            name=enquiry.contact_name,
            company_name=enquiry.contact_company,
            email=enquiry.contact_email,
            phone=enquiry.contact_phone,
            source=source,
            notes=(
                f"Enquiry via: {post_title}\n"
                f"URL: {enquiry.public_url_submitted_from}\n\n"
                f"Message:\n{enquiry.message}"
            ),
            tags=["blog_lead"],
        )
        # Store campaign and referral in tags/metadata
        if enquiry.utm_campaign:
            lead.tags.append(f"utm_campaign:{enquiry.utm_campaign}")

        lead.save()
        return lead

    def _notify_sales_team(self, enquiry: BlogEnquiry, lead):
        """Notify the assigned sales user or all sales managers."""
        if lead.assigned_to:
            recipients = [lead.assigned_to]
        else:
            from apps.authentication.models import UserCompany
            from apps.authentication.models import User
            sales_user_pks = UserCompany.objects.filter(
                company=enquiry.company,
                is_active=True,
                role__in=["sales_manager", "company_admin"],
            ).values_list("user_id", flat=True).distinct()
            recipients = list(User.objects.filter(pk__in=sales_user_pks))

        post_ref = enquiry.post.title if enquiry.post else "the website"
        for user in recipients:
            self.send_notification(
                recipient=user,
                title="New Blog Lead",
                message=(
                    f"{enquiry.contact_name} ({enquiry.contact_email}) submitted an enquiry "
                    f"via '{post_ref}'. Lead: {lead.number}."
                ),
                notification_type="info",
                action_url=f"/crm/leads/{lead.pk}/",
                company=enquiry.company,
            )
