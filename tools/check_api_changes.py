"""Detect breaking vs non-breaking changes between two OpenAPI specs.

Compares an old and new OpenAPI 3.x spec and classifies changes:

- BREAKING: removed paths, removed methods, removed/changed required params
- NON_BREAKING: added paths, added methods, added optional params, added response codes
- NONE: specs are functionally identical

Usage:
    from tools.check_api_changes import detect_changes, ChangeKind
    result = detect_changes(old_spec, new_spec)
    print(result.kind, result.changes)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


class ChangeKind(enum.Enum):
    """Classification of API changes."""

    NONE = "NONE"
    NON_BREAKING = "NON_BREAKING"
    BREAKING = "BREAKING"


@dataclass
class ChangeResult:
    """Result of comparing two OpenAPI specs."""

    kind: ChangeKind
    changes: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.kind == ChangeKind.NONE:
            return "NONE: no API changes detected"
        lines = [f"{self.kind.value}: {len(self.changes)} change(s)"]
        for change in self.changes:
            lines.append(f"  - {change}")
        return "\n".join(lines)


def detect_changes(old: dict, new: dict) -> ChangeResult:
    """Compare two OpenAPI specs and return classified changes."""
    breaking: list[str] = []
    non_breaking: list[str] = []

    old_paths = old.get("paths", {})
    new_paths = new.get("paths", {})

    # Removed paths
    for path in old_paths:
        if path not in new_paths:
            breaking.append(f"removed path: {path}")

    # Added paths
    for path in new_paths:
        if path not in old_paths:
            non_breaking.append(f"added path: {path}")

    # Changes within shared paths
    for path in old_paths:
        if path not in new_paths:
            continue
        old_item = old_paths[path]
        new_item = new_paths[path]
        _compare_path_item(path, old_item, new_item, breaking, non_breaking)

    # Classify
    all_changes = breaking + non_breaking
    if breaking:
        return ChangeResult(kind=ChangeKind.BREAKING, changes=all_changes)
    if non_breaking:
        return ChangeResult(kind=ChangeKind.NON_BREAKING, changes=all_changes)
    return ChangeResult(kind=ChangeKind.NONE)


def _compare_path_item(
    path: str,
    old_item: dict,
    new_item: dict,
    breaking: list[str],
    non_breaking: list[str],
) -> None:
    """Compare methods and parameters for a single path."""
    old_methods = {m for m in old_item if m in HTTP_METHODS}
    new_methods = {m for m in new_item if m in HTTP_METHODS}

    # Removed methods
    for method in old_methods - new_methods:
        breaking.append(f"removed method: {method.upper()} {path}")

    # Added methods
    for method in new_methods - old_methods:
        non_breaking.append(f"added method: {method.upper()} {path}")

    # Changes within shared methods
    for method in old_methods & new_methods:
        old_op = old_item[method]
        new_op = new_item[method]
        _compare_operation(path, method, old_op, new_op, breaking, non_breaking)


def _compare_operation(
    path: str,
    method: str,
    old_op: dict,
    new_op: dict,
    breaking: list[str],
    non_breaking: list[str],
) -> None:
    """Compare parameters and responses for a single operation."""
    label = f"{method.upper()} {path}"

    _compare_parameters(label, old_op, new_op, breaking, non_breaking)
    _compare_responses(label, old_op, new_op, breaking, non_breaking)


def _compare_parameters(
    label: str,
    old_op: dict,
    new_op: dict,
    breaking: list[str],
    non_breaking: list[str],
) -> None:
    """Compare operation parameters."""
    old_params = {p["name"]: p for p in old_op.get("parameters", [])}
    new_params = {p["name"]: p for p in new_op.get("parameters", [])}

    # Removed parameters that were required
    for name in old_params:
        if name not in new_params:
            old_p = old_params[name]
            if old_p.get("required", False):
                breaking.append(f"removed required parameter '{name}' from {label}")
            else:
                non_breaking.append(f"removed optional parameter '{name}' from {label}")

    # Added parameters
    for name in new_params:
        if name not in old_params:
            new_p = new_params[name]
            if new_p.get("required", False):
                breaking.append(f"added required parameter '{name}' to {label}")
            else:
                non_breaking.append(f"added optional parameter '{name}' to {label}")

    # Changed parameters
    for name in old_params:
        if name not in new_params:
            continue
        old_p = old_params[name]
        new_p = new_params[name]

        # Required → optional is breaking (clients may depend on server requiring it)
        if old_p.get("required", False) and not new_p.get("required", False):
            breaking.append(f"parameter '{name}' changed from required to optional in {label}")

        # Optional → required is breaking (clients may not be sending it)
        if not old_p.get("required", False) and new_p.get("required", False):
            breaking.append(f"parameter '{name}' changed from optional to required in {label}")


def _compare_responses(
    label: str,
    old_op: dict,
    new_op: dict,
    breaking: list[str],
    non_breaking: list[str],
) -> None:
    """Compare operation response codes."""
    old_responses = set(old_op.get("responses", {}).keys())
    new_responses = set(new_op.get("responses", {}).keys())

    for code in old_responses - new_responses:
        breaking.append(f"removed response status {code} from {label}")

    for code in new_responses - old_responses:
        non_breaking.append(f"added response status {code} to {label}")
