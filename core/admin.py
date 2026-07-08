"""
Django Admin Configuration
All ERP models registered with custom admin classes
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from apps.authentication.models import (
    ActivityLog,
    ModulePermission,
    PasswordResetToken,
    Permission,
    Role,
    User,
    UserCompany,
    UserSession,
)

# ─── Authentication ────────────────────────────────────────────────────────────


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = [
        "email",
        "full_name",
        "role",
        "primary_company",
        "is_active",
        "date_joined",
    ]
    list_filter = ["role", "is_active", "is_staff", "two_factor_enabled"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["-date_joined"]
    readonly_fields = ["last_login", "date_joined", "last_active", "last_login_ip"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Personal info"),
            {"fields": ("first_name", "last_name", "phone", "avatar")},
        ),
        (_("Company & Role"), {"fields": ("primary_company", "role")}),
        (
            _("Preferences"),
            {"fields": ("language", "timezone", "theme", "date_format")},
        ),
        (
            _("Security"),
            {
                "fields": (
                    "two_factor_enabled",
                    "two_factor_method",
                    "failed_login_attempts",
                    "locked_until",
                )
            },
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            _("Activity"),
            {"fields": ("last_login", "last_active", "last_login_ip", "date_joined")},
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "password1",
                    "password2",
                    "role",
                ),
            },
        ),
    )


@admin.register(UserCompany)
class UserCompanyAdmin(admin.ModelAdmin):
    list_display = ["user", "company", "role", "is_active", "joined_at"]
    list_filter = ["is_active", "company"]
    search_fields = ["user__email", "company__name"]


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "action",
        "module",
        "resource_type",
        "ip_address",
        "created_at",
    ]
    list_filter = ["action", "module", "company"]
    search_fields = ["user__email", "description", "resource_id"]
    readonly_fields = [
        "user",
        "company",
        "action",
        "module",
        "resource_type",
        "resource_id",
        "description",
        "ip_address",
        "created_at",
    ]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ModulePermission)
class ModulePermissionAdmin(admin.ModelAdmin):
    list_display = [
        "role",
        "module",
        "can_create",
        "can_read",
        "can_update",
        "can_delete",
        "can_approve",
        "can_export",
    ]
    list_filter = ["role", "module"]
    list_editable = [
        "can_create",
        "can_read",
        "can_update",
        "can_delete",
        "can_approve",
        "can_export",
    ]


# ─── Company ───────────────────────────────────────────────────────────────────

from apps.company.models import (  # noqa: E402
    Branch,
    Company,
    Currency,
    Department,
    ExchangeRate,
    FiscalYear,
    Tax,
    TaxGroup,
)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "status",
        "subscription_plan",
        "default_currency",
        "created_at",
    ]
    list_filter = ["status", "subscription_plan", "company_type"]
    search_fields = ["name", "legal_name", "tax_id"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        (
            "Basic Info",
            {
                "fields": (
                    "name",
                    "legal_name",
                    "registration_number",
                    "tax_id",
                    "vat_number",
                    "company_type",
                    "industry",
                    "status",
                )
            },
        ),
        ("Contact", {"fields": ("phone", "mobile", "email", "website")}),
        (
            "Address",
            {
                "fields": (
                    "address_line1",
                    "address_line2",
                    "city",
                    "state",
                    "country",
                    "postal_code",
                )
            },
        ),
        (
            "Branding",
            {"fields": ("logo", "favicon", "primary_color", "secondary_color")},
        ),
        ("Financial", {"fields": ("default_currency", "fiscal_year_start")}),
        (
            "Settings",
            {"fields": ("language", "timezone", "date_format", "number_format")},
        ),
        ("Subscription", {"fields": ("subscription_plan", "trial_ends_at")}),
    )


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "company", "is_headquarters", "is_active"]
    list_filter = ["company", "is_headquarters", "is_active"]
    search_fields = ["name", "code"]


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "company", "branch", "head", "is_active"]
    list_filter = ["company", "is_active"]
    search_fields = ["name", "code"]


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "symbol", "decimal_places", "is_active", "is_base"]
    list_filter = ["is_active", "is_base"]
    list_editable = ["is_active", "is_base"]


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "start_date", "end_date", "status", "is_current"]
    list_filter = ["company", "status", "is_current"]


@admin.register(Tax)
class TaxAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "rate", "tax_type", "is_active"]
    list_filter = ["company", "tax_type", "is_active"]


# ─── HRMS ──────────────────────────────────────────────────────────────────────

from apps.hrms.models import (  # noqa: E402
    Attendance,
    Employee,
    JobTitle,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    PayrollPeriod,
    Payslip,
)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = [
        "employee_id",
        "full_name",
        "company",
        "department",
        "job_title",
        "status",
        "joining_date",
    ]
    list_filter = ["company", "status", "department", "gender"]
    search_fields = ["employee_id", "first_name", "last_name", "email", "national_id"]
    readonly_fields = ["created_at", "updated_at"]

    def full_name(self, obj):
        return obj.full_name

    full_name.short_description = "Name"


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ["employee", "date", "status", "check_in", "check_out", "work_hours"]
    list_filter = ["company", "status", "date"]
    search_fields = [
        "employee__first_name",
        "employee__last_name",
        "employee__employee_id",
    ]
    date_hierarchy = "date"


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "employee",
        "leave_type",
        "start_date",
        "end_date",
        "total_days",
        "status",
    ]
    list_filter = ["company", "status", "leave_type"]
    search_fields = ["number", "employee__first_name", "employee__last_name"]


@admin.register(PayrollPeriod)
class PayrollPeriodAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "company",
        "period_start",
        "period_end",
        "status",
        "total_net",
    ]
    list_filter = ["company", "status"]


@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "employee",
        "payroll_period",
        "gross_salary",
        "net_salary",
        "status",
    ]
    list_filter = ["company", "status", "payroll_period"]
    search_fields = ["number", "employee__first_name", "employee__last_name"]


# ─── CRM ───────────────────────────────────────────────────────────────────────

from apps.crm.models import Customer, Lead  # noqa: E402


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "name",
        "company_name",
        "status",
        "source",
        "expected_revenue",
        "assigned_to",
    ]
    list_filter = ["company", "status", "source"]
    search_fields = ["name", "company_name", "email", "number"]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "customer_code",
        "customer_type",
        "email",
        "phone",
        "is_active",
    ]
    list_filter = ["company", "customer_type", "is_active"]
    search_fields = ["name", "customer_code", "email"]


# ─── Sales ─────────────────────────────────────────────────────────────────────

from apps.sales.models import Invoice, Payment, Quotation, SalesOrder  # noqa: E402


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ["number", "customer", "status", "total", "created_at"]
    list_filter = ["company", "status"]
    search_fields = ["number", "customer__name"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "customer",
        "invoice_date",
        "due_date",
        "total",
        "balance_due",
        "status",
    ]
    list_filter = ["company", "status"]
    search_fields = ["number", "customer__name"]
    date_hierarchy = "invoice_date"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "invoice",
        "customer",
        "amount",
        "payment_date",
        "method",
        "status",
    ]
    list_filter = ["company", "status", "method"]


# ─── Purchase ──────────────────────────────────────────────────────────────────

from apps.purchase.models import PurchaseOrder, PurchaseRequest, Vendor  # noqa: E402


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ["name", "vendor_code", "vendor_type", "status", "rating"]
    list_filter = ["company", "status", "vendor_type"]
    search_fields = ["name", "vendor_code", "email"]


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ["number", "vendor", "order_date", "total", "balance_due", "status"]
    list_filter = ["company", "status"]
    search_fields = ["number", "vendor__name"]


# ─── Inventory ─────────────────────────────────────────────────────────────────

from apps.inventory.models import (  # noqa: E402
    Product,
    ProductCategory,
    StockMovement,
    StockRecord,
    Warehouse,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "category", "cost_price", "sale_price", "is_active"]
    list_filter = ["company", "product_type", "is_active", "category"]
    search_fields = ["sku", "name", "barcode"]
    list_editable = ["is_active"]


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "parent", "company", "is_active"]
    list_filter = ["company", "is_active"]
    search_fields = ["name"]


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "company", "branch", "is_active"]
    list_filter = ["company", "is_active"]


@admin.register(StockRecord)
class StockRecordAdmin(admin.ModelAdmin):
    list_display = [
        "product",
        "warehouse",
        "quantity_on_hand",
        "quantity_reserved",
        "average_cost",
    ]
    list_filter = ["company", "warehouse"]
    search_fields = ["product__sku", "product__name"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "product",
        "warehouse",
        "movement_type",
        "quantity",
        "movement_date",
    ]
    list_filter = ["company", "movement_type", "warehouse"]
    date_hierarchy = "movement_date"


# ─── Accounting ────────────────────────────────────────────────────────────────

from apps.accounting.models import (  # noqa: E402
    Account,
    BankAccount,
    Journal,
    JournalEntry,
)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "account_type", "current_balance", "is_active"]
    list_filter = ["company", "account_type", "is_active"]
    search_fields = ["code", "name"]
    ordering = ["code"]


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "journal",
        "date",
        "total_debit",
        "total_credit",
        "status",
    ]
    list_filter = ["company", "status", "journal"]
    search_fields = ["number", "reference"]
    date_hierarchy = "date"


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "bank_name",
        "account_number",
        "currency",
        "current_balance",
        "is_active",
    ]
    list_filter = ["company", "currency", "is_active"]


# ─── Projects ──────────────────────────────────────────────────────────────────

from apps.projects.models import Project, Task  # noqa: E402


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "name",
        "status",
        "priority",
        "manager",
        "start_date",
        "end_date",
    ]
    list_filter = ["company", "status", "priority"]
    search_fields = ["name", "number"]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "status", "priority", "assigned_to", "due_date"]
    list_filter = ["company", "status", "priority"]
    search_fields = ["title", "project__name"]


# ─── HelpDesk ──────────────────────────────────────────────────────────────────

from apps.helpdesk.models import Ticket, TicketCategory  # noqa: E402


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "title",
        "status",
        "priority",
        "assigned_to",
        "sla_breached",
        "created_at",
    ]
    list_filter = ["company", "status", "priority", "sla_breached"]
    search_fields = ["number", "title"]
    date_hierarchy = "created_at"


@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "company", "sla_hours", "auto_assign_to", "is_active"]
    list_filter = ["company", "is_active"]


# ─── Notifications ─────────────────────────────────────────────────────────────

from apps.notifications.models import EmailLog, Notification  # noqa: E402


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["recipient", "title", "notification_type", "is_read", "created_at"]
    list_filter = ["notification_type", "is_read", "company"]
    search_fields = ["title", "recipient__email"]


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ["recipient_email", "subject", "status", "template", "created_at"]
    list_filter = ["status", "template"]
    search_fields = ["recipient_email", "subject"]
    readonly_fields = [
        "recipient_email",
        "recipient_name",
        "subject",
        "body",
        "status",
        "sent_at",
        "error_message",
        "template",
        "created_at",
    ]


# --- Automatically Generated Admin Registrations ---

from apps.authentication.models import (  # noqa: E402
    EmailVerificationToken,
)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["company", "name", "code", "description", "is_system"]


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ["role", "module", "resource", "action", "is_allowed"]


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "expires_at", "is_used", "ip_address"]


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "expires_at", "is_used"]


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "session_key",
        "ip_address",
        "user_agent",
        "device",
        "location",
    ]


from apps.company.models import CompanySettings  # noqa: E402


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ["from_currency", "to_currency", "rate", "effective_date", "source"]


@admin.register(TaxGroup)
class TaxGroupAdmin(admin.ModelAdmin):
    list_display = ["company", "name", "description", "is_active"]


@admin.register(CompanySettings)
class CompanySettingsAdmin(admin.ModelAdmin):
    list_display = ["company", "key", "value", "value_type"]


from apps.hrms.models import (  # noqa: E402
    EmployeeDocument,
    EmployeeSalary,
    EmployeeSkill,
    ExperienceRecord,
    SalaryComponent,
    SalaryStructure,
    WorkSchedule,
)


@admin.register(JobTitle)
class JobTitleAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "name",
        "description",
        "grade",
    ]


@admin.register(EmployeeDocument)
class EmployeeDocumentAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "employee",
        "document_type",
        "title",
    ]


@admin.register(EmployeeSkill)
class EmployeeSkillAdmin(admin.ModelAdmin):
    list_display = ["employee", "skill_name", "proficiency", "years_experience"]


@admin.register(ExperienceRecord)
class ExperienceRecordAdmin(admin.ModelAdmin):
    list_display = [
        "employee",
        "company_name",
        "job_title",
        "start_date",
        "end_date",
        "is_current",
    ]


@admin.register(WorkSchedule)
class WorkScheduleAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "name",
        "check_in_time",
        "check_out_time",
    ]


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "name",
        "code",
        "days_allowed",
    ]


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = [
        "employee",
        "leave_type",
        "year",
        "allocated",
        "used",
        "carried_forward",
    ]


@admin.register(SalaryStructure)
class SalaryStructureAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "name",
        "description",
        "is_active",
    ]


@admin.register(SalaryComponent)
class SalaryComponentAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "salary_structure",
        "name",
        "code",
    ]


@admin.register(EmployeeSalary)
class EmployeeSalaryAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "employee",
        "salary_structure",
        "basic_salary",
    ]


from apps.crm.models import LeadActivity  # noqa: E402


@admin.register(LeadActivity)
class LeadActivityAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "lead",
        "activity_type",
        "subject",
    ]


from apps.sales.models import InvoiceLine, QuotationLine, SalesOrderLine  # noqa: E402


@admin.register(QuotationLine)
class QuotationLineAdmin(admin.ModelAdmin):
    list_display = [
        "quotation",
        "product",
        "description",
        "quantity",
        "unit_price",
        "discount_percent",
    ]


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "currency",
        "exchange_rate",
        "notes",
    ]


@admin.register(SalesOrderLine)
class SalesOrderLineAdmin(admin.ModelAdmin):
    list_display = [
        "sales_order",
        "product",
        "description",
        "quantity",
        "unit_price",
        "discount_percent",
    ]


@admin.register(InvoiceLine)
class InvoiceLineAdmin(admin.ModelAdmin):
    list_display = [
        "invoice",
        "product",
        "description",
        "quantity",
        "unit_price",
        "discount_percent",
    ]


from apps.purchase.models import (  # noqa: E402
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrderLine,
    PurchaseRequestLine,
)


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = ["created_by", "updated_by", "company", "notes", "number", "title"]


@admin.register(PurchaseRequestLine)
class PurchaseRequestLineAdmin(admin.ModelAdmin):
    list_display = [
        "request",
        "product",
        "description",
        "quantity",
        "unit",
        "estimated_unit_price",
    ]


@admin.register(PurchaseOrderLine)
class PurchaseOrderLineAdmin(admin.ModelAdmin):
    list_display = [
        "purchase_order",
        "product",
        "description",
        "quantity",
        "unit",
        "unit_price",
    ]


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "notes",
        "number",
        "purchase_order",
    ]


@admin.register(GoodsReceiptLine)
class GoodsReceiptLineAdmin(admin.ModelAdmin):
    list_display = [
        "goods_receipt",
        "po_line",
        "quantity_received",
        "quantity_accepted",
        "quantity_rejected",
        "rejection_reason",
    ]


from apps.inventory.models import (  # noqa: E402
    BinLocation,
    Brand,
    InventoryTransfer,
    InventoryTransferLine,
    ProductVariant,
    UnitOfMeasure,
)


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "name",
        "abbreviation",
        "uom_type",
    ]


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ["created_by", "updated_by", "company", "name", "logo", "is_active"]


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ["created_by", "updated_by", "company", "product", "name", "sku"]


@admin.register(BinLocation)
class BinLocationAdmin(admin.ModelAdmin):
    list_display = ["created_by", "updated_by", "company", "warehouse", "name", "code"]


@admin.register(InventoryTransfer)
class InventoryTransferAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "notes",
        "number",
        "from_warehouse",
    ]


@admin.register(InventoryTransferLine)
class InventoryTransferLineAdmin(admin.ModelAdmin):
    list_display = [
        "transfer",
        "product",
        "variant",
        "quantity_requested",
        "quantity_sent",
        "quantity_received",
    ]


from apps.accounting.models import BankTransaction, JournalItem, TaxReturn  # noqa: E402


@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "name",
        "code",
        "journal_type",
    ]


@admin.register(JournalItem)
class JournalItemAdmin(admin.ModelAdmin):
    list_display = [
        "journal_entry",
        "account",
        "description",
        "debit",
        "credit",
        "currency",
    ]


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "number",
        "bank_account",
        "transaction_date",
    ]


@admin.register(TaxReturn)
class TaxReturnAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "number",
        "period_start",
        "period_end",
    ]


from apps.projects.models import (  # noqa: E402
    Milestone,
    ProjectMember,
    TaskComment,
    TimeLog,
)


@admin.register(ProjectMember)
class ProjectMemberAdmin(admin.ModelAdmin):
    list_display = ["project", "user", "role", "joined_at", "hours_allocated"]


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "project",
        "name",
        "description",
    ]


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ["created_by", "updated_by", "company", "task", "author", "content"]


@admin.register(TimeLog)
class TimeLogAdmin(admin.ModelAdmin):
    list_display = ["created_by", "updated_by", "company", "task", "user", "date"]


from apps.assets.models import (  # noqa: E402
    Asset,
    AssetCategory,
    AssetMaintenance,
    DepreciationEntry,
)


@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "name",
        "depreciation_method",
        "useful_life_years",
    ]


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ["created_by", "updated_by", "company", "notes", "number", "name"]


@admin.register(AssetMaintenance)
class AssetMaintenanceAdmin(admin.ModelAdmin):
    list_display = ["created_by", "updated_by", "company", "number", "asset", "title"]


@admin.register(DepreciationEntry)
class DepreciationEntryAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "asset",
        "period_start",
        "period_end",
    ]


from apps.helpdesk.models import KnowledgeBaseArticle, TicketReply  # noqa: E402


@admin.register(TicketReply)
class TicketReplyAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "ticket",
        "author",
        "content",
    ]


@admin.register(KnowledgeBaseArticle)
class KnowledgeBaseArticleAdmin(admin.ModelAdmin):
    list_display = ["created_by", "updated_by", "company", "title", "slug", "content"]


from apps.documents.models import (  # noqa: E402
    Document,
    DocumentCategory,
    DocumentVersion,
)


@admin.register(DocumentCategory)
class DocumentCategoryAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "name",
        "parent",
        "description",
    ]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["created_by", "updated_by", "company", "notes", "number", "title"]


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "document",
        "version",
        "file",
    ]


from apps.workflow.models import (  # noqa: E402
    WorkflowAction,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStep,
)


@admin.register(WorkflowDefinition)
class WorkflowDefinitionAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "name",
        "description",
        "trigger_model",
    ]


@admin.register(WorkflowStep)
class WorkflowStepAdmin(admin.ModelAdmin):
    list_display = [
        "workflow",
        "name",
        "step_order",
        "step_type",
        "approver_type",
        "approver_user",
    ]


@admin.register(WorkflowInstance)
class WorkflowInstanceAdmin(admin.ModelAdmin):
    list_display = [
        "created_by",
        "updated_by",
        "company",
        "definition",
        "current_step",
        "status",
    ]


@admin.register(WorkflowAction)
class WorkflowActionAdmin(admin.ModelAdmin):
    list_display = ["created_by", "updated_by", "company", "instance", "step", "actor"]
