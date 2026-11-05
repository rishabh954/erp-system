"""
Social Media Platform Adapters
Each adapter handles the platform-specific API calls for publishing a blog post.

All adapters use official APIs only. No browser automation or unofficial methods.

Supported platforms:
  - Facebook Pages (Graph API v19+)
  - Instagram Business (Graph API v19+ via Facebook Business)
  - LinkedIn Company Pages (LinkedIn API v2)
  - Twitter/X (via Tweepy, if installed)

IMPORTANT: Real publishing requires valid OAuth credentials configured per-company.
           In development / without credentials, adapters raise clear errors.
           Test suites mock these adapters entirely.
"""

import logging
from abc import ABC

import requests

from apps.blog.models import BlogPost, SocialMediaAccount, SocialMediaPublication

logger = logging.getLogger(__name__)


# ─── Base Adapter ─────────────────────────────────────────────────────────────


class BaseSocialAdapter(ABC):
    """Abstract base for all platform adapters."""

    TIMEOUT = 30  # seconds

    def publish(
        self,
        post: BlogPost,
        account: SocialMediaAccount,
        publication: SocialMediaPublication,
    ) -> dict:
        """
        Publish the post to this platform.
        Returns a dict with at least {'id': '<external_post_id>'}.
        Raises ValueError for known platform limitations.
        Raises requests.HTTPError for recoverable failures.
        """
        raise NotImplementedError

    def _get_image_url(self, post: BlogPost) -> str | None:
        if post.featured_image:
            try:
                return post.featured_image.url
            except Exception:
                pass
        return None

    def _build_full_caption(self, publication: SocialMediaPublication, post: BlogPost) -> str:
        parts = []
        if publication.caption:
            parts.append(publication.caption)
        if post.public_url:
            parts.append(post.public_url)
        if publication.hashtags:
            parts.append(publication.hashtags)
        return "\n\n".join(p for p in parts if p)


# ─── Facebook Adapter ─────────────────────────────────────────────────────────


class FacebookAdapter(BaseSocialAdapter):
    """
    Facebook Pages Graph API v19.0
    Endpoint: https://graph.facebook.com/v19.0/{page_id}/feed
    Required permission: pages_manage_posts
    """

    GRAPH_API_BASE = "https://graph.facebook.com/v19.0"

    def publish(self, post, account, publication):
        if not account.page_id or not account.page_access_token:
            raise ValueError(
                "Facebook Page ID and Page Access Token are required. "
                "Please reconnect this Facebook account in Social Media Settings."
            )

        message = self._build_full_caption(publication, post)
        payload = {"message": message, "access_token": account.page_access_token}

        image_url = self._get_image_url(post) if publication.include_featured_image else None
        if image_url:
            # Post with link and image
            payload["link"] = post.public_url or image_url
        elif post.public_url:
            payload["link"] = post.public_url

        response = requests.post(
            f"{self.GRAPH_API_BASE}/{account.page_id}/feed",
            data=payload,
            timeout=self.TIMEOUT,
        )

        if not response.ok:
            data = response.json()
            err = data.get("error", {})
            # Token expiry
            if err.get("code") in (190, 102):
                raise ValueError(f"expired_token: {err.get('message', 'Token expired')}")
            raise requests.HTTPError(
                f"Facebook API error {err.get('code')}: {err.get('message', response.text[:200])}"
            )

        data = response.json()
        post_id = data.get("id", "")
        page_id, _, fb_post_id = post_id.partition("_")
        post_url = f"https://www.facebook.com/{page_id}/posts/{fb_post_id}" if fb_post_id else ""

        return {"id": post_id, "url": post_url}


# ─── Instagram Adapter ────────────────────────────────────────────────────────


class InstagramAdapter(BaseSocialAdapter):
    """
    Instagram Business Graph API v19.0
    Two-step: create media container → publish container
    Required permissions: instagram_basic, instagram_content_publish
    Image is REQUIRED for Instagram photo posts.
    """

    GRAPH_API_BASE = "https://graph.facebook.com/v19.0"

    def publish(self, post, account, publication):
        if not account.page_id or not account.page_access_token:
            raise ValueError(
                "Instagram Business Account ID and Access Token are required. "
                "Please reconnect this Instagram account."
            )

        image_url = self._get_image_url(post) if publication.include_featured_image else None
        caption = self._build_full_caption(publication, post)

        if not image_url:
            # Instagram requires an image for photo posts
            raise ValueError(
                "Instagram requires a featured image to publish a photo post. "
                "Please add a featured image to this blog post, or share a manual caption instead."
            )

        # Step 1: Create media container
        container_payload = {
            "image_url": image_url,
            "caption": caption[:2200],  # Instagram caption limit
            "access_token": account.page_access_token,
        }
        container_response = requests.post(
            f"{self.GRAPH_API_BASE}/{account.page_id}/media",
            data=container_payload,
            timeout=self.TIMEOUT,
        )
        if not container_response.ok:
            self._handle_error(container_response, "Instagram container creation")

        container_id = container_response.json().get("id")
        if not container_id:
            raise ValueError("Instagram: no container ID returned from media creation.")

        # Step 2: Publish the container
        publish_response = requests.post(
            f"{self.GRAPH_API_BASE}/{account.page_id}/media_publish",
            data={"creation_id": container_id, "access_token": account.page_access_token},
            timeout=self.TIMEOUT,
        )
        if not publish_response.ok:
            self._handle_error(publish_response, "Instagram media publish")

        post_id = publish_response.json().get("id", "")
        return {"id": post_id, "permalink": f"https://www.instagram.com/p/{post_id}/"}

    def _handle_error(self, response, context: str):
        data = response.json()
        err = data.get("error", {})
        if err.get("code") in (190, 102):
            raise ValueError(f"expired_token: {err.get('message', 'Token expired')}")
        raise requests.HTTPError(
            f"{context} failed [{err.get('code')}]: {err.get('message', response.text[:200])}"
        )


