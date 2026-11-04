"""
Company Management Views
Settings, Branches, Departments, Users, Fiscal Years, Currencies
"""

import re
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.generic import ListView, TemplateView, UpdateView, View

from apps.authentication.models import UserCompany
from core.mixins import CompanyMixin

from .models import (
    Branch,
    Company,
    Currency,
    Department,
    ExchangeRate,
    FiscalYear,
    Tax,
    TaxGroup,
)

COMPANY_MANAGEABLE_ROLES = {
    "employee",
    "manager",
    "hr_manager",
    "accountant",
    "company_admin",
}


def _required_text(data, key, label, max_length):
    value = data.get(key, "").strip()
    if not value:
        raise ValueError(f"{label} is required.")
    if len(value) > max_length:
        raise ValueError(f"{label} must be {max_length} characters or fewer.")
    return value


def _optional_text(data, key, label, max_length):
    value = data.get(key, "").strip()
    if len(value) > max_length:
        raise ValueError(f"{label} must be {max_length} characters or fewer.")
    return value


def _choice(value, choices, label):
    allowed = {choice[0] for choice in choices}
    if value not in allowed:
        raise ValueError(f"Select a valid {label}.")
    return value


def _company_role(value):
    if value not in COMPANY_MANAGEABLE_ROLES:
        raise ValueError("Select a valid company role.")
    return value


def _checkbox(data, key):
    value = data.get(key)
    if value is None:
        return False
    if value != "on":
        raise ValueError(f"Invalid value for {key.replace('_', ' ')}.")
    return True


def _related_object(model, value, label, **filters):
    if not value:
        return None
    try:
        obj = model.objects.filter(**filters).filter(pk=value).first()
    except (ValidationError, ValueError, TypeError):
        obj = None
    if obj is None:
        raise ValueError(f"Select a valid {label}.")
    return obj


def _valid_date(value, label):
    parsed = parse_date(value or "")
    if parsed is None:
        raise ValueError(f"Enter a valid {label} date (YYYY-MM-DD).")
    return parsed


def _valid_decimal(value, label, *, max_digits, decimal_places, minimum=None):
    from decimal import Decimal, InvalidOperation

    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Enter a valid {label}.") from None
    if not parsed.is_finite():
        raise ValueError(f"Enter a finite {label}.")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    sign, digits, exponent = parsed.as_tuple()
    integer_digits = max(len(digits) + exponent, 0)
    fraction_digits = max(-exponent, 0)
    if integer_digits + fraction_digits > max_digits or fraction_digits > decimal_places:
        raise ValueError(
            f"{label} supports at most {max_digits} digits and {decimal_places} decimal places."
        )
    return parsed


# ── Settings ──────────────────────────────────────────────────────────────────


