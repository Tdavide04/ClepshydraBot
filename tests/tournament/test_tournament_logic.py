import pytest
from utils.tournament_logic import (
    omw_bar,
    rank_label,
    split_into_columns,
    split_field_value,
)


class TestOmwBar:

    def test_bar_sempre_10_caratteri(self):
        for pct in range(0, 101):
            bar = omw_bar(pct)
            block_part = bar.split(" ")[0]
            assert len(block_part) == 10, f"Barra errata per {pct}%: '{bar}'"

    def test_bar_valori_noti(self):
        assert omw_bar(0) == "\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591 0.0%"
        assert omw_bar(33) == "\u2588\u2588\u2588\u2591\u2591\u2591\u2591\u2591\u2591\u2591 33.0%"
        assert omw_bar(50) == "\u2588\u2588\u2588\u2588\u2588\u2591\u2591\u2591\u2591\u2591 50.0%"
        assert omw_bar(100) == "\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588 100.0%"

    def test_bar_pct_0(self):
        bar = omw_bar(0)
        assert bar == "\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591 0.0%"

    def test_bar_pct_100(self):
        bar = omw_bar(100)
        assert bar == "\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588 100.0%"

    def test_bar_clamp_sopra_100(self):
        bar = omw_bar(105)
        block_part = bar.split(" ")[0]
        assert len(block_part) == 10
        assert bar == "\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588 105.0%"

    def test_bar_clamp_sotto_0(self):
        bar = omw_bar(-5)
        assert bar == "\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591 -5.0%"


class TestRankLabel:

    def test_primo_oro(self):
        assert rank_label(1) == "\U0001F947"

    def test_secondo_argento(self):
        assert rank_label(2) == "\U0001F948"

    def test_terzo_bronzo(self):
        assert rank_label(3) == "\U0001F949"

    def test_quarto_numero(self):
        assert rank_label(4) == "4."

    def test_decimo_numero(self):
        assert rank_label(10) == "10."

    def test_centesimo_numero(self):
        assert rank_label(100) == "100."


class TestSplitIntoColumns:

    def test_split_pari(self):
        items = list(range(18))
        left, right = split_into_columns(items)
        assert len(left) == 9
        assert len(right) == 9

    def test_split_dispari(self):
        items = list(range(7))
        left, right = split_into_columns(items)
        assert len(left) == 4
        assert len(right) == 3

    def test_split_due_elementi(self):
        items = [1, 2]
        left, right = split_into_columns(items)
        assert left == [1]
        assert right == [2]

    def test_split_un_elemento(self):
        items = [1]
        left, right = split_into_columns(items)
        assert left == [1]
        assert right == []

    def test_split_lista_vuota(self):
        items = []
        left, right = split_into_columns(items)
        assert left == []
        assert right == []

    def test_split_ceil_floor_corretto(self):
        for n in range(1, 21):
            items = list(range(n))
            left, right = split_into_columns(items)
            expected_left = (n + 1) // 2
            assert len(left) == expected_left, f"n={n}: left dovrebbe essere {expected_left}, got {len(left)}"
            assert len(right) == n - expected_left, f"n={n}: right dovrebbe essere {n - expected_left}, got {len(right)}"

    def test_split_mantiene_ordine(self):
        items = ["a", "b", "c", "d", "e"]
        left, right = split_into_columns(items)
        assert left == ["a", "b", "c"]
        assert right == ["d", "e"]


class TestSplitFieldValue:

    def test_sotto_limite(self):
        lines = ["riga corta", "altra riga"]
        chunks = split_field_value(lines, max_chars=100)
        assert len(chunks) == 1
        assert chunks[0] == "riga corta\naltra riga"

    def test_sopra_limite(self):
        lines = ["x" * 600, "y" * 600]
        chunks = split_field_value(lines, max_chars=1000)
        assert len(chunks) >= 2

    def test_una_riga_sotto_limite(self):
        lines = ["x" * 500]
        chunks = split_field_value(lines, max_chars=1000)
        assert len(chunks) == 1

    def test_una_riga_sopra_limite(self):
        lines = ["x" * 1500]
        chunks = split_field_value(lines, max_chars=1000)
        assert len(chunks) == 1
        assert chunks[0] == "x" * 1500
