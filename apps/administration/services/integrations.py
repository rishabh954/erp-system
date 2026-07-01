# Placeholder for Integration Services
# Each service should implement connection testing, sync logic, and webhooks.

import uuid
import random
from django.utils import timezone

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
    pass

class GoogleCalendarService(BaseIntegrationService):
    pass

class MicrosoftOutlookService(BaseIntegrationService):
    pass
