# Placeholder for Integration Services
# Each service should implement connection testing, sync logic, and webhooks.

import uuid
import random
import os
from django.utils import timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

class BaseIntegrationService:
    def __init__(self, credentials=None):
        self.credentials = credentials or {}
        self.is_connected = bool(credentials)

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

class RazorpayService(BaseIntegrationService):
    def generate_payment_link(self, amount, currency, reference_id, description, customer_email, customer_phone):
        if not self.is_connected:
            raise ValueError("Razorpay is not connected")
        # Mock payment link generation
        link_id = f"plink_{uuid.uuid4().hex[:12]}"
        return {
            "id": link_id,
            "short_url": f"https://rzp.io/i/{link_id}",
            "amount": amount,
            "currency": currency,
            "status": "created",
            "reference_id": reference_id
        }
        
    def verify_payment(self, payment_id, signature, order_id):
        # Mock payment verification
        return {"status": "success", "verified": True, "transaction_id": f"pay_{uuid.uuid4().hex[:12]}"}

class StripeService(BaseIntegrationService):
    pass

class PayPalService(BaseIntegrationService):
    pass

class TwilioService(BaseIntegrationService):
    def send_sms(self, to_number, message_body):
        if not self.is_connected:
            raise ValueError("Twilio is not connected")
        # Mock SMS sending
        message_sid = f"SM{uuid.uuid4().hex[:32]}"
        return {
            "status": "queued",
            "sid": message_sid,
            "to": to_number,
            "date_created": timezone.now().isoformat()
        }

class ShiprocketService(BaseIntegrationService):
    def create_shipment(self, order_id, pickup_pincode, delivery_pincode, weight, dimensions):
        if not self.is_connected:
            raise ValueError("Shiprocket is not connected")
        # Mock shipment creation
        awb_code = f"AWB{random.randint(10000000, 99999999)}"
        shipment_id = random.randint(1000000, 9999999)
        return {
            "status": "success",
            "shipment_id": shipment_id,
            "awb_code": awb_code,
            "courier_name": random.choice(["Delhivery", "BlueDart", "XpressBees"]),
            "estimated_delivery": (timezone.now() + timezone.timedelta(days=3)).isoformat()
        }
        
    def track_shipment(self, awb_code):
        # Mock tracking
        statuses = ["PICKUP_SCHEDULED", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]
        return {
            "awb_code": awb_code,
            "status": random.choice(statuses),
            "last_update": timezone.now().isoformat()
        }

class GoogleDriveService(BaseIntegrationService):
    def __init__(self, credentials=None):
        super().__init__(credentials)
        self.credentials_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'config', 'google_credentials.json')
        self.scopes = ['https://www.googleapis.com/auth/drive']
        self.service = None
        self._init_service()

    def _init_service(self):
        try:
            if os.path.exists(self.credentials_path) and os.path.getsize(self.credentials_path) > 2: # must be larger than {}
                self.creds = service_account.Credentials.from_service_account_file(
                    self.credentials_path, scopes=self.scopes)
                self.service = build('drive', 'v3', credentials=self.creds)
                self.is_connected = True
            else:
                self.is_connected = False
        except Exception as e:
            self.is_connected = False

    def upload_file(self, file_name, file_content_or_path, folder_id=None):
        if not self.is_connected or not self.service:
            raise ValueError("Google Drive is not configured. Add credentials to config/google_credentials.json")
            
        file_metadata = {'name': file_name}
        if folder_id:
            file_metadata['parents'] = [folder_id]

        media = MediaFileUpload(file_content_or_path, resumable=True)
        
        # Send the file to Google Drive
        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        return {
            "status": "success",
            "file_id": file.get("id"),
            "web_view_link": file.get("webViewLink")
        }
        
    def get_file_link(self, file_id):
        if not self.is_connected:
            raise ValueError("Google Drive is not configured")
        return f"https://drive.google.com/file/d/{file_id}/view"

class GoogleCalendarService(BaseIntegrationService):
    pass

class MicrosoftOutlookService(BaseIntegrationService):
    pass

class WhatsAppService(BaseIntegrationService):
    def send_template_message(self, to_number, template_name, language_code="en", components=None):
        """
        Sends a WhatsApp template message using Meta's Cloud API.
        """
        if not self.is_connected:
            raise ValueError("WhatsApp is not connected")
            
        # Mock WhatsApp message sending
        message_id = f"wamid.{uuid.uuid4().hex[:32]}"
        return {
            "status": "queued",
            "message_id": message_id,
            "to": to_number,
            "template": template_name,
            "timestamp": timezone.now().isoformat()
        }
