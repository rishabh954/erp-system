"""
HRMS Models
Employee, Attendance, Leave Management, Payroll
"""

import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import (
    AddressMixin,
    BranchScoped,
    CompanyScoped,
    ContactMixin,
    SequenceMixin,
)
from core.services import BaseService


class JobTitle(CompanyScoped):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    grade = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "hrms_job_titles"
        unique_together = ("company", "name")

    def __str__(self):
        return self.name


class Employee(BranchScoped, AddressMixin, ContactMixin):
    """Core employee record."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        INACTIVE = "inactive", _("Inactive")
        ON_LEAVE = "on_leave", _("On Leave")
        TERMINATED = "terminated", _("Terminated")
        PROBATION = "probation", _("Probation")
        SUSPENDED = "suspended", _("Suspended")

    class Gender(models.TextChoices):
        MALE = "male", _("Male")
        FEMALE = "female", _("Female")
        OTHER = "other", _("Other")
        PREFER_NOT = "prefer_not", _("Prefer Not to Say")

    class MaritalStatus(models.TextChoices):
        SINGLE = "single", _("Single")
        MARRIED = "married", _("Married")
        DIVORCED = "divorced", _("Divorced")
        WIDOWED = "widowed", _("Widowed")

    # Identity
    employee_id = models.CharField(max_length=50, db_index=True)
    user = models.OneToOneField(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employee",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=15, choices=Gender.choices, blank=True)
    marital_status = models.CharField(
        max_length=15, choices=MaritalStatus.choices, blank=True
    )
    national_id = models.CharField(max_length=100, blank=True)
    passport_number = models.CharField(max_length=50, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    profile_photo = models.ImageField(
        upload_to="employees/photos/", null=True, blank=True
    )

    # Work
    job_title = models.ForeignKey(
        "administration.Designation", null=True, blank=True, on_delete=models.SET_NULL
    )
    department = models.ForeignKey(
        "company.Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
    )
    manager = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="direct_reports",
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    joining_date = models.DateField()
    confirmation_date = models.DateField(null=True, blank=True)
    termination_date = models.DateField(null=True, blank=True)
    termination_reason = models.TextField(blank=True)
    work_location = models.CharField(max_length=200, blank=True)
    work_type = models.CharField(
        max_length=20,
        choices=[("onsite", "On-site"), ("remote", "Remote"), ("hybrid", "Hybrid")],
        default="onsite",
    )

    # Emergency contact
    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_phone = models.CharField(max_length=30, blank=True)
    emergency_contact_relation = models.CharField(max_length=100, blank=True)

    # Financial
    bank_name = models.CharField(max_length=200, blank=True)
    bank_account_number = models.CharField(max_length=100, blank=True)
    bank_routing_number = models.CharField(max_length=50, blank=True)
    tax_id = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "hrms_employees"
        unique_together = ("company", "employee_id")
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "joining_date"]),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.employee_id})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def years_of_service(self):
        if not self.joining_date:
            return 0
        end = self.termination_date or timezone.localdate()
        return (end - self.joining_date).days // 365


class EmployeeDocument(CompanyScoped):
    """Documents attached to an employee profile."""

    class DocType(models.TextChoices):
        CONTRACT = "contract", _("Employment Contract")
        ID_PROOF = "id_proof", _("ID Proof")
        PASSPORT = "passport", _("Passport")
        EDUCATION = "education", _("Education Certificate")
        EXPERIENCE = "experience", _("Experience Letter")
        OTHER = "other", _("Other")

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="documents"
    )
    document_type = models.CharField(max_length=20, choices=DocType.choices)
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to="employees/documents/")
    expiry_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Verification
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_documents",
    )

    class Meta:
        db_table = "hrms_employee_documents"

    def __str__(self):
        return f"{self.employee.full_name} — {self.title}"


class EmployeeSkill(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="skills"
    )
    skill_name = models.CharField(max_length=100)
    proficiency = models.CharField(
        max_length=15,
        choices=[
            ("beginner", "Beginner"),
            ("intermediate", "Intermediate"),
            ("advanced", "Advanced"),
            ("expert", "Expert"),
        ],
        default="intermediate",
    )
    years_experience = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "hrms_employee_skills"


class ExperienceRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="experience_records"
    )
    company_name = models.CharField(max_length=255)
    job_title = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "hrms_experience_records"
        ordering = ["-start_date"]


# ─── Attendance ───────────────────────────────────────────────────────────────


class WorkSchedule(CompanyScoped):
    """Work schedule / shift definition."""

    name = models.CharField(max_length=100)
    check_in_time = models.TimeField()
    check_out_time = models.TimeField()
    grace_period_minutes = models.PositiveSmallIntegerField(default=15)
    working_days = models.JSONField(
        default=list, help_text="List of weekday numbers 0=Mon..6=Sun"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "hrms_work_schedules"

    def __str__(self):
        return f"{self.name} ({self.check_in_time}–{self.check_out_time})"


class ShiftAssignment(CompanyScoped):
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="shift_assignments"
    )
    schedule = models.ForeignKey(
        WorkSchedule, on_delete=models.CASCADE, related_name="assignments"
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "hrms_shift_assignments"
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.employee.full_name} - {self.schedule.name}"


class BiometricLog(models.Model):
    class PunchType(models.TextChoices):
        IN = "in", _("Check In")
        OUT = "out", _("Check Out")

    import uuid as _uuid

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="biometric_logs"
    )
    timestamp = models.DateTimeField(db_index=True)
    punch_type = models.CharField(max_length=10, choices=PunchType.choices)
    device_id = models.CharField(max_length=100, blank=True)
    is_processed = models.BooleanField(default=False)

    class Meta:
        db_table = "hrms_biometric_logs"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.employee.full_name} {self.punch_type} @ {self.timestamp}"


class Attendance(CompanyScoped):
    """Daily attendance record per employee."""

    class Status(models.TextChoices):
        PRESENT = "present", _("Present")
        ABSENT = "absent", _("Absent")
        LATE = "late", _("Late")
        HALF_DAY = "half_day", _("Half Day")
        ON_LEAVE = "on_leave", _("On Leave")
        HOLIDAY = "holiday", _("Holiday")
        WEEKEND = "weekend", _("Weekend")

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="attendance_records"
    )
    date = models.DateField(db_index=True)
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PRESENT
    )
    work_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    late_minutes = models.PositiveSmallIntegerField(default=0)
    early_departure_minutes = models.PositiveSmallIntegerField(default=0)
    check_in_location = models.CharField(max_length=255, blank=True)
    check_out_location = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "hrms_attendance"
        unique_together = ("employee", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["company", "date"]),
            models.Index(fields=["employee", "date"]),
        ]

    def __str__(self):
        return f"{self.employee.full_name} — {self.date} ({self.status})"

    def save(self, *args, **kwargs):
        if self.check_in and self.check_out:
            delta = self.check_out - self.check_in
            self.work_hours = round(delta.total_seconds() / 3600, 2)
        super().save(*args, **kwargs)


# ─── Leave Management ──────────────────────────────────────────────────────────


class LeaveType(CompanyScoped):
    """Types of leaves configured per company."""

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    days_allowed = models.DecimalField(max_digits=5, decimal_places=1)
    carry_forward = models.BooleanField(default=False)
    max_carry_forward_days = models.DecimalField(
        max_digits=5, decimal_places=1, default=0
    )
    is_paid = models.BooleanField(default=True)
    requires_approval = models.BooleanField(default=True)
    gender_specific = models.CharField(
        max_length=10,
        choices=[("all", "All"), ("male", "Male Only"), ("female", "Female Only")],
        default="all",
    )
    min_service_days = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=7, default="#4361ee")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "hrms_leave_types"
        unique_together = ("company", "code")

    def __str__(self):
        return f"{self.name} ({self.days_allowed} days)"


class LeaveBalance(models.Model):
    """Annual leave balance per employee per leave type."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="leave_balances"
    )
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    year = models.PositiveSmallIntegerField()
    allocated = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    used = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    carried_forward = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    pending = models.DecimalField(max_digits=5, decimal_places=1, default=0)

    class Meta:
        db_table = "hrms_leave_balances"
        unique_together = ("employee", "leave_type", "year")

    @property
    def available(self):
        return self.allocated + self.carried_forward - self.used - self.pending

    def __str__(self):
        return f"{self.employee.full_name} | {self.leave_type.name} | {self.year}"