# ─── LinkedIn Adapter ─────────────────────────────────────────────────────────


class LinkedInAdapter(BaseSocialAdapter):
    """
    LinkedIn Company Pages UGC Posts API v2
    Endpoint: https://api.linkedin.com/v2/ugcPosts
    Required scope: w_organization_social
    """

    API_BASE = "https://api.linkedin.com/v2"

    def publish(self, post, account, publication):
        if not account.access_token:
            raise ValueError(
                "LinkedIn Access Token is required. "
                "Please reconnect this LinkedIn account in Social Media Settings."
            )
        if not account.account_id:
            raise ValueError(
                "LinkedIn Organization ID (account_id) is required. "
                "Please reconfigure this LinkedIn account."
            )

        caption = self._build_full_caption(publication, post)
        image_url = self._get_image_url(post) if publication.include_featured_image else None

        headers = {
            "Authorization": f"Bearer {account.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        if image_url and post.public_url:
            payload = {
                "author": f"urn:li:organization:{account.account_id}",
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": caption[:3000]},
                        "shareMediaCategory": "ARTICLE",
                        "media": [
                            {
                                "status": "READY",
                                "description": {"text": post.excerpt[:200] if post.excerpt else ""},
                                "originalUrl": post.public_url,
                                "title": {"text": post.title[:200]},
                                "thumbnails": [{"url": image_url}] if image_url else [],
                            }
                        ],
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                },
            }
        else:
            payload = {
                "author": f"urn:li:organization:{account.account_id}",
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": caption[:3000]},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                },
            }

        response = requests.post(
            f"{self.API_BASE}/ugcPosts",
            json=payload,
            headers=headers,
            timeout=self.TIMEOUT,
        )

        if not response.ok:
            data = response.json() if response.content else {}
            msg = data.get("message", response.text[:200])
            if response.status_code in (401, 403):
                raise ValueError(f"expired_token: {msg}")
            raise requests.HTTPError(f"LinkedIn API error {response.status_code}: {msg}")

        post_id = response.headers.get("x-restli-id", "")
        return {"id": post_id, "url": ""}


# ─── Twitter/X Adapter ────────────────────────────────────────────────────────


class TwitterXAdapter(BaseSocialAdapter):
    """
    Twitter/X API v2 via Tweepy.
    Requires tweepy>=4.0 — install separately: pip install tweepy
    """

    def publish(self, post, account, publication):
        try:
            import tweepy
        except ImportError:
            raise ValueError(
                "The 'tweepy' package is not installed. "
                "Install it with: pip install tweepy"
            )

        if not account.access_token or not account.refresh_token:
            raise ValueError(
                "Twitter/X access credentials are missing. "
                "Please reconnect this Twitter/X account."
            )

        caption = self._build_full_caption(publication, post)
        # Twitter has a 280-character limit for basic accounts
        tweet_text = caption[:280]

        client = tweepy.Client(
            bearer_token=None,
            access_token=account.access_token,
            access_token_secret=account.refresh_token,  # reused as oauth secret
            consumer_key=self._get_consumer_key(account),
            consumer_secret=self._get_consumer_secret(account),
        )

        try:
            response = client.create_tweet(text=tweet_text)
            tweet_id = response.data.get("id", "")
            return {"id": tweet_id, "url": f"https://twitter.com/i/web/status/{tweet_id}"}
        except tweepy.errors.Unauthorized:
            raise ValueError("expired_token: Twitter/X credentials are invalid or expired.")
        except tweepy.errors.TweepyException as exc:
            raise requests.HTTPError(f"Twitter/X API error: {exc}")

    def _get_consumer_key(self, account: SocialMediaAccount) -> str:
        """Retrieve app consumer key from company settings."""
        from apps.administration.models import Integration
        try:
            integration = Integration.objects.get(
                company=account.company, provider="twitter_x"
            )
            return integration.credentials.get("consumer_key", "")
        except Exception:
            return ""

    def _get_consumer_secret(self, account: SocialMediaAccount) -> str:
        from apps.administration.models import Integration
        try:
            integration = Integration.objects.get(
                company=account.company, provider="twitter_x"
            )
            return integration.credentials.get("consumer_secret", "")
        except Exception:
            return ""


# ─── Adapter Registry ─────────────────────────────────────────────────────────


_ADAPTER_MAP = {
    SocialMediaAccount.Platform.FACEBOOK: FacebookAdapter,
    SocialMediaAccount.Platform.INSTAGRAM: InstagramAdapter,
    SocialMediaAccount.Platform.LINKEDIN: LinkedInAdapter,
    SocialMediaAccount.Platform.TWITTER_X: TwitterXAdapter,
}


def get_adapter(platform: str) -> BaseSocialAdapter:
    """Return the adapter instance for the given platform choice value."""
    adapter_cls = _ADAPTER_MAP.get(platform)
    if not adapter_cls:
        raise ValueError(
            f"No social media adapter registered for platform '{platform}'. "
            f"Supported: {list(_ADAPTER_MAP.keys())}"
        )
    return adapter_cls()
