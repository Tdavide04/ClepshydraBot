# ClepshydraBot — Resoconto Tecnico

**Versione documento 2.0 — Settembre 2026**
**Autore: tdavide — Confidenziale**

Scheda di riferimento sintetica su dove e come gira il bot in produzione. Per architettura, funzionalità,
comandi, cache e roadmap operativa, vedi la [Documentazione Correlata](#documentazione-correlata) in
fondo: questo documento non li ripete.

---

## 1. Istanza di Produzione

| Campo | Valore |
|---|---|
| Provider | Oracle Cloud Infrastructure — Free Tier |
| Regione | eu-milan-1 (AD-1, Fault Domain: FD-2) — Milano, Italia |
| OCID Istanza | `ocid1.instance.oc1.eu-milan-1.anwgsljrtzu6yzqc...` |
| Data di avvio | 4 Maggio 2026, 20:29:36 UTC |
| IP Pubblico | 80.225.91.142 |
| Username SSH | ubuntu |
| Accesso | SSH con chiave privata |
| Process Manager | `pm2` — riavvio automatico del bot in caso di crash |

## 2. Specifiche Hardware

| Specifica | Valore |
|---|---|
| Shape | VM.Standard.E2.1.Micro |
| OCPU | 1 (non ridimensionabile) |
| RAM | 1 GB |
| Rete | 0.5 Gbps |
| Storage | Block Storage only (nessun disco locale) |
| Crittografia | In-transit encryption abilitata |
| Firmware | UEFI_64 |
| Launch Mode | PARAVIRTUALIZED |

## 3. Sistema Operativo

| Specifica | Valore |
|---|---|
| OS | Canonical Ubuntu 24.04 LTS |
| Immagine | Canonical-Ubuntu-24.04-2026.03.31-0 |
| Secure Boot | Disabilitato |
| Measured Boot | Disabilitato |
| TPM | Disabilitato |
| IMDS | Version 2 only |

## 4. Stack Tecnologico

### 4.1 Dipendenze Python (`requirements.txt`, produzione)

| Libreria | Ruolo |
|---|---|
| `discord.py` | Integrazione API Discord: slash command, modal, select menu, eventi, cog |
| `aiohttp` | Client HTTP asincrono per Scryfall (retry + rate limiting) |
| `Pillow (PIL)` | Generazione immagini deck showcase |
| `python-dotenv` | Caricamento `.env` |
| `SQLAlchemy[asyncio]` | ORM asincrono |
| `aiosqlite` | Driver asincrono SQLite |

`requirements-dev.txt` aggiunge `pytest` e `ruff` per sviluppo/CI.

### 4.2 Servizi Esterni

| Servizio | Utilizzo |
|---|---|
| Discord API | Gateway WebSocket (eventi) + REST (messaggi, embed, file) |
| Scryfall API | `POST /cards/collection` (fetch batch), `GET prints_search_uri` (legalità Arena) |

### 4.3 Versioni

| Componente | Versione |
|---|---|
| Python | 3.12+ |
| discord.py | Latest stable |
| Bot | vedi `CHANGELOG.md` per la versione corrente |

## 5. Vincolo di Risorse

Con 1 OCPU e 1 GB RAM (non ridimensionabile su Free Tier), il bot è progettato per minimizzare il
consumo di memoria e CPU. Questo vincolo ha guidato scelte architetturali chiave: SQLite invece di
PostgreSQL, cache su file JSON invece di Redis, un solo processo (nessun worker separato). Il dettaglio
di queste scelte e i relativi trade-off sono tracciati in `docs/infrastruttura.md` (sezione "Vincoli") e
nella roadmap dei miglioramenti.

---

## Documentazione Correlata

| Argomento | Documento |
|---|---|
| Deployment, variabili d'ambiente, logging, dipendenze, CI | `docs/infrastruttura.md` |
| Architettura a layer (cogs/services/repositories/database) | `docs/architettura.md` |
| Comandi slash e permessi | `docs/comandi.md` |
| Schema database e migrazioni | `docs/database.md` |
| Sistema di cache (Scryfall, override rarità, banlist) | `docs/caching.md` |
| Validazione mazzi Artisan | `docs/deck-validation.md` |
| Sistema banlist | `docs/banlist-system.md` |
| Sistema presentazioni | `docs/presentazioni.md` |
| Sistema tornei Swiss | `docs/tornei.md` |
| Debito tecnico e piano di miglioramento | `docs/roadmap-miglioramenti.md` |
| Guida per Claude Code | `CLAUDE.md` |
