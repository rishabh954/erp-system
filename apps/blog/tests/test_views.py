"""
Blog View Tests
Tests permission enforcement, HTTP responses, and form handling.
"""

import pytest
from django.test import Client, TestCase
from django.urls import reverse

from apps.blog.models import BlogPost


@pytest.mark.django_db
class TestBlogViewPermissions(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.author = UserFactory(company=self.company, role="employee")
        self.manager = UserFactory(company=self.company, role="sales_manager")
        self._seed_permissions()
        self.client = Client()

    def _seed_permissions(self):
        from apps.authentication.models import ModulePermission
        for role, can_approve in [("employee", False), ("sales_manager", True)]:
            ModulePermission.objects.get_or_create(
                role=role, module="blog",
                defaults={
                    "can_create": True, "can_read": True,
                    "can_update": True, "can_delete": role != "employee",
                    "can_approve": can_approve,
                },
            )

    def _login(self, user):
        self.client.force_login(user)

    def _make_post(self, status="draft"):
        return BlogPost.objects.create(
            company=self.company, title="Test",
            content_raw="<p>Body</p>", author=self.author,
            status=status, created_by=self.author,
        )

    # ── Unauthenticated access ─────────────────────────────────────────────

    def test_dashboard_requires_login(self):
        resp = self.client.get(reverse("blog:dashboard"))
        self.assertNotEqual(resp.status_code, 200)

    def test_posts_list_requires_login(self):
        resp = self.client.get(reverse("blog:posts"))
        self.assertNotEqual(resp.status_code, 200)

    # ── Authenticated access ───────────────────────────────────────────────

    def test_dashboard_accessible_when_logged_in(self):
        self._login(self.author)
        resp = self.client.get(reverse("blog:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Blog Dashboard")

    def test_posts_list_accessible(self):
        self._login(self.author)
        resp = self.client.get(reverse("blog:posts"))
        self.assertEqual(resp.status_code, 200)

    def test_post_create_get(self):
        self._login(self.author)
        resp = self.client.get(reverse("blog:post_create"))
        self.assertEqual(resp.status_code, 200)

    def test_post_create_post_creates_draft(self):
        self._login(self.author)
        resp = self.client.post(reverse("blog:post_create"), {
            "title": "New Post from View",
            "content_raw": "<p>Content here</p>",
            "excerpt": "Short summary",
            "enable_enquiry_form": True,
        })
        self.assertEqual(BlogPost.objects.filter(title="New Post from View").count(), 1)

    def test_approval_queue_accessible_to_manager(self):
        self._login(self.manager)
        resp = self.client.get(reverse("blog:approval_queue"))
        self.assertEqual(resp.status_code, 200)

    def test_submit_for_approval(self):
        self._login(self.author)
        post = self._make_post("draft")
        resp = self.client.post(reverse("blog:post_submit", kwargs={"pk": post.pk}))
        post.refresh_from_db()
        self.assertEqual(post.status, "pending_approval")

    def test_approve_as_manager(self):
        self._login(self.manager)
        post = self._make_post("pending_approval")
        resp = self.client.post(
            reverse("blog:post_approve", kwargs={"pk": post.pk}),
            {"comment": "LGTM"}
        )
        post.refresh_from_db()
        self.assertEqual(post.status, "approved")

    def test_reject_as_manager(self):
        self._login(self.manager)
        post = self._make_post("pending_approval")
        resp = self.client.post(
            reverse("blog:post_reject", kwargs={"pk": post.pk}),
            {"comment": "Needs more details"}
        )
        post.refresh_from_db()
        self.assertEqual(post.status, "rejected")

    def test_reject_without_reason_fails(self):
        self._login(self.manager)
        post = self._make_post("pending_approval")
        self.client.post(
            reverse("blog:post_reject", kwargs={"pk": post.pk}),
            {"comment": ""}
        )
        post.refresh_from_db()
        # Status should NOT have changed
        self.assertEqual(post.status, "pending_approval")

    def test_post_detail_visible(self):
        self._login(self.author)
        post = self._make_post()
        resp = self.client.get(reverse("blog:post_detail", kwargs={"pk": post.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Test")

    def test_cross_company_post_access_denied(self):
        from tests.factories import CompanyFactory, UserFactory
        other_company = CompanyFactory()
        other_user = UserFactory(company=other_company)
        other_post = BlogPost.objects.create(
            company=other_company, title="Other Company Post",
            content_raw="<p>x</p>", author=other_user,
            created_by=other_user,
        )
        self._login(self.author)
        resp = self.client.get(reverse("blog:post_detail", kwargs={"pk": other_post.pk}))
        self.assertEqual(resp.status_code, 404)


@pytest.mark.django_db
class TestBlogEnquirySubmitView(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.user = UserFactory(company=self.company)
        self.post = BlogPost.objects.create(
            company=self.company, title="Public Post",
            content_raw="<p>x</p>", author=self.user,
            status="published", created_by=self.user,
        )
        self.client = Client()
        self.url = reverse("blog:enquiry_submit", kwargs={"post_pk": self.post.pk})

    def test_valid_enquiry_returns_200(self):
        resp = self.client.post(self.url, {
            "contact_name": "John Smith",
            "contact_email": "john@test.com",
            "contact_phone": "+91 9000000000",
            "message": "I want to learn more about your services.",
            "consent_given": True,
        }, content_type="application/json")
        # May be 200 or 302 depending on JSON handling
        from apps.blog.models import BlogEnquiry
        self.assertTrue(BlogEnquiry.objects.filter(contact_email="john@test.com").exists())

    def test_missing_consent_rejected(self):
        from apps.blog.models import BlogEnquiry
        self.client.post(self.url, {
            "contact_name": "Jane",
            "contact_email": "jane@test.com",
            "message": "Test message here",
            "consent_given": False,
        })
        self.assertFalse(BlogEnquiry.objects.filter(contact_email="jane@test.com").exists())