class LeaveRequest(CompanyScoped, SequenceMixin):
    """Employee leave application with approval workflow."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Pending Approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")

    class DayType(models.TextChoices):
        FULL = "full", _("Full Day")
        HALF_MORNING = "half_morning", _("Half Day (Morning)")
        HALF_AFTERNOON = "half_afternoon", _("Half Day (Afternoon)")

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="leave_requests"
    )
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    start_date = models.DateField()
    end_date = models.DateField()
    day_type = models.CharField(
        max_length=20, choices=DayType.choices, default=DayType.FULL
    )
    total_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    reason = models.TextField()
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    approved_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_leaves",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    attachment = models.FileField(upload_to="leaves/", null=True, blank=True)

    class Meta:
        db_table = "hrms_leave_requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} | {self.employee.full_name} | {self.leave_type.name}"


# ─── Payroll ──────────────────────────────────────────────────────────────────


class SalaryStructure(CompanyScoped):
    """Template defining earnings and deduction components."""

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "hrms_salary_structures"

    def __str__(self):
        return self.name


class SalaryComponent(CompanyScoped):
    """Individual earning or deduction component."""

    class ComponentType(models.TextChoices):
        EARNING = "earning", _("Earning")
        DEDUCTION = "deduction", _("Deduction")
        TAX = "tax", _("Tax")

    class CalcType(models.TextChoices):
        FIXED = "fixed", _("Fixed Amount")
        PERCENTAGE = "percentage", _("Percentage of Basic")
        FORMULA = "formula", _("Formula")

    salary_structure = models.ForeignKey(
        SalaryStructure, on_delete=models.CASCADE, related_name="components"
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20)
    component_type = models.CharField(max_length=15, choices=ComponentType.choices)
    calc_type = models.CharField(
        max_length=15, choices=CalcType.choices, default=CalcType.FIXED
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    formula = models.TextField(blank=True)
    is_taxable = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "hrms_salary_components"
        ordering = ["component_type", "order"]

    def __str__(self):
        return f"{self.name} ({self.component_type})"


class EmployeeSalary(CompanyScoped):
    """Employee's assigned salary and structure."""

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="salaries"
    )
    salary_structure = models.ForeignKey(SalaryStructure, on_delete=models.PROTECT)
    basic_salary = models.DecimalField(max_digits=15, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    currency = models.ForeignKey("company.Currency", on_delete=models.PROTECT)
    is_current = models.BooleanField(default=True)

    class Meta:
        db_table = "hrms_employee_salaries"
        ordering = ["-effective_from"]

    def __str__(self):
        return f"{self.employee.full_name} — {self.basic_salary} from {self.effective_from}"


class PayrollPeriod(CompanyScoped, SequenceMixin):
    """A payroll run for a specific month/period."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PROCESSING = "processing", _("Processing")
        COMPLETED = "completed", _("Completed")
        APPROVED = "approved", _("Approved")
        PAID = "paid", _("Paid")

    name = models.CharField(max_length=200)
    period_start = models.DateField()
    period_end = models.DateField()
    payment_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT
    )
    total_gross = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_net = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.ForeignKey(
        "company.Currency", on_delete=models.PROTECT, null=True
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "hrms_payroll_periods"
        ordering = ["-period_start"]

    def __str__(self):
        return f"{self.name} ({self.status})"


class Payslip(CompanyScoped, SequenceMixin):
    """Individual payslip for one employee in a payroll period."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        GENERATED = "generated", _("Generated")
        APPROVED = "approved", _("Approved")
        PAID = "paid", _("Paid")

    payroll_period = models.ForeignKey(
        PayrollPeriod, on_delete=models.CASCADE, related_name="payslips"
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="payslips"
    )
    employee_salary = models.ForeignKey(EmployeeSalary, on_delete=models.PROTECT)
    working_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    present_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    absent_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    basic_salary = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    gross_salary = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_tax = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT
    )
    components = models.JSONField(default=list)  # Snapshot of all earnings/deductions
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(max_length=50, blank=True)
    payment_reference = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "hrms_payslips"
        unique_together = ("payroll_period", "employee")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} | {self.employee.full_name} | {self.payroll_period.name}"


