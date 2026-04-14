# RiskFlow Documentation

RiskFlow automates the mapping of messy reinsurance spreadsheets (Bordereaux) to a standardized schema. Upload a spreadsheet, and RiskFlow uses AI to figure out which columns map to which fields — then validates every row.

## What does RiskFlow do?

Reinsurance companies receive bordereaux spreadsheets from cedents (insurance companies). These spreadsheets have inconsistent column names — one cedent calls it "GWP", another calls it "Gross Written Premium", a third uses "Premium Amount". RiskFlow automatically maps these messy headers to your target schema and validates the data.

**Before RiskFlow:** Manual mapping by underwriters. Slow, error-prone, doesn't scale.
**After RiskFlow:** Upload the file, get mapped and validated data back in seconds.

---

## Documentation

### Tutorials — Learn by doing

Start here if you're new to RiskFlow.

- [Your First Upload](tutorials/first-upload.md) — Upload a bordereaux file and get mapped results in 5 minutes

### How-to Guides — Solve a specific problem

Step-by-step instructions for common tasks.

- [Use the GUI Dashboard](how-to/use-the-gui.md) — Upload, inspect, and correct via the Streamlit dashboard
- [Upload and Map a Spreadsheet](how-to/upload-and-map.md) — Map headers to the target schema via the API
- [Handle Multi-Sheet Excel Files](how-to/multi-sheet-excel.md) — Pick which sheet to process
- [Correct a Wrong Mapping](how-to/correct-mappings.md) — Override the AI when it gets a mapping wrong
- [Process Large Files Asynchronously](how-to/async-upload.md) — Upload without waiting for results
- [Use a Custom Schema](how-to/custom-schema.md) — Define your own target fields instead of the default 6
- [Configure Scaling](how-to/configure-scaling.md) — Set concurrency limits, choose job store, rollback
- [Debug with Logging](how-to/debug-with-logging.md) — Enable DEBUG logs, trace requests, diagnose bottlenecks

### Explanation — Understand how it works

Background and context for product owners and testers.

- [Features Overview](explanation/features.md) — What RiskFlow delivers and how each feature works
- [How Mapping Works](explanation/how-mapping-works.md) — The AI mapping pipeline from upload to validated output
- [Confidence Scores](explanation/confidence-scores.md) — What the numbers mean and when to trust them
- [The Correction Feedback Loop](explanation/corrections.md) — How human corrections improve future mappings
- [Scaling Architecture](explanation/scaling-architecture.md) — How RiskFlow handles 5 concurrent users

### Reference — Look up details

Complete specifications for developers and testers.

- [API Reference](reference/api.md) — All endpoints, parameters, request/response shapes, error codes
- [OpenAPI Specification](reference/openapi.md) — Machine-readable spec, code generation, CI enforcement
- [API Versioning](reference/versioning.md) — Semantic versioning, breaking change detection, GitHub releases
- [Target Schema](reference/schema.md) — Default schema fields, types, constraints, and how to create custom schemas
- [Error Codes](reference/errors.md) — Every error code, what triggers it, and what to do about it
- [Configuration](reference/configuration.md) — All environment variables with defaults and rollback values

### Engineering Sessions — How we built it

Session presentations documenting design decisions, lessons learned, and metrics.

- [Scaling, Observability & Quality (12-14 Apr)](presentations/2026-04-12-14-scaling-observability-quality.md) — 5-user scaling plan, confidence fix, harness improvements
- [Test Coverage Tracking (8 Apr)](presentations/2026-04-08-test-coverage-tracking.md) — Coverage measurement, PR traceability
- [Migration Cleanup (6 Apr)](presentations/2026-04-06-migration-cleanup-and-test-coverage.md) — RiskRecord removal, test gaps
- [OpenAPI & Versioning (4 Apr)](presentations/2026-04-04-openapi-spec-and-api-versioning.md) — Spec export, breaking change detection
- [Interactive Session API (2 Apr)](presentations/2026-04-02-interactive-session-api-and-harness-completion.md) — 5 REST endpoints, Flow Mapper
- [Harness Engineering (26 Mar)](presentations/2026-03-26-harness-engineering-part1.md) — Hooks, rules, agents, TDD workflow
