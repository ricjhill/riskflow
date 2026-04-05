"""Tests for the hexagonal architecture linter.

Verifies that the AST-based linter catches boundary violations
and produces agent-readable error messages with fix suggestions.
"""

from pathlib import Path


from tools.hexagonal_linter import check_file


class TestLayerDetection:
    """Linter must correctly identify which layer a file belongs to."""

    def test_domain_model_file(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "domain" / "model" / "schema.py"
        f.parent.mkdir(parents=True)
        f.write_text("x = 1\n")
        errors = check_file(f)
        assert errors == []

    def test_adapter_file(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "adapters" / "http" / "routes.py"
        f.parent.mkdir(parents=True)
        f.write_text("x = 1\n")
        errors = check_file(f)
        assert errors == []

    def test_non_src_file_ignored(self, tmp_path: Path) -> None:
        f = tmp_path / "tests" / "test_something.py"
        f.parent.mkdir(parents=True)
        f.write_text("from src.adapters import foo\n")
        errors = check_file(f)
        assert errors == []


class TestBoundaryViolations:
    """Core rule: dependencies only point inward."""

    def test_domain_importing_adapters(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "domain" / "model" / "bad.py"
        f.parent.mkdir(parents=True)
        f.write_text("from src.adapters.storage.cache import RedisCache\n")
        errors = check_file(f)
        assert len(errors) == 1
        assert "domain" in errors[0]
        assert "adapters" in errors[0]

    def test_domain_importing_entrypoint(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "domain" / "service" / "bad.py"
        f.parent.mkdir(parents=True)
        f.write_text("from src.entrypoint.main import create_app\n")
        errors = check_file(f)
        assert len(errors) == 1
        assert "entrypoint" in errors[0]

    def test_ports_importing_adapters(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "ports" / "output" / "bad.py"
        f.parent.mkdir(parents=True)
        f.write_text("from src.adapters.slm.mapper import GroqMapper\n")
        errors = check_file(f)
        assert len(errors) == 1

    def test_adapters_importing_entrypoint(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "adapters" / "http" / "bad.py"
        f.parent.mkdir(parents=True)
        f.write_text("from src.entrypoint.main import create_app\n")
        errors = check_file(f)
        assert len(errors) == 1


class TestAllowedImports:
    """Valid imports must not trigger violations."""

    def test_domain_importing_domain(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "domain" / "service" / "ok.py"
        f.parent.mkdir(parents=True)
        f.write_text("from src.domain.model.schema import ColumnMapping\n")
        errors = check_file(f)
        assert errors == []

    def test_domain_importing_ports(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "domain" / "service" / "ok.py"
        f.parent.mkdir(parents=True)
        f.write_text("from src.ports.output.repo import CachePort\n")
        errors = check_file(f)
        assert errors == []

    def test_adapters_importing_domain(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "adapters" / "slm" / "ok.py"
        f.parent.mkdir(parents=True)
        f.write_text("from src.domain.model.schema import MappingResult\n")
        errors = check_file(f)
        assert errors == []

    def test_adapters_importing_ports(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "adapters" / "http" / "ok.py"
        f.parent.mkdir(parents=True)
        f.write_text("from src.ports.output.mapper import MapperPort\n")
        errors = check_file(f)
        assert errors == []

    def test_entrypoint_importing_everything(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "entrypoint" / "ok.py"
        f.parent.mkdir(parents=True)
        f.write_text(
            "from src.domain.model.schema import ColumnMapping\n"
            "from src.ports.output.repo import CachePort\n"
            "from src.adapters.storage.cache import RedisCache\n"
        )
        errors = check_file(f)
        assert errors == []

    def test_stdlib_imports_always_allowed(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "domain" / "model" / "ok.py"
        f.parent.mkdir(parents=True)
        f.write_text(
            "import datetime\n"
            "import hashlib\n"
            "import json\n"
            "import enum\n"
            "import functools\n"
            "from typing import Any, Protocol\n"
        )
        errors = check_file(f)
        assert errors == []

    def test_third_party_imports_allowed(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "domain" / "model" / "ok.py"
        f.parent.mkdir(parents=True)
        f.write_text("from pydantic import BaseModel\nimport structlog\n")
        errors = check_file(f)
        assert errors == []


class TestErrorMessages:
    """Error messages must be agent-readable with fix suggestions."""

    def test_includes_file_and_line(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "domain" / "model" / "bad.py"
        f.parent.mkdir(parents=True)
        f.write_text("x = 1\nfrom src.adapters.http import routes\n")
        errors = check_file(f)
        assert ":2" in errors[0]  # line 2

    def test_includes_fix_suggestion(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "domain" / "model" / "bad.py"
        f.parent.mkdir(parents=True)
        f.write_text("from src.adapters.storage.cache import RedisCache\n")
        errors = check_file(f)
        assert "FIX:" in errors[0]


class TestMultipleViolations:
    """A file with multiple violations should report all of them."""

    def test_reports_all_violations(self, tmp_path: Path) -> None:
        f = tmp_path / "src" / "domain" / "model" / "bad.py"
        f.parent.mkdir(parents=True)
        f.write_text(
            "from src.adapters.http import routes\nfrom src.entrypoint.main import create_app\n"
        )
        errors = check_file(f)
        assert len(errors) == 2


class TestRealCodebase:
    """Run the linter against the actual src/ directory."""

    def test_no_violations_in_codebase(self) -> None:
        from tools.hexagonal_linter import main

        # main() calls sys.exit(1) on violations, so if this doesn't
        # raise, the codebase is clean
        errors = main(exit_on_error=False)
        assert errors == [], f"Found violations:\n" + "\n".join(errors)
