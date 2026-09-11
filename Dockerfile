# syntax=docker/dockerfile:1

# ---- builder: installa le dipendenze in un venv isolato ----
FROM python:3.12-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- runtime: solo il venv gia' pronto + il codice applicativo ----
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Utente non-root: la home (usata da pip in fase di build) resta nel builder,
# qui serve solo eseguire main.py con permessi minimi.
RUN useradd --create-home --uid 1000 clepshydra

COPY . .
RUN mkdir -p data && chown -R clepshydra:clepshydra /app

USER clepshydra

CMD ["python", "main.py"]