# ════════════════════════ RECRUITMENT ═════════════════════════════════════════


class JobPosting(CompanyScoped):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")
        CLOSED = "closed", _("Closed")
        CANCELLED = "cancelled", _("Cancelled")

    title = models.CharField(max_length=200)
    department = models.ForeignKey(
        "company.Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="job_postings",
    )
    description = models.TextField()
    requirements = models.TextField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    employment_type = models.CharField(
        max_length=50, blank=True
    )  # Full-time, Part-time, etc.
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    posted_date = models.DateField(null=True, blank=True)
    closing_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "hrms_job_postings"
        ordering = ["-posted_date"]

    def __str__(self):
        return f"{self.title} ({self.department.name if self.department else 'N/A'})"


class JobApplication(CompanyScoped):
    class Stage(models.TextChoices):
        APPLIED = "applied", _("Applied")
        SHORTLISTED = "shortlisted", _("Shortlisted")
        INTERVIEWING = "interviewing", _("Interviewing")
        OFFERED = "offered", _("Offered")
        HIRED = "hired", _("Hired")
        REJECTED = "rejected", _("Rejected")

    job_posting = models.ForeignKey(
        JobPosting, on_delete=models.CASCADE, related_name="applications"
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    resume = models.FileField(upload_to="recruitment/resumes/", null=True, blank=True)
    cover_letter = models.TextField(blank=True)
    stage = models.CharField(
        max_length=20, choices=Stage.choices, default=Stage.APPLIED
    )
    applied_date = models.DateTimeField(auto_now_add=True)
    rating = models.PositiveSmallIntegerField(default=0)  # 1 to 5

    class Meta:
        db_table = "hrms_job_applications"
        ordering = ["-applied_date"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.job_posting.title}"


class Interview(CompanyScoped):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", _("Scheduled")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")
        NO_SHOW = "no_show", _("No Show")

    application = models.ForeignKey(
        JobApplication, on_delete=models.CASCADE, related_name="interviews"
    )
    interviewer = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="conducted_interviews"
    )
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=60)
    location_or_link = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SCHEDULED
    )
    feedback = models.TextField(blank=True)
    rating = models.PositiveSmallIntegerField(default=0)  # 1 to 5

    class Meta:
        db_table = "hrms_interviews"
        ordering = ["-scheduled_at"]

    def __str__(self):
        return f"Interview for {self.application} with {self.interviewer}"


