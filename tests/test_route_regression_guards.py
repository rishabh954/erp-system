import ast
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import get_resolver, reverse
from django.urls.resolvers import URLPattern, URLResolver


def _namespace_contains(url_name):
    resolver = get_resolver()
    parts = url_name.split(":")
    for namespace in parts[:-1]:
        namespace_entry = resolver.namespace_dict.get(namespace)
        if namespace_entry is None:
            return False
        resolver = namespace_entry[1]
    return parts[-1] in resolver.reverse_dict


def _literal_route_names():
    names = set()
    template_root = Path(settings.BASE_DIR)
    for path in template_root.rglob("*.html"):
        if any(part in {"venv", ".git", "staticfiles"} for part in path.parts):
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        names.update(re.findall(r"{\%\s*url\s+['\"]([^'\"]+)['\"]", content))

    source_root = Path(settings.BASE_DIR) / "apps"
    for path in source_root.rglob("*.py"):
        if "test" in path.parts or "tests" in path.parts or "migrations" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            func_name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else ""
            )
            if func_name not in {"reverse", "reverse_lazy", "redirect"}:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                value = first.value
                if not value.startswith(("/", "http://", "https://", "#")):
                    names.add(value)
    return names


@pytest.mark.django_db
def test_all_literal_template_and_python_url_names_resolve():
    unresolved = sorted(name for name in _literal_route_names() if not _namespace_contains(name))
    assert not unresolved, f"Unresolved URL names: {unresolved}"


def _parameterless_route_names(patterns, route_prefix="", namespace_prefix=""):
    for pattern in patterns:
        route = route_prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            namespace = f"{pattern.namespace}:" if pattern.namespace else ""
            yield from _parameterless_route_names(
                pattern.url_patterns, route, namespace_prefix + namespace
            )
        elif isinstance(pattern, URLPattern) and pattern.name:
            if "<" not in route and "(?P<" not in route and "(?<" not in route:
                yield namespace_prefix + pattern.name


@pytest.mark.django_db
def test_company_admin_can_get_all_parameterless_routes_without_server_errors(client, user):
    client.force_login(user)
    names = set(_parameterless_route_names(get_resolver().url_patterns))
    names.difference_update({"logout", "auth:logout", "account_logout"})
    failures = []
    for name in sorted(names):
        try:
            path = reverse(name)
        except Exception:
            continue
        response = client.get(path)
        if response.status_code >= 500:
            failures.append((name, path, response.status_code))
    assert not failures, f"Routes returned 5xx: {failures}"
