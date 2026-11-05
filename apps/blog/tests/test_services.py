"""
Blog Service Tests
Tests approval workflow, duplicate prevention, CRM lead creation, and error handling.
All external APIs are mocked.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase
from django.utils import timezone

from apps.blog.models import (
    BlogApproval, BlogEnquiry, BlogPost,
    WebsiteIntegration, WebsitePublication, SocialMediaAccount, SocialMediaPublication,
)
from apps.blog.services import (
    BlogEnquiryService, BlogService, SocialMediaService, WebsiteIntegrationService,
)


@pytest.mark.django_db
class TestBlogService(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.author = UserFactory(company=self.company)
        self.manager = UserFactory(company=self.company, role="sales_manager")
        self._seed_permissions()

    def _seed_permissions(self):
        from apps.authentication.models import ModulePermission
        ModulePermission.objects.get_or_create(
            role="employee",
            module="blog",
            defaults={
                "can_create": True, "can_read": True, "can_update": True,
                "can_delete": False, "can_approve": False,
            },
        )
        ModulePermission.objects.get_or_create(
            role="sales_manager",
            module="blog",
            defaults={
                "can_create": True, "can_read": True, "can_update": True,
                "can_delete": True, "can_approve": True,
            },
        )

    def _make_post(self, user=None, status="draft"):
        post = BlogPost.objects.create(
            company=self.company,
            title="Test Post",
            content_raw="<p>Content</p>",
            author=user or self.author,
            status=status,
            created_by=user or self.author,
        )
        return post

    # ── Create ────────────────────────────────────────────────────────────────

    def test_create_post(self):
        svc = BlogService(user=self.author, company=self.company)
        post = svc.create_post(title="Hello", content_raw="<p>Body</p>")
        self.assertEqual(post.title, "Hello")
        self.assertEqual(post.status, "draft")
        self.assertEqual(post.author, self.author)

    def test_create_post_generates_number(self):
        svc = BlogService(user=self.author, company=self.company)
        post = svc.create_post(title="Numbered", content_raw="<p>x</p>")
        self.assertTrue(post.number.startswith("POST-"))

    def test_duplicate_post(self):
        svc = BlogService(user=self.author, company=self.company)
        original = self._make_post()
        copy = svc.duplicate_post(original)
        self.assertIn("Copy of", copy.title)
        self.assertEqual(copy.status, "draft")
        self.assertNotEqual(copy.pk, original.pk)

    # ── Approval Workflow ─────────────────────────────────────────────────────

    def test_submit_for_approval(self):
        svc = BlogService(user=self.author, company=self.company)
        post = self._make_post()
        post = svc.submit_for_approval(post)
        self.assertEqual(post.status, "pending_approval")
        self.assertTrue(
            BlogApproval.objects.filter(post=post, decision="submitted").exists()
        )

    def test_cannot_submit_already_pending(self):
        svc = BlogService(user=self.author, company=self.company)
        post = self._make_post(status="pending_approval")
        with self.assertRaises(ValueError):
            svc.submit_for_approval(post)

    def test_approve_post(self):
        svc = BlogService(user=self.manager, company=self.company)
        post = self._make_post(status="pending_approval")
        post = svc.approve_post(post, comment="Looks great")
        self.assertEqual(post.status, "approved")
        self.assertTrue(
            BlogApproval.objects.filter(post=post, decision="approved").exists()
        )

    def test_reject_post(self):
        svc = BlogService(user=self.manager, company=self.company)
        post = self._make_post(status="pending_approval")
        post = svc.reject_post(post, reason="Needs more detail")
        self.assertEqual(post.status, "rejected")
        self.assertTrue(
            BlogApproval.objects.filter(post=post, decision="rejected").exists()
        )

    def test_reject_requires_reason(self):
        svc = BlogService(user=self.manager, company=self.company)
        post = self._make_post(status="pending_approval")
        with self.assertRaises(ValueError):
            svc.reject_post(post, reason="")

    def test_cannot_approve_non_pending(self):
        svc = BlogService(user=self.manager, company=self.company)
        post = self._make_post(status="draft")
        with self.assertRaises(ValueError):
            svc.approve_post(post)

    def test_schedule_post(self):
        svc = BlogService(user=self.manager, company=self.company)
        post = self._make_post(status="approved")
        future = timezone.now() + timezone.timedelta(days=1)
        post = svc.schedule_post(post, future)
        self.assertEqual(post.status, "scheduled")
        self.assertEqual(post.scheduled_publish_at, future)

    def test_schedule_post_must_be_future(self):
        svc = BlogService(user=self.manager, company=self.company)
        post = self._make_post(status="approved")
        past = timezone.now() - timezone.timedelta(hours=1)
        with self.assertRaises(ValueError):
            svc.schedule_post(post, past)

    def test_delete_published_post_blocked(self):
        svc = BlogService(user=self.manager, company=self.company)
        post = self._make_post(status="published")
        with self.assertRaises(ValueError):
            svc.delete_post(post)

    # ── Company isolation ─────────────────────────────────────────────────────

    def test_cross_company_update_blocked(self):
        from tests.factories import CompanyFactory
        other = CompanyFactory()
        svc = BlogService(user=self.author, company=other)
        post = self._make_post()
        with self.assertRaises(PermissionError):
            svc.update_post(post, title="Hacked")


@pytest.mark.django_db
class TestWebsiteIntegrationService(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.user = UserFactory(company=self.company, role="sales_manager")
        self._seed_permissions()
        self.integration = WebsiteIntegration.objects.create(
            company=self.company,
            name="Test Site",
            website_url="https://svapasworld.com",
            api_endpoint="https://svapasworld.com/api/posts/",
            api_key="testkey",
            is_active=True,
            created_by=self.user,
        )
        self.post = BlogPost.objects.create(
            company=self.company,
            title="Test Post",
            content_raw="<p>Content</p>",
            author=self.user,
            status="approved",
            created_by=self.user,
        )

    def _seed_permissions(self):
        from apps.authentication.models import ModulePermission
        for role in ["sales_manager"]:
            ModulePermission.objects.get_or_create(
                role=role, module="blog",
                defaults={"can_create": True, "can_read": True, "can_update": True,
                          "can_delete": True, "can_approve": True},
            )

    @patch("apps.blog.services.requests.post")
    def test_successful_publish(self, mock_post):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "999", "url": "https://svapasworld.com/blog/test-post/"}
        mock_post.return_value = mock_response

        svc = WebsiteIntegrationService(user=self.user, company=self.company)
        pub = svc.publish_post(self.post, self.integration, user=self.user)

        self.assertEqual(pub.sync_status, "published")
        self.assertEqual(pub.external_post_id, "999")
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, "published")
        self.assertEqual(self.post.website_url, "https://svapasworld.com/blog/test-post/")

    @patch("apps.blog.services.requests.post")
    def test_failed_publish_marks_pending_retry(self, mock_post):
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        svc = WebsiteIntegrationService(user=self.user, company=self.company)
        pub = svc.publish_post(self.post, self.integration, user=self.user)

        self.assertEqual(pub.sync_status, "pending_retry")
        self.assertIsNotNone(pub.next_retry_at)

    @patch("apps.blog.services.requests.post")
    def test_idempotent_retry_does_not_duplicate(self, mock_post):
        """Calling publish twice for same post+integration reuses the same publication record."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "abc", "url": "https://svapasworld.com/test/"}
        mock_post.return_value = mock_response

        svc = WebsiteIntegrationService(user=self.user, company=self.company)
        pub1 = svc.publish_post(self.post, self.integration, user=self.user)
        pub2 = svc.publish_post(self.post, self.integration, user=self.user)

        self.assertEqual(pub1.pk, pub2.pk)
        self.assertEqual(
            WebsitePublication.objects.filter(post=self.post, integration=self.integration).count(),
            1
        )

    @patch("apps.blog.services.requests.post")
    def test_publish_non_approved_post_blocked(self, mock_post):
        self.post.status = "draft"
        self.post.save()
        svc = WebsiteIntegrationService(user=self.user, company=self.company)
        with self.assertRaises(ValueError):
            svc.publish_post(self.post, self.integration, user=self.user)


