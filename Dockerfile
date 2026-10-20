# syntax=docker/dockerfile:1

# ---- builder: installs dependencies into an isolated venv ----
FROM python:3.12-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- runtime: only the prebuilt venv + the application code ----
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Non-root user: the home directory (used by pip at build time) stays in the
# builder, here we only need to run main.py with minimal permissions.
RUN useradd --create-home --uid 1000 clepshydra

COPY . .
RUN mkdir -p data && chown -R clepshydra:clepshydra /app

USER clepshydra

CMD ["python", "main.py"]
