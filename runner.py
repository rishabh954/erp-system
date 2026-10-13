import subprocess, os, sys
os.chdir(r'c:\Users\91878\OneDrive\Desktop\erp-system\erp-system')
env = {**os.environ, 'DEBUG': 'True', 'DB_ENGINE': 'django.db.backends.sqlite3', 'DB_NAME': '/tmp/erp.sqlite3', 'DJANGO_TESTING': '1'}
args = sys.argv[1:]
r = subprocess.run([sys.executable, '-m', 'pytest', '--no-cov', '--nomigrations'] + args, env=env, capture_output=True, text=True)
print(r.stdout[-6000:])
print(r.stderr[-2000:])
sys.exit(r.returncode)
