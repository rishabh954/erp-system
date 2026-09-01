$ErrorActionPreference = 'Stop'
Set-Location 'c:\Users\OM\Documents\GitHub\erp-system'
$env:DB_HOST = 'sqlite'
$env:DB_ENGINE = 'django.db.backends.sqlite3'
& '.\venv\Scripts\python.exe' - <<'PY'
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from apps.authentication.models import User
from apps.company.models import Company
from django.db import connection

company = Company.objects.create(name='Debug Co', company_type='llc')
user = User.objects.create(email='debug@example.com', username='debuguser', first_name='D', last_name='E', primary_company=company, role=User.Role.COMPANY_ADMIN)
print('pk', user.pk)
print('before save attr', repr(user.totp_secret))
user.totp_secret = 'JBSWY3DPEHPK3PXP'
user.save(update_fields=['totp_secret'])
print('after save attr', repr(user.totp_secret))
print('exists', User.objects.filter(pk=user.pk).exists())
print('values', list(User.objects.filter(pk=user.pk).values_list('pk','username','totp_secret')))
with connection.cursor() as c:
    c.execute('SELECT id, username, totp_secret FROM auth_users WHERE id = %s', [str(user.pk)])
    print('raw row', c.fetchone())
PY