class CompanyCreateView(LoginRequiredMixin, View):
    template_name = "company/company_create.html"

    def get(self, request):
        if request.user.primary_company:
            return redirect("dashboard:index")

        import zoneinfo
        from collections import defaultdict

        tz_groups = defaultdict(list)
        for tz in sorted(zoneinfo.available_timezones()):
            region = tz.split("/")[0]
            tz_groups[region].append(tz)

        currencies = Currency.objects.filter(is_active=True)
        if not currencies.exists():
            from django.core.management import call_command

            try:
                call_command("seed_currencies")
                currencies = Currency.objects.filter(is_active=True)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Failed to seed currencies: %s", e)

        return render(
            request,
            self.template_name,
            {
                "currencies": currencies,
                "tz_groups": dict(sorted(tz_groups.items())),
                "company_type_choices": Company.CompanyType.choices,
            },
        )

    def post(self, request):
        if request.user.primary_company:
            return redirect("dashboard:index")

        data = request.POST
        values = data.dict()
        errors = {}
        name = data.get("name", "").strip()
        if not name:
            errors["name"] = "Company name is required."
        elif len(name) > 255:
            errors["name"] = "Company name must be 255 characters or fewer."
        company_type = data.get("company_type", "").strip().lower().replace(" ", "_")
        if company_type and company_type not in Company.CompanyType.values:
            errors["company_type"] = "Select a valid company type."
        legal_name = data.get("legal_name", "").strip()
        industry = data.get("industry", "").strip()
        if len(legal_name) > 255:
            errors["legal_name"] = "Legal name must be 255 characters or fewer."
        if len(industry) > 100:
            errors["industry"] = "Industry must be 100 characters or fewer."
        fiscal_year_start = data.get("fiscal_year_start", "01-01").strip()
        try:
            from datetime import datetime
            datetime.strptime(f"{fiscal_year_start}-2000", "%m-%d-%Y")
        except ValueError:
            errors["fiscal_year_start"] = "Enter a valid month and day (MM-DD)."
        timezone_name = data.get("timezone", "UTC").strip()
        try:
            import zoneinfo
            zoneinfo.ZoneInfo(timezone_name)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            errors["timezone"] = "Select a valid timezone."
        currency = None
        currency_id = data.get("default_currency", "").strip()
        if currency_id:
            try:
                currency = Currency.objects.filter(pk=currency_id, is_active=True).first()
            except ValidationError:
                currency = None
            if not currency:
                errors["default_currency"] = "Select an active currency."
        if errors:
            import zoneinfo
            from collections import defaultdict
            tz_groups = defaultdict(list)
            for tz in sorted(zoneinfo.available_timezones()):
                tz_groups[tz.split("/")[0]].append(tz)
            return render(request, self.template_name, {
                "currencies": Currency.objects.filter(is_active=True),
                "tz_groups": dict(sorted(tz_groups.items())),
                "errors": errors, "form_data": values,
                "company_type_choices": Company.CompanyType.choices,
            })

        with transaction.atomic():
            company = Company.objects.create(
                name=name,
                legal_name=data.get("legal_name", "").strip(),
                company_type=company_type or Company.CompanyType.LLC,
                industry=data.get("industry", "").strip(),
                fiscal_year_start=fiscal_year_start,
                timezone=timezone_name,
                default_currency=currency,
            )
            UserCompany.objects.create(
                user=request.user, company=company, role="company_admin", is_active=True
            )
            request.user.primary_company = company
            request.user.role = "company_admin"
            request.user.save(update_fields=["primary_company", "role"])

        messages.success(request, "Company created successfully.")
        return redirect("dashboard:index")


# ── Settings ──────────────────────────────────────────────────────────────────


