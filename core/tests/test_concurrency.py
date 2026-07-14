import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.test import TransactionTestCase
from core.services import BaseService
from apps.company.models import Company
from apps.sales.models import Quotation
from django.db import connection

class SequenceGeneratorConcurrencyTest(TransactionTestCase):
    
    def setUp(self):
        # Create a company to attach the quotations to
        self.company = Company.objects.create(
            name="Concurrency Test Company"
        )
        # Clear out Quotation for safety
        Quotation.objects.filter(company=self.company).delete()

    def create_quotation(self, index):
        from django.db import transaction
        try:
            with transaction.atomic():
                number = BaseService.generate_sequence_number("QUO", Quotation, self.company.id)
                import time
                time.sleep(0.1)  # Simulate some processing time to encourage race conditions
                Quotation.objects.create(
                    company=self.company,
                    number=number,
                    total=Decimal("100.00"),
                    date=timezone.now().date()
                )
                return number
        finally:
            connection.close()

    import unittest
    
    @unittest.skipIf(connection.vendor == 'sqlite', "SQLite does not support select_for_update concurrency")
    def test_concurrent_sequence_generation_prevents_duplicates(self):
        """
        Tests that multiple threads attempting to generate a sequence number 
        simultaneously do not receive duplicate numbers due to race conditions.
        """
        thread_count = 5
        results = set()
        
        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [executor.submit(self.create_quotation, i) for i in range(thread_count)]
            for future in as_completed(futures):
                results.add(future.result())
        
        # We expect exactly `thread_count` unique results.
        self.assertEqual(len(results), thread_count, f"Expected {thread_count} unique sequence numbers, got {len(results)}. Duplicates found!")
        self.assertEqual(Quotation.objects.count(), thread_count)
