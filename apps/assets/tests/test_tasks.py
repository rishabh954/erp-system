import pytest

from apps.assets.tasks import process_depreciation


@pytest.mark.django_db
def test_process_depreciation_no_crash():
    # Calling this directly should not raise NameError for timezone
    process_depreciation()
