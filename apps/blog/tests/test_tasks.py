"""
Blog Celery Task Tests
All external API calls are mocked. No real credentials required.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase
from django.utils import timezone

from apps.blog.models import BlogPost, WebsiteIntegration, WebsitePublication
from apps.blog.tasks import (
    check_integration_health,
    process_blog_enquiry_task,
    publish_scheduled_posts,
    retry_failed_website_pubs,
)


@pytest.mark.django_db
class TestPublishScheduledPostsTask(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.user = UserFactory(company=self.company, role="sales_manager")
        self._seed_permissions()
        self.integration = WebsiteIntegration.objects.create(
            company=self.company,
            name="Test Site",
            website_url="https://test.com",
            api_endpoint="https://test.com/api/posts/",
            is_active=True,
            created_by=self.user,
        )

    def _seed_permissions(self):
        from apps.authentication.models import ModulePermission
        ModulePermission.objects.get_or_create(
            role="sales_manager", module="blog",
            defaults={"can_create": True, "can_read": True, "can_update": True,
                      "can_delete": True, "can_approve": True},
        )

    def _make_scheduled_post(self, hours_ago=1):
        return BlogPost.objects.create(
            company=self.company, title="Scheduled Post",
            content_raw="<p>Content</p>", author=self.user,
            status="scheduled",
            scheduled_publish_at=timezone.now() - timezone.timedelta(hours=hours_ago),
            created_by=self.user,
        )

    @patch("apps.blog.tasks.publish_post_to_website_task.delay")
    def test_due_scheduled_posts_dispatched(self, mock_delay):
        post = self._make_scheduled_post()
        result = publish_scheduled_posts()
        mock_delay.assert_called_once_with(str(post.pk), str(self.integration.pk))
        self.assertIn("1", result)

    @patch("apps.blog.tasks.publish_post_to_website_task.delay")
    def test_future_scheduled_post_not_dispatched(self, mock_delay):
        BlogPost.objects.create(
            company=self.company, title="Future Post",
            content_raw="<p>x</p>", author=self.user,
            status="scheduled",
            scheduled_publish_at=timezone.now() + timezone.timedelta(days=1),
            created_by=self.user,
        )
        publish_scheduled_posts()
        mock_delay.assert_not_called()

    @patch("apps.blog.tasks.publish_post_to_website_task.delay")
    def test_no_integration_skipped(self, mock_delay):
        self.integration.is_active = False
        self.integration.save()
        self._make_scheduled_post()
        publish_scheduled_posts()
        mock_delay.assert_not_called()


@pytest.mark.django_db
class TestRetryFailedWebsitePublicationsTask(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.user = UserFactory(company=self.company)
        self.integration = WebsiteIntegration.objects.create(
            company=self.company,
            name="Site",
            website_url="https://test.com",
            api_endpoint="https://test.com/api/posts/",
            is_active=True,
            created_by=self.user,
        )
        self.post = BlogPost.objects.create(
            company=self.company, title="Retry Post",
            content_raw="<p>x</p>", author=self.user,
            status="approved", created_by=self.user,
        )

    @patch("apps.blog.tasks.publish_post_to_website_task.delay")
    def test_pending_retry_due_is_dispatched(self, mock_delay):
        WebsitePublication.objects.create(
            company=self.company,
            post=self.post,
            integration=self.integration,
            sync_status="pending_retry",
            next_retry_at=timezone.now() - timezone.timedelta(minutes=5),
            created_by=self.user,
        )
        retry_failed_website_pubs()
        mock_delay.assert_called_once()

    @patch("apps.blog.tasks.publish_post_to_website_task.delay")
    def test_not_yet_due_not_dispatched(self, mock_delay):
        WebsitePublication.objects.create(
            company=self.company,
            post=self.post,
            integration=self.integration,
            sync_status="pending_retry",
            next_retry_at=timezone.now() + timezone.timedelta(hours=2),
            created_by=self.user,
        )
        retry_failed_website_pubs()
        mock_delay.assert_not_called()


@pytest.mark.django_db
class TestProcessBlogEnquiryTask(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.user = UserFactory(company=self.company)
        self.post = BlogPost.objects.create(
            company=self.company, title="Post",
            content_raw="<p>x</p>", author=self.user,
            status="published", created_by=self.user,
        )

    def test_task_creates_crm_lead(self):
        from apps.blog.models import BlogEnquiry
        from apps.crm.models import Lead
        enquiry = BlogEnquiry.objects.create(
            company=self.company, post=self.post,
            contact_name="Task User", contact_email="task@test.com",
            message="Task enquiry test message", consent_given=True,
        )
        result = process_blog_enquiry_task(str(enquiry.pk))
        self.assertEqual(result["status"], "lead_created")
        self.assertTrue(Lead.objects.filter(email="task@test.com").exists())

    def test_task_with_invalid_id(self):
        import uuid
        result = process_blog_enquiry_task(str(uuid.uuid4()))
        self.assertEqual(result["status"], "not_found")


@pytest.mark.django_db
class TestCheckIntegrationHealthTask(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.user = UserFactory(company=self.company)
        self.integration = WebsiteIntegration.objects.create(
            company=self.company,
            name="Health Test Site",
            website_url="https://test.com",
            api_endpoint="https://test.com/api/posts/",
            is_active=True,
            created_by=self.user,
        )

    @patch("apps.blog.services.requests.get")
    def test_healthy_integration_marked_connected(self, mock_get):
        mock_get.return_value = MagicMock(ok=True)
        results = check_integration_health()
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.status, "connected")

    @patch("apps.blog.services.requests.get")
    def test_unhealthy_integration_marked_error(self, mock_get):
        mock_get.return_value = MagicMock(ok=False)
        check_integration_health()
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.status, "error")
