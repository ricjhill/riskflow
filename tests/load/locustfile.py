"""Locust load test for RiskFlow API.

Run against a live server (docker compose up -d):

    uv run locust -f tests/load/locustfile.py --host http://localhost:8000

Or headless for CI:

    uv run locust -f tests/load/locustfile.py \
        --host http://localhost:8000 \
        --headless \
        --users 10 \
        --spawn-rate 2 \
        --run-time 30s \
        --csv benchmarks/load_test

The --csv flag writes results to benchmarks/load_test_stats.csv for tracking.

What this tests:
    - /health: baseline latency, no business logic
    - /upload: full pipeline latency under concurrency
    - /schemas: read-only metadata endpoint

Performance targets (configurable):
    - /health p95 < 50ms
    - /upload p95 < 5000ms (includes SLM call)
    - /schemas p95 < 100ms
"""

import csv
import io

from locust import HttpUser, between, task


class RiskFlowUser(HttpUser):
    """Simulates a user interacting with the RiskFlow API."""

    wait_time = between(1, 3)

    def on_start(self) -> None:
        """Create a sample CSV file for upload tests."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Policy No.", "Start Date", "End Date", "TSI", "GWP", "Ccy"])
        for i in range(50):
            writer.writerow(
                [
                    f"POL-{i:04d}",
                    "2025-01-01",
                    "2025-12-31",
                    100000 + i * 1000,
                    5000 + i * 100,
                    "USD",
                ]
            )
        self._csv_content = output.getvalue().encode()

    @task(5)
    def health_check(self) -> None:
        """High-frequency health check — baseline latency measurement."""
        self.client.get("/health")

    @task(2)
    def list_schemas(self) -> None:
        """List available schemas."""
        self.client.get("/schemas")

    @task(1)
    def upload_file(self) -> None:
        """Upload a CSV for mapping — the critical path."""
        self.client.post(
            "/upload",
            files={"file": ("load_test.csv", self._csv_content, "text/csv")},
        )

    @task(1)
    def upload_with_schema(self) -> None:
        """Upload with explicit schema selection."""
        self.client.post(
            "/upload?schema=standard_reinsurance",
            files={"file": ("load_test.csv", self._csv_content, "text/csv")},
        )
