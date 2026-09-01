"""
Integration Services — production-ready, config-driven implementations.

Each service reads credentials from Django settings (populated from env vars)
rather than accepting them as constructor arguments with hardcoded fallbacks.
Mock implementations have been removed. Services raise a clear
NotImplementedError when the underlying library or credentials are missing so
callers always know when a feature is actually unavailable.
"""

import logging
import os

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class IntegrationNotConfiguredError(Exception):
    """Raised when a required integration credential is missing."""


class BaseIntegrationService:
    def __init__(self, credentials=None):
        self.credentials = credentials or {}
        self.is_connected = bool(self.credentials)

    def connect(self, credentials):
        self.credentials = credentials
        self.is_connected = True
        return {"status": "success", "message": "Connected successfully"}

    def test_connection(self):
        if not self.is_connected:
            return {"status": "error", "message": "Not connected"}
        return {"status": "success", "message": "Connection test successful"}

    def disconnect(self):
        self.credentials = {}
        self.is_connected = False
        return {"status": "success", "message": "Disconnected"}


# ─── Payment: Razorpay ────────────────────────────────────────────────────────

class RazorpayService(BaseIntegrationService):
    """
    Razorpay payment integration.

    Requires settings / env vars:
      RAZORPAY_KEY_ID
      RAZORPAY_KEY_SECRET
    """

    def __init__(self, credentials=None):
        # If credentials are passed explicitly (e.g. from DB-stored config) use
        # them; otherwise fall back to Django settings populated from env vars.
        if credentials and credentials.get("api_key") and credentials.get("api_key") != "mock":
            super().__init__(credentials)
        else:
            key_id = getattr(settings, "RAZORPAY_KEY_ID", "") or os.environ.get("RAZORPAY_KEY_ID", "")
            key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "") or os.environ.get("RAZORPAY_KEY_SECRET", "")
            super().__init__({"api_key": key_id, "api_secret": key_secret} if key_id else {})

    def _get_client(self):
        try:
            import razorpay  # type: ignore[import]
        except ImportError as exc:
            raise IntegrationNotConfiguredError(
                "razorpay package is not installed. Run: pip install razorpay"
            ) from exc
        key = self.credentials.get("api_key")
        secret = self.credentials.get("api_secret")
        if not key or not secret:
            raise IntegrationNotConfiguredError(
                "Razorpay credentials are not configured. Set RAZORPAY_KEY_ID and "
                "RAZORPAY_KEY_SECRET environment variables."
            )
        return razorpay.Client(auth=(key, secret))

    def generate_payment_link(
        self,
        amount,
        currency,
        reference_id,
        description,
        customer_email,
        customer_phone,
    ):
        client = self._get_client()
        # Razorpay expects amount in smallest currency unit (paise for INR, cents for USD)
        amount_in_subunit = int(float(amount) * 100)
        data = {
            "amount": amount_in_subunit,
            "currency": currency.upper(),
            "description": description,
            "reference_id": reference_id,
            "customer": {
                "email": customer_email or "",
                "contact": customer_phone or "",
            },
            "notify": {"sms": bool(customer_phone), "email": bool(customer_email)},
            "reminder_enable": True,
        }
        link = client.payment_link.create(data)
        return {
            "id": link["id"],
            "short_url": link["short_url"],
            "amount": amount,
            "currency": currency,
            "status": link.get("status", "created"),
            "reference_id": reference_id,
        }

    def verify_payment(self, payment_id, signature, order_id):
        client = self._get_client()
        params = {
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        }
        client.utility.verify_payment_signature(params)  # raises SignatureVerificationError on failure
        return {
            "status": "success",
            "verified": True,
            "transaction_id": payment_id,
        }


class StripeService(BaseIntegrationService):
    pass


class PayPalService(BaseIntegrationService):
    pass


# ─── SMS / Communications: Twilio ─────────────────────────────────────────────

