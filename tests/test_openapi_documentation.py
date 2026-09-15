import inspect
import re

from pydantic import BaseModel

from app import schemas
from app.main import app

HANGUL_PATTERN = re.compile(r"[가-힣]")
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def test_every_api_operation_has_korean_summary_and_description():
    undocumented: list[str] = []

    for path, path_item in app.openapi()["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            summary = operation.get("summary", "")
            description = operation.get("description", "")
            if not HANGUL_PATTERN.search(summary) or not HANGUL_PATTERN.search(description):
                undocumented.append(f"{method.upper()} {path}")

    assert undocumented == []


def test_every_openapi_tag_has_korean_description():
    undocumented = [
        tag["name"]
        for tag in app.openapi()["tags"]
        if not HANGUL_PATTERN.search(tag.get("description", ""))
    ]

    assert undocumented == []


def test_every_public_schema_field_has_korean_description():
    undocumented: list[str] = []

    for model_name, model in vars(schemas).items():
        if not inspect.isclass(model) or not issubclass(model, BaseModel) or model is BaseModel:
            continue
        if model.__module__ != schemas.__name__:
            continue
        for field_name, field in model.model_fields.items():
            if not field.description or not HANGUL_PATTERN.search(field.description):
                undocumented.append(f"{model_name}.{field_name}")

    assert undocumented == []
