# Placeholder for Integration Services
# Each service should implement connection testing, sync logic, and webhooks.

class BaseIntegrationService:
    def connect(self, credentials):
        raise NotImplementedError

    def test_connection(self):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

class RazorpayService(BaseIntegrationService):
    pass

class StripeService(BaseIntegrationService):
    pass

class PayPalService(BaseIntegrationService):
    pass

class ShiprocketService(BaseIntegrationService):
    pass

class GoogleDriveService(BaseIntegrationService):
    pass

class GoogleCalendarService(BaseIntegrationService):
    pass

class MicrosoftOutlookService(BaseIntegrationService):
    pass
