"""Export the FastAPI app's OpenAPI schema to openapi.json.

Usage:
    uv run python -m tools.export_openapi [output_path]

The script ensures null adapters are used (no Redis or Groq required)
by clearing REDIS_URL before importing the app.
"""

import json
import os
import sys


def main(output_path: str = "openapi.json") -> None:
    """Generate the OpenAPI spec and write it to *output_path*."""
    # Ensure null adapters — no live Redis or Groq needed.
    os.environ.pop("REDIS_URL", None)

    from src.entrypoint.main import create_app

    app = create_app()
    spec = app.openapi()

    with open(output_path, "w") as f:
        json.dump(spec, f, indent=2)

    endpoint_count = sum(len(methods) for methods in spec.get("paths", {}).values())
    print(f"Exported {len(spec['paths'])} paths ({endpoint_count} operations) to {output_path}")


if __name__ == "__main__":
    dest = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
    main(dest)
