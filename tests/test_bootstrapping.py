import pytest
from django.core.management import call_command
from apps.company.models import Currency
from django.contrib.auth.models import Permission

@pytest.mark.django_db
def test_seed_currencies_management_command():
    """Test that seeding currencies works and is idempotent."""
    # Conftest already seeded currencies, so count is > 0
    count_initial = Currency.objects.count()
    assert count_initial > 0
    
    # First run
    call_command('seed_currencies')
    count_after_first = Currency.objects.count()
    assert count_after_first > 0
    
    # Second run should not duplicate
    call_command('seed_currencies')
    count_after_second = Currency.objects.count()
    assert count_after_second == count_after_first

@pytest.mark.django_db
def test_setup_permissions_management_command():
    """Test that setup_permissions works and creates custom permissions."""
    from apps.authentication.models import ModulePermission
    
    # First run
    call_command('setup_permissions')
    
    # Assert some custom permissions were created
    assert ModulePermission.objects.exists()
    
    # Run again to ensure idempotency (should not crash)
    call_command('setup_permissions')
