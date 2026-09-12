FROM python:3.12-slim

WORKDIR /app

# Install dependencies first, in their own layer, so `pip install` is only
# re-run when requirements.txt actually changes (not on every code edit).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Same port uvicorn binds to in local dev (see .claude/CLAUDE.md /
# docs/deploy-runbook.md) — the host-side port is remapped in docker-compose,
# not here.
EXPOSE 8000

# Shell form (not exec/JSON-array form) so $PORT is expanded by the shell —
# Railway injects PORT at runtime and the container must bind to it.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log
