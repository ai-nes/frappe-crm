import ast
from pathlib import Path

import frappe
from frappe import _


SKIP_DIRS = {"__pycache__", "node_modules", "public", "templates"}


@frappe.whitelist(allow_guest=True)
def get_openapi_spec():
    if not frappe.conf.developer_mode:
        frappe.throw(_("API docs are only available in developer mode"))

    paths = {}
    for method in get_whitelisted_methods():
        operation = {
            "tags": [method["module"]],
            "summary": method["summary"] or method["name"],
            "description": method["description"],
            "operationId": f'{method["dotted_path"]}.{method["http_method"].lower()}',
            "responses": {
                "200": {
                    "description": "Successful response",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"message": {}},
                            }
                        }
                    },
                }
            },
            "x-frappe-dotted-path": method["dotted_path"],
            "x-frappe-allow-guest": method["allow_guest"],
        }

        if method["parameters"]:
            operation["requestBody"] = {
                "required": any(p["required"] for p in method["parameters"]),
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                p["name"]: p["schema"] for p in method["parameters"]
                            },
                            "required": [
                                p["name"] for p in method["parameters"] if p["required"]
                            ],
                        }
                    }
                },
            }

        paths.setdefault(f'/api/method/{method["dotted_path"]}', {})[
            method["http_method"].lower()
        ] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Frappe CRM API",
            "version": frappe.get_attr("crm.__version__"),
            "description": "Generated from @frappe.whitelist methods in the CRM app. Use in local development only.",
        },
        "servers": [{"url": frappe.utils.get_url()}],
        "paths": dict(sorted(paths.items())),
    }


def get_whitelisted_methods():
    app_path = Path(frappe.get_app_path("crm"))
    methods = []

    for file_path in sorted(app_path.rglob("*.py")):
        if any(part in SKIP_DIRS for part in file_path.parts):
            continue

        try:
            tree = ast.parse(file_path.read_text())
        except SyntaxError:
            continue

        module = get_module_path(app_path, file_path)
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue

            decorator = get_whitelist_decorator(node)
            if not decorator:
                continue

            methods.append(
                {
                    "name": node.name,
                    "module": module,
                    "dotted_path": f"{module}.{node.name}",
                    "http_method": get_decorator_methods(decorator)[0],
                    "allow_guest": get_decorator_bool_kwarg(decorator, "allow_guest"),
                    "summary": (ast.get_docstring(node) or "").split("\n")[0],
                    "description": ast.get_docstring(node) or "",
                    "parameters": get_parameters(node),
                }
            )

    return methods


def get_module_path(app_path, file_path):
    relative_path = file_path.relative_to(app_path.parent).with_suffix("")
    return ".".join(relative_path.parts)


def get_whitelist_decorator(node):
    for decorator in node.decorator_list:
        if is_whitelist_decorator(decorator):
            return decorator
    return None


def is_whitelist_decorator(decorator):
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(target, ast.Attribute) and target.attr == "whitelist"


def get_decorator_methods(decorator):
    if not isinstance(decorator, ast.Call):
        return ["POST"]

    for keyword in decorator.keywords:
        if keyword.arg != "methods":
            continue
        if isinstance(keyword.value, ast.List):
            return [
                value.value.upper()
                for value in keyword.value.elts
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            ] or ["POST"]
        value = get_string_value(keyword.value)
        if value:
            return [value.upper()]

    return ["POST"]


def get_decorator_bool_kwarg(decorator, name):
    if not isinstance(decorator, ast.Call):
        return False

    for keyword in decorator.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return bool(keyword.value.value)
    return False


def get_string_value(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def get_parameters(node):
    parameters = []
    defaults = list(node.args.defaults)
    default_offset = len(node.args.args) - len(defaults)

    for index, arg in enumerate(node.args.args):
        if arg.arg in {"self", "cls"}:
            continue

        default = defaults[index - default_offset] if index >= default_offset else None
        parameters.append(
            {
                "name": arg.arg,
                "required": default is None,
                "schema": get_schema(arg.annotation),
            }
        )

    return parameters


def get_schema(annotation):
    if annotation is None:
        return {"type": "string"}

    annotation_name = annotation_to_string(annotation)
    if annotation_name in {"int", "frappe.types.DF.Int"}:
        return {"type": "integer"}
    if annotation_name in {"float"}:
        return {"type": "number"}
    if annotation_name in {"bool"}:
        return {"type": "boolean"}
    if annotation_name in {"list", "tuple"}:
        return {"type": "array", "items": {}}
    if annotation_name in {"dict"}:
        return {"type": "object"}
    return {"type": "string"}


def annotation_to_string(annotation):
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        parent = annotation_to_string(annotation.value)
        return f"{parent}.{annotation.attr}" if parent else annotation.attr
    if isinstance(annotation, ast.Subscript):
        return annotation_to_string(annotation.value)
    return ""
