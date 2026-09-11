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

`VERSION` **non** è una variabile d'ambiente: è una costante hardcoded in `config/config.py` (append
`-test` se `TEST_MODE`), aggiornata a mano ad ogni release insieme a `CHANGELOG.md` — vedi la nota
"Versioning" in cima a quel file per la convenzione (MINOR per feature, PATCH per fix).

### Test Mode

`TEST_MODE` cambia:
- Token Discord (produzione vs test)
- Server Discord (guild ID)
- Canali di destinazione
- Database (`clepsydra.db` → `clepsydra_test.db`)

---

## Deployment

### Avvio con pm2 (attuale)

```bash
source .venv/bin/activate
pm2 start main.py --name clepshydrabot --interpreter .venv/bin/python
```

`pm2` gestisce il processo e lo riavvia automaticamente in caso di crash. Comandi utili:

```bash
pm2 status              # stato del processo
pm2 logs clepshydrabot  # log in tempo reale
pm2 restart clepshydrabot
pm2 save                # persiste la process list
pm2 startup             # riavvia pm2 (e i processi salvati) al boot della VM
```

`main.py` intercetta `discord.LoginFailure` e altre eccezioni di startup, esce con codice non-zero e
stampa un errore esplicito su stderr — visibile in `pm2 logs clepshydrabot`. Da notare: se il token è
genuinamente scaduto/invalido, `pm2` riavvierà comunque il processo (`Restart=on-failure`-style), che
fallirà di nuovo allo stesso modo finché non si aggiorna manualmente il token — il riavvio automatico
non "risolve" un problema di credenziali, dà solo visibilità continua nei log.

### Avvio con systemd (alternativa non in uso)

Il unit file e' disponibile in `deploy/clepshydrabot.service` (da copiare in `/etc/systemd/system/`),
mantenuto come alternativa nel repository ma non installato sulla VM di produzione (dove si usa `pm2`):

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

Con systemd, lo stesso comportamento di `main.py` (uscita non-zero su errori di startup) sarebbe visibile in `journalctl -u clepshydrabot` invece che in `pm2 logs`.

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

`pytest.ini` (`pythonpath = .`) aggiunge esplicitamente la root del repo a `sys.path`: senza, l'invocazione nuda `pytest tests/` (usata dalla CI, a differenza di `python -m pytest` che aggiunge la cwd automaticamente) fallisce con `ModuleNotFoundError` sui moduli di primo livello (`services`, `database`, `utils`), perché non esiste un `tests/__init__.py` a catena fino alla root.

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

### Sprint 7 — Docker (completato)

`Dockerfile` multi-stage: uno stage `builder` installa le dipendenze in un venv isolato
(`/opt/venv`), lo stage finale copia solo il venv già pronto + il codice applicativo, gira come utente
non-root (`clepshydra`, uid 1000). `.dockerignore` esclude `.git`, `data/` (mai bakato nell'immagine —
contiene solo dati runtime/cache, ricreato a ogni avvio dal volume), `.env` (mai nell'immagine, iniettato
a runtime), test/docs/legacy.

`docker-compose.yml`:
- `restart: unless-stopped`
- `env_file: .env` (letto dall'host all'avvio, non copiato nell'immagine)
- volume Docker nominato `clepshydra-data` montato su `/app/data` — persiste tra i riavvii del container

```bash
docker compose up -d --build   # build + avvio
docker compose logs -f bot     # log in tempo reale
docker compose down            # ferma (il volume dati resta)
```

Questa è un'opzione di deployment **aggiuntiva**, non sostituisce `pm2` (sezione "Deployment" sopra),
che resta il metodo effettivamente in uso in produzione finché non si decide di migrare.

### Sprint 8 — CI/CD (completato)

`.github/workflows/ci.yml`, attivo su push/PR:
- `pytest` su ogni push e PR — **gate bloccante**
- `ruff` lint (`ruff.toml`, regole minime `E4,E7,E9,F`, `legacy/` escluso — vedi CLAUDE.md "Legacy code") —
  **gate bloccante**: il debito di lint pre-esistente (~54 problemi) è stato sanato nello Step 8 di
  `docs/roadmap-miglioramenti.md`

Ancora da fare:
- `build` check Docker in CI (verifica che l'immagine si costruisca ad ogni push, senza deploy)
- Deploy automatico su OCI via SSH/deploy key
