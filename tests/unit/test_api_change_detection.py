"""Tests for tools/check_api_changes.py — OpenAPI breaking change detection.

Compares two OpenAPI specs and classifies changes as:
- BREAKING (removed paths, removed methods, removed required params, type changes)
- NON_BREAKING (added paths, added optional params, added properties)
- NONE (specs are identical)
"""

import pytest

from tools.check_api_changes import ChangeKind, ChangeResult, detect_changes


# --- Fixtures: minimal valid OpenAPI specs ---


def _spec(paths: dict, components: dict | None = None) -> dict:
    """Build a minimal OpenAPI 3.1 spec."""
    spec: dict = {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": paths,
    }
    if components:
        spec["components"] = components
    return spec


def _path_with_get(
    properties: dict | None = None,
    parameters: list | None = None,
) -> dict:
    """Build a path item with a GET operation."""
    op: dict = {"responses": {"200": {"description": "OK"}}}
    if properties:
        op["responses"]["200"]["content"] = {
            "application/json": {"schema": {"type": "object", "properties": properties}}
        }
    if parameters:
        op["parameters"] = parameters
    return {"get": op}


# --- No change ---


class TestNoChange:
    """Identical specs produce NONE."""

    def test_identical_specs(self) -> None:
        old = _spec({"/health": _path_with_get()})
        new = _spec({"/health": _path_with_get()})
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.NONE
        assert result.changes == []

    def test_identical_empty_specs(self) -> None:
        old = _spec({})
        new = _spec({})
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.NONE


# --- Breaking changes ---


class TestBreakingChanges:
    """Changes that remove or alter existing contract surface."""

    def test_removed_path_is_breaking(self) -> None:
        old = _spec({"/health": _path_with_get(), "/users": _path_with_get()})
        new = _spec({"/health": _path_with_get()})
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.BREAKING
        assert any("/users" in c for c in result.changes)

    def test_removed_method_is_breaking(self) -> None:
        old = _spec({"/health": {"get": {"responses": {}}, "post": {"responses": {}}}})
        new = _spec({"/health": {"get": {"responses": {}}}})
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.BREAKING
        assert any("POST" in c and "/health" in c for c in result.changes)

    def test_removed_required_parameter_is_breaking(self) -> None:
        param = {"name": "id", "in": "query", "required": True}
        old = _spec({"/items": _path_with_get(parameters=[param])})
        new = _spec({"/items": _path_with_get(parameters=[])})
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.BREAKING
        assert any("id" in c for c in result.changes)

    def test_required_param_made_optional_is_breaking(self) -> None:
        """Changing required=True to required=False could break clients relying on it."""
        old_param = {"name": "id", "in": "query", "required": True}
        new_param = {"name": "id", "in": "query", "required": False}
        old = _spec({"/items": _path_with_get(parameters=[old_param])})
        new = _spec({"/items": _path_with_get(parameters=[new_param])})
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.BREAKING

    def test_multiple_breaking_changes(self) -> None:
        old = _spec(
            {
                "/health": _path_with_get(),
                "/users": _path_with_get(),
                "/items": _path_with_get(),
            }
        )
        new = _spec({"/health": _path_with_get()})
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.BREAKING
        assert len(result.changes) >= 2


# --- Non-breaking changes ---


class TestNonBreakingChanges:
    """Changes that only add to the contract surface."""

    def test_added_path_is_non_breaking(self) -> None:
        old = _spec({"/health": _path_with_get()})
        new = _spec({"/health": _path_with_get(), "/users": _path_with_get()})
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.NON_BREAKING
        assert any("/users" in c for c in result.changes)

    def test_added_method_is_non_breaking(self) -> None:
        old = _spec({"/health": {"get": {"responses": {}}}})
        new = _spec({"/health": {"get": {"responses": {}}, "post": {"responses": {}}}})
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.NON_BREAKING
        assert any("POST" in c and "/health" in c for c in result.changes)

    def test_added_optional_parameter_is_non_breaking(self) -> None:
        param = {"name": "filter", "in": "query", "required": False}
        old = _spec({"/items": _path_with_get(parameters=[])})
        new = _spec({"/items": _path_with_get(parameters=[param])})
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.NON_BREAKING

    def test_added_response_status_code_is_non_breaking(self) -> None:
        old = _spec({"/items": {"get": {"responses": {"200": {"description": "OK"}}}}})
        new = _spec(
            {
                "/items": {
                    "get": {
                        "responses": {
                            "200": {"description": "OK"},
                            "404": {"description": "Not found"},
                        }
                    }
                }
            }
        )
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.NON_BREAKING


# --- Mixed changes: breaking wins ---


class TestMixedChanges:
    """When both breaking and non-breaking changes exist, result is BREAKING."""

    def test_breaking_plus_non_breaking_is_breaking(self) -> None:
        old = _spec({"/health": _path_with_get(), "/users": _path_with_get()})
        new = _spec({"/health": _path_with_get(), "/new": _path_with_get()})
        result = detect_changes(old, new)
        assert result.kind == ChangeKind.BREAKING
        assert len(result.changes) >= 2


# --- ChangeResult interface ---


class TestChangeResult:
    """Verify the result object structure."""

    def test_result_has_kind_and_changes(self) -> None:
        old = _spec({"/health": _path_with_get()})
        result = detect_changes(old, old)
        assert hasattr(result, "kind")
        assert hasattr(result, "changes")
        assert isinstance(result.changes, list)

    def test_result_summary_includes_kind(self) -> None:
        old = _spec({"/health": _path_with_get()})
        result = detect_changes(old, old)
        assert "NONE" in str(result)
