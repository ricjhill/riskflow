"""Dynamic pydantic model factory for configurable target schemas.

build_record_model(schema) generates a pydantic BaseModel class at runtime
from a TargetSchema definition. The generated model has:
- Typed fields matching the schema (str, float, date, str for currency)
- field_validator functions for constraints (non_negative, not_empty, allowed_values)
- model_validator functions for cross-field rules (date ordering)

The model is cached by schema fingerprint — calling build_record_model
with the same schema returns the same class instance (no regeneration).
"""

import datetime
import functools
from typing import Any

from pydantic import BaseModel, create_model, field_validator, model_validator

from src.domain.model.target_schema import FieldDefinition, FieldType, TargetSchema

# Type mapping from schema FieldType to Python types
_TYPE_MAP: dict[FieldType, type] = {
    FieldType.STRING: str,
    FieldType.DATE: datetime.date,
    FieldType.FLOAT: float,
    FieldType.CURRENCY: str,
}


@functools.lru_cache(maxsize=32)
def _build_cached(fingerprint: str, schema_json: str) -> type[BaseModel]:
    """Cache key is the fingerprint; schema_json carries the data.

    lru_cache requires hashable args, so we serialize the schema to JSON.
    The fingerprint alone would work as a key but passing the JSON avoids
    needing a separate lookup to reconstruct the schema.
    """
    schema = TargetSchema.model_validate_json(schema_json)
    return _build_model(schema)


def build_record_model(schema: TargetSchema) -> type[BaseModel]:
    """Build a pydantic model class from a TargetSchema.

    Cached by schema fingerprint — same schema returns same class.
    """
    return _build_cached(schema.fingerprint, schema.model_dump_json())


def clear_record_model_cache() -> None:
    """Clear the LRU cache for dynamic record models.

    Exposed as a public function so tests can force cold builds
    without importing the private ``_build_cached`` symbol.
    """
    _build_cached.cache_clear()


def _build_model(schema: TargetSchema) -> type[BaseModel]:
    """Internal: construct the pydantic model from schema definition."""
    # Build field definitions for create_model
    field_definitions: dict[str, Any] = {}
    for name, defn in schema.fields.items():
        python_type = _TYPE_MAP[defn.type]
        if defn.required:
            field_definitions[name] = (python_type, ...)
        else:
            field_definitions[name] = (python_type | None, None)

    # Create the base model
    Model = create_model(f"DynamicRecord_{schema.name}", **field_definitions)

    # Attach field validators for constraints
    validators: dict[str, Any] = {}
    for name, defn in schema.fields.items():
        _attach_field_validators(validators, name, defn)

    # Attach cross-field validators
    _attach_cross_field_validators(validators, schema)

    # Rebuild the model with validators
    if validators:
        namespace: dict[str, Any] = {"__annotations__": {}}
        namespace.update(validators)
        ModelWithValidators: type[BaseModel] = type(  # type: ignore[assignment]
            Model.__name__, (Model,), namespace
        )
        ModelWithValidators.model_rebuild()
        return ModelWithValidators

    return Model


def _attach_field_validators(
    validators: dict[str, Any],
    field_name: str,
    defn: FieldDefinition,
) -> None:
    """Add field-level constraint validators to the namespace."""
    if defn.non_negative:
        name = field_name  # capture in closure

        @field_validator(name, mode="after")
        def _check_non_negative(cls: Any, v: float) -> float:
            if v < 0:
                msg = f"{name} must be non-negative, got {v}"
                raise ValueError(msg)
            return v

        validators[f"validate_{field_name}_non_negative"] = _check_non_negative

    if defn.not_empty:
        name = field_name

        @field_validator(name, mode="after")
        def _check_not_empty(cls: Any, v: str) -> str:
            if not v.strip():
                msg = f"{name} must not be empty"
                raise ValueError(msg)
            return v

        validators[f"validate_{field_name}_not_empty"] = _check_not_empty

    if defn.allowed_values is not None:
        name = field_name
        allowed = defn.allowed_values

        @field_validator(name, mode="after")
        def _check_allowed(cls: Any, v: str) -> str:
            if v not in allowed:
                msg = f"{name} must be one of {allowed}, got '{v}'"
                raise ValueError(msg)
            return v

        validators[f"validate_{field_name}_allowed"] = _check_allowed


def _attach_cross_field_validators(
    validators: dict[str, Any],
    schema: TargetSchema,
) -> None:
    """Add model-level validators for cross-field rules."""
    for i, rule in enumerate(schema.cross_field_rules):
        earlier = rule.earlier
        later = rule.later

        @model_validator(mode="after")
        def _check_date_order(self: Any) -> Any:
            earlier_val = getattr(self, earlier, None)
            later_val = getattr(self, later, None)
            # Skip if either date is None (optional field not provided)
            if earlier_val is not None and later_val is not None:
                if later_val < earlier_val:
                    msg = f"{later} must not be before {earlier}"
                    raise ValueError(msg)
            return self

        validators[f"validate_date_order_{i}"] = _check_date_order
