FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ ./backend/
COPY knowledge_base/ ./knowledge_base/
COPY eval/ ./eval/

# Req 27.4/27.5: run as a dedicated non-root user rather than root. The
# directories the app writes to at runtime (/app/data, /app/logs) are
# chown'd to that user before the switch so reads/writes against them keep
# working without permission errors.
RUN groupadd --system app && useradd --system --gid app --home-dir /app --no-create-home app \
    && mkdir -p /app/data /app/logs \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
