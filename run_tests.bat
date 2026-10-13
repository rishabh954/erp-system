@echo off
set DEBUG=True
set DB_ENGINE=django.db.backends.sqlite3
set DB_NAME=/tmp/erp.sqlite3
set DJANGO_TESTING=1
python -m pytest --no-cov --nomigrations %*
