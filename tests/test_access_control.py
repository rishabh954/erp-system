import re
from dataclasses import dataclass
from uuid import UUID

import pytest
from django.conf import settings
from django.test import Client
from django.urls import URLPattern, get_resolver

from apps.authentication.models import ModulePermission, User, UserCompany
from apps.company.models import Department
from apps.crm.models import Customer, Lead
from apps.hrms.models import Employee
from apps.inventory.models import Product
from apps.projects.models import Project
from apps.purchase.models import PurchaseOrder, Vendor
from apps.sales.models import SalesOrder
from core.factories import CompanyFactory, UserFactory


@dataclass(frozen=True)
class URLCase:
    path: str
    name: str
    callback: object


# Public auth entry points, health probes, API discovery/docs, and PWA assets are
# intentionally reachable without a logged-in user. No inbound webhook route is
# registered in the root URLconf; the administration webhook page stays protected.
PUBLIC_NAMES = {
    "api-root",
    "email_verify",
    "health",
    "health_live",
    "health_ready",
    "login",
    "manifest",
    "offline",
    "password_reset",
    "password_reset_confirm",
    "redoc",
    "register",
    "schema",
    "service_worker",
    "swagger-ui",
    "token_obtain_pair",
    "token_refresh",
    "token_verify",
    "two_factor_verify",
    "2fa-verify",
}


def _sample_value(name, converter=None, expression=""):
    converter_name = converter.__class__.__name__ if converter else ""
    if converter_name == "UUIDConverter" or "uuid" in name.lower():
        return str(UUID("00000000-0000-0000-0000-000000000001"))
    if converter_name == "IntConverter" or re.search(r"\\d", expression):
        return "1"
    if converter_name == "PathConverter":
        return "access-control/sample"
    return "access-control"


def _render_path(route, converters):
    def replace_converter(match):
        name = match.group("name")
        converter = converters.get(name)
        value = _sample_value(name, converter)
        return converter.to_url(value) if converter else value

    route = re.sub(
        r"<(?:(?P<type>[^:>]+):)?(?P<name>[^>]+)>", replace_converter, route
    )

    def replace_regex_group(match):
        name, expression = match.group("name"), match.group("expression")
        return _sample_value(name, expression=expression)

    route = re.sub(
        r"\(\?P<(?P<name>[A-Za-z_]\w*)>(?P<expression>[^)]*)\)",
        replace_regex_group,
        route,
    )
    route = route.replace(r"\.", ".").replace("^", "").replace("$", "")
    route = route.replace("/?", "/").replace("\\", "")
    return "/" + route.lstrip("/")


def _is_public(name, route):
    if name in PUBLIC_NAMES:
        return True
    if settings.DEBUG and route.startswith("__debug__/"):
        return True
    return route.startswith(("^static/", "static/", "manifest.json", "service-worker.js"))


def _url_cases():
    cases = []

    def walk(patterns, prefix="", converters=None):
        converters = converters or {}
        for pattern in patterns:
            route = prefix + str(pattern.pattern)
            current_converters = {**converters, **pattern.pattern.converters}
            if isinstance(pattern, URLPattern):
                name = pattern.name or "unnamed"
                if not _is_public(name, route):
                    cases.append(
                        URLCase(
                            path=_render_path(route, current_converters),
                            name=name,
                            callback=pattern.callback,
                        )
                    )
            else:
                walk(pattern.url_patterns, route, current_converters)

    walk(get_resolver().url_patterns)
    return tuple(cases)


URL_CASES = _url_cases()


def _request_methods(callback):
    actions = getattr(callback, "actions", None)
    if actions:
        return tuple(method.upper() for method in actions if method != "head")

    view_class = getattr(callback, "view_class", None) or getattr(callback, "cls", None)
    if view_class:
        return tuple(
            method.upper()
            for method in ("get", "post", "put", "patch", "delete")
            if callable(getattr(view_class, method, None))
        )
    return ("GET", "POST", "PUT", "PATCH", "DELETE")


def _route_label(case, method="GET"):
    return f"{method} {case.path} [{case.name}]"


