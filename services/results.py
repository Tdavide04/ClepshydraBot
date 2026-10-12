from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceResult:
    """Esito di un'operazione del service: `ok` per decidere il flusso,
    `message` da mostrare all'utente.

    Sostituisce, un metodo alla volta, il ritorno di una semplice stringa
    che i cog interpretavano per confronto di testo - fragile: RisultatoView
    cercava "Registrato" con la maiuscola mentre submit_result() restituiva
    "Risultato registrato!", quindi ogni risultato andava a log come WARN.
    """

    ok: bool
    message: str
