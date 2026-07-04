import math
from dataclasses import dataclass


RATING_INITIAL = 1500.0
RD_INITIAL = 350.0
VOLATILITY_INITIAL = 0.06
RATING_FLOOR = 100.0
TAU = 0.5
CONVERGENCE_THRESHOLD = 1e-6
MAX_ITERATIONS = 1000


@dataclass
class Rating:
    value: float
    rd: float
    volatility: float
    matches: int = 0


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _e(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def _to_glicko(r: float, rd: float) -> tuple[float, float]:
    return (r - 1500.0) / 173.7178, rd / 173.7178


def _from_glicko(mu: float, phi: float) -> tuple[float, float]:
    return 173.7178 * mu + 1500.0, 173.7178 * phi


def _improved_sigma(
    sigma: float,
    delta: float,
    variance: float,
    phi: float,
) -> float:
    def f(x: float) -> float:
        ex = math.exp(x)
        d = phi * phi + variance + ex
        num = ex * (delta * delta - d)
        den = 2.0 * d * d
        return num / den - (x - math.log(sigma * sigma)) / (TAU * TAU)

    a = math.log(sigma * sigma)
    if delta * delta > phi * phi + variance:
        b = math.log(delta * delta - phi * phi - variance)
    else:
        b = a - TAU
        while f(b) < 0:
            b -= TAU

    for _ in range(MAX_ITERATIONS):
        fa = f(a)
        fb = f(b)
        if fb - fa == 0:
            break
        c = a + (a - b) * fa / (fb - fa)
        fc = f(c)
        if fc * fb < 0:
            a = b
            fa = fb
        else:
            fa /= 2.0
        b = c
        fb = fc
        if abs(b - a) < CONVERGENCE_THRESHOLD:
            break

    return math.exp(a / 2.0) if a == b else math.exp(b / 2.0)


def rate_1vs1(
    winner: Rating,
    loser: Rating,
    winner_game_wins: int = 2,
    loser_game_wins: int = 0,
) -> tuple[Rating, Rating]:
    mu_w, phi_w = _to_glicko(winner.value, winner.rd)
    mu_l, phi_l = _to_glicko(loser.value, loser.rd)

    g_phi_l = _g(phi_l)
    g_phi_w = _g(phi_w)

    e_w = _e(mu_w, mu_l, phi_l)
    e_l = _e(mu_l, mu_w, phi_w)

    variance_w = 1.0 / (g_phi_l * g_phi_l * e_w * (1.0 - e_w))
    variance_l = 1.0 / (g_phi_w * g_phi_w * e_l * (1.0 - e_l))

    delta_w = variance_w * g_phi_l * (1.0 - e_w)
    delta_l = variance_l * g_phi_w * (0.0 - e_l)

    new_sigma_w = _improved_sigma(winner.volatility, delta_w, variance_w, phi_w)
    new_sigma_l = _improved_sigma(loser.volatility, delta_l, variance_l, phi_l)

    phi_star_w = math.sqrt(phi_w * phi_w + new_sigma_w * new_sigma_w)
    phi_star_l = math.sqrt(phi_l * phi_l + new_sigma_l * new_sigma_l)

    phi_new_w = 1.0 / math.sqrt(1.0 / (phi_star_w * phi_star_w) + 1.0 / variance_w)
    phi_new_l = 1.0 / math.sqrt(1.0 / (phi_star_l * phi_star_l) + 1.0 / variance_l)

    mu_new_w = mu_w + phi_new_w * phi_new_w * g_phi_l * (1.0 - e_w)
    mu_new_l = mu_l + phi_new_l * phi_new_l * g_phi_w * (0.0 - e_l)

    r_w, rd_w = _from_glicko(mu_new_w, phi_new_w)
    r_l, rd_l = _from_glicko(mu_new_l, phi_new_l)

    return (
        Rating(max(RATING_FLOOR, r_w), rd_w, new_sigma_w, winner.matches + 1),
        Rating(max(RATING_FLOOR, r_l), rd_l, new_sigma_l, loser.matches + 1),
    )


def rate_draw(
    player_a: Rating,
    player_b: Rating,
) -> tuple[Rating, Rating]:
    mu_a, phi_a = _to_glicko(player_a.value, player_a.rd)
    mu_b, phi_b = _to_glicko(player_b.value, player_b.rd)

    g_phi_b = _g(phi_b)
    g_phi_a = _g(phi_a)

    e_a = _e(mu_a, mu_b, phi_b)
    e_b = _e(mu_b, mu_a, phi_a)

    variance_a = 1.0 / (g_phi_b * g_phi_b * e_a * (1.0 - e_a))
    variance_b = 1.0 / (g_phi_a * g_phi_a * e_b * (1.0 - e_b))

    delta_a = variance_a * g_phi_b * (0.5 - e_a)
    delta_b = variance_b * g_phi_a * (0.5 - e_b)

    new_sigma_a = _improved_sigma(player_a.volatility, delta_a, variance_a, phi_a)
    new_sigma_b = _improved_sigma(player_b.volatility, delta_b, variance_b, phi_b)

    phi_star_a = math.sqrt(phi_a * phi_a + new_sigma_a * new_sigma_a)
    phi_star_b = math.sqrt(phi_b * phi_b + new_sigma_b * new_sigma_b)

    phi_new_a = 1.0 / math.sqrt(1.0 / (phi_star_a * phi_star_a) + 1.0 / variance_a)
    phi_new_b = 1.0 / math.sqrt(1.0 / (phi_star_b * phi_star_b) + 1.0 / variance_b)

    mu_new_a = mu_a + phi_new_a * phi_new_a * g_phi_b * (0.5 - e_a)
    mu_new_b = mu_b + phi_new_b * phi_new_b * g_phi_a * (0.5 - e_b)

    r_a, rd_a = _from_glicko(mu_new_a, phi_new_a)
    r_b, rd_b = _from_glicko(mu_new_b, phi_new_b)

    return (
        Rating(max(RATING_FLOOR, r_a), rd_a, new_sigma_a, player_a.matches + 1),
        Rating(max(RATING_FLOOR, r_b), rd_b, new_sigma_b, player_b.matches + 1),
    )