def _client_request(client, method, path, **extra):
    return getattr(client, method.lower())(path, **extra)


ACCESS_CASES = tuple(
    (case, method)
    for case in URL_CASES
    for method in _request_methods(case.callback)
)


@pytest.mark.parametrize(
    "case,method",
    ACCESS_CASES,
    ids=lambda value: value.name if isinstance(value, URLCase) else value,
)
def test_anonymous_requests_do_not_succeed(case, method):
    client = Client(raise_request_exception=False)
    response = _client_request(client, method, case.path)

    assert not 200 <= response.status_code < 300, (
        f"Anonymous access returned {response.status_code}: "
        f"{_route_label(case, method)}"
    )


@pytest.mark.django_db
def test_user_without_module_permissions_is_denied(company):
    user = User.objects.create_user(
        email="no-module-permissions@example.com",
        password="test-password",
        first_name="No",
        last_name="Permissions",
        role=User.Role.EMPLOYEE,
        primary_company=company,
    )
    UserCompany.objects.create(
        user=user,
        company=company,
        role=User.Role.EMPLOYEE,
        is_active=True,
    )
    ModulePermission.objects.filter(role=User.Role.EMPLOYEE).delete()
    client = Client(raise_request_exception=False)
    client.force_login(user)

    failures = []
    for case in URL_CASES:
        response = client.get(case.path)
        if 200 <= response.status_code < 300:
            failures.append(f"{_route_label(case)} -> {response.status_code}")

    if failures:
        print("Routes accessible without module permissions:")
        print("\n".join(failures))

    assert not failures, "Routes accessible without module permissions:\n" + "\n".join(
        failures
    )


@pytest.mark.django_db
def test_company_b_cannot_read_company_a_objects(client, company):
    company_a = company
    company_b = CompanyFactory(name="Access Control Company B")
    user_b = UserFactory(
        email="company-b-access@example.com",
        primary_company=company_b,
        role=User.Role.COMPANY_ADMIN,
    )
    UserCompany.objects.create(
        user=user_b,
        company=company_b,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )

    customer_a = Customer.objects.create(company=company_a, name="Customer A")
    lead_a = Lead.objects.create(company=company_a, name="Lead A", expected_revenue=0)
    order_a = SalesOrder.objects.create(
        company=company_a, customer=customer_a, order_date="2026-01-01"
    )
    vendor_a = Vendor.objects.create(company=company_a, name="Vendor A")
    purchase_order_a = PurchaseOrder.objects.create(
        company=company_a,
        vendor=vendor_a,
        order_date="2026-01-01",
        expected_delivery="2026-01-01",
    )
    project_a = Project.objects.create(company=company_a, name="Project A")
    product_a = Product.objects.create(
        company=company_a,
        name="Product A",
        sku="ACCESS-A-001",
        product_type="stockable",
        cost_price="10.00",
        sale_price="20.00",
    )
    department_a = Department.objects.create(
        company=company_a, name="Department A", code="ACCESS-A"
    )
    employee_a = Employee.objects.create(
        company=company_a,
        department=department_a,
        employee_id="ACCESS-A-001",
        first_name="Employee",
        last_name="A",
        joining_date="2026-01-01",
    )

    paths = (
        ("crm:customer_detail", customer_a.pk),
        ("crm:lead_detail", lead_a.pk),
        ("sales:order_detail", order_a.pk),
        ("purchase:vendor_detail", vendor_a.pk),
        ("purchase:order_detail", purchase_order_a.pk),
        ("projects:detail", project_a.pk),
        ("inventory:product_detail", product_a.pk),
        ("hrms:employee_detail", employee_a.pk),
    )

    from django.urls import reverse

    client.force_login(user_b)
    failures = []
    for url_name, object_id in paths:
        response = client.get(reverse(url_name, kwargs={"pk": object_id}))
        if response.status_code not in (403, 404):
            failures.append(f"{url_name} ({object_id}) -> {response.status_code}")

    assert not failures, "Cross-company object access was not denied:\n" + "\n".join(
        failures
    )