class CompanySettingsView(CompanyMixin, View):
    required_permission = "company.update"
    template_name = "company/settings.html"

    def get(self, request):
        import zoneinfo
        from collections import defaultdict

        company = self.company()

        tz_groups = defaultdict(list)
        for tz in sorted(zoneinfo.available_timezones()):
            region = tz.split("/")[0]
            tz_groups[region].append(tz)

        return render(
            request,
            self.template_name,
            {
                "company": company,
                "currencies": Currency.objects.filter(is_active=True),
                "tz_groups": dict(sorted(tz_groups.items())),
            },
        )

    def post(self, request):
        company = self.company()
        data = request.POST
        import zoneinfo
        from datetime import datetime

        try:
            name = _required_text(
                {"name": data.get("name", company.name)},
                "name",
                "Company name",
                255,
            )
            legal_name = _optional_text(data, "legal_name", "Legal name", 255)
            tax_id = _optional_text(data, "tax_id", "Tax ID", 100)
            vat_number = _optional_text(data, "vat_number", "VAT number", 100)
            phone = _optional_text(data, "phone", "Phone", 30)
            email = _optional_text(data, "email", "Email", 254)
            website = _optional_text(data, "website", "Website", 200)
            address_line1 = _optional_text(data, "address_line1", "Address", 255)
            city = _optional_text(data, "city", "City", 100)
            country = _optional_text(data, "country", "Country", 100)
            language = _choice(
                data.get("language", "en").strip(),
                (("en", "English"), ("fr", "French"), ("es", "Spanish")),
                "language",
            )
            if email:
                validate_email(email)
            if website:
                URLValidator()(website)

            tz_input = data.get("timezone", "UTC").strip()
            try:
                zoneinfo.ZoneInfo(tz_input)
            except (zoneinfo.ZoneInfoNotFoundError, ValueError):
                raise ValueError(f"Invalid timezone: {tz_input}.") from None
            fiscal_year_start = data.get("fiscal_year_start", "01-01").strip()
            datetime.strptime(f"{fiscal_year_start}-2000", "%m-%d-%Y")
            primary_color = data.get("primary_color", "#4361ee").strip()
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", primary_color):
                raise ValueError("Primary color must be a six-digit hex color.")
            currency = None
            currency_id = data.get("default_currency", "").strip()
            if currency_id:
                currency = _related_object(
                    Currency, currency_id, "active currency", is_active=True
                )

            valuation_method = company.inventory_valuation_method
            if "inventory_valuation_method" in data:
                valuation_method = _choice(
                    data["inventory_valuation_method"],
                    Company._meta.get_field("inventory_valuation_method").choices,
                    "inventory valuation method",
                )
        except (ValueError, ValidationError) as exc:
            messages.error(request, str(exc) or "Invalid company settings.")
            return redirect("company:settings")

        company.name = name
        company.legal_name = legal_name
        company.tax_id = tax_id
        company.vat_number = vat_number
        company.phone = phone
        company.email = email
        company.website = website
        company.address_line1 = address_line1
        company.city = city
        company.country = country
        company.language = language
        company.timezone = tz_input
        company.fiscal_year_start = fiscal_year_start
        company.primary_color = primary_color
        company.inventory_valuation_method = valuation_method
        if currency is not None:
            company.default_currency = currency
        if request.FILES.get("logo"):
            company.logo = request.FILES["logo"]
        company.save()
        messages.success(request, "Company settings updated.")
        return redirect("company:settings")


class SwitchCompanyView(CompanyMixin, View):
    required_permission = "company.read"
    def get(self, request, company_id):
        from apps.authentication.models import UserCompany

        try:
            uc = UserCompany.objects.get(
                user=request.user, company_id=company_id, is_active=True
            )
            request.user.primary_company = uc.company
            request.user.save(update_fields=["primary_company"])
            messages.success(request, f"Switched to {uc.company.name}.")
        except UserCompany.DoesNotExist:
            messages.error(request, "You do not have access to that company.")
        return redirect("dashboard:index")


# ── Branches ──────────────────────────────────────────────────────────────────


class BranchListView(CompanyMixin, ListView):
    required_permission = "company.read"
    template_name = "company/branches/list.html"
    context_object_name = "branches"

    def get_queryset(self):
        return (
            Branch.objects.filter(company=self.company(), is_deleted=False)
            .select_related("manager")
            .order_by("name")
        )


class BranchCreateView(CompanyMixin, View):
    required_permission = "company.create"
    template_name = "company/branches/form.html"

    def get(self, request):
        from apps.authentication.models import User

        return render(
            request,
            self.template_name,
            {
                "managers": User.objects.filter(
                    companies=self.company(), is_active=True
                ),
            },
        )

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            name = _required_text(data, "name", "Branch name", 255)
            code = _required_text(data, "code", "Branch code", 20)
            email = _optional_text(data, "email", "Email", 254)
            if email:
                validate_email(email)
            manager_id = data.get("manager", "").strip()
            manager = None
            if manager_id:
                membership = UserCompany.objects.filter(
                    company=company, user_id=manager_id, is_active=True,
                    user__is_active=True,
                ).select_related("user").first()
                if not membership:
                    raise ValueError("Select an active company branch manager.")
                manager = membership.user
            is_headquarters = _checkbox(data, "is_headquarters")
            phone = _optional_text(data, "phone", "Phone", 30)
            address_line1 = _optional_text(data, "address_line1", "Address", 255)
            city = _optional_text(data, "city", "City", 100)
            country = _optional_text(data, "country", "Country", 100)
            Branch.objects.create(
                company=company,
                name=name,
                code=code,
                is_headquarters=is_headquarters,
                phone=phone,
                email=email,
                address_line1=address_line1,
                city=city,
                country=country,
                manager=manager,
            )
            messages.success(request, "Branch created.")
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect("company:branches")


