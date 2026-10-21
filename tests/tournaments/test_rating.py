import pytest

from features.tournaments.rating import (
    RATING_FLOOR,
    Rating,
    rate_1vs1,
    rate_draw,
)


class TestRate1vs1:
    def test_winner_rises_loser_falls(self):
        winner = Rating(1500.0, 350.0, 0.06)
        loser = Rating(1500.0, 350.0, 0.06)
        new_winner, new_loser = rate_1vs1(winner, loser)
        assert new_winner.value > 1500.0
        assert new_loser.value < 1500.0

    def test_rd_decreases_for_both(self):
        winner = Rating(1500.0, 350.0, 0.06)
        loser = Rating(1500.0, 350.0, 0.06)
        new_winner, new_loser = rate_1vs1(winner, loser)
        assert new_winner.rd < 350.0
        assert new_loser.rd < 350.0

    def test_matches_incremented(self):
        winner = Rating(1500.0, 350.0, 0.06, matches=0)
        loser = Rating(1500.0, 350.0, 0.06, matches=0)
        new_winner, new_loser = rate_1vs1(winner, loser)
        assert new_winner.matches == 1
        assert new_loser.matches == 1

    def test_floor_at_100(self):
        winner = Rating(100.0, 350.0, 0.06)
        loser = Rating(100.0, 350.0, 0.06)
        new_winner, new_loser = rate_1vs1(winner, loser)
        assert new_loser.value >= RATING_FLOOR

    def test_favorite_gains_less_than_underdog_loses(self):
        strong = Rating(2000.0, 200.0, 0.06)
        weak = Rating(1000.0, 200.0, 0.06)
        new_strong, new_weak = rate_1vs1(strong, weak)
        gain = new_strong.value - strong.value
        loss = new_weak.value - weak.value
        assert gain < abs(loss)

    def test_game_wins_parameters_unused(self):
        winner = Rating(1500.0, 350.0, 0.06)
        loser = Rating(1500.0, 350.0, 0.06)
        win_2_0, lose_0_2 = rate_1vs1(winner, loser, 2, 0)
        win_2_1, lose_1_2 = rate_1vs1(winner, loser, 2, 1)
        assert win_2_0.value == win_2_1.value
        assert lose_0_2.value == lose_1_2.value


class TestRateDraw:
    def test_both_rise_with_high_rd(self):
        a = Rating(1500.0, 350.0, 0.06)
        b = Rating(1500.0, 350.0, 0.06)
        new_a, new_b = rate_draw(a, b)
        assert new_a.value >= 1500.0
        assert new_b.value >= 1500.0

    def test_rd_decreases_for_both_after_draw(self):
        a = Rating(1500.0, 350.0, 0.06)
        b = Rating(1500.0, 350.0, 0.06)
        new_a, new_b = rate_draw(a, b)
        assert new_a.rd < 350.0
        assert new_b.rd < 350.0

    def test_draw_costs_the_favorite_rating(self):
        strong = Rating(2000.0, 200.0, 0.06)
        weak = Rating(1000.0, 200.0, 0.06)
        new_strong, new_weak = rate_draw(strong, weak)
        assert new_strong.value < strong.value
        assert new_weak.value > weak.value


class TestRatingVectors:
    def test_glicko2_scaling_correct(self):
        a = Rating(1500.0, 200.0, 0.06)
        b = Rating(1400.0, 30.0, 0.06)
        new_a, new_b = rate_1vs1(a, b)
        assert new_a.value == pytest.approx(1563.5642, abs=0.01)
        assert new_b.value == pytest.approx(1398.1436, abs=0.01)
        assert new_a.rd == pytest.approx(175.4027, abs=0.01)
        assert new_b.rd == pytest.approx(31.6702, abs=0.01)
