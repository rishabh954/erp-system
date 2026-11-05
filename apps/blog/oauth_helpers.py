"""
OAuth helpers for social media account connection.
Handles state generation, redirect URL building, and callback processing.

Each platform requires app credentials configured in company Integration settings
or environment variables:

  FACEBOOK_APP_ID / FACEBOOK_APP_SECRET
  INSTAGRAM_APP_ID / INSTAGRAM_APP_SECRET  (same Facebook App, different scopes)
  LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET
  TWITTER_CONSUMER_KEY / TWITTER_CONSUMER_SECRET

Credentials are never stored in code. They are read from environment variables
or from apps.administration.models.Integration per company.
"""

import logging
import os
import secrets
import urllib.parse

from django.urls import reverse
from django.utils import timezone

from apps.blog.models import SocialMediaAccount

logger = logging.getLogger(__name__)


# ─── State token helpers ──────────────────────────────────────────────────────


def _generate_state(platform: str, company_id: str) -> str:
    """Generate a CSRF state token for an OAuth flow."""
    token = secrets.token_urlsafe(32)
    from django.core.cache import cache
    cache.set(f"oauth_state:{platform}:{token}", str(company_id), timeout=600)
    return token


def _validate_state(platform: str, state: str):
    """Validate and consume the OAuth state token. Returns company_id or raises ValueError."""
    from django.core.cache import cache
    key = f"oauth_state:{platform}:{state}"
    company_id = cache.get(key)
    if not company_id:
        raise ValueError("Invalid or expired OAuth state token. Please try connecting again.")
    cache.delete(key)
    return company_id


# ─── Facebook / Instagram ─────────────────────────────────────────────────────


def _facebook_oauth_url(request, company, platform: str) -> str:
    app_id = os.environ.get("FACEBOOK_APP_ID", "")
    if not app_id:
        raise ValueError(
            "FACEBOOK_APP_ID environment variable is not configured. "
            "Please set up your Facebook App credentials in environment settings."
        )

    state = _generate_state(platform, str(company.pk))
    callback_url = request.build_absolute_uri(
        reverse("blog:social_oauth_callback", kwargs={"platform": platform})
    )

    if platform == SocialMediaAccount.Platform.FACEBOOK:
        scope = "pages_manage_posts,pages_read_engagement,pages_show_list"
    else:  # instagram
        scope = "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement"

    params = {
        "client_id": app_id,
        "redirect_uri": callback_url,
        "scope": scope,
        "state": state,
        "response_type": "code",
    }
    return "https://www.facebook.com/v19.0/dialog/oauth?" + urllib.parse.urlencode(params)


def _facebook_oauth_callback(request, company, platform: str) -> SocialMediaAccount:
    """Exchange code for token, fetch page list, persist account."""
    app_id = os.environ.get("FACEBOOK_APP_ID", "")
    app_secret = os.environ.get("FACEBOOK_APP_SECRET", "")
    code = request.GET.get("code")
    state = request.GET.get("state")

    _validate_state(platform, state)

    callback_url = request.build_absolute_uri(
        reverse("blog:social_oauth_callback", kwargs={"platform": platform})
    )

    import requests as req

    # Exchange code for user token
    token_response = req.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": callback_url,
            "code": code,
        },
        timeout=15,
    )
    token_response.raise_for_status()
    user_token = token_response.json().get("access_token")

    # Exchange for long-lived token
    ll_response = req.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": user_token,
        },
        timeout=15,
    )
    ll_response.raise_for_status()
    ll_token = ll_response.json().get("access_token")

    # Get pages this user manages
    pages_response = req.get(
        "https://graph.facebook.com/v19.0/me/accounts",
        params={"access_token": ll_token, "fields": "id,name,access_token"},
        timeout=15,
    )
    pages_response.raise_for_status()
    pages = pages_response.json().get("data", [])

    if not pages:
        raise ValueError("No Facebook Pages found for this account. Please ensure you manage a Facebook Page.")

    page = pages[0]  # Use first page; in production, allow user to select

    account, created = SocialMediaAccount.objects.update_or_create(
        company=company,
        platform=platform,
        account_id=page["id"],
        defaults={
            "account_name": page["name"],
            "page_id": page["id"],
            "page_name": page["name"],
            "page_access_token": page["access_token"],
            "access_token": ll_token,
            "connection_status": SocialMediaAccount.ConnectionStatus.CONNECTED,
            "connected_at": timezone.now(),
            "is_active": True,
            "error_message": "",
            "granted_permissions": ["pages_manage_posts", "pages_read_engagement"],
        },
    )
    return account


# ─── LinkedIn ─────────────────────────────────────────────────────────────────


def _linkedin_oauth_url(request, company) -> str:
    client_id = os.environ.get("LINKEDIN_CLIENT_ID", "")
    if not client_id:
        raise ValueError(
            "LINKEDIN_CLIENT_ID environment variable is not configured."
        )

    state = _generate_state("linkedin", str(company.pk))
    callback_url = request.build_absolute_uri(
        reverse("blog:social_oauth_callback", kwargs={"platform": "linkedin"})
    )

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": callback_url,
        "state": state,
        "scope": "w_organization_social r_organization_social",
    }
    return "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(params)


def _linkedin_oauth_callback(request, company) -> SocialMediaAccount:
    client_id = os.environ.get("LINKEDIN_CLIENT_ID", "")
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
    code = request.GET.get("code")
    state = request.GET.get("state")

    _validate_state("linkedin", state)

    callback_url = request.build_absolute_uri(
        reverse("blog:social_oauth_callback", kwargs={"platform": "linkedin"})
    )

    import requests as req

    token_response = req.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    token_response.raise_for_status()
    token_data = token_response.json()
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 5184000)  # ~60 days default

    # Get organizations the user can manage
    orgs_response = req.get(
        "https://api.linkedin.com/v2/organizationAcls",
        params={
            "q": "roleAssignee",
            "projection": "(elements*(organization~(id,localizedName)))",
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        timeout=15,
    )

    org_id = ""
    org_name = "LinkedIn Company Page"
    if orgs_response.ok:
        elements = orgs_response.json().get("elements", [])
        if elements:
            org = elements[0].get("organization~", {})
            org_id = str(org.get("id", ""))
            org_name = org.get("localizedName", "LinkedIn Company Page")

    expires_at = timezone.now() + timezone.timedelta(seconds=expires_in)

    account, _ = SocialMediaAccount.objects.update_or_create(
        company=company,
        platform="linkedin",
        account_id=org_id,
        defaults={
            "account_name": org_name,
            "access_token": access_token,
            "token_expires_at": expires_at,
            "connection_status": SocialMediaAccount.ConnectionStatus.CONNECTED,
            "connected_at": timezone.now(),
            "is_active": True,
            "error_message": "",
            "granted_permissions": ["w_organization_social"],
        },
    )
    return account


# ─── Router ───────────────────────────────────────────────────────────────────


def get_oauth_redirect_url(platform: str, request, company) -> str:
    if platform in ("facebook", "instagram"):
        return _facebook_oauth_url(request, company, platform)
    elif platform == "linkedin":
        return _linkedin_oauth_url(request, company)
    else:
        raise ValueError(f"OAuth not implemented for platform '{platform}'.")


def handle_oauth_callback(platform: str, request, company) -> SocialMediaAccount:
    if platform in ("facebook", "instagram"):
        return _facebook_oauth_callback(request, company, platform)
    elif platform == "linkedin":
        return _linkedin_oauth_callback(request, company)
    else:
        raise ValueError(f"OAuth callback not implemented for platform '{platform}'.")