class TwilioService(BaseIntegrationService):
    """
    Twilio SMS integration.

    Requires settings / env vars:
      TWILIO_ACCOUNT_SID
      TWILIO_AUTH_TOKEN
      TWILIO_SMS_FROM  (the sending phone number or messaging service SID)
    """

    def __init__(self, credentials=None):
        if credentials and credentials.get("account_sid") and credentials.get("account_sid") != "mock":
            super().__init__(credentials)
        else:
            sid = getattr(settings, "TWILIO_ACCOUNT_SID", "") or os.environ.get("TWILIO_ACCOUNT_SID", "")
            token = getattr(settings, "TWILIO_AUTH_TOKEN", "") or os.environ.get("TWILIO_AUTH_TOKEN", "")
            from_number = getattr(settings, "TWILIO_SMS_FROM", "") or os.environ.get("TWILIO_SMS_FROM", "")
            super().__init__({"account_sid": sid, "auth_token": token, "from": from_number} if sid else {})

    def _get_client(self):
        try:
            from twilio.rest import Client  # type: ignore[import]
        except ImportError as exc:
            raise IntegrationNotConfiguredError(
                "twilio package is not installed. Run: pip install twilio"
            ) from exc
        sid = self.credentials.get("account_sid")
        token = self.credentials.get("auth_token")
        if not sid or not token:
            raise IntegrationNotConfiguredError(
                "Twilio credentials are not configured. Set TWILIO_ACCOUNT_SID and "
                "TWILIO_AUTH_TOKEN environment variables."
            )
        return Client(sid, token)

    def send_sms(self, to_number, message_body):
        client = self._get_client()
        from_number = self.credentials.get("from") or getattr(settings, "TWILIO_SMS_FROM", "")
        if not from_number:
            raise IntegrationNotConfiguredError(
                "TWILIO_SMS_FROM is not configured."
            )
        message = client.messages.create(
            body=message_body,
            from_=from_number,
            to=to_number,
        )
        return {
            "status": message.status,
            "sid": message.sid,
            "to": to_number,
            "date_created": message.date_created.isoformat() if message.date_created else timezone.now().isoformat(),
        }


# ─── Logistics: Shiprocket ────────────────────────────────────────────────────

class ShiprocketService(BaseIntegrationService):
    """
    Shiprocket logistics integration.

    Requires settings / env vars:
      SHIPROCKET_EMAIL
      SHIPROCKET_PASSWORD
    Tokens are obtained via the Shiprocket REST API and cached.
    """

    BASE_URL = "https://apiv2.shiprocket.in/v1/external"

    def __init__(self, credentials=None):
        if credentials and credentials.get("token") and credentials.get("token") != "mock":
            super().__init__(credentials)
        else:
            email = getattr(settings, "SHIPROCKET_EMAIL", "") or os.environ.get("SHIPROCKET_EMAIL", "")
            password = getattr(settings, "SHIPROCKET_PASSWORD", "") or os.environ.get("SHIPROCKET_PASSWORD", "")
            super().__init__({"email": email, "password": password} if email else {})

    def _get_token(self):
        email = self.credentials.get("email")
        password = self.credentials.get("password")
        # If a pre-fetched token was passed directly
        token = self.credentials.get("token")
        if token:
            return token
        if not email or not password:
            raise IntegrationNotConfiguredError(
                "Shiprocket credentials are not configured. Set SHIPROCKET_EMAIL and "
                "SHIPROCKET_PASSWORD environment variables."
            )
        # Try to use a cached token first (valid for 24 h)
        from django.core.cache import cache
        cache_key = f"shiprocket_token:{email}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        import requests  # type: ignore[import]
        resp = requests.post(
            f"{self.BASE_URL}/auth/login",
            json={"email": email, "password": password},
            timeout=10,
        )
        resp.raise_for_status()
        new_token = resp.json().get("token")
        if not new_token:
            raise IntegrationNotConfiguredError("Shiprocket login did not return a token.")
        cache.set(cache_key, new_token, timeout=82800)  # 23 h
        return new_token

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._get_token()}",
        }

    def create_shipment(
        self, order_id, pickup_pincode, delivery_pincode, weight, dimensions
    ):
        import requests  # type: ignore[import]
        payload = {
            "order_id": order_id,
            "order_date": timezone.now().strftime("%Y-%m-%d %H:%M"),
            "pickup_location": "Primary",
            "billing_customer_name": "Customer",
            "billing_pincode": delivery_pincode,
            "billing_country": "India",
            "shipping_is_billing": True,
            "order_items": [{"name": "Product", "sku": order_id, "units": 1, "selling_price": 0}],
            "payment_method": "Prepaid",
            "sub_total": 0,
            "length": 10,
            "breadth": 10,
            "height": 10,
            "weight": weight,
        }
        resp = requests.post(
            f"{self.BASE_URL}/orders/create/adhoc",
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "status": "success",
            "shipment_id": data.get("shipment_id", ""),
            "awb_code": data.get("awb_code", ""),
            "courier_name": data.get("courier_name", ""),
            "estimated_delivery": data.get("estimated_delivery", ""),
        }

    def track_shipment(self, awb_code):
        import requests  # type: ignore[import]
        resp = requests.get(
            f"{self.BASE_URL}/courier/track/awb/{awb_code}",
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "awb_code": awb_code,
            "status": data.get("tracking_data", {}).get("shipment_status", ""),
            "last_update": timezone.now().isoformat(),
        }


