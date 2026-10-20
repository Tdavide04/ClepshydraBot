# ADR-0002 — Standard di sviluppo: TDD, Conventional Commits, gate automatici

**Stato:** accettato (2026-10-20). Gate automatici in arrivo con gli step 10-17 di
`docs/roadmap-miglioramenti.md`.

## Contesto

Discovery del 2026-10-20. Il progetto ha già buone abitudini, ma solo per convenzione:

- 53 commit su 63 seguono `tipo: descrizione`, senza scope né controlli.
- I fix recenti hanno un test di regressione che fallisce sul codice precedente (es. 3.6.2), ma non c'è
  una regola scritta.
- Il lint copre solo `E4,E7,E9,F`. `ruff format` non è mai stato applicato (57 file su 84 da
  riformattare).
- Le dipendenze non hanno versioni fissate e non esiste un hook locale.
- `cogs/tournament_system/cog.py` contiene 9 punti in cui il codice decide cosa fare cercando frasi nel
  messaggio restituito dal service.

## Decisione

1. **TDD obbligatorio per la logica** (`services/`, `utils/`, `repositories/`, `database/`): red →
   green → refactor. Ogni bug fix parte da un test di regressione che fallisce sul codice attuale. I cog
   (Discord UI) sono esenti: si mantengono sottili, e la verifica manuale in `TEST_MODE` viene annotata
   nel `CHANGELOG.md`.
2. **Conventional Commits** con scope di progetto e oggetto in inglese (ADR-0003); il tipo determina il bump di
   versione (vedi `CLAUDE.md` → "Conventional Commits").
3. **Gate automatici**: framework `pre-commit` (ruff check, ruff format, controllo del messaggio di
   commit) e gli stessi controlli in CI. Il lint si allarga a piccoli passi e non torna mai indietro: una
   nuova famiglia di regole entra in `ruff.toml` solo quando il codice è già pulito per quella famiglia.
4. **`CLAUDE.md` snello**: contiene regole, comandi, mappa e invarianti. Il razionale storico va negli ADR
   in `docs/adr/` o nei documenti tematici di `docs/`.

## Alternative scartate

- **Husky / lint-staged** (skill `setup-pre-commit`): ecosistema Node, inadatto a un progetto Python.
- **TDD anche sui cog** con fake di `discord.Interaction`: costo iniziale alto e test fragili rispetto al
  valore. Si preferisce spostare le decisioni nei service, che sono testabili.
- **Solo regole scritte, senza enforcement**: le convenzioni restano affidate alla memoria di chi lavora.

## Conseguenze

- Serve un commit di riformattazione una tantum (step 12), che sporca `git blame`: va aggiunto in
  `.git-blame-ignore-revs`.
- Il debito "string matching cog ↔ service" diventa uno step esplicito (step 17) invece di restare una
  nota.
