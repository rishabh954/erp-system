import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['DB_HOST'] = 'sqlite'
os.environ['DB_ENGINE'] = 'django.db.backends.sqlite3'
import django
django.setup()
from django.db import connection
from apps.authentication.models import User
from apps.company.models import Company

c = Company.objects.create(name='X', company_type='llc')
u = User(email='x@test.com', first_name='A', last_name='B', username='x', primary_company=c)
u.set_password('pw')
u.totp_secret = 'JBSWY3DPEHPK3PXP'
print('before save field prep', User._meta.get_field('totp_secret').get_prep_value('JBSWY3DPEHPK3PXP'))
u.save(update_fields=['totp_secret'])
print('after save ORM value', User.objects.get(pk=u.pk).totp_secret)
with connection.cursor() as cursor:
    cursor.execute('SELECT totp_secret FROM auth_users WHERE id = %s', [str(u.pk)])
    row = cursor.fetchone()
    print('raw row', row)
    print('raw repr', repr(row[0]) if row else None)