# ── Departments ───────────────────────────────────────────────────────────────


class DepartmentListView(CompanyMixin, ListView):
    required_permission = "company.read"
    template_name = "company/departments/list.html"
    context_object_name = "departments"

    def get_queryset(self):
        return (
            Department.objects.filter(company=self.company(), is_deleted=False)
            .select_related("parent", "head")
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.hrms.models import Employee

        for dept in ctx["departments"]:
            dept.employee_count = Employee.objects.filter(
                department=dept, status="active", is_deleted=False
            ).count()
        return ctx


class DepartmentCreateView(CompanyMixin, View):
    required_permission = "company.create"
    template_name = "company/departments/form.html"

    def get(self, request):
        from apps.authentication.models import User
        from apps.company.models import Branch, Department

        return render(
            request,
            self.template_name,
            {
                "branches": Branch.objects.filter(
                    company=self.company(), is_active=True, is_deleted=False
                ),
                "departments": Department.objects.filter(
                    company=self.company(), is_deleted=False
                ),
                "users": User.objects.filter(
                    companies=self.company(), is_active=True
                ).order_by("first_name"),
            },
        )

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            from apps.authentication.models import UserCompany

            name = _required_text(data, "name", "Department name", 255)
            code = _required_text(data, "code", "Department code", 20)
            description = _optional_text(data, "description", "Description", 10000)
            cost_center = _optional_text(data, "cost_center", "Cost center", 50)
            parent_id = data.get("parent", "").strip()
            branch_id = data.get("branch", "").strip()
            head_id = data.get("head", "").strip()
            parent = _related_object(
                Department, parent_id, "parent department",
                company=company, is_deleted=False,
            )
            branch = _related_object(
                Branch, branch_id, "active branch",
                company=company, is_active=True, is_deleted=False,
            )
            head = None
            if head_id:
                membership = UserCompany.objects.filter(
                    company=company, user_id=head_id, is_active=True,
                    user__is_active=True,
                ).select_related("user").first()
                if not membership:
                    raise ValueError("Select an active company department head.")
                head = membership.user
            Department.objects.create(
                company=company,
                name=name,
                code=code,
                description=description,
                parent=parent,
                branch=branch,
                head=head,
                cost_center=cost_center,
            )
            messages.success(request, "Department created.")
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect("company:departments")


# ── Users & Roles ─────────────────────────────────────────────────────────────


class UserManagementView(CompanyMixin, ListView):
    required_permission = "company.manage_users"
    template_name = "company/users/list.html"
    context_object_name = "users"

    def get_queryset(self):
        from apps.authentication.models import User

        return User.objects.filter(companies=self.company(), is_active=True).order_by(
            "first_name"
        )


class InviteUserView(CompanyMixin, View):
    required_permission = "company.manage_users"
    def post(self, request):
        company = self.company()

        from apps.authentication.models import User, UserCompany

        try:
            email = _required_text(request.POST, "email", "Email", 254).lower()
            validate_email(email)
            role = _company_role(request.POST.get("role", User.Role.EMPLOYEE))
            with transaction.atomic():
                user, created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        "first_name": email.split("@")[0][:100],
                        "role": role,
                        "is_active": True,
                    },
                )

                if created:
                    temp_pass = User.objects.make_random_password()
                    user.set_password(temp_pass)
                    user.save()

                UserCompany.objects.get_or_create(
                    user=user, company=company, defaults={"role": role}
                )

                if not user.primary_company:
                    user.primary_company = company
                    user.save(update_fields=["primary_company"])
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e))
            return redirect("company:users")

        messages.success(request, f"User {email} added to {company.name}.")
        return redirect("company:users")


