# EnterpriseERP — Installation & Deployment Guide

## Table of Contents
1. [System Requirements](#requirements)
2. [Local Development Setup](#local)
3. [Docker Deployment](#docker)
4. [Production Ubuntu Server Deployment](#production)
5. [Configuration Reference](#config)
6. [Post-Installation Setup](#post-install)
7. [Troubleshooting](#troubleshooting)

---

## 1. System Requirements <a name="requirements"></a>

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8+ GB |
| Disk | 20 GB | 50+ GB SSD |
| OS | Ubuntu 20.04 | Ubuntu 22.04+ |
| Python | 3.12+ | 3.12 |
| PostgreSQL | 14+ | 16 |
| Redis | 6+ | 7 |
| Node.js | Not required | — |

---

## 2. Local Development Setup <a name="local"></a>

### Clone and set up environment
```bash
git clone https://github.com/your-org/enterprise-erp.git
cd enterprise-erp

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate          # Linux/Mac
# venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and configure env
cp .env.example .env
nano .env                         # Edit values
```

### Set up PostgreSQL locally
```bash
sudo -u postgres psql
CREATE DATABASE erp_db;
CREATE USER erp_user WITH PASSWORD 'erp_password';
GRANT ALL PRIVILEGES ON DATABASE erp_db TO erp_user;
ALTER DATABASE erp_db OWNER TO erp_user;
\q
```

### Run Redis locally
```bash
# Ubuntu
sudo apt install redis-server
sudo systemctl start redis

# macOS
brew install redis
brew services start redis
```

### Initialize the database
```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
python manage.py compilemessages
```

### Load initial data (optional)
```bash
python manage.py loaddata fixtures/currencies.json
python manage.py loaddata fixtures/default_permissions.json
```

### Start development servers
```bash
# Terminal 1: Django
python manage.py runserver 0.0.0.0:8000

# Terminal 2: Celery worker
celery -A config.celery worker -l info

# Terminal 3: Celery beat
celery -A config.celery beat -l info

# Terminal 4: Flower (optional - Celery monitoring)
celery -A config.celery flower --port=5555
```

Open: http://localhost:8000

---

## 3. Docker Deployment <a name="docker"></a>

### Quick start (development)
```bash
cp .env.example .env
# Edit .env with your values

docker-compose up --build -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f web
docker-compose logs -f celery_worker
```

### Run migrations inside Docker
```bash
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
```

### Stop and clean up
```bash
docker-compose down          # Stop containers
docker-compose down -v       # Stop + remove volumes (⚠️ deletes data)
```

---

## 4. Production Ubuntu Server Deployment <a name="production"></a>

### Step 1: Server preparation
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3-pip \
    postgresql postgresql-contrib redis-server nginx \
    certbot python3-certbot-nginx \
    build-essential libpq-dev gettext curl git supervisor
```

### Step 2: PostgreSQL setup
```bash
sudo -u postgres psql
CREATE DATABASE erp_db;
CREATE USER erp_user WITH PASSWORD 'STRONG_PASSWORD_HERE';
GRANT ALL PRIVILEGES ON DATABASE erp_db TO erp_user;
ALTER DATABASE erp_db OWNER TO erp_user;
\q

# Enable and start PostgreSQL
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

### Step 3: Redis setup
```bash
sudo nano /etc/redis/redis.conf
# Add: requirepass STRONG_REDIS_PASSWORD

sudo systemctl enable redis
sudo systemctl restart redis
```

### Step 4: Application setup
```bash
sudo useradd -m -s /bin/bash erp
sudo su - erp

git clone https://github.com/your-org/enterprise-erp.git /home/erp/app
cd /home/erp/app

python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env  # Configure production values: DEBUG=False, proper DB creds, etc.

python manage.py migrate
python manage.py collectstatic --noinput
python manage.py compilemessages
python manage.py createsuperuser
```

### Step 5: Gunicorn with Supervisor
```bash
sudo nano /etc/supervisor/conf.d/erp_web.conf
```
```ini
[program:erp_web]
command=/home/erp/app/venv/bin/gunicorn config.wsgi:application
    --bind 0.0.0.0:8000
    --workers 4
    --worker-class sync
    --timeout 120
    --max-requests 1000
    --max-requests-jitter 50
directory=/home/erp/app
user=erp
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/erp/gunicorn.log
environment=DJANGO_SETTINGS_MODULE="config.settings"

[program:erp_celery]
command=/home/erp/app/venv/bin/celery -A config.celery worker -l info -c 4
directory=/home/erp/app
user=erp
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/erp/celery_worker.log

[program:erp_celery_beat]
command=/home/erp/app/venv/bin/celery -A config.celery beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
directory=/home/erp/app
user=erp
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/erp/celery_beat.log
```
```bash
sudo mkdir -p /var/log/erp
sudo chown erp:erp /var/log/erp
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start all
```

### Step 6: Nginx with SSL
```bash
sudo nano /etc/nginx/sites-available/erp
```
```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    client_max_body_size 50M;

    location /static/ {
        alias /home/erp/app/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        alias /home/erp/app/media/;
        expires 7d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/erp /etc/nginx/sites-enabled/
sudo nginx -t
sudo certbot --nginx -d yourdomain.com
sudo systemctl restart nginx
```

---

## 5. Configuration Reference <a name="config"></a>

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key (50+ chars) | — |
| `DEBUG` | Debug mode (`True`/`False`) | `False` |
| `DB_NAME` | PostgreSQL database name | `erp_db` |
| `DB_USER` | PostgreSQL username | `erp_user` |
| `DB_PASSWORD` | PostgreSQL password | — |
| `DB_HOST` | PostgreSQL host | `db` |
| `REDIS_URL` | Redis connection URL | `redis://redis:6379/0` |
| `CELERY_BROKER_URL` | Celery broker | `redis://redis:6379/1` |
| `EMAIL_HOST` | SMTP server | `smtp.gmail.com` |
| `DEFAULT_CURRENCY` | Base currency code | `USD` |
| `ENABLE_2FA` | Enable 2FA | `True` |

---

## 6. Post-Installation Setup <a name="post-install"></a>

After installation, log in as superuser and complete:

1. **Create your company** → Company → Company Management → Add Company
2. **Set default currency** → Company → Currencies → Mark USD (or your currency) as base
3. **Create fiscal year** → Company → Fiscal Years → Add current year
4. **Set up Chart of Accounts** → Accounting → Chart of Accounts → Import or create
5. **Configure tax rates** → Company → Tax Settings
6. **Create departments & branches** → Company → Departments / Branches
7. **Add employees** → HRMS → Employees → Add Employee
8. **Configure leave types** → HRMS → Leave Management → Leave Types
9. **Create warehouses** → Inventory → Warehouses
10. **Add products** → Inventory → Products
11. **Configure email** → Settings → .env file → EMAIL_HOST etc.
12. **Set up workflow approvals** → Workflow → Workflow Definitions

---

## 7. Troubleshooting <a name="troubleshooting"></a>

### Static files not loading
```bash
python manage.py collectstatic --noinput --clear
sudo systemctl restart nginx
```

### Database migrations failing
```bash
python manage.py showmigrations
python manage.py migrate --run-syncdb
```

### Celery tasks not running
```bash
celery -A config.celery inspect active
celery -A config.celery inspect registered
redis-cli ping  # Should return PONG
```

### Check application logs
```bash
# Docker
docker-compose logs -f web
docker-compose logs -f celery_worker

# Supervisor
sudo tail -f /var/log/erp/gunicorn.log
sudo tail -f /var/log/erp/celery_worker.log

# Application
tail -f logs/erp.log
```

### Reset admin password
```bash
python manage.py changepassword admin@yourdomain.com
```

### Clear Redis cache
```bash
redis-cli -a YOUR_REDIS_PASSWORD FLUSHDB
```
