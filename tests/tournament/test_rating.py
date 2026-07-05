import pytest
from services.rating import (
    Rating,
    rate_1vs1,
    rate_draw,
    RATING_INITIAL,
    RD_INITIAL,
    VOLATILITY_INITIAL,
    RATING_FLOOR,
)


class TestRate1vs1:

    def test_vincitore_sale_perdente_scende(self):
        winner = Rating(1500.0, 350.0, 0.06)
        loser = Rating(1500.0, 350.0, 0.06)
        new_winner, new_loser = rate_1vs1(winner, loser)
        assert new_winner.value > 1500.0
        assert new_loser.value < 1500.0

    def test_rd_entrambi_diminuisce(self):
        winner = Rating(1500.0, 350.0, 0.06)
        loser = Rating(1500.0, 350.0, 0.06)
        new_winner, new_loser = rate_1vs1(winner, loser)
        assert new_winner.rd < 350.0
        assert new_loser.rd < 350.0

    def test_matches_incrementati(self):
        winner = Rating(1500.0, 350.0, 0.06, matches=0)
        loser = Rating(1500.0, 350.0, 0.06, matches=0)
        new_winner, new_loser = rate_1vs1(winner, loser)
        assert new_winner.matches == 1
        assert new_loser.matches == 1

    def test_floor_a_100(self):
        winner = Rating(100.0, 350.0, 0.06)
        loser = Rating(100.0, 350.0, 0.06)
        new_winner, new_loser = rate_1vs1(winner, loser)
        assert new_loser.value >= RATING_FLOOR

    def test_favorito_guadagna_poco_sfavorito_perde_molto(self):
        forte = Rating(2000.0, 200.0, 0.06)
        debole = Rating(1000.0, 200.0, 0.06)
        nuovo_forte, nuovo_debole = rate_1vs1(forte, debole)
        guadagno = nuovo_forte.value - forte.value
        perdita = nuovo_debole.value - debole.value
        assert guadagno < abs(perdita)

    def test_parametri_game_wins_non_usati(self):
        winner = Rating(1500.0, 350.0, 0.06)
        loser = Rating(1500.0, 350.0, 0.06)
        win_2_0, lose_0_2 = rate_1vs1(winner, loser, 2, 0)
        win_2_1, lose_1_2 = rate_1vs1(winner, loser, 2, 1)
        assert win_2_0.value == win_2_1.value
        assert lose_0_2.value == lose_1_2.value


class TestRateDraw:

    def test_entrambi_salgono_se_rd_alta(self):
        a = Rating(1500.0, 350.0, 0.06)
        b = Rating(1500.0, 350.0, 0.06)
        new_a, new_b = rate_draw(a, b)
        assert new_a.value >= 1500.0
        assert new_b.value >= 1500.0

    def test_rd_entrambi_dopo_pareggio(self):
        a = Rating(1500.0, 350.0, 0.06)
        b = Rating(1500.0, 350.0, 0.06)
        new_a, new_b = rate_draw(a, b)
        assert new_a.rd < 350.0
        assert new_b.rd < 350.0

    def test_pareggio_favorito_perde_rating(self):
        forte = Rating(2000.0, 200.0, 0.06)
        debole = Rating(1000.0, 200.0, 0.06)
        nuovo_forte, nuovo_debole = rate_draw(forte, debole)
        assert nuovo_forte.value < forte.value
        assert nuovo_debole.value > debole.value


class TestRatingVectors:

    def test_glicko2_scaling_corretto(self):
        a = Rating(1500.0, 200.0, 0.06)
        b = Rating(1400.0, 30.0, 0.06)
        new_a, new_b = rate_1vs1(a, b)
        assert new_a.value == pytest.approx(1563.5642, abs=0.01)
        assert new_b.value == pytest.approx(1398.1436, abs=0.01)
        assert new_a.rd == pytest.approx(175.4027, abs=0.01)
        assert new_b.rd == pytest.approx(31.6702, abs=0.01)
