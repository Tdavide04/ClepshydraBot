from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceResult:
    """Outcome of a service operation: `ok` drives the flow, `message` is
    shown to the user.

    Replaces, one method at a time, plain string returns that cogs parsed by
    text matching - fragile: RisultatoView looked for "Registrato" capitalized
    while submit_result() returned "Risultato registrato!", so every result
    was logged as WARN.
    """

    ok: bool
    message: str
