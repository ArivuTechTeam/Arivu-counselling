FROM python:3.12-slim

WORKDIR /app

# Install dependencies first, in their own layer, so `pip install` is only
# re-run when dependency inputs actually change (not on every code edit).
# requirements.lock pins and hashes the full Python 3.12/Linux dependency tree.
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY . .

# Same port uvicorn binds to in local dev (see .claude/CLAUDE.md /
# docs/deploy-runbook.md) — the host-side port is remapped in docker-compose,
# not here.
EXPOSE 8000

# Shell form (not exec/JSON-array form) so $PORT is expanded by the shell —
# Railway injects PORT at runtime and the container must bind to it.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log