class UserUpdateView(CompanyMixin, View):
    required_permission = "company.manage_users"
    template_name = "company/users/form.html"

    def get(self, request, pk):
        from apps.authentication.models import User, UserCompany

        user = get_object_or_404(User, pk=pk, companies=self.company())
        user_company = get_object_or_404(UserCompany, user=user, company=self.company())
        return render(
            request,
            self.template_name,
            {"user_obj": user, "user_company": user_company},
        )

    def post(self, request, pk):
        from apps.authentication.models import User, UserCompany

        user = get_object_or_404(User, pk=pk, companies=self.company())
        user_company = get_object_or_404(UserCompany, user=user, company=self.company())

        role = request.POST.get("role")
        try:
            role = _company_role(role)
            is_active = _checkbox(request.POST, "is_active")
            with transaction.atomic():
                user_company.role = role
                user_company.is_active = is_active
                user_company.save(update_fields=["role", "is_active"])

                # Keep the legacy global role in sync only for the primary company.
                if user.primary_company == self.company():
                    user.role = role
                    user.is_active = is_active
                    user.save(update_fields=["role", "is_active"])
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e))
            return redirect("company:users")
        messages.success(request, f"Updated {user.email} successfully.")
        return redirect("company:users")


class UserRemoveView(CompanyMixin, View):
    required_permission = "company.manage_users"
    def post(self, request, pk):
        from apps.authentication.models import User, UserCompany

        user = get_object_or_404(User, pk=pk, companies=self.company())

        # Don't let users remove themselves
        if user == request.user:
            messages.error(request, "You cannot remove yourself from the company.")
            return redirect("company:users")

        UserCompany.objects.filter(user=user, company=self.company()).delete()

        # Clear primary company if it was this company
        if user.primary_company == self.company():
            user.primary_company = user.companies.first()
            user.save(update_fields=["primary_company"])

        messages.success(request, f"Removed {user.email} from the company.")
        return redirect("company:users")


# ── Fiscal Years ──────────────────────────────────────────────────────────────


class FiscalYearListView(CompanyMixin, ListView):
    required_permission = "company.read"
    template_name = "company/fiscal_years/list.html"
    context_object_name = "fiscal_years"

    def get_queryset(self):
        return FiscalYear.objects.filter(company=self.company()).order_by("-start_date")


class FiscalYearCreateView(CompanyMixin, View):
    required_permission = "company.create"
    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            name = _required_text(data, "name", "Fiscal year name", 100)
            start_date = _valid_date(data.get("start_date"), "start")
            end_date = _valid_date(data.get("end_date"), "end")
            if end_date < start_date:
                raise ValueError("Fiscal year end date must be on or after its start date.")
            is_current = _checkbox(data, "is_current")
            FiscalYear.objects.create(
                company=company,
                name=name,
                start_date=start_date,
                end_date=end_date,
                is_current=is_current,
            )
            messages.success(request, "Fiscal year created.")
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect("company:fiscal_years")


# ── Currencies ────────────────────────────────────────────────────────────────


class CurrencyListView(CompanyMixin, TemplateView):
    required_permission = "company.read"
    template_name = "company/currencies/list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["currencies"] = Currency.objects.filter(is_active=True).order_by("code")
        ctx["exchange_rates"] = ExchangeRate.objects.select_related(
            "from_currency", "to_currency"
        ).order_by("-effective_date")[:20]
        return ctx


