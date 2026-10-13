$env:DEBUG = "True"
$env:DB_ENGINE = "django.db.backends.sqlite3"
$env:DB_NAME = "/tmp/erp.sqlite3"
$env:DJANGO_TESTING = "1"
& python -m pytest --no-cov --nomigrations $args 2>&1 | Out-File -FilePath test_results.txt -Encoding UTF8
Get-Content test_results.txt | Select-Object -Last 50