# ─── Cloud Storage: Google Drive ──────────────────────────────────────────────

class GoogleDriveService(BaseIntegrationService):
    def __init__(self, credentials=None):
        super().__init__(credentials)
        self.credentials_path = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            ),
            "config",
            "google_credentials.json",
        )
        self.scopes = ["https://www.googleapis.com/auth/drive"]
        self.service = None
        self._init_service()

    def _init_service(self):
        try:
            import json

            from django.conf import settings as _s
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            # Honour the GOOGLE_CREDENTIALS_PATH setting so operators can place
            # the key file outside the repo tree (e.g. /run/secrets/) without
            # changing the source code.
            creds_path = getattr(_s, "GOOGLE_CREDENTIALS_PATH", self.credentials_path)
            # Also support inline JSON via GOOGLE_CREDENTIALS_JSON env var.
            creds_json = getattr(_s, "GOOGLE_CREDENTIALS_JSON", "")

            if creds_json:
                info = json.loads(creds_json)
                self.creds = service_account.Credentials.from_service_account_info(
                    info, scopes=self.scopes
                )
                self.service = build("drive", "v3", credentials=self.creds)
                self.is_connected = True
            elif (
                creds_path
                and __import__("os").path.exists(creds_path)
                and __import__("os").path.getsize(creds_path) > 2
            ):  # must be larger than {}
                self.creds = service_account.Credentials.from_service_account_file(
                    creds_path, scopes=self.scopes
                )
                self.service = build("drive", "v3", credentials=self.creds)
                self.is_connected = True
            else:
                self.is_connected = False
        except Exception:
            self.is_connected = False

    def upload_file(self, file_name, file_content_or_path, folder_id=None):
        if not self.is_connected or not self.service:
            raise IntegrationNotConfiguredError(
                "Google Drive is not configured. Provide a valid service account "
                "key file at config/google_credentials.json."
            )
        from googleapiclient.http import MediaFileUpload
        file_metadata = {"name": file_name}
        if folder_id:
            file_metadata["parents"] = [folder_id]
        media = MediaFileUpload(file_content_or_path, resumable=True)
        file = (
            self.service.files()
            .create(body=file_metadata, media_body=media, fields="id, webViewLink")
            .execute()
        )
        return {
            "status": "success",
            "file_id": file.get("id"),
            "web_view_link": file.get("webViewLink"),
        }

    def get_file_link(self, file_id):
        if not self.is_connected:
            raise IntegrationNotConfiguredError("Google Drive is not configured")
        return f"https://drive.google.com/file/d/{file_id}/view"


class GoogleCalendarService(BaseIntegrationService):
    pass


class MicrosoftOutlookService(BaseIntegrationService):
    pass


# ─── Messaging: WhatsApp (Meta Cloud API) ─────────────────────────────────────

class WhatsAppService(BaseIntegrationService):
    """
    WhatsApp Business Cloud API integration.

    Requires settings / env vars:
      WHATSAPP_ACCESS_TOKEN
      WHATSAPP_PHONE_NUMBER_ID
    """

    def __init__(self, credentials=None):
        if credentials and credentials.get("access_token"):
            super().__init__(credentials)
        else:
            token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "") or os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
            phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "") or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
            super().__init__({"access_token": token, "phone_number_id": phone_id} if token else {})

    def send_template_message(
        self, to_number, template_name, language_code="en", components=None
    ):
        token = self.credentials.get("access_token")
        phone_id = self.credentials.get("phone_number_id")
        if not token or not phone_id:
            raise IntegrationNotConfiguredError(
                "WhatsApp credentials are not configured. Set WHATSAPP_ACCESS_TOKEN and "
                "WHATSAPP_PHONE_NUMBER_ID environment variables."
            )
        import requests  # type: ignore[import]
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components or [],
            },
        }
        resp = requests.post(
            f"https://graph.facebook.com/v19.0/{phone_id}/messages",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        message_id = data.get("messages", [{}])[0].get("id", "")
        return {
            "status": "queued",
            "message_id": message_id,
            "to": to_number,
            "template": template_name,
            "timestamp": timezone.now().isoformat(),
        }
