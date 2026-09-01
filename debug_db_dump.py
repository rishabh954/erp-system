import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['DB_HOST'] = 'sqlite'
os.environ['DB_ENGINE'] = 'django.db.backends.sqlite3'
import django
django.setup()
from django.db import connection
from apps.authentication.models import User
from core.factories import CompanyFactory

company = CompanyFactory()
u = User.objects.create(email='dump@example.com', username='dumpuser', first_name='A', last_name='B', primary_company=company, role=User.Role.COMPANY_ADMIN)
u.totp_secret = 'JBSWY3DPEHPK3PXP'
u.save(update_fields=['totp_secret'])
print('instance pk', u.pk, 'str', str(u.pk), 'hex', u.pk.hex)
print('orm value', User.objects.filter(pk=u.pk).values_list('pk', 'totp_secret').first())
print('full table rows:')
for row in connection.cursor().execute('SELECT id, username, totp_secret FROM auth_users').fetchall():
    print(repr(row))
print('where by hex:')
print(connection.cursor().execute('SELECT id, username, totp_secret FROM auth_users WHERE id = ?', [u.pk.hex]).fetchall())
print('where by str:')
print(connection.cursor().execute('SELECT id, username, totp_secret FROM auth_users WHERE id = ?', [str(u.pk)]).fetchall())
