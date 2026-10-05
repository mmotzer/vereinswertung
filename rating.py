"""Python port of the pinned Lichess/scalachess Glicko calculation.

See reference/versions.json and NOTICE.md for original code and licenses.
Only human standard-chess bullet/blitz/rapid ratings are supported.
"""
from dataclasses import dataclass, replace, asdict
from math import exp, log, pi, sqrt

SCALE = 173.7178
PERIODS_PER_DAY = 0.21436
COLOR_ADVANTAGE = 11.782457
TAU = 0.75
ENGINE_VERSION = "lichess-2026-10-04-v1"


@dataclass(frozen=True)
class Rating:
    rating: float = 1500.0
    rd: float = 500.0
    volatility: float = 0.09
    games: int = 0
    latest: float | None = None

    def json(self):
        return asdict(self)


def live(r: Rating, timestamp: float) -> Rating:
    """Lichess previewDeviation; canonical stored RD is anchored at latest."""
    days = max(0.0, timestamp - r.latest) / 86400 if r.latest is not None else 0.0
    rd = sqrt(r.rd ** 2 + days * PERIODS_PER_DAY * r.volatility ** 2 * SCALE ** 2)
    return replace(r, rd=max(45.0, min(500.0, rd)))


def compute_one(player: Rating, opponent: Rating, score: float,
                advantage: float = 0.0, elapsed_periods: float = 0.0) -> Rating:
    """scalachess RatingCalculator.calculateNewRating (single game).

    Lila computeGame sets skipDeviationIncrease=true, hence elapsed_periods=0.
    Time inflation is applied separately by live(), before computing both sides.
    """
    phi = player.rd / SCALE
    opp_phi = opponent.rd / SCALE
    mu = (player.rating - 1500.0) / SCALE
    g = 1 / sqrt(1 + 3 * opp_phi ** 2 / pi ** 2)
    expected = 1 / (1 + exp(-g * (player.rating - opponent.rating + advantage) / SCALE))
    v = 1 / (g ** 2 * expected * (1 - expected))
    outcome = g * (score - expected)
    delta = v * outcome
    a = log(player.volatility ** 2)

    def f(x):
        ex = exp(x)
        return ex * (delta ** 2 - phi ** 2 - v - ex) / (2 * (phi ** 2 + v + ex) ** 2) - (x - a) / TAU ** 2

    A = a
    if delta ** 2 > phi ** 2 + v:
        B = log(delta ** 2 - phi ** 2 - v)
    else:
        k = 1
        B = a - k * abs(TAU)
        while f(B) < 0:
            k += 1
            if k > 1000:
                raise ArithmeticError("Glicko-Konvergenz fehlgeschlagen")
            B = a - k * abs(TAU)
    fA, fB = f(A), f(B)
    for _ in range(1000):
        if abs(B - A) <= 0.000001:
            break
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB <= 0:
            A, fA = B, fB
        else:
            fA /= 2
        B, fB = C, fC
    else:
        raise ArithmeticError("Glicko-Konvergenz fehlgeschlagen")
    sigma = exp(A / 2)
    phi_star = sqrt(phi ** 2 + elapsed_periods * sigma ** 2)
    new_phi = 1 / sqrt(1 / phi_star ** 2 + 1 / v)
    return replace(player, rating=1500 + SCALE * (mu + new_phi ** 2 * outcome),
                   rd=new_phi * SCALE, volatility=sigma, games=player.games + 1)


def regulate(before: Rating, after: Rating, category: str, timestamp: float) -> Rating:
    """Lila RatingRegulator and PerfExt.addOrReset/cap, for human players."""
    factor = {"bullet": 1.010, "blitz": 1.005, "rapid": 1.015}[category]
    rating = after.rating
    if rating > before.rating:
        rating = before.rating + (rating - before.rating) * factor
    rating = max(before.rating - 700, min(before.rating + 700, rating))
    if not (0 < rating < 4000 and 0 < after.rd < 1000 and 0 < after.volatility < 0.2):
        raise ArithmeticError("Ungültiges Glicko-Ergebnis; Import nicht gespeichert")
    return replace(after, rating=max(400.0, rating), rd=max(45.0, min(500.0, after.rd)),
                   volatility=min(0.1, after.volatility), latest=timestamp)


def game(white: Rating, black: Rating, score: float, category: str, timestamp: float):
    w, b = live(white, timestamp), live(black, timestamp)
    return (regulate(w, compute_one(w, b, score, COLOR_ADVANTAGE), category, timestamp),
            regulate(b, compute_one(b, w, 1 - score, -COLOR_ADVANTAGE), category, timestamp))
