import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_all_model_changes_have_migrations():
    call_command("makemigrations", check=True, dry_run=True, verbosity=0)
