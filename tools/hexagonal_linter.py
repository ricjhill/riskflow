"""AST-based hexagonal architecture linter.

Parses Python imports via the AST (not grep) to enforce the dependency
direction: domain ← ports ← adapters ← entrypoint.

Advantages over the bash grep approach:
- Ignores imports inside comments and strings
- Handles both `import X` and `from X import Y`
- Reports exact file:line for each violation
- Includes agent-readable FIX suggestions
- Can detect the layer from any path depth (src/domain/model/schema.py)

Run directly: python -m tools.hexagonal_linter
Or import: from tools.hexagonal_linter import check_file, main
"""

import ast
import sys
from pathlib import Path

# Layers and what each layer is allowed to import from (local src modules only).
# Stdlib and third-party imports are always allowed — this only governs
# imports from src.domain, src.ports, src.adapters, src.entrypoint.
LAYER_RULES: dict[str, set[str]] = {
    "domain": {"domain", "ports"},
    "ports": {"domain", "ports"},
    "adapters": {"domain", "ports", "adapters"},
    "entrypoint": {"domain", "ports", "adapters", "entrypoint"},
}

# The four local layers we check. Anything not in this set (stdlib,
# third-party) is always allowed.
LOCAL_LAYERS = {"domain", "ports", "adapters", "entrypoint"}

FIX_SUGGESTIONS: dict[str, str] = {
    "domain": (
        "FIX: domain/ may only import from domain/ and ports/. "
        "Define a Protocol in src/ports/output/ and have the adapter implement it."
    ),
    "ports": (
        "FIX: ports/ may only import from domain/ and ports/. "
        "Ports define interfaces — they must not reference implementations."
    ),
    "adapters": (
        "FIX: adapters/ may only import from domain/, ports/, and adapters/. "
        "Adapters are wired by entrypoint/, not the other way around."
    ),
}


def _detect_layer(path: Path) -> str | None:
    """Determine which architectural layer a file belongs to.

    Looks for 'domain', 'ports', 'adapters', or 'entrypoint' in the
    path parts. Returns None for files outside the hexagonal structure
    (e.g., tests, tools).
    """
    parts = path.parts
    for layer in LOCAL_LAYERS:
        if layer in parts:
            return layer
    return None


def _extract_local_layer(module: str) -> str | None:
    """Extract the local layer from an import module string.

    'src.adapters.http.routes' → 'adapters'
    'src.domain.model.schema' → 'domain'
    'pydantic' → None (not a local layer)
    'datetime' → None (not a local layer)
    """
    parts = module.split(".")
    # Handle 'src.X' prefix
    if len(parts) >= 2 and parts[0] == "src" and parts[1] in LOCAL_LAYERS:
        return parts[1]
    # Handle bare 'domain', 'ports', etc. (unlikely but defensive)
    if parts[0] in LOCAL_LAYERS:
        return parts[0]
    return None


def check_file(path: Path) -> list[str]:
    """Check a single Python file for hexagonal boundary violations.

    Returns a list of agent-readable error strings, empty if clean.
    """
    current_layer = _detect_layer(path)
    if current_layer is None:
        return []

    try:
        source = path.read_text()
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    allowed = LAYER_RULES[current_layer]
    errors: list[str] = []

    for node in ast.walk(tree):
        module: str | None = None
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                _check_import(module, current_layer, allowed, path, node.lineno, errors)
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            _check_import(module, current_layer, allowed, path, node.lineno, errors)

    return errors


def _check_import(
    module: str,
    current_layer: str,
    allowed: set[str],
    path: Path,
    lineno: int,
    errors: list[str],
) -> None:
    """Check if a single import violates the boundary rules."""
    imported_layer = _extract_local_layer(module)
    if imported_layer is None:
        return  # stdlib or third-party — always allowed

    if imported_layer not in allowed:
        fix = FIX_SUGGESTIONS.get(current_layer, "")
        errors.append(
            f"VIOLATION: Layer '{current_layer}' cannot import '{imported_layer}' "
            f"(from '{module}') in {path}:{lineno}. {fix}"
        )


def main(exit_on_error: bool = True) -> list[str]:
    """Scan all Python files in src/ for boundary violations.

    When exit_on_error is True (CLI usage), calls sys.exit(1) on violations.
    When False (test usage), returns the error list.
    """
    src_dir = Path("src")
    all_errors: list[str] = []

    for py_file in sorted(src_dir.rglob("*.py")):
        all_errors.extend(check_file(py_file))

    if all_errors:
        if exit_on_error:
            print("\n".join(all_errors), file=sys.stderr)
            print(
                f"\nTotal Architecture Violations: {len(all_errors)}",
                file=sys.stderr,
            )
            sys.exit(1)
    elif exit_on_error:
        print("Architecture Integrity: GREEN")

    return all_errors


if __name__ == "__main__":
    main()
