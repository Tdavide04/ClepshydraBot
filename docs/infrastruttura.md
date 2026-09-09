# Infrastruttura

## Panoramica

ClepshydraBot è ospitato su **Oracle Cloud Infrastructure (OCI) Free Tier** in esecuzione su una VM `VM.Standard.E2.1.Micro` con 1 GB RAM.

---

## Specifiche VM

| Parametro | Valore |
|---|---|
| Provider | OCI Free Tier |
| Shape | VM.Standard.E2.1.Micro |
| Regione | eu-milan-1 (Milano) |
| OCPU | 1 (ARM, non ridimensionabile) |
| RAM | 1 GB |
| Rete | 0.5 Gbps |
| Storage | Block Storage |
| OS | Ubuntu 24.04 LTS |
| IP Pubblico | 80.225.91.142 |

### Vincoli

1 GB RAM ha guidato scelte architetturali chiave:
- **SQLite** invece di PostgreSQL (nessun processo DB separato)
- **Cache JSON** invece di Redis (nessun servizio in-memory esterno)
- **Scritture atomiche** su file invece di journal WAL pesante

---

## Configurazione Ambiente (`config/config.py`)

### Variabili d'Ambiente

Caricate da `.env` tramite `python-dotenv`:

| Variabile | Descrizione | Test Mode |
|---|---|---|
| `DISCORD_TOKEN` | Token bot produzione | `DISCORD_TOKEN_TEST` |
| `GUILD_ID` | Server Discord | `GUILD_ID_TEST` |
| `PRESENTATION_CHANNEL_ID` | Canale presentazioni | `*_TEST` |
| `TOURNAMENT_CHANNEL_ID` | Canale torneo | `*_TEST` |
| `PUBLIC_DECK_CHANNEL_ID` | Canale deck pubblici | `*_TEST` |
| `LOG_CHANNEL_ID` | Canale logging | `*_TEST` |
| `INITIAL_ROLE` | Ruolo iniziale (default: Viandante) | stessi |
| `FINAL_ROLE` | Ruolo verificato (default: Planeswalker) | stessi |
| `ADMIN_ROLE` | Ruolo admin (default: Staff) | stessi |
| `DB_PATH` | Percorso DB (default: `data/clepsydra.db`) | suffisso `_test.db` |
| `TEST_MODE` | Flag test | — |
| `VERSION` | Versione bot | append `-test` |

### Test Mode

`TEST_MODE` cambia:
- Token Discord (produzione vs test)
- Server Discord (guild ID)
- Canali di destinazione
- Database (`clepsydra.db` → `clepsydra_test.db`)

---

## Deployment

### Avvio Manuale (attuale)

```bash
source .venv/bin/activate
python main.py
```

Processo gestito via `screen` o `tmux`.

### Avvio con systemd (consigliato)

Il unit file e' disponibile in `deploy/clepshydrabot.service` (da copiare in `/etc/systemd/system/`):

```
[Unit]
Description=ClepshydraBot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/clepsydrabot
EnvironmentFile=/opt/clepsydrabot/.env
ExecStart=/opt/clepsydrabot/.venv/bin/python main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

`main.py` intercetta `discord.LoginFailure` e altre eccezioni di startup, esce con codice non-zero e stampa un errore esplicito su stderr — visibile in `journalctl -u clepshydrabot` e necessario perche' `Restart=on-failure` scatti in modo affidabile.

---

## Dipendenze (`requirements.txt`)

```
discord.py
python-dotenv
aiohttp
Pillow
sqlalchemy[asyncio]
aiosqlite
```

Installazione (produzione):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Installazione (sviluppo, aggiunge `pytest` e `ruff`):

```bash
pip install -r requirements-dev.txt
```

---

## Logging

### Sistema di Log (`cogs/logger.py`)

Tutti gli eventi vengono loggati su un canale Discord dedicato tramite embed:

| Livello | Colore | Eventi |
|---|---|---|
| `INFO` | Verde | Operazioni completate (presentazioni, verifiche ok, torneo creato) |
| `WARN` | Giallo | Validazioni fallite, carte bannate, campi non validi |
| `ERROR` | Rosso | Eccezioni non gestite, errori Scryfall, problemi DB |
| `DEBUG` | Grigio | Startup, migrazioni, sync comandi |

### Log su Console

Oltre al canale Discord, il bot scrive log su stdout/stderr per debug via SSH. I fallimenti di avvio (token invalido, eccezioni non gestite in `setup_hook`) vengono sempre scritti su stderr con prefisso `FATAL:`, anche quando il canale Discord di log non e' raggiungibile.

---

## Roadmap Infrastrutturale

### Sprint 7 — Docker (da fare)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

`docker-compose.yml` con:
- Volume persistente per `data/`
- `restart: unless-stopped`
- Bind mount per `.env`

### Sprint 8 — CI/CD (parziale)

`.github/workflows/ci.yml`, attivo su push/PR:
- `pytest` su ogni push e PR — **gate bloccante**
- `ruff` lint (`ruff.toml`, regole minime `E4,E7,E9,F`) — **step informativo**, non bloccante: il codebase ha debito di lint pre-esistente non ancora sanato

Ancora da fare:
- `build` check Docker (dipende dal completamento dello Sprint 7)
- Deploy automatico su OCI via SSH/deploy key