class CurrencyCreateView(CompanyMixin, View):
    required_permission = "company.create"
    def post(self, request):
        try:
            import re

            code = _required_text(request.POST, "code", "Currency code", 3).upper()
            name = _required_text(request.POST, "name", "Currency name", 100)
            symbol = _optional_text(request.POST, "symbol", "Currency symbol", 5)
            raw_places = request.POST.get("decimal_places", "2")
            if not raw_places.isdigit():
                raise ValueError("Currency decimal places must be a whole number.")
            decimal_places = int(raw_places)
            if not 0 <= decimal_places <= 4:
                raise ValueError("Currency decimal places must be between 0 and 4.")
            if not re.fullmatch(r"[A-Z]{3}", code):
                raise ValueError("Currency code must contain exactly three letters.")
            is_base = _checkbox(request.POST, "is_base")
            Currency.objects.create(
                code=code,
                name=name,
                symbol=symbol,
                decimal_places=decimal_places,
                is_base=is_base,
                is_active=True,
            )
            messages.success(request, "Currency added successfully.")
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect("company:currencies")


class CurrencyUpdateView(CompanyMixin, UpdateView):
    required_permission = "company.update"
    model = Currency
    template_name = "company/currencies/form.html"
    fields = ["code", "name", "symbol", "decimal_places", "is_base", "is_active"]

    def get_success_url(self):
        from django.urls import reverse_lazy

        return reverse_lazy("company:currencies")

    def form_valid(self, form):
        import re

        code = form.cleaned_data["code"].strip().upper()
        decimal_places = form.cleaned_data["decimal_places"]
        if not re.fullmatch(r"[A-Z]{3}", code):
            form.add_error("code", "Currency code must contain exactly three letters.")
            return self.form_invalid(form)
        if not 0 <= decimal_places <= 4:
            form.add_error(
                "decimal_places", "Currency decimal places must be between 0 and 4."
            )
            return self.form_invalid(form)
        form.instance.code = code
        messages.success(self.request, "Currency updated successfully.")
        return super().form_valid(form)


class CurrencyDeleteView(CompanyMixin, View):
    required_permission = "company.delete"
    def post(self, request, pk):
        try:
            currency = Currency.objects.get(pk=pk)
            # Instead of a hard delete, we set is_active=False
            # This prevents foreign key errors in old exchange rates/invoices
            currency.is_active = False
            currency.save(update_fields=["is_active"])
            messages.success(
                request, f"Currency {currency.code} has been successfully deleted."
            )
        except Currency.DoesNotExist:
            messages.error(request, "Currency not found.")
        except Exception as e:
            messages.error(request, f"Error deleting currency: {e}")
        return redirect("company:currencies")


class ExchangeRateCreateView(CompanyMixin, View):
    required_permission = "company.create"
    def post(self, request):
        try:
            from_currency = _related_object(
                Currency,
                request.POST.get("from_currency", "").strip(),
                "active source currency",
                is_active=True,
            )
            to_currency = _related_object(
                Currency,
                request.POST.get("to_currency", "").strip(),
                "active destination currency",
                is_active=True,
            )
            if from_currency == to_currency:
                raise ValueError("Source and destination currencies must be different.")
            rate = _valid_decimal(
                request.POST.get("rate"),
                "exchange rate",
                max_digits=20,
                decimal_places=6,
                minimum=Decimal("0.000001"),
            )
            effective_date = _valid_date(
                request.POST.get("effective_date"), "effective"
            )

            ExchangeRate.objects.create(
                from_currency=from_currency,
                to_currency=to_currency,
                rate=rate,
                effective_date=effective_date,
                source="manual",
            )
            messages.success(request, "Exchange rate added successfully.")
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect("company:currencies")


# ════════════════════════ UNIT OF MEASURE ═════════════════════════════════════

from apps.inventory.models import UnitOfMeasure  # noqa: E402


class UomListView(CompanyMixin, TemplateView):
    required_permission = "company.read"
    template_name = "company/uoms/list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Assuming CompanyScoped models support soft-delete via is_deleted, if not we just filter is_active
        ctx["uoms"] = UnitOfMeasure.objects.filter(company=self.company()).order_by(
            "name"
        )
        return ctx