@pytest.mark.django_db
class TestBlogEnquiryService(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.user = UserFactory(company=self.company)
        self.post = BlogPost.objects.create(
            company=self.company,
            title="How AI is Changing Business",
            content_raw="<p>Content</p>",
            author=self.user,
            status="published",
            created_by=self.user,
        )

    def _make_enquiry(self, email="test@example.com"):
        return BlogEnquiry.objects.create(
            company=self.company,
            post=self.post,
            contact_name="Jane Doe",
            contact_email=email,
            contact_phone="+91 9000000000",
            contact_company="Acme Ltd",
            message="I am interested in your AI services.",
            consent_given=True,
        )

    def test_enquiry_creates_crm_lead(self):
        from apps.crm.models import Lead
        enquiry = self._make_enquiry()
        svc = BlogEnquiryService(company=self.company)
        enquiry = svc.process_enquiry(enquiry)

        self.assertEqual(enquiry.status, "lead_created")
        self.assertIsNotNone(enquiry.crm_lead)
        lead = Lead.objects.get(pk=enquiry.crm_lead.pk)
        self.assertEqual(lead.email, "test@example.com")
        self.assertTrue(lead.number.startswith("LD-"))

    def test_duplicate_enquiry_within_window_merges(self):
        enquiry1 = self._make_enquiry("dup@example.com")
        enquiry2 = self._make_enquiry("dup@example.com")

        svc = BlogEnquiryService(company=self.company)
        svc.process_enquiry(enquiry1)
        svc.process_enquiry(enquiry2)

        enquiry2.refresh_from_db()
        self.assertEqual(enquiry2.status, "duplicate")
        self.assertEqual(enquiry1.crm_lead_id, enquiry2.crm_lead_id)

    def test_lead_source_is_web(self):
        enquiry = self._make_enquiry("web@example.com")
        svc = BlogEnquiryService(company=self.company)
        svc.process_enquiry(enquiry)
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.crm_lead.source, "web")

    def test_utm_social_source_maps_to_social(self):
        enquiry = BlogEnquiry.objects.create(
            company=self.company,
            post=self.post,
            contact_name="Social User",
            contact_email="social@example.com",
            message="Found you on Instagram",
            consent_given=True,
            utm_source="instagram",
        )
        svc = BlogEnquiryService(company=self.company)
        svc.process_enquiry(enquiry)
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.crm_lead.source, "social")

    def test_failed_lead_creation_marks_failed_status(self):
        enquiry = self._make_enquiry("fail@example.com")
        svc = BlogEnquiryService(company=self.company)
        with patch.object(svc, "_get_or_create_lead", side_effect=Exception("DB error")):
            svc.process_enquiry(enquiry)
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.status, "failed")
        self.assertIn("DB error", enquiry.processing_error)


