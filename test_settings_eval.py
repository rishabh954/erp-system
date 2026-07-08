import sys
import os

print(f"sys.argv: {sys.argv}")
print(f"pytest in sys.modules: {'pytest' in sys.modules}")
print(f"DB_HOST: {os.environ.get('DB_HOST')}")

is_testing = 'test' in sys.argv or 'pytest' in sys.modules or any('pytest' in arg for arg in sys.argv)
print(f"is_testing: {is_testing}")
