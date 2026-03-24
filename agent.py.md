# Agent Instructions — Python

Read this file alongside `agent.md`. This file defines Python-specific tooling,
folder structure, and conventions. The shared principles in `agent.md` take
precedence — this file extends them, it does not override them.

---

## Project
- Python version: 3.12+
- Dependency management: `uv` — do not use `pip` directly
- HTTP framework: FastAPI (specify alternative in TASK.md if needed)
- Database: PostgreSQL via `asyncpg` or `psycopg3`
- Logger: `structlog`
- Linter and formatter: `ruff`
- Type checker: `mypy`
- Test runner: `pytest`
- Config: `pyproject.toml` at repo root — do not modify linter or mypy settings

## Permissions
- Run any `uv`, `python`, or `pytest` command freely
- Edit any `.py` file
- Do not modify `uv.lock` manually

---

## Runtime
Virtual environment must be active before running any command.
```
uv venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows
uv sync
```

---

## Folder structure

```
src/
  main.py              # wire everything together, then start — nothing else
  domain/
    model/             # dataclasses and value objects — no I/O, no framework imports
    service/           # business logic operating on models
  ports/
    input.py           # Protocols the domain exposes (use cases)
    output.py          # Protocols the domain depends on (repos, queues, etc.)
  adapters/
    http/              # input adapters: FastAPI route handlers
    postgres/          # output adapters: database repository implementations
    queue/             # output adapters: SQS, Redis, etc.
  mocks/               # mock implementations of port Protocols for testing

tests/
  unit/                # domain and service tests — no I/O
  integration/         # adapter tests — marked with @pytest.mark.integration
```

---

## Baseline command
```
pytest -x -v tests/unit/
```

---

## TDD commands
- Confirm red: `pytest -x -v tests/unit/ 2>&1 | grep FAILED`
- Confirm green: `pytest -x -v tests/unit/`
- After green: `mypy src/` then `ruff check src/`

---

## Definition of done — Python commands
- [ ] `mypy src/`
- [ ] `pytest -x -v tests/unit/`
- [ ] `ruff check src/`
- [ ] `ruff format --check src/`

---

## Checkpointing — Python commands
Commit when all three pass:
```
mypy src/
pytest -x -v tests/unit/
ruff check src/
```

---

## Ports via Protocol
Use `typing.Protocol` for port interfaces — not abstract base classes.

```python
# correct
from typing import Protocol

class WebhookRepository(Protocol):
    async def save(self, webhook: Webhook) -> None: ...
    async def find_by_id(self, id: str) -> Webhook | None: ...

# wrong
from abc import ABC, abstractmethod

class WebhookRepository(ABC):
    @abstractmethod
    async def save(self, webhook: Webhook) -> None: ...
```

`Protocol` is structural — adapters implement the interface without inheriting
from it, which keeps adapters decoupled from the domain.

---

## Dependency inversion — Python example
```python
# correct — accept the Protocol (port)
def create_processor(repo: WebhookRepository) -> Processor:

# wrong — accept the concrete type
def create_processor(repo: PostgresRepository) -> Processor:
```

---

## Async
Decide per project: sync or async — do not mix within a service.
If async: use `asyncio` throughout. Do not use threads alongside async code.
If sync: keep it simple, no premature async.
The choice must be stated in TASK.md.

---

## Error handling
Define domain exceptions in `domain/model/errors.py`:
```python
class DomainError(Exception):
    """Base class for all domain errors."""

class NotFoundError(DomainError):
    pass

class InvalidInputError(DomainError):
    pass
```

Adapters map domain errors to protocol responses:
```python
except NotFoundError:
    raise HTTPException(status_code=404, detail="not found")
```

Never leak `asyncpg`, `psycopg3`, or other infrastructure exceptions into
the domain layer. Never swallow exceptions silently — if intentionally
ignored, comment why.

---

## Configuration
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    database_url: str
    queue_url: str
    port: int
```

Load from environment variables in `main.py` only using `os.environ` —
not `os.getenv` with a default (fail fast on missing values).
No environment variable reads inside domain, ports, or adapters.

```python
def load_config() -> Config:
    return Config(
        database_url=os.environ["DATABASE_URL"],  # KeyError if missing — intentional
        queue_url=os.environ["QUEUE_URL"],
        port=int(os.environ["PORT"]),
    )
```

---

## Logging
Logger: `structlog` only — do not use the stdlib `logging` module directly
or add `loguru` or similar.
Pass via dependency injection — never use a global logger.

```python
# correct
logger.info("webhook_processed", id=webhook.id, duration_ms=duration_ms)

# wrong
logger.info(f"webhook {webhook.id} processed in {duration_ms}ms")
```

Log at adapter boundaries. Domain logic raises exceptions — adapters log them.

---

## Testing
- Framework: `pytest`
- Mocks: `pytest-mock` (`mocker` fixture) — do not use `unittest.mock` directly
- Fixtures over setUp/tearDown
- Integration tests in `tests/integration/` marked with `@pytest.mark.integration`
- Run unit tests only by default: `pytest tests/unit/`
- Run integration tests explicitly: `pytest -m integration`
- Test file naming: `test_webhook_service.py` next to the module it tests

---

## Type hints
- All functions must have full parameter and return type annotations
- No `Any` unless absolutely unavoidable — comment why if used
- Prefer `X | None` over `Optional[X]` (Python 3.10+ syntax)
- Use `TypeAlias` for complex type aliases
- Run `mypy --strict src/` as part of Definition of Done

---

## Conventions
- Use `@dataclass(frozen=True)` for value objects and config
- Prefer plain functions over classes in domain logic
- Adapters may use classes when the framework requires it
- No mutable global state — inject all dependencies
- No `from module import *`
- File names: `snake_case.py`
- Class names: `PascalCase`
- Functions and variables: `snake_case`
- Run `ruff format src/` before finishing
- Do not add dependencies to `pyproject.toml` without recording in `DECISIONS.md`