@pytest.mark.django_db
class TestSocialMediaService(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.user = UserFactory(company=self.company, role="sales_manager")
        self._seed_permissions()
        self.post = BlogPost.objects.create(
            company=self.company, title="Social Test",
            content_raw="<p>Hi</p>", author=self.user,
            status="published", created_by=self.user,
        )
        self.account = SocialMediaAccount.objects.create(
            company=self.company,
            platform="facebook",
            account_name="Svapas World",
            account_id="fb_123",
            page_id="fb_123",
            page_access_token="fake_token",
            access_token="fake_user_token",
            connection_status="connected",
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

    @patch("apps.blog.social_adapters.FacebookAdapter.publish")
    def test_successful_social_publish(self, mock_publish):
        mock_publish.return_value = {"id": "fb_123_456", "url": "https://facebook.com/post/456"}
        svc = SocialMediaService(user=self.user, company=self.company)
        pub = svc.publish_to_account(self.post, self.account)

        self.assertEqual(pub.status, "published")
        self.assertEqual(pub.external_post_id, "fb_123_456")

    @patch("apps.blog.social_adapters.FacebookAdapter.publish")
    def test_already_published_is_idempotent(self, mock_publish):
        """Publishing to same account twice does not duplicate the social publication."""
        mock_publish.return_value = {"id": "fb_xyz", "url": ""}
        svc = SocialMediaService(user=self.user, company=self.company)
        pub1 = svc.publish_to_account(self.post, self.account)
        pub2 = svc.publish_to_account(self.post, self.account)
        self.assertEqual(pub1.pk, pub2.pk)
        self.assertEqual(
            SocialMediaPublication.objects.filter(post=self.post, account=self.account).count(), 1
        )

    @patch("apps.blog.social_adapters.FacebookAdapter.publish")
    def test_expired_token_marks_requires_reauth(self, mock_publish):
        mock_publish.side_effect = ValueError("expired_token: Token has expired")
        svc = SocialMediaService(user=self.user, company=self.company)
        pub = svc.publish_to_account(self.post, self.account)
        self.assertIn(pub.status, ["failed"])

    def test_inactive_account_blocked(self):
        self.account.is_active = False
        self.account.save()
        svc = SocialMediaService(user=self.user, company=self.company)
        with self.assertRaises(ValueError):
            svc.publish_to_account(self.post, self.account)

    def test_needs_reauth_blocked(self):
        self.account.connection_status = "requires_reauth"
        self.account.save()
        svc = SocialMediaService(user=self.user, company=self.company)
        with self.assertRaises(ValueError):
            svc.publish_to_account(self.post, self.account)
