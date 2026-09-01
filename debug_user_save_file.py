import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['DB_HOST'] = 'sqlite'
os.environ['DB_ENGINE'] = 'django.db.backends.sqlite3'
import django
django.setup()
from apps.authentication.models import User
from core.factories import CompanyFactory
from django.db import connection

company = CompanyFactory()
u = User.objects.create(
    email='debuguser@example.com',
    username='debuguser',
    first_name='A',
    last_name='B',
    primary_company=company,
    role=User.Role.COMPANY_ADMIN,
)
print('created', u.pk)
print('exists before', User.objects.filter(pk=u.pk).exists())
print('prior secret', repr(u.totp_secret))
u.totp_secret = 'JBSWY3DPEHPK3PXP'
print('assigned secret', repr(u.totp_secret))
u.save(update_fields=['totp_secret'])
print('exists after', User.objects.filter(pk=u.pk).exists())
print('values', list(User.objects.filter(pk=u.pk).values_list('pk', 'totp_secret', 'username')))
with connection.cursor() as c:
    c.execute('SELECT id, username, totp_secret FROM auth_users WHERE id = %s', [str(u.pk)])
    print('raw row', c.fetchone())
