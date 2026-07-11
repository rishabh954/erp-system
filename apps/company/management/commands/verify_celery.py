import logging
import sys
import time

from django.core.management.base import BaseCommand

from apps.company.tasks import update_exchange_rates


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Verifies that Celery tasks execute successfully against a real broker."

    def handle(self, *args, **options):
        self.stdout.write("Submitting task to Celery broker...")
        try:
            result = update_exchange_rates.delay()
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            self.stderr.write(
                self.style.ERROR(
                    "Failed to submit task to broker. Is Redis/Celery running? Error: An unexpected error occurred."
                )
            )
            sys.exit(1)

        self.stdout.write(f"Task submitted with ID: {result.id}")
        self.stdout.write("Waiting for task to complete (timeout: 15s)...")

        start_time = time.time()
        while not result.ready():
            if time.time() - start_time > 15:
                self.stderr.write(
                    self.style.ERROR(
                        "Task timed out! \n"
                        "Please verify:\n"
                        "1. 'celery -A config.celery worker' is running\n"
                        "2. The broker (Redis) is accessible\n"
                        "3. The CELERY_BROKER_URL in .env matches the broker"
                    )
                )
                sys.exit(1)
            time.sleep(1)
            self.stdout.write(".", ending="")
            self.stdout.flush()

        self.stdout.write("\n")

        if result.successful():
            self.stdout.write(
                self.style.SUCCESS(
                    f"Task executed successfully! Result: {result.result}"
                )
            )
        else:
            self.stderr.write(
                self.style.ERROR(f"Task failed with error: {result.result}")
            )
            sys.exit(1)
