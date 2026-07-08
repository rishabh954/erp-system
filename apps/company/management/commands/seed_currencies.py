from django.core.management.base import BaseCommand

from apps.company.models import Currency


class Command(BaseCommand):
    help = "Seeds standard ISO currencies for use during company onboarding."

    def handle(self, *args, **options):
        currencies = [
            {"code": "USD", "name": "US Dollar", "symbol": "$", "decimal_places": 2},
            {"code": "EUR", "name": "Euro", "symbol": "€", "decimal_places": 2},
            {
                "code": "GBP",
                "name": "British Pound",
                "symbol": "£",
                "decimal_places": 2,
            },
            {"code": "INR", "name": "Indian Rupee", "symbol": "₹", "decimal_places": 2},
            {
                "code": "AUD",
                "name": "Australian Dollar",
                "symbol": "A$",
                "decimal_places": 2,
            },
            {
                "code": "CAD",
                "name": "Canadian Dollar",
                "symbol": "C$",
                "decimal_places": 2,
            },
            {"code": "JPY", "name": "Japanese Yen", "symbol": "¥", "decimal_places": 0},
            {"code": "CNY", "name": "Chinese Yuan", "symbol": "¥", "decimal_places": 2},
            {"code": "AED", "name": "UAE Dirham", "symbol": "د.إ", "decimal_places": 2},
            {
                "code": "SGD",
                "name": "Singapore Dollar",
                "symbol": "S$",
                "decimal_places": 2,
            },
        ]

        created_count = 0
        for c in currencies:
            obj, created = Currency.objects.get_or_create(
                code=c["code"],
                defaults={
                    "name": c["name"],
                    "symbol": c["symbol"],
                    "decimal_places": c["decimal_places"],
                    "is_active": True,
                    "is_base": False,
                },
            )
            if created:
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully seeded {created_count} default currencies."
            )
        )
