"""YAML-based schema loader implementing SchemaLoaderPort.

Reads a YAML config file and returns a validated TargetSchema.
Raises InvalidSchemaError on any failure — missing file, malformed
YAML, or schema validation errors. This is a fatal startup error:
the app should not boot with an invalid schema.
"""

from pathlib import Path

import yaml
from pydantic import ValidationError

from src.domain.model.errors import InvalidSchemaError
from src.domain.model.target_schema import TargetSchema


class YamlSchemaLoader:
    """Loads a TargetSchema from a YAML file."""

    def load(self, path: str) -> TargetSchema:
        """Load and validate a target schema from a YAML file.

        Raises InvalidSchemaError if:
        - File does not exist
        - YAML is malformed
        - Schema content is invalid (wrong types, bad constraints, etc.)
        """
        file_path = Path(path)
        if not file_path.exists():
            msg = f"Schema file not found: {path}"
            raise InvalidSchemaError(msg)

        try:
            raw = file_path.read_text()
        except OSError as e:
            msg = f"Failed to read schema file: {path}"
            raise InvalidSchemaError(msg) from e

        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            msg = f"Failed to parse YAML in schema file: {path}"
            raise InvalidSchemaError(msg) from e

        if not isinstance(data, dict):
            msg = f"Schema file must contain a YAML mapping, got {type(data).__name__}: {path}"
            raise InvalidSchemaError(msg)

        try:
            return TargetSchema.model_validate(data)
        except ValidationError as e:
            msg = f"Invalid schema in {path}: {e}"
            raise InvalidSchemaError(msg) from e