class UomCreateView(CompanyMixin, View):
    required_permission = "company.create"
    def post(self, request):
        try:
            name = _required_text(request.POST, "name", "Unit name", 100)
            abbreviation = _required_text(
                request.POST, "abbreviation", "Abbreviation", 20
            )
            uom_type = _choice(
                request.POST.get("uom_type", "unit"),
                UnitOfMeasure._meta.get_field("uom_type").choices,
                "unit type",
            )
            is_active = _checkbox(request.POST, "is_active")
            UnitOfMeasure.objects.create(
                company=self.company(),
                name=name,
                abbreviation=abbreviation,
                uom_type=uom_type,
                is_active=is_active,
            )
            messages.success(request, "Unit of Measure created successfully.")
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error creating UOM: {e}")
        return redirect("company:uoms")


class UomUpdateView(CompanyMixin, View):
    required_permission = "company.update"
    def post(self, request, pk):
        try:
            uom = get_object_or_404(UnitOfMeasure, pk=pk, company=self.company())
            name = _required_text(request.POST, "name", "Unit name", 100)
            abbreviation = _required_text(
                request.POST, "abbreviation", "Abbreviation", 20
            )
            uom_type = _choice(
                request.POST.get("uom_type", "unit"),
                UnitOfMeasure._meta.get_field("uom_type").choices,
                "unit type",
            )
            is_active = _checkbox(request.POST, "is_active")
            uom.name = name
            uom.abbreviation = abbreviation
            uom.uom_type = uom_type
            uom.is_active = is_active
            uom.save()
            messages.success(request, "Unit of Measure updated successfully.")
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error updating UOM: {e}")
        return redirect("company:uoms")


class UomDeleteView(CompanyMixin, View):
    required_permission = "company.delete"
    def post(self, request, pk):
        try:
            uom = get_object_or_404(UnitOfMeasure, pk=pk, company=self.company())
            if hasattr(uom, "is_deleted"):
                uom.is_deleted = True
                uom.is_active = False
                uom.save()
                messages.success(request, "Unit of Measure archived successfully.")
            else:
                uom.delete()
                messages.success(request, "Unit of Measure deleted successfully.")
        except Exception as e:
            messages.error(request, f"Error deleting UOM: {e}")
        return redirect("company:uoms")


# ════════════════════════ TAXES ═══════════════════════════════════════════════


class TaxListView(CompanyMixin, TemplateView):
    required_permission = "company.read"
    template_name = "company/taxes/list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["taxes"] = (
            Tax.objects.filter(company=self.company())
            .select_related("tax_group", "tax_account")
            .order_by("name")
        )
        ctx["tax_groups"] = TaxGroup.objects.filter(
            company=self.company(), is_active=True
        )
        try:
            from apps.accounting.models import Account

            ctx["accounts"] = Account.objects.filter(
                company=self.company(), is_active=True
            )
        except ImportError:
            ctx["accounts"] = []
        return ctx


class TaxCreateView(CompanyMixin, View):
    required_permission = "company.create"
    def post(self, request):
        try:
            from apps.accounting.models import Account

            company = self.company()
            name = _required_text(request.POST, "name", "Tax name", 100)
            rate = _valid_decimal(
                request.POST.get("rate"),
                "tax rate",
                max_digits=7,
                decimal_places=4,
                minimum=Decimal("0"),
            )
            tax_type = _choice(
                request.POST.get("tax_type", Tax.TaxType.PERCENTAGE),
                Tax.TaxType.choices,
                "tax type",
            )
            if tax_type == Tax.TaxType.PERCENTAGE and rate > Decimal("100"):
                raise ValueError("Percentage tax rate cannot exceed 100.")
            tax_group = _related_object(
                TaxGroup,
                request.POST.get("tax_group", "").strip(),
                "active tax group",
                company=company,
                is_active=True,
            )
            tax_account = _related_object(
                Account,
                request.POST.get("tax_account", "").strip(),
                "active tax account",
                company=company,
                is_active=True,
            )
            is_compound = _checkbox(request.POST, "is_compound")
            is_active = _checkbox(request.POST, "is_active")

            Tax.objects.create(
                company=company,
                name=name,
                rate=rate,
                tax_type=tax_type,
                tax_group=tax_group,
                tax_account=tax_account,
                is_compound=is_compound,
                is_active=is_active,
            )
            messages.success(request, "Tax created successfully.")
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error creating tax: {e}")
        return redirect("company:taxes")