# ════════════════════════ HRMS EXTENSIONS (APPRAISAL, TRAINING, EXPENSES) ═════


class PerformanceAppraisal(CompanyScoped):
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="appraisals"
    )
    manager = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_appraisals",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    goals_agreed = models.TextField(blank=True)
    manager_feedback = models.TextField(blank=True)
    employee_feedback = models.TextField(blank=True)
    rating = models.DecimalField(
        max_digits=3, decimal_places=1, default=0, help_text=_("Rating from 1.0 to 5.0")
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
        ],
        default="draft",
    )

    class Meta:
        db_table = "hrms_performance_appraisals"
        ordering = ["-period_end"]

    def __str__(self):
        return f"Appraisal for {self.employee.full_name} ({self.period_start} to {self.period_end})"


class TrainingProgram(CompanyScoped):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    trainer_name = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    location = models.CharField(max_length=200, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    attendees = models.ManyToManyField(
        Employee, related_name="training_programs", blank=True
    )

    class Meta:
        db_table = "hrms_training_programs"
        ordering = ["-start_date"]

    def __str__(self):
        return self.name


class ExpenseClaim(CompanyScoped, SequenceMixin):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SUBMITTED = "submitted", _("Submitted")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        PAID = "paid", _("Paid")

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="expense_claims"
    )
    expense_date = models.DateField()
    category = models.CharField(max_length=100)  # Travel, Meals, Supplies
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.ForeignKey(
        "company.Currency", null=True, blank=True, on_delete=models.SET_NULL
    )
    attachment = models.FileField(upload_to="expenses/", null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    approved_by = models.ForeignKey(
        "authentication.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    workflows = __import__(
        "django.contrib.contenttypes.fields", fromlist=["GenericRelation"]
    ).GenericRelation(
        "workflow.WorkflowInstance",
        object_id_field="object_id",
        content_type_field="content_type",
    )

    class Meta:
        db_table = "hrms_expense_claims"
        ordering = ["-expense_date"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = BaseService.generate_sequence_number("EXP", self.__class__, self.company_id)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} | {self.employee.full_name} - {self.amount}"


class TravelRequest(CompanyScoped, SequenceMixin):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Pending Approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        COMPLETED = "completed", _("Completed")

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="travel_requests"
    )
    destination = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    purpose = models.TextField()
    estimated_cost = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )

    workflows = __import__(
        "django.contrib.contenttypes.fields", fromlist=["GenericRelation"]
    ).GenericRelation(
        "workflow.WorkflowInstance",
        object_id_field="object_id",
        content_type_field="content_type",
    )

    class Meta:
        db_table = "hrms_travel_requests"
        ordering = ["-start_date"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = BaseService.generate_sequence_number("TRV", self.__class__, self.company_id)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} | {self.employee.full_name} to {self.destination}"


class EmployeeAsset(CompanyScoped):
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="assigned_assets"
    )
    asset_name = models.CharField(max_length=200)
    asset_tag = models.CharField(max_length=100, blank=True)
    assigned_date = models.DateField()
    returned_date = models.DateField(null=True, blank=True)
    condition = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "hrms_employee_assets"
        ordering = ["-assigned_date"]

    def __str__(self):
        return f"{self.asset_name} -> {self.employee.full_name}"
