"""Tests that every third-party import in src/ is a declared runtime dependency.

Catches the exact class of bug that caused two production failures:
python-dateutil and pyyaml were imported in src/ but only installed as
transitive deps of streamlit (a dev dep). The production container
(uv sync --no-dev) crashed with ModuleNotFoundError.

This test scans all .py files under src/, extracts top-level imports,
maps them to PyPI package names, and verifies each one appears in
pyproject.toml [project].dependencies.
"""

import ast
from pathlib import Path

import pytest

# --- Import name → PyPI package name mapping ---
# Most packages use the same name for import and PyPI, but some don't.
# This map covers the known mismatches in this project.
IMPORT_TO_PACKAGE: dict[str, str] = {
    "yaml": "pyyaml",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "uvicorn": "uvicorn",
    "redis": "redis",
    "openai": "openai",
    "polars": "polars",
    "structlog": "structlog",
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "openpyxl": "openpyxl",
    "fastexcel": "fastexcel",
    "pydantic_settings": "pydantic-settings",
}

# Standard library modules — never need to be declared
STDLIB_MODULES: set[str] = {
    "abc",
    "ast",
    "asyncio",
    "collections",
    "concurrent",
    "contextlib",
    "copy",
    "csv",
    "dataclasses",
    "datetime",
    "enum",
    "functools",
    "hashlib",
    "importlib",
    "io",
    "json",
    "logging",
    "math",
    "os",
    "pathlib",
    "re",
    "shutil",
    "sys",
    "tempfile",
    "threading",
    "time",
    "tracemalloc",
    "typing",
    "unittest",
    "uuid",
    "gc",
    "glob",
    "resource",
    "socket",
    "subprocess",
    "signal",
    "http",
    "urllib",
}

# Internal project imports — not third-party
INTERNAL_PREFIXES: tuple[str, ...] = ("src.",)

SRC_DIR = Path(__file__).parent.parent.parent / "src"
PYPROJECT = Path(__file__).parent.parent.parent / "pyproject.toml"


def _parse_package_name(dep_str: str) -> str:
    """Extract the bare package name from a PEP 508 dependency string.

    Handles: version specifiers (>=, ==, <, !=, ~=), extras ([security]),
    and environment markers (; python_version>="3.10").
    """
    import re

    # Strip environment markers first: "package; python_version>='3.10'" → "package"
    name = dep_str.split(";")[0].strip()
    # Strip extras: "requests[security]" → "requests"
    name = re.split(r"\[", name)[0]
    # Strip version specifiers: "fastapi>=0.135.2" → "fastapi"
    name = re.split(r"[><=!~]", name)[0].strip()
    return name


def _get_runtime_deps() -> set[str]:
    """Extract package names from [project].dependencies in pyproject.toml."""
    import tomllib

    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)

    deps: set[str] = set()
    for dep_str in data.get("project", {}).get("dependencies", []):
        name = _parse_package_name(dep_str)
        deps.add(name.lower())
    return deps


def _get_third_party_imports() -> set[str]:
    """Scan all .py files in src/ and extract third-party top-level import names."""
    third_party: set[str] = set()

    for py_file in SRC_DIR.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level = alias.name.split(".")[0]
                    if top_level not in STDLIB_MODULES and not any(
                        alias.name.startswith(p) for p in INTERNAL_PREFIXES
                    ):
                        third_party.add(top_level)
            elif isinstance(node, ast.ImportFrom):
                if node.module and not any(node.module.startswith(p) for p in INTERNAL_PREFIXES):
                    top_level = node.module.split(".")[0]
                    if top_level not in STDLIB_MODULES:
                        third_party.add(top_level)

    return third_party


def _resolve_package_name(import_name: str) -> str:
    """Map a Python import name to its PyPI package name."""
    return IMPORT_TO_PACKAGE.get(import_name, import_name)


class TestRuntimeDependenciesComplete:
    """Every third-party import in src/ must be a declared runtime dependency."""

    def test_all_imports_have_runtime_deps(self) -> None:
        """Scan src/ imports and verify each maps to a [project].dependencies entry."""
        runtime_deps = _get_runtime_deps()
        third_party_imports = _get_third_party_imports()

        missing: list[str] = []
        for import_name in sorted(third_party_imports):
            package_name = _resolve_package_name(import_name)
            if package_name.lower() not in runtime_deps:
                missing.append(
                    f"  import '{import_name}' → package '{package_name}' "
                    f"not in [project].dependencies"
                )

        assert not missing, (
            "Third-party imports in src/ missing from runtime dependencies:\n"
            + "\n".join(missing)
            + "\n\nFix: uv add <package> (adds to [project].dependencies)"
        )

    def test_known_problematic_packages_declared(self) -> None:
        """Explicit check for packages that previously caused production failures."""
        runtime_deps = _get_runtime_deps()

        for package in ["python-dateutil", "pyyaml"]:
            assert package in runtime_deps, (
                f"'{package}' must be in [project].dependencies — "
                f"previously caused ModuleNotFoundError in production container"
            )

    @pytest.mark.parametrize(
        "import_name, expected_package",
        [
            ("yaml", "pyyaml"),
            ("dateutil", "python-dateutil"),
            ("dotenv", "python-dotenv"),
            ("pydantic_settings", "pydantic-settings"),
        ],
        ids=[
            "yaml→pyyaml",
            "dateutil→python-dateutil",
            "dotenv→python-dotenv",
            "pydantic_settings→pydantic-settings",
        ],
    )
    def test_import_to_package_mapping(self, import_name: str, expected_package: str) -> None:
        """Verify the import→package name mapping handles known mismatches."""
        assert _resolve_package_name(import_name) == expected_package

    def test_stdlib_not_flagged(self) -> None:
        """Standard library modules should not appear in third-party imports."""
        third_party = _get_third_party_imports()
        stdlib_leaked = third_party & STDLIB_MODULES
        assert not stdlib_leaked, (
            f"Standard library modules incorrectly classified as third-party: {stdlib_leaked}"
        )

    def test_internal_imports_not_flagged(self) -> None:
        """src.* imports should not appear in third-party imports."""
        third_party = _get_third_party_imports()
        internal_leaked = {
            i for i in third_party if any(i.startswith(p.rstrip(".")) for p in INTERNAL_PREFIXES)
        }
        assert not internal_leaked, (
            f"Internal imports incorrectly classified as third-party: {internal_leaked}"
        )

    @pytest.mark.parametrize(
        "dep_str, expected",
        [
            ("fastapi>=0.135.2", "fastapi"),
            ("pydantic==2.12.5", "pydantic"),
            ("numpy<2.0", "numpy"),
            ("numpy~=1.24.0", "numpy"),
            ("numpy!=1.24.0", "numpy"),
            ("requests[security]>=1.0", "requests"),
            ('package; python_version>="3.10"', "package"),
            ("some-package[extra1,extra2]>=1.0,<2.0", "some-package"),
        ],
        ids=[
            ">=",
            "==",
            "<",
            "~=",
            "!=",
            "extras",
            "marker",
            "multiple-extras-and-bounds",
        ],
    )
    def test_parse_package_name(self, dep_str: str, expected: str) -> None:
        """Verify the dependency string parser handles all PEP 508 forms."""
        assert _parse_package_name(dep_str) == expected
