"""Tests for InvalidSchemaError, SchemaLoaderPort, and YamlSchemaLoader.

Loops 8-10: error type, port protocol, and YAML adapter for loading
target schemas from config files.
"""

import pytest

from src.domain.model.errors import InvalidSchemaError, RiskFlowError
from src.domain.model.target_schema import DEFAULT_TARGET_SCHEMA, FieldType, TargetSchema
from src.adapters.parsers.schema_loader import YamlSchemaLoader
from src.ports.output.schema_loader import SchemaLoaderPort


# --- Loop 8: InvalidSchemaError ---


class TestInvalidSchemaError:
    def test_inherits_from_riskflow_error(self) -> None:
        assert issubclass(InvalidSchemaError, RiskFlowError)

    def test_carries_message(self) -> None:
        err = InvalidSchemaError("bad schema")
        assert str(err) == "bad schema"

    def test_catchable_by_base(self) -> None:
        with pytest.raises(RiskFlowError):
            raise InvalidSchemaError("test")


# --- Loop 9: SchemaLoaderPort ---


class TestSchemaLoaderPort:
    def test_is_runtime_checkable(self) -> None:
        assert isinstance(YamlSchemaLoader(), SchemaLoaderPort)

    def test_incomplete_class_does_not_satisfy(self) -> None:
        class BadLoader:
            pass

        assert not isinstance(BadLoader(), SchemaLoaderPort)


# --- Loop 10: YamlSchemaLoader ---


