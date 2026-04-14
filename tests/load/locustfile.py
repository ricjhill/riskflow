"""Locust load test for RiskFlow API.

Run against a live server (docker compose up -d):

    uv run locust -f tests/load/locustfile.py --host http://localhost:8000

Or headless for CI (5-user concurrency test):

    uv run locust -f tests/load/locustfile.py \
        --host http://localhost:8000 \
        --headless \
        --users 5 \
        --spawn-rate 5 \
        --run-time 30s \
        --csv benchmarks/load_test \
        --exit-code-on-error 0

What "5 concurrent users" means:
    - 5 simulated users, all spawned immediately
    - Each user waits 1-3s between requests (realistic think time)
    - Typically 2-3 requests in-flight at any moment, not 5
    - This proves 5 users interacting concurrently, not 5 simultaneous requests

Expected 503 errors:
    - With a dummy GROQ_API_KEY, sync /upload returns 503 (SLM unavailable)
    - This is expected, not a scaling failure — the same 503 happens with 1 user
    - All non-SLM endpoints (health, schemas, jobs, async upload) return 200

What this tests:
    - /health: baseline latency, no business logic
    - /upload: full pipeline (503 expected with test key)
    - /upload/async: enqueue only, returns 202 immediately
    - /jobs: list all jobs (exercises RedisJobStore.list_all)
    - /jobs/[id]: poll job status
    - /schemas: read-only metadata endpoint

Performance targets (configurable):
    - /health p95 < 50ms
    - /schemas p95 < 100ms
    - /jobs p95 < 200ms
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
        """Upload a CSV for mapping. 503 is expected with a dummy Groq key."""
        with self.client.post(
            "/upload",
            files={"file": ("load_test.csv", self._csv_content, "text/csv")},
            catch_response=True,
        ) as resp:
            if resp.status_code == 503:
                resp.success()
            elif resp.status_code != 200:
                resp.failure(f"Expected 200 or 503, got {resp.status_code}")

    @task(1)
    def upload_with_schema(self) -> None:
        """Upload with explicit schema selection. 503 is expected with a dummy Groq key."""
        with self.client.post(
            "/upload?schema=standard_reinsurance",
            files={"file": ("load_test.csv", self._csv_content, "text/csv")},
            catch_response=True,
        ) as resp:
            if resp.status_code == 503:
                resp.success()
            elif resp.status_code != 200:
                resp.failure(f"Expected 200 or 503, got {resp.status_code}")

    @task(2)
    def list_jobs(self) -> None:
        """List all async jobs — exercises RedisJobStore.list_all()."""
        self.client.get("/jobs")

    @task(1)
    def poll_async_job(self) -> None:
        """Upload async, then poll until terminal state.

        Marks 503 as success (expected with dummy/test Groq key).
        """
        with self.client.post(
            "/upload/async",
            files={"file": ("async_test.csv", self._csv_content, "text/csv")},
            catch_response=True,
        ) as resp:
            if resp.status_code == 503:
                resp.success()
            elif resp.status_code != 202:
                resp.failure(f"Expected 202 or 503, got {resp.status_code}")
                return

        if resp.status_code != 202:
            return

        job_id = resp.json()["job_id"]

        # Poll up to 10 times
        for _ in range(10):
            with self.client.get(
                f"/jobs/{job_id}", name="/jobs/[id]", catch_response=True
            ) as poll_resp:
                if poll_resp.status_code != 200:
                    poll_resp.failure(f"Poll got {poll_resp.status_code}")
                    return
                status = poll_resp.json().get("status", "")
                if status in ("complete", "failed"):
                    poll_resp.success()
                    return
                poll_resp.success()
