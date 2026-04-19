FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for Polars/Excel
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

RUN useradd --create-home --shell /bin/bash riskflow
USER riskflow

CMD ["uv", "run", "--no-dev", "uvicorn", "src.entrypoint.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
