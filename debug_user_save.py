import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['DB_HOST'] = 'sqlite'
os.environ['DB_ENGINE'] = 'django.db.backends.sqlite3'

import django
django.setup()
from django.db import connection
from apps.authentication.models import User
from apps.company.models import Company

company = Company.objects.create(name='Debug Co', company_type='llc')
user = User.objects.create(email='debug@example.com', username='debuguser', first_name='D', last_name='E', primary_company=company, role=User.Role.COMPANY_ADMIN)
print('pk', user.pk)
print('before rows', User.objects.filter(pk=user.pk).count())
print('before secret', repr(user.totp_secret))
user.totp_secret = 'JBSWY3DPEHPK3PXP'
print('before save direct attr', repr(user.totp_secret))
user.save(update_fields=['totp_secret'])
print('after save attr', repr(user.totp_secret))
print('after rows', User.objects.filter(pk=user.pk).count())
print('after fetch', User.objects.filter(pk=user.pk).values_list('pk','totp_secret','username'))
with connection.cursor() as c:
    c.execute('SELECT pk, username, totp_secret FROM auth_users WHERE id = %s', [str(user.pk)])
    print('raw q', c.fetchone())
    c.execute('SELECT COUNT(*) FROM auth_users WHERE id = %s', [str(user.pk)])
    print('count', c.fetchone())
