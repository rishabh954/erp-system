import logging
"""
HRMS Views
Employees, Attendance, Leave Management, Payroll
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from core.mixins import CompanyMixin
from core.permissions import PermissionRequiredMixin
from django.views.generic import DetailView, ListView, TemplateView, View

from .models import (
    Attendance,
    Employee,
    EmployeeDocument,
    EmployeeSalary,
    EmployeeSkill,
    ExperienceRecord,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    PayrollPeriod,
    Payslip,
    SalaryComponent,
    SalaryStructure,
)


logger = logging.getLogger(__name__)


# ════════════════════════ EMPLOYEES ══════════════════════════════════════════


class EmployeeListView(CompanyMixin, ListView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/employees/list.html"
    context_object_name = "employees"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Employee.objects.filter(company=self.company(), is_deleted=False)
            .select_related("job_title", "department", "branch", "manager")
            .order_by("first_name")
        )

        user = self.request.user
        if getattr(user, "role", "") == "employee":
            try:
                emp_profile = user.employee
                if emp_profile and emp_profile.department:
                    qs = qs.filter(department=emp_profile.department)
            except AttributeError:
                pass

        q = self.request.GET.get("q", "")
        status = self.request.GET.get("status", "")
        dept = self.request.GET.get("department", "")

        if q:
            qs = qs.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(employee_id__icontains=q)
                | Q(email__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        if dept:
            qs = qs.filter(department_id=dept)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.company.models import Department

        ctx["departments"] = Department.objects.filter(
            company=self.company(), is_active=True, is_deleted=False
        )
        ctx["status_choices"] = Employee.Status.choices
        ctx["total_count"] = Employee.objects.filter(
            company=self.company(), is_deleted=False
        ).count()
        ctx["active_count"] = Employee.objects.filter(
            company=self.company(), status="active", is_deleted=False
        ).count()
        return ctx


class EmployeeDetailView(CompanyMixin, DetailView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/employees/detail.html"
    context_object_name = "employee"

    def get_object(self):
        return get_object_or_404(
            Employee, pk=self.kwargs["pk"], company=self.company(), is_deleted=False
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        emp = self.object
        today = timezone.localdate()
        ctx["attendance_this_month"] = Attendance.objects.filter(
            employee=emp, date__year=today.year, date__month=today.month
        ).order_by("-date")
        ctx["leave_balances"] = LeaveBalance.objects.filter(
            employee=emp, year=today.year
        ).select_related("leave_type")
        ctx["recent_payslips"] = (
            Payslip.objects.filter(employee=emp, is_deleted=False)
            .select_related("payroll_period")
            .order_by("-created_at")[:6]
        )
        ctx["skills"] = emp.skills.all()
        ctx["documents"] = emp.documents.filter(is_deleted=False)
        ctx["experience"] = emp.experience_records.all().order_by("-start_date")

        ctx["current_salary"] = emp.salaries.filter(is_current=True).first()
        ctx["salary_structures"] = SalaryStructure.objects.filter(
            company=self.company(), is_active=True
        )
        from apps.company.models import Currency

        ctx["currencies"] = Currency.objects.filter(is_active=True)
        return ctx


class EmployeeUpdateView(CompanyMixin, View):
    required_permission = "hrms.update"
    template_name = "hrms/employees/form.html"

    def get(self, request, pk):
        emp = get_object_or_404(Employee, pk=pk, company=self.company())
        ctx = self._ctx()
        ctx["emp"] = emp
        return render(request, self.template_name, ctx)

    def post(self, request, pk):
        emp = get_object_or_404(Employee, pk=pk, company=self.company())
        data = request.POST
        employee_id = data.get("employee_id")
        if (
            employee_id
            and Employee.objects.filter(company=self.company(), employee_id=employee_id)
            .exclude(pk=pk)
            .exists()
        ):
            messages.error(
                request,
                f'Employee ID "{employee_id}" is already assigned to another employee.',
            )
            ctx = self._ctx()
            ctx["emp"] = emp
            return render(request, self.template_name, ctx)

        try:
            emp.employee_id = data.get("employee_id", emp.employee_id)
            emp.first_name = data.get("first_name", emp.first_name)
            emp.last_name = data.get("last_name", emp.last_name)
            emp.email = data.get("email", emp.email)
            emp.phone = data.get("phone", emp.phone)
            emp.joining_date = data.get("joining_date", emp.joining_date)
            emp.department_id = data.get("department") or None
            emp.branch_id = data.get("branch") or None
            emp.job_title_id = data.get("job_title") or None
            emp.status = data.get("status", emp.status)
            emp.gender = data.get("gender", emp.gender)
            emp.date_of_birth = data.get("date_of_birth") or None
            emp.address_line1 = data.get("address_line1", emp.address_line1)
            emp.city = data.get("city", emp.city)
            emp.country = data.get("country", emp.country)
            emp.national_id = data.get("national_id", emp.national_id)
            emp.emergency_contact_name = data.get(
                "emergency_contact_name", emp.emergency_contact_name
            )
            emp.emergency_contact_phone = data.get(
                "emergency_contact_phone", emp.emergency_contact_phone
            )
            emp.marital_status = data.get("marital_status", emp.marital_status)
            emp.nationality = data.get("nationality", emp.nationality)
            emp.emergency_contact_relation = data.get(
                "emergency_contact_relation", emp.emergency_contact_relation
            )

            if request.FILES.get("profile_photo"):
                emp.profile_photo = request.FILES["profile_photo"]
            emp.save()
            self._ensure_user_account(emp, self.company())

            messages.success(request, f"Employee {emp.full_name} updated successfully.")
            return redirect("hrms:employee_detail", pk=emp.pk)
        except Exception as e:
            messages.error(request, f"Error updating employee: {e}")
            ctx = self._ctx()
            ctx["emp"] = emp
            return render(request, self.template_name, ctx)

    def _ensure_user_account(self, emp, company):
        if emp.email and not emp.user_id:
            from apps.authentication.models import User, UserCompany

            user = User.objects.filter(email=emp.email).first()
            if not user:
                user = User.objects.create_user(
                    email=emp.email,
                    username=emp.email,
                    password="Welcome@123",
                    first_name=emp.first_name,
                    last_name=emp.last_name,
                    role=User.Role.EMPLOYEE,
                    primary_company=company,
                )
            elif not user.primary_company:
                user.primary_company = company
                user.save(update_fields=["primary_company"])
            emp.user = user
            emp.save(update_fields=["user"])
            UserCompany.objects.get_or_create(
                user=user, company=company, defaults={"is_active": True}
            )

    def _ctx(self):
        from apps.administration.models import Designation
        from apps.company.models import Branch, Department

        company = self.company()
        return {
            "departments": Department.objects.filter(
                company=company, is_active=True, is_deleted=False
            ),
            "branches": Branch.objects.filter(
                company=company, is_active=True, is_deleted=False
            ),
            "job_titles": Designation.objects.filter(
                company=company, is_active=True, is_deleted=False
            ),
            "managers": Employee.objects.filter(
                company=company, status=Employee.Status.ACTIVE, is_deleted=False
            ),
            "status_choices": Employee.Status.choices,
            "gender_choices": Employee.Gender.choices,
            "marital_status_choices": Employee.MaritalStatus.choices,
        }


class EmployeeCreateView(CompanyMixin, View):
    required_permission = "hrms.create"
    template_name = "hrms/employees/form.html"

    def get(self, request):
        return render(request, self.template_name, self._ctx())

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            from .services import EmployeeService

            service = EmployeeService(user=request.user, company=company)
            emp = service.onboard_employee(data, request.user, files=request.FILES)

            messages.success(request, f"Employee {emp.full_name} created successfully.")
            return redirect("hrms:employee_detail", pk=emp.pk)
        except ValueError as e:
            messages.error(request, str(e))
            return render(request, self.template_name, self._ctx())
        except Exception as e:
            messages.error(request, f"Error creating employee: {e}")
            return render(request, self.template_name, self._ctx())

    def _ensure_user_account(self, emp, company):
        if emp.email and not emp.user_id:
            from apps.authentication.models import User, UserCompany

            user = User.objects.filter(email=emp.email).first()
            if not user:
                user = User.objects.create_user(
                    email=emp.email,
                    username=emp.email,
                    password="Welcome@123",
                    first_name=emp.first_name,
                    last_name=emp.last_name,
                    role=User.Role.EMPLOYEE,
                )
            emp.user = user
            emp.save(update_fields=["user"])
            UserCompany.objects.get_or_create(
                user=user, company=company, defaults={"is_active": True}
            )

    def _ctx(self):
        from apps.administration.models import Designation
        from apps.company.models import Branch, Department

        company = self.company()
        return {
            "departments": Department.objects.filter(
                company=company, is_active=True, is_deleted=False
            ),
            "branches": Branch.objects.filter(
                company=company, is_active=True, is_deleted=False
            ),
            "job_titles": Designation.objects.filter(
                company=company, is_active=True, is_deleted=False
            ),
            "managers": Employee.objects.filter(
                company=company, status=Employee.Status.ACTIVE, is_deleted=False
            ),
            "status_choices": Employee.Status.choices,
            "gender_choices": Employee.Gender.choices,
            "marital_status_choices": Employee.MaritalStatus.choices,
        }


# ─── Advanced Employee Profiles ──────────────────────────────────────────────


class EmployeeDocumentCreateView(CompanyMixin, View):
    required_permission = "hrms.create"
    def post(self, request, pk):
        emp = get_object_or_404(Employee, pk=pk, company=self.company())
        data = request.POST
        if request.FILES.get("file"):
            doc = EmployeeDocument(
                company=self.company(),
                employee=emp,
                document_type=data.get("document_type"),
                title=data.get("title"),
                file=request.FILES["file"],
                expiry_date=data.get("expiry_date") or None,
                notes=data.get("notes", ""),
            )
            doc.save()
            messages.success(request, "Document uploaded successfully.")
        return redirect("hrms:employee_detail", pk=pk)


class EmployeeDocumentDeleteView(CompanyMixin, View):
    required_permission = "hrms.delete"
    def post(self, request, pk, doc_id):
        emp = get_object_or_404(Employee, pk=pk, company=self.company())
        doc = get_object_or_404(
            EmployeeDocument, pk=doc_id, employee=emp, company=self.company()
        )
        doc.delete()
        messages.success(request, "Document deleted.")
        return redirect("hrms:employee_detail", pk=pk)


class EmployeeSkillCreateView(CompanyMixin, View):
    required_permission = "hrms.create"
    def post(self, request, pk):
        emp = get_object_or_404(Employee, pk=pk, company=self.company())
        data = request.POST
        skill = EmployeeSkill(
            employee=emp,
            skill_name=data.get("skill_name"),
            proficiency=data.get("proficiency"),
            years_experience=data.get("years_experience") or 0,
        )
        skill.save()
        messages.success(request, "Skill added successfully.")
        return redirect("hrms:employee_detail", pk=pk)


class EmployeeSkillDeleteView(CompanyMixin, View):
    required_permission = "hrms.delete"
    def post(self, request, pk, skill_id):
        emp = get_object_or_404(Employee, pk=pk, company=self.company())
        skill = get_object_or_404(EmployeeSkill, pk=skill_id, employee=emp)
        skill.delete()
        messages.success(request, "Skill removed.")
        return redirect("hrms:employee_detail", pk=pk)


class ExperienceRecordCreateView(CompanyMixin, View):
    required_permission = "hrms.create"
    def post(self, request, pk):
        emp = get_object_or_404(Employee, pk=pk, company=self.company())
        data = request.POST
        exp = ExperienceRecord(
            employee=emp,
            company_name=data.get("company_name"),
            job_title=data.get("job_title"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date") or None,
            is_current=data.get("is_current") == "on",
            description=data.get("description", ""),
        )
        exp.save()
        messages.success(request, "Experience record added.")
        return redirect("hrms:employee_detail", pk=pk)


class ExperienceRecordDeleteView(CompanyMixin, View):
    required_permission = "hrms.delete"
    def post(self, request, pk, exp_id):
        emp = get_object_or_404(Employee, pk=pk, company=self.company())
        exp = get_object_or_404(ExperienceRecord, pk=exp_id, employee=emp)
        exp.delete()
        messages.success(request, "Experience record deleted.")
        return redirect("hrms:employee_detail", pk=pk)


# ════════════════════════ ATTENDANCE ════════════════════════════════════════


class AttendanceView(CompanyMixin, TemplateView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/attendance/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()
        today = timezone.localdate()
        ctx["today"] = today
        ctx["attendance_today"] = (
            Attendance.objects.filter(company=company, date=today)
            .select_related("employee")
            .order_by("employee__first_name")
        )
        ctx["present"] = Attendance.objects.filter(
            company=company, date=today, status="present"
        ).count()
        ctx["absent"] = Attendance.objects.filter(
            company=company, date=today, status="absent"
        ).count()
        ctx["on_leave"] = Attendance.objects.filter(
            company=company, date=today, status="on_leave"
        ).count()
        ctx["late"] = Attendance.objects.filter(
            company=company, date=today, status="late"
        ).count()
        return ctx


class CheckInView(CompanyMixin, View):
    required_permission = "hrms.create"
    def post(self, request):
        try:
            emp = Employee.objects.get(user=request.user, is_deleted=False)
        except Employee.DoesNotExist:
            return JsonResponse(
                {"error": "Your user account is not linked to an employee profile."},
                status=400,
            )

        from .services import AttendanceService

        service = AttendanceService(user=request.user, company=self.company())
        att = service.check_in(emp)
        return JsonResponse({"status": "ok", "check_in": str(att.check_in)})


class CheckOutView(CompanyMixin, View):
    required_permission = "hrms.create"
    def post(self, request):
        try:
            emp = Employee.objects.get(user=request.user, is_deleted=False)
        except Employee.DoesNotExist:
            return JsonResponse(
                {"error": "Your user account is not linked to an employee profile."},
                status=400,
            )

        try:
            from .services import AttendanceService

            service = AttendanceService(user=request.user, company=self.company())
            att = service.check_out(emp)
            return JsonResponse({"status": "ok", "work_hours": float(att.work_hours)})
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)


# ════════════════════════ LEAVE MANAGEMENT ═══════════════════════════════════


class LeaveListView(CompanyMixin, ListView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/leaves/list.html"
    context_object_name = "leaves"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            LeaveRequest.objects.filter(company=self.company(), is_deleted=False)
            .select_related("employee", "leave_type", "approved_by")
            .order_by("-created_at")
        )

        # Non-HR users only see their own
        if self.request.user.role not in ("hr_manager", "company_admin", "super_admin"):
            try:
                emp = Employee.objects.get(user=self.request.user, is_deleted=False)
                qs = qs.filter(employee=emp)
            except Employee.DoesNotExist:
                qs = qs.none()

        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = LeaveRequest.Status.choices
        ctx["pending_count"] = LeaveRequest.objects.filter(
            company=self.company(), status="pending", is_deleted=False
        ).count()
        return ctx


class LeaveRequestCreateView(CompanyMixin, View):
    required_permission = "hrms.create"
    template_name = "hrms/leaves/form.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "leave_types": LeaveType.objects.filter(
                    company=self.company(), is_active=True, is_deleted=False
                ),
                "day_type_choices": LeaveRequest.DayType.choices,
            },
        )

    def post(self, request):
        company = self.company()
        try:
            emp = Employee.objects.get(
                user=request.user, company=company, is_deleted=False
            )
        except Employee.DoesNotExist:
            messages.error(request, "No employee profile found for your account.")
            return redirect("hrms:leaves")

        try:
            from .services import LeaveService

            service = LeaveService(user=request.user, company=company)
            leave = service.request_leave(emp, request.POST, request.FILES)
            messages.success(
                request, f"Leave request {leave.number} submitted successfully."
            )
        except Exception as e:
            messages.error(request, f"Error submitting leave request: {e}")

        return redirect("hrms:leaves")


class LeaveApproveView(CompanyMixin, View):
    required_permission = "hrms.approve"
    def post(self, request, pk):
        leave = get_object_or_404(
            LeaveRequest, pk=pk, company=self.company(), is_deleted=False
        )
        action = request.POST.get("action")

        try:
            from .services import LeaveService

            service = LeaveService(user=request.user, company=self.company())
            service.process_leave(leave, action, request.user, request.POST)

            if action == "approve":
                messages.success(request, f"Leave request {leave.number} approved.")
            elif action == "reject":
                messages.warning(request, f"Leave request {leave.number} rejected.")
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error processing leave request: {e}")

        return redirect("hrms:leaves")


# ─── Salary Structures ────────────────────────────────────────────────────────


class SalaryStructureListView(CompanyMixin, ListView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/salary_structures/list.html"
    context_object_name = "structures"

    def get_queryset(self):
        return SalaryStructure.objects.filter(company=self.company())


class SalaryStructureCreateView(CompanyMixin, View):
    required_permission = "hrms.create"
    template_name = "hrms/salary_structures/form.html"

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        data = request.POST
        structure = SalaryStructure(
            company=self.company(),
            name=data.get("name"),
            description=data.get("description", ""),
            is_active=data.get("is_active") == "on",
        )
        structure.save()
        messages.success(request, "Salary structure created.")
        return redirect("hrms:salary_structure_detail", pk=structure.pk)


class SalaryStructureDetailView(CompanyMixin, DetailView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/salary_structures/detail.html"
    context_object_name = "structure"

    def get_object(self):
        return get_object_or_404(
            SalaryStructure, pk=self.kwargs["pk"], company=self.company()
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["components"] = self.object.components.all()
        ctx["component_types"] = SalaryComponent.ComponentType.choices
        ctx["calc_types"] = SalaryComponent.CalcType.choices
        return ctx


class SalaryComponentCreateView(CompanyMixin, View):
    required_permission = "hrms.create"
    def post(self, request, pk):
        structure = get_object_or_404(SalaryStructure, pk=pk, company=self.company())
        data = request.POST
        comp = SalaryComponent(
            company=self.company(),
            salary_structure=structure,
            name=data.get("name"),
            code=data.get("code"),
            component_type=data.get("component_type"),
            calc_type=data.get("calc_type"),
            amount=data.get("amount") or 0,
            percentage=data.get("percentage") or 0,
            formula=data.get("formula", ""),
            is_taxable=data.get("is_taxable") == "on",
            order=data.get("order") or 0,
        )
        comp.save()
        messages.success(request, "Component added.")
        return redirect("hrms:salary_structure_detail", pk=pk)


class SalaryComponentDeleteView(CompanyMixin, View):
    required_permission = "hrms.delete"
    def post(self, request, pk, comp_id):
        structure = get_object_or_404(SalaryStructure, pk=pk, company=self.company())
        comp = get_object_or_404(
            SalaryComponent,
            pk=comp_id,
            salary_structure=structure,
            company=self.company(),
        )
        comp.delete()
        messages.success(request, "Component deleted.")
        return redirect("hrms:salary_structure_detail", pk=pk)


class EmployeeSalaryCreateView(CompanyMixin, View):
    required_permission = "hrms.create"
    def post(self, request, pk):
        emp = get_object_or_404(Employee, pk=pk, company=self.company())
        data = request.POST
        from apps.company.models import Currency

        curr = get_object_or_404(Currency, pk=data.get("currency"))
        struct = get_object_or_404(SalaryStructure, pk=data.get("salary_structure"))

        sal = EmployeeSalary(
            company=self.company(),
            employee=emp,
            salary_structure=struct,
            basic_salary=data.get("basic_salary"),
            effective_from=data.get("effective_from"),
            currency=curr,
        )
        sal.save()
        messages.success(request, "Salary configured successfully.")
        return redirect("hrms:employee_detail", pk=pk)


# ════════════════════════ PAYROLL ═════════════════════════════════════════════


class PayrollListView(CompanyMixin, ListView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/payroll/list.html"
    context_object_name = "periods"
    paginate_by = 12

    def get_queryset(self):
        return PayrollPeriod.objects.filter(
            company=self.company(), is_deleted=False
        ).order_by("-period_start")


class PayrollDetailView(CompanyMixin, DetailView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/payroll/detail.html"
    context_object_name = "period"

    def get_object(self):
        return get_object_or_404(
            PayrollPeriod,
            pk=self.kwargs["pk"],
            company=self.company(),
            is_deleted=False,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["payslips"] = (
            Payslip.objects.filter(payroll_period=self.object, is_deleted=False)
            .select_related("employee")
            .order_by("employee__first_name")
        )
        return ctx


class PayrollProcessView(CompanyMixin, View):
    required_permission = "hrms.approve"
    def post(self, request, pk):
        period = get_object_or_404(
            PayrollPeriod, pk=pk, company=self.company(), is_deleted=False
        )
        try:
            # We will process it via celery, but using the service layer instead of monolithic task logic
            # Let's call the task, and we'll refactor the task to use the PayrollService
            from .tasks import process_payroll_task

            process_payroll_task.delay(str(period.pk), request.user.pk)
            messages.success(
                request,
                f"Payroll processing started for {period.name}. This may take a few minutes.",
            )
        except Exception as e:
            messages.error(request, f"Error starting payroll: {e}")

        return redirect("hrms:payroll_detail", pk=pk)


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path

app_name = "hrms"

urlpatterns = [
    path("employees/", EmployeeListView.as_view(), name="employees"),
    path("employees/create/", EmployeeCreateView.as_view(), name="employee_create"),
    path("employees/<uuid:pk>/", EmployeeDetailView.as_view(), name="employee_detail"),
    path("attendance/", AttendanceView.as_view(), name="attendance"),
    path("attendance/check-in/", CheckInView.as_view(), name="check_in"),
    path("attendance/check-out/", CheckOutView.as_view(), name="check_out"),
    path("leaves/", LeaveListView.as_view(), name="leaves"),
    path(
        "leaves/create/", LeaveRequestCreateView.as_view(), name="leave_request_create"
    ),
    path("leaves/<uuid:pk>/approve/", LeaveApproveView.as_view(), name="leave_approve"),
    path("payroll/", PayrollListView.as_view(), name="payroll"),
    path("payroll/<uuid:pk>/", PayrollDetailView.as_view(), name="payroll_detail"),
    path(
        "payroll/<uuid:pk>/process/",
        PayrollProcessView.as_view(),
        name="payroll_process",
    ),
]

# ════════════════════════ RECRUITMENT ═════════════════════════════════════════

from .models import JobApplication, JobPosting


class JobPostingListView(CompanyMixin, ListView):
    required_permission = "hrms.create"
    template_name = "hrms/recruitment/job_postings.html"
    context_object_name = "jobs"

    def get_queryset(self):
        return JobPosting.objects.filter(company=self.company()).select_related(
            "department"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.company.models import Department

        ctx["departments"] = Department.objects.filter(company=self.company())
        ctx["statuses"] = JobPosting.Status.choices
        return ctx

    def post(self, request):
        data = request.POST
        from apps.company.models import Department

        dept = None
        if data.get("department"):
            dept = get_object_or_404(
                Department, pk=data.get("department"), company=self.company()
            )

        job = JobPosting(
            company=self.company(),
            title=data.get("title"),
            department=dept,
            description=data.get("description"),
            requirements=data.get("requirements", ""),
            location=data.get("location", ""),
            employment_type=data.get("employment_type", ""),
            status=data.get("status", JobPosting.Status.DRAFT),
            posted_date=data.get("posted_date") or None,
            closing_date=data.get("closing_date") or None,
        )
        job.save()
        messages.success(request, "Job posting created successfully.")
        return redirect("hrms:job_postings")


class JobPostingDetailView(CompanyMixin, DetailView):
    required_permission = "hrms.create"
    template_name = "hrms/recruitment/job_posting_detail.html"
    context_object_name = "job"

    def get_queryset(self):
        return JobPosting.objects.filter(company=self.company()).select_related(
            "department"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["applications"] = self.object.applications.all()
        return ctx

    def post(self, request, pk):
        job = get_object_or_404(JobPosting, pk=pk, company=self.company())
        action = request.POST.get("action")
        if action == "update_status":
            job.status = request.POST.get("status")
            job.save()
            messages.success(
                request, f"Job status updated to {job.get_status_display()}"
            )
        return redirect("hrms:job_posting_detail", pk=pk)


class JobApplicationListView(CompanyMixin, ListView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/recruitment/applications.html"
    context_object_name = "applications"

    def get_queryset(self):
        return JobApplication.objects.filter(company=self.company()).select_related(
            "job_posting"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["jobs"] = JobPosting.objects.filter(
            company=self.company(), status=JobPosting.Status.PUBLISHED
        )
        ctx["stages"] = JobApplication.Stage.choices
        return ctx

    def post(self, request):
        data = request.POST
        job = get_object_or_404(
            JobPosting, pk=data.get("job_posting"), company=self.company()
        )
        app = JobApplication(
            company=self.company(),
            job_posting=job,
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            email=data.get("email"),
            phone=data.get("phone", ""),
            cover_letter=data.get("cover_letter", ""),
            stage=data.get("stage", JobApplication.Stage.APPLIED),
        )
        if request.FILES.get("resume"):
            app.resume = request.FILES["resume"]
        app.save()
        messages.success(request, "Application submitted successfully.")
        return redirect("hrms:job_applications")


class JobApplicationDetailView(CompanyMixin, DetailView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/recruitment/application_detail.html"
    context_object_name = "application"

    def get_queryset(self):
        return JobApplication.objects.filter(company=self.company()).select_related(
            "job_posting"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["interviews"] = self.object.interviews.select_related("interviewer")
        return ctx

    def post(self, request, pk):
        app = get_object_or_404(JobApplication, pk=pk, company=self.company())
        action = request.POST.get("action")
        if action == "update_stage":
            app.stage = request.POST.get("stage")
            app.save()
            messages.success(
                request, f"Application stage updated to {app.get_stage_display()}"
            )
        return redirect("hrms:application_detail", pk=pk)


# ════════════════════════ PERFORMANCE APPRAISAL ═══════════════════════════════
from .models import ExpenseClaim, PerformanceAppraisal, TrainingProgram


class PerformanceAppraisalListView(CompanyMixin, ListView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/appraisals/list.html"
    context_object_name = "appraisals"

    def get_queryset(self):
        return PerformanceAppraisal.objects.filter(
            company=self.company()
        ).select_related("employee", "manager")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["employees"] = Employee.objects.filter(
            company=self.company(), status="active", is_deleted=False
        )
        return ctx

    def post(self, request):
        data = request.POST
        emp = get_object_or_404(
            Employee, pk=data.get("employee"), company=self.company()
        )
        manager = None
        if data.get("manager"):
            manager = get_object_or_404(
                Employee, pk=data.get("manager"), company=self.company()
            )

        appraisal = PerformanceAppraisal(
            company=self.company(),
            employee=emp,
            manager=manager,
            period_start=data.get("period_start"),
            period_end=data.get("period_end"),
            goals_agreed=data.get("goals_agreed", ""),
            status="draft",
        )
        appraisal.save()
        messages.success(request, "Performance appraisal created successfully.")
        return redirect("hrms:appraisals")


class PerformanceAppraisalDetailView(CompanyMixin, DetailView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/appraisals/detail.html"
    context_object_name = "appraisal"

    def get_queryset(self):
        return PerformanceAppraisal.objects.filter(
            company=self.company()
        ).select_related("employee", "manager")

    def post(self, request, pk):
        appraisal = get_object_or_404(
            PerformanceAppraisal, pk=pk, company=self.company()
        )
        action = request.POST.get("action")

        if action == "update_appraisal":
            appraisal.rating = request.POST.get("rating", appraisal.rating)
            appraisal.status = request.POST.get("status", appraisal.status)
            appraisal.manager_feedback = request.POST.get(
                "manager_feedback", appraisal.manager_feedback
            )
            appraisal.employee_feedback = request.POST.get(
                "employee_feedback", appraisal.employee_feedback
            )
            appraisal.save()
            messages.success(request, "Appraisal updated successfully.")

        return redirect("hrms:appraisal_detail", pk=pk)


# ════════════════════════ TRAINING PROGRAM ════════════════════════════════════


class TrainingProgramListView(CompanyMixin, ListView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/training/list.html"
    context_object_name = "programs"

    def get_queryset(self):
        return TrainingProgram.objects.filter(company=self.company()).prefetch_related(
            "attendees"
        )

    def post(self, request):
        data = request.POST
        program = TrainingProgram(
            company=self.company(),
            name=data.get("name"),
            description=data.get("description", ""),
            trainer_name=data.get("trainer_name", ""),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            location=data.get("location", ""),
            cost=data.get("cost") or 0,
        )
        program.save()
        messages.success(request, "Training program created successfully.")
        return redirect("hrms:training_programs")


class TrainingProgramDetailView(CompanyMixin, DetailView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/training/detail.html"
    context_object_name = "program"

    def get_queryset(self):
        return TrainingProgram.objects.filter(company=self.company()).prefetch_related(
            "attendees"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # All employees not yet enrolled
        enrolled_ids = self.object.attendees.values_list("id", flat=True)
        ctx["available_employees"] = Employee.objects.filter(
            company=self.company(), status="active", is_deleted=False
        ).exclude(id__in=enrolled_ids)
        return ctx

    def post(self, request, pk):
        program = get_object_or_404(TrainingProgram, pk=pk, company=self.company())
        action = request.POST.get("action")

        if action == "add_attendee":
            emp_id = request.POST.get("employee_id")
            if emp_id:
                emp = get_object_or_404(Employee, pk=emp_id, company=self.company())
                program.attendees.add(emp)
                messages.success(request, f"{emp.full_name} enrolled in training.")
        elif action == "remove_attendee":
            emp_id = request.POST.get("employee_id")
            if emp_id:
                emp = get_object_or_404(Employee, pk=emp_id, company=self.company())
                program.attendees.remove(emp)
                messages.success(request, f"{emp.full_name} removed from training.")

        return redirect("hrms:training_program_detail", pk=pk)


# ════════════════════════ EXPENSE CLAIMS ══════════════════════════════════════


class ExpenseClaimListView(CompanyMixin, ListView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/expenses/list.html"
    context_object_name = "claims"

    def get_queryset(self):
        return ExpenseClaim.objects.filter(company=self.company()).select_related(
            "employee", "currency"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["employees"] = Employee.objects.filter(
            company=self.company(), status="active", is_deleted=False
        )
        from apps.company.models import Currency

        ctx["currencies"] = Currency.objects.filter(is_active=True)
        return ctx

    def post(self, request):
        data = request.POST
        emp = get_object_or_404(
            Employee, pk=data.get("employee"), company=self.company()
        )

        from apps.company.models import Currency

        currency = None
        if data.get("currency"):
            currency = get_object_or_404(Currency, pk=data.get("currency"))

        claim = ExpenseClaim(
            company=self.company(),
            employee=emp,
            expense_date=data.get("expense_date"),
            category=data.get("category", "General"),
            description=data.get("description", ""),
            amount=data.get("amount"),
            currency=currency,
            status=ExpenseClaim.Status.SUBMITTED,
        )
        if request.FILES.get("attachment"):
            claim.attachment = request.FILES["attachment"]

        claim.save()
        messages.success(request, "Expense claim submitted successfully.")
        return redirect("hrms:expense_claims")


class ExpenseClaimDetailView(CompanyMixin, DetailView):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    template_name = "hrms/expenses/detail.html"
    context_object_name = "claim"

    def get_queryset(self):
        return ExpenseClaim.objects.filter(company=self.company()).select_related(
            "employee", "approved_by", "currency"
        )

    def post(self, request, pk):
        claim = get_object_or_404(ExpenseClaim, pk=pk, company=self.company())
        action = request.POST.get("action")

        if action == "update_status":
            new_status = request.POST.get("status")
            if new_status in dict(ExpenseClaim.Status.choices):
                claim.status = new_status
                if new_status == ExpenseClaim.Status.APPROVED:
                    claim.approved_by = request.user
                elif new_status in [
                    ExpenseClaim.Status.REJECTED,
                    ExpenseClaim.Status.DRAFT,
                ]:
                    claim.approved_by = None
                claim.save()
                messages.success(
                    request, f"Claim status updated to {claim.get_status_display()}"
                )

        return redirect("hrms:expense_claim_detail", pk=pk)