class TaxUpdateView(CompanyMixin, View):
    required_permission = "company.update"
    def post(self, request, pk):
        try:
            from apps.accounting.models import Account

            tax = get_object_or_404(Tax, pk=pk, company=self.company())
            company = self.company()
            name = _required_text(request.POST, "name", "Tax name", 100)
            rate = _valid_decimal(
                request.POST.get("rate"),
                "tax rate",
                max_digits=7,
                decimal_places=4,
                minimum=Decimal("0"),
            )
            tax_type = _choice(
                request.POST.get("tax_type", Tax.TaxType.PERCENTAGE),
                Tax.TaxType.choices,
                "tax type",
            )
            if tax_type == Tax.TaxType.PERCENTAGE and rate > Decimal("100"):
                raise ValueError("Percentage tax rate cannot exceed 100.")
            tax_group = _related_object(
                TaxGroup,
                request.POST.get("tax_group", "").strip(),
                "active tax group",
                company=company,
                is_active=True,
            )
            tax_account = _related_object(
                Account,
                request.POST.get("tax_account", "").strip(),
                "active tax account",
                company=company,
                is_active=True,
            )
            is_compound = _checkbox(request.POST, "is_compound")
            is_active = _checkbox(request.POST, "is_active")
            tax.name = name
            tax.rate = rate
            tax.tax_type = tax_type
            tax.tax_group = tax_group
            tax.tax_account = tax_account
            tax.is_compound = is_compound
            tax.is_active = is_active
            tax.save()
            messages.success(request, "Tax updated successfully.")
        except (ValueError, ValidationError) as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error updating tax: {e}")
        return redirect("company:taxes")


class TaxDeleteView(CompanyMixin, View):
    required_permission = "company.delete"
    def post(self, request, pk):
        try:
            tax = get_object_or_404(Tax, pk=pk, company=self.company())
            # Soft delete if applicable or just hard delete/deactivate
            if hasattr(tax, "is_deleted"):
                tax.is_deleted = True
                tax.is_active = False
                tax.save()
            else:
                tax.delete()
            messages.success(request, "Tax removed successfully.")
        except Exception as e:
            messages.error(request, f"Error removing tax: {e}")
        return redirect("company:taxes")


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path  # noqa: E402

app_name = "company"

urlpatterns = [
    path("settings/", CompanySettingsView.as_view(), name="settings"),
    path("switch/<uuid:company_id>/", SwitchCompanyView.as_view(), name="switch"),
    path("branches/", BranchListView.as_view(), name="branches"),
    path("branches/create/", BranchCreateView.as_view(), name="branch_create"),
    path("departments/", DepartmentListView.as_view(), name="departments"),
    path(
        "departments/create/", DepartmentCreateView.as_view(), name="department_create"
    ),
    path("users/", UserManagementView.as_view(), name="users"),
    path("users/invite/", InviteUserView.as_view(), name="user_invite"),
    path("fiscal-years/", FiscalYearListView.as_view(), name="fiscal_years"),
    path(
        "fiscal-years/create/",
        FiscalYearCreateView.as_view(),
        name="fiscal_year_create",
    ),
    path("currencies/", CurrencyListView.as_view(), name="currencies"),
    path("currencies/create/", CurrencyCreateView.as_view(), name="currency_create"),
    path(
        "currencies/rates/create/",
        ExchangeRateCreateView.as_view(),
        name="exchange_rate_create",
    ),
]
