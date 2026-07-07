# 🏢 EnterpriseERP — Complete System

> Production-ready Enterprise Resource Planning system built with Django 5+, PostgreSQL, Redis, Celery, Bootstrap 5, and glassmorphism UI.

---

## 📁 Project Structure

```
erp_system/
├── config/                          # Django project configuration
│   ├── settings.py                  # Production-ready settings
│   ├── urls.py                      # Root URL configuration
│   ├── celery.py                    # Celery + beat schedule
│   ├── wsgi.py / asgi.py
│   └── __init__.py
│
├── core/                            # Shared base layer
│   ├── models.py                    # Abstract base models (UUID, soft-delete, audit)
│   ├── services.py                  # Base service + repository pattern
│   ├── middleware.py                # Audit, tenant, active-user middleware
│   ├── pagination.py                # Standard paginator
│   ├── exceptions.py                # Custom DRF exception handler
│   ├── context_processors.py        # Company, notifications, theme
│   └── admin.py                     # All admin registrations
│
├── apps/
│   ├── authentication/              # Custom User model, RBAC, 2FA, JWT
│   │   ├── models.py                # User, Role, Permission, ActivityLog, Session
│   │   ├── views.py                 # Login, logout, register, 2FA, profile
│   │   ├── forms.py                 # Auth forms
│   │   ├── services.py              # 2FA, email verification, token generation
│   │   ├── tasks.py                 # Session cleanup, audit log retention
│   │   ├── urls.py                  # Web URL patterns
│   │   └── api/
│   │       ├── views.py             # JWT login/logout, UserViewSet, RoleViewSet
│   │       └── urls.py              # API URL patterns
│   │
│   ├── company/                     # Multi-company, branches, departments
│   │   ├── models.py                # Company, Branch, Department, Currency, FY, Tax
│   │   ├── views.py                 # Settings, branches, departments, users
│   │   ├── tasks.py                 # Exchange rates, trial reminders
│   │   └── urls.py
│   │
│   ├── hrms/                        # Human Resource Management
│   │   ├── models.py                # Employee, Attendance, Leave, Payroll, Payslip
│   │   ├── views.py                 # Employee CRUD, attendance, leave, payroll
│   │   ├── tasks.py                 # Payroll processing, auto-attendance, leave balance
│   │   └── urls.py
│   │
│   ├── crm/                         # Customer Relationship Management
│   │   ├── models.py                # Lead, Customer, LeadActivity
│   │   ├── views.py                 # Leads, pipeline, customers
│   │   └── urls.py
│   │
│   ├── sales/                       # Sales Management
│   │   ├── models.py                # Quotation, SalesOrder, Invoice, Payment
│   │   ├── views.py                 # Full sales workflow views
│   │   ├── tasks.py                 # Overdue invoice checker
│   │   ├── urls.py
│   │   └── api/
│   │       ├── views.py             # Full DRF ViewSets
│   │       └── urls.py
│   │
│   ├── purchase/                    # Purchase Management
│   │   ├── models.py                # Vendor, PurchaseRequest, PurchaseOrder, GRN
│   │   ├── views.py                 # Full purchase workflow
│   │   └── urls.py
│   │
│   ├── inventory/                   # Inventory Management
│   │   ├── models.py                # Product, Warehouse, StockRecord, Movement, Transfer
│   │   ├── views.py                 # Products, warehouses, movements, reports
│   │   ├── tasks.py                 # Low stock alerts
│   │   └── urls.py
│   │
│   ├── accounting/                  # Accounting Module
│   │   ├── models.py                # Account, Journal, JournalEntry, BankAccount
│   │   ├── views.py                 # CoA, journals, bank, B/S, P&L, trial balance
│   │   └── urls.py
│   │
│   ├── projects/                    # Project Management
│   │   ├── models.py                # Project, Task, Milestone, TimeLog, Comment
│   │   ├── views.py                 # Projects, kanban, tasks, time logging
│   │   └── urls.py
│   │
│   ├── assets/                      # Asset Management
│   │   ├── models.py                # Asset, AssetCategory, Maintenance, Depreciation
│   │   ├── views.py                 # Asset CRUD, maintenance, depreciation
│   │   ├── tasks.py                 # Monthly depreciation processing
│   │   └── urls.py
│   │
│   ├── helpdesk/                    # Help Desk
│   │   ├── models.py                # Ticket, TicketCategory, Reply, KnowledgeBase
│   │   ├── views.py                 # Tickets, replies, SLA management
│   │   └── urls.py
│   │
│   ├── documents/                   # Document Management
│   │   ├── models.py                # Document, DocumentCategory, DocumentVersion
│   │   ├── views.py                 # Upload, versioning, approval
│   │   └── urls.py
│   │
│   ├── notifications/               # Notification Engine
│   │   ├── models.py                # Notification, EmailLog
│   │   ├── views.py                 # List, mark-read, API ViewSet
│   │   ├── tasks.py                 # Email sending, bulk notifications, workflow
│   │   └── urls.py
│   │
│   ├── workflow/                    # Workflow Automation
│   │   ├── models.py                # WorkflowDefinition, Step, Instance, Action
│   │   ├── views.py                 # Definitions, instances, approvals
│   │   └── urls.py
│   │
│   └── dashboard/                   # Dashboards
│       ├── views.py                 # CEO, HR, Sales, Finance dashboards + global search
│       ├── urls.py
│       └── api/urls.py
│
├── templates/                       # HTML templates
│   ├── base.html                    # Master layout (sidebar, navbar, notifications)
│   ├── authentication/
│   │   └── login.html               # Glassmorphism login page
│   ├── dashboard/
│   │   └── index.html               # CEO dashboard with Chart.js
│   ├── sales/invoices/
│   │   └── detail.html              # Invoice detail with payment modal
│   ├── hrms/employees/
│   │   └── list.html                # Employee grid/list view
│   ├── projects/
│   │   └── kanban.html              # Drag-and-drop Kanban board
│   └── accounting/reports/
│       └── profit_and_loss.html     # P&L statement with charts
│
├── static/
│   ├── css/erp-main.css             # Full design system (glassmorphism, dark mode)
│   └── js/erp-main.js               # ERP JS (sidebar, theme, notifications, kanban)
│
├── docker/
│   ├── entrypoint.sh                # Docker startup script
│   └── nginx/erp.conf               # Nginx reverse proxy config
│
├── Dockerfile                       # Production Docker image
├── docker-compose.yml               # Full stack: Django + PG + Redis + Celery + Nginx
├── requirements.txt                 # All Python dependencies
├── .env.example                     # Environment variables template
├── INSTALLATION.md                  # Complete setup & deployment guide
├── verify_system.py                 # Connectivity verification script
└── manage.py
```

