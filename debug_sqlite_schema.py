import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
os.environ['DB_HOST']='sqlite'
os.environ['DB_ENGINE']='django.db.backends.sqlite3'
import django
django.setup()
from django.db import connection
from apps.authentication.models import User
from core.factories import CompanyFactory

print('tables=', connection.introspection.table_names())
print('auth_users schema=', connection.cursor().execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='auth_users'").fetchone())
print('field type=', type(User._meta.get_field('totp_secret')))
company = CompanyFactory()
u = User.objects.create(email='schema2@example.com', username='schema2', first_name='A', last_name='B', primary_company=company, role=User.Role.COMPANY_ADMIN)
u.totp_secret = 'JBSWY3DPEHPK3PXP'
u.save(update_fields=['totp_secret'])
print('orm values=', list(User.objects.filter(pk=u.pk).values_list('pk','username','totp_secret')))
print('raw rows=', connection.cursor().execute('SELECT id, username, totp_secret FROM auth_users WHERE id = ?', [str(u.pk)]).fetchone())
print('all raw=', connection.cursor().execute('SELECT id, username, totp_secret FROM auth_users').fetchall())
