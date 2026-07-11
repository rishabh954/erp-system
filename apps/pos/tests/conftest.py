import pytest

from apps.authentication.models import User
from apps.company.models import Company


@pytest.fixture
def pos_company(db):
    return Company.objects.create(name="POS Test Company")

from django.core.management import call_command


@pytest.fixture(autouse=True)
def setup_perms(db):
    call_command('setup_permissions')

@pytest.fixture
def pos_user_with_read(db, pos_company):
    # Customer Portal role has no POS access by default, but let's give them a role that has read-only pos, wait, no role has read-only POS.
    # Let's create a custom ModulePermission for this user's role
    user = User.objects.create_user(email="read@pos.com", password="password", primary_company=pos_company, role=User.Role.EMPLOYEE)
    # The EMPLOYEE role has pos.read and pos.create, wait, I need a role that ONLY has read. Let's make CUSTOMER_PORTAL have pos.read only.
    # Actually, I can just modify the ModulePermission for EMPLOYEE to have can_create=False for the read user, but it's by role.
    # Let's just create a custom role or modify the DB directly.
    from apps.authentication.models import ModulePermission
    ModulePermission.objects.filter(role=User.Role.CUSTOMER_PORTAL, module="pos").delete()
    ModulePermission.objects.create(role=User.Role.CUSTOMER_PORTAL, module="pos", can_read=True, can_create=False)
    user.role = User.Role.CUSTOMER_PORTAL
    user.save()
    return user

@pytest.fixture
def pos_user_with_create(db, pos_company):
    # EMPLOYEE role has pos.create because of our earlier setup_permissions.py change
    user = User.objects.create_user(email="create@pos.com", password="password", primary_company=pos_company, role=User.Role.EMPLOYEE)
    return user
