FROM ghcr.io/astral-sh/uv:0.13.6 AS uv
FROM python:3.12.16-slim-bookworm

COPY --from=uv /uv /bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
COPY contracts ./contracts
RUN uv sync --locked --no-dev --no-editable \
    && groupadd --gid 1000 workflow \
    && useradd --uid 1000 --gid 1000 --no-create-home workflow
USER 1000:1000
EXPOSE 8000
CMD ["uvicorn", "crm_workflow.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
