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
u = User.objects.create(
    email='x9@example.com',
    username='x9',
    first_name='A',
    last_name='B',
    primary_company=company,
    role=User.Role.COMPANY_ADMIN,
)
print('before set', repr(u.totp_secret), u.username)
u.totp_secret = 'JBSWY3DPEHPK3PXP'
print('prepared', repr(User._meta.get_field('totp_secret').get_prep_value('JBSWY3DPEHPK3PXP')))
u.save(update_fields=['totp_secret'])
print('instance after save', repr(u.totp_secret))
print('fresh read', repr(User.objects.get(pk=u.pk).totp_secret))
with connection.cursor() as cursor:
    cursor.execute('SELECT totp_secret FROM auth_users WHERE id = %s', [str(u.pk)])
    row = cursor.fetchone()
    print('raw db row', row)
    print('raw repr', repr(row[0]) if row else None)

plain = 'PLAINTEXT_SECRET'
with connection.cursor() as cursor:
    cursor.execute('UPDATE auth_users SET totp_secret = %s WHERE id = %s', [plain, str(u.pk)])
print('legacy read', repr(User.objects.get(pk=u.pk).totp_secret))
