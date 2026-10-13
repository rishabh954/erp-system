"""Run a targeted set of tests and output results to a file."""
import subprocess
import os
import sys
import time

os.chdir(r'c:\Users\91878\OneDrive\Desktop\erp-system\erp-system')
env = {
    **os.environ,
    'DEBUG': 'True',
    'DB_ENGINE': 'django.db.backends.sqlite3',
    'DB_NAME': '/tmp/erp.sqlite3',
    'DJANGO_TESTING': '1',
}

test_paths = [
    'apps/accounting/tests.py',
    'apps/accounting/test_regression_bugs.py',
    'apps/analytics/tests.py',
    'apps/api/test_serializers.py',
    'apps/crm/tests/test_views_setup.py',
    'apps/sales/tests/test_regression_bugs.py',
    'apps/administration/tests/test_url_fixes.py',
    'apps/inventory/tests/test_main.py',
    'tests/test_production_hardening.py',
]

outfile = f'test_results_{int(time.time())}.txt'
r = subprocess.run(
    [sys.executable, '-m', 'pytest', '--no-cov', '--nomigrations', '-v', '--tb=short',
     '-p', 'no:cacheprovider', '-o', 'addopts='] + test_paths,
    env=env,
    capture_output=True,
    text=True,
    timeout=600,
)

output = r.stdout + '\n' + r.stderr
with open(outfile, 'w') as f:
    f.write(output)
with open('latest_test_results.txt', 'w') as f:
    f.write(output)

print(f"Output written to {outfile}")
print(output[-4000:])
sys.exit(r.returncode)