---

## 🛠️ Verification & Capabilities

- **System Verification**: Use `python verify_system.py` to validate database, redis, and celery worker connectivity post-deployment.
- **Automated Seeding**: Default Chart of Accounts and currencies are automatically bootstrapped during migrations (`apps/company/management/commands/seed_default_coa.py`).
- **CSV Import**: Full support for importing CSV data (e.g. Customers, Inventory, Chart of Accounts) directly through the admin panels or dedicated import endpoints.

---

## 🚀 Quick Start

```bash
# 1. Clone and configure
cp .env.example .env && nano .env

# 2. Start with Docker
docker-compose up --build -d

# 3. Visit
open http://localhost
```

---

## 🏗️ Architecture

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, Django 5, Django REST Framework |
| Database | PostgreSQL 16 (UUID PKs, soft-delete, indexes) |
| Cache / Queue | Redis 7 |
| Task Queue | Celery 5 + Celery Beat |
| Auth | JWT (SimpleJWT) + Session + 2FA (TOTP) |
| Frontend | Bootstrap 5, Chart.js, DataTables, SweetAlert2 |
| Containerization | Docker + Docker Compose |
| Web Server | Nginx + Gunicorn |

---

## 🧩 Modules

| # | Module | Key Features |
|---|--------|-------------|
| 1 | **Auth & Users** | RBAC (10 roles), 2FA, JWT, activity logs, session control |
| 2 | **Company** | Multi-company, branches, departments, fiscal years, currencies |
| 3 | **HRMS** | Employees, attendance, leave workflow, payroll processing |
| 4 | **CRM** | Leads, pipeline Kanban, customers, activity timeline |
| 5 | **Sales** | Quotation → SO → Invoice → Payment workflow |
| 6 | **Purchase** | Vendors, requisitions, POs, goods receipts |
| 7 | **Inventory** | Products, multi-warehouse, stock movements, transfers |
| 8 | **Accounting** | Chart of accounts, double-entry journals, bank, financial reports |
| 9 | **Projects** | Projects, milestones, Kanban tasks, time logging |
| 10 | **Assets** | Registration, allocation, depreciation, maintenance |
| 11 | **Help Desk** | Tickets, SLA tracking, knowledge base |
| 12 | **Documents** | Upload, versioning, approval workflow |
| 13 | **Notifications** | In-app, email (Celery), real-time badge updates |
| 14 | **Workflow** | Configurable approval flows for any model |
| 15 | **Dashboards** | CEO, HR, Sales, Finance — Chart.js KPIs |

---

## 🔑 Default Login

After first boot, log in with the superuser you created:

```
URL:      http://localhost/auth/login/
Email:    admin@yourdomain.com    (from .env)
Password: (your DJANGO_SUPERUSER_PASSWORD)
```

---

## 📄 License

MIT License — free for commercial and personal use.
