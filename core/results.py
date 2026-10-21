from dataclasses import dataclass
from enum import StrEnum


class ResultKind(StrEnum):
    """Which of several outcomes a ServiceResult reports, for the few methods whose callers must tell more
    than success from failure apart (today only generate_next_round())."""

    PENDING_RESULTS = "pending_results"
    TOURNAMENT_COMPLETED = "tournament_completed"


@dataclass(frozen=True)
class ServiceResult:
    """Outcome of a service operation: `ok` drives the flow, `message` is
    shown to the user, `kind` (optional) says which case it is when `ok`
    alone isn't enough.

    Replaced plain string returns that cogs parsed by text matching -
    fragile: RisultatoView looked for "Registrato" capitalized while
    submit_result() returned "Risultato registrato!", so every result was
    logged as WARN; /iscriviti didn't check at all and announced refused
    registrations as confirmed (fixed in 3.6.7).
    """

    ok: bool
    message: str
    kind: ResultKind | None = None