class TestYamlSchemaLoader:
    def test_loads_valid_yaml(self, tmp_path: pytest.TempPathFactory) -> None:
        yaml_content = """
name: test_schema
fields:
  Policy_ID:
    type: string
    required: true
    not_empty: true
  Amount:
    type: float
    required: true
    non_negative: true
"""
        path = tmp_path / "schema.yaml"
        path.write_text(yaml_content)

        loader = YamlSchemaLoader()
        schema = loader.load(str(path))

        assert isinstance(schema, TargetSchema)
        assert schema.name == "test_schema"
        assert schema.field_names == {"Policy_ID", "Amount"}

    def test_loads_schema_with_all_sections(self, tmp_path: pytest.TempPathFactory) -> None:
        yaml_content = """
name: full_schema
fields:
  Policy_ID:
    type: string
    not_empty: true
  Start:
    type: date
  End:
    type: date
  Amount:
    type: float
    non_negative: true
  Currency:
    type: currency
    allowed_values: [USD, GBP]
cross_field_rules:
  - earlier: Start
    later: End
slm_hints:
  - source_alias: GWP
    target: Amount
  - source_alias: Ccy
    target: Currency
"""
        path = tmp_path / "schema.yaml"
        path.write_text(yaml_content)

        loader = YamlSchemaLoader()
        schema = loader.load(str(path))

        assert len(schema.fields) == 5
        assert len(schema.cross_field_rules) == 1
        assert len(schema.slm_hints) == 2

    def test_raises_on_nonexistent_file(self) -> None:
        loader = YamlSchemaLoader()
        with pytest.raises(InvalidSchemaError, match="not found"):
            loader.load("/nonexistent/schema.yaml")

    def test_raises_on_malformed_yaml(self, tmp_path: pytest.TempPathFactory) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("{{{{not yaml")

        loader = YamlSchemaLoader()
        with pytest.raises(InvalidSchemaError, match="parse"):
            loader.load(str(path))

    def test_raises_on_invalid_schema(self, tmp_path: pytest.TempPathFactory) -> None:
        """Valid YAML but invalid schema — non_negative on a string field."""
        yaml_content = """
name: bad_schema
fields:
  Name:
    type: string
    non_negative: true
"""
        path = tmp_path / "bad_schema.yaml"
        path.write_text(yaml_content)

        loader = YamlSchemaLoader()
        with pytest.raises(InvalidSchemaError, match="non_negative"):
            loader.load(str(path))

    def test_raises_on_empty_file(self, tmp_path: pytest.TempPathFactory) -> None:
        path = tmp_path / "empty.yaml"
        path.write_text("")

        loader = YamlSchemaLoader()
        with pytest.raises(InvalidSchemaError):
            loader.load(str(path))

    def test_raises_on_missing_name(self, tmp_path: pytest.TempPathFactory) -> None:
        yaml_content = """
fields:
  ID:
    type: string
"""
        path = tmp_path / "no_name.yaml"
        path.write_text(yaml_content)

        loader = YamlSchemaLoader()
        with pytest.raises(InvalidSchemaError):
            loader.load(str(path))

    def test_raises_on_comment_only_file(self, tmp_path: pytest.TempPathFactory) -> None:
        """A file with only YAML comments — yaml.safe_load returns None."""
        path = tmp_path / "comments.yaml"
        path.write_text("# just a comment\n# nothing else\n")

        loader = YamlSchemaLoader()
        with pytest.raises(InvalidSchemaError, match="mapping"):
            loader.load(str(path))

    def test_raises_on_yaml_list_instead_of_dict(self, tmp_path: pytest.TempPathFactory) -> None:
        """Valid YAML but a list, not a mapping."""
        path = tmp_path / "list.yaml"
        path.write_text("- item1\n- item2\n- item3\n")

        loader = YamlSchemaLoader()
        with pytest.raises(InvalidSchemaError, match="mapping"):
            loader.load(str(path))

    def test_ignores_unknown_top_level_fields(self, tmp_path: pytest.TempPathFactory) -> None:
        """Extra unknown fields in YAML should not cause failure —
        pydantic ignores them by default."""
        yaml_content = """
name: test_schema
fields:
  ID:
    type: string
extra_field: this_should_be_ignored
version: 99
"""
        path = tmp_path / "extra.yaml"
        path.write_text(yaml_content)

        loader = YamlSchemaLoader()
        schema = loader.load(str(path))
        assert schema.name == "test_schema"

    def test_raises_on_cross_field_rule_bad_reference(self, tmp_path: pytest.TempPathFactory) -> None:
        """Valid YAML, valid structure, but cross-field rule references
        a field that doesn't exist. Error message should propagate."""
        yaml_content = """
name: bad_rules
fields:
  Start:
    type: date
cross_field_rules:
  - earlier: Start
    later: NonexistentEnd
"""
        path = tmp_path / "bad_rule.yaml"
        path.write_text(yaml_content)

        loader = YamlSchemaLoader()
        with pytest.raises(InvalidSchemaError, match="NonexistentEnd"):
            loader.load(str(path))

    def test_unicode_field_names(self, tmp_path: pytest.TempPathFactory) -> None:
        """Non-ASCII field names should work — reinsurance data from
        non-English markets may use local field names."""
        yaml_content = """
name: unicode_schema
fields:
  Versicherungsnummer:
    type: string
    not_empty: true
  Prämie:
    type: float
    non_negative: true
"""
        path = tmp_path / "unicode.yaml"
        path.write_text(yaml_content, encoding="utf-8")

        loader = YamlSchemaLoader()
        schema = loader.load(str(path))
        assert "Versicherungsnummer" in schema.field_names
        assert "Prämie" in schema.field_names

    def test_raises_on_unreadable_file(self, tmp_path: pytest.TempPathFactory) -> None:
        """Permission denied should raise InvalidSchemaError."""
        import os

        path = tmp_path / "locked.yaml"
        path.write_text("name: test\nfields:\n  ID:\n    type: string\n")
        os.chmod(str(path), 0o000)

        loader = YamlSchemaLoader()
        try:
            with pytest.raises(InvalidSchemaError):
                loader.load(str(path))
        finally:
            os.chmod(str(path), 0o644)


class TestDefaultYamlFile:
    """schemas/default.yaml must load and match DEFAULT_TARGET_SCHEMA."""

    def test_default_yaml_loads(self) -> None:
        loader = YamlSchemaLoader()
        schema = loader.load("schemas/default.yaml")
        assert isinstance(schema, TargetSchema)

    def test_default_yaml_matches_python_constant(self) -> None:
        loader = YamlSchemaLoader()
        from_yaml = loader.load("schemas/default.yaml")
        assert from_yaml.field_names == DEFAULT_TARGET_SCHEMA.field_names
        assert from_yaml.required_field_names == DEFAULT_TARGET_SCHEMA.required_field_names
        assert from_yaml.fingerprint == DEFAULT_TARGET_SCHEMA.fingerprint

    def test_default_yaml_has_slm_hints(self) -> None:
        loader = YamlSchemaLoader()
        schema = loader.load("schemas/default.yaml")
        aliases = {h.source_alias for h in schema.slm_hints}
        assert aliases == {"GWP", "TSI", "Ccy", "Certificate"}
