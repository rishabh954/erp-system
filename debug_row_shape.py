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
u = User.objects.create(email='rowshape@example.com', username='rowshape', first_name='A', last_name='B', primary_company=company, role=User.Role.COMPANY_ADMIN)
u.totp_secret = 'JBSWY3DPEHPK3PXP'
u.save(update_fields=['totp_secret'])
print('pk instance', u.pk)
print('all rows', list(User.objects.values_list('pk','username','totp_secret')))
print('raw all users', connection.cursor().execute('SELECT id, username, totp_secret FROM auth_users').fetchall())
print('specific raw', connection.cursor().execute('SELECT id, username, totp_secret FROM auth_users WHERE id = %s', [str(u.pk)]).fetchone())
print('pk repr str', str(u.pk))
