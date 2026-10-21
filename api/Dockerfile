# Build context is the repo root (the API will import the patristica package).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

# Dependencies only, from the lock file, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev --extra api

COPY patristica ./patristica
COPY api ./api

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8000
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
