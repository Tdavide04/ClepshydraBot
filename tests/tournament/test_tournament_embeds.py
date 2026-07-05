import re
import pytest

try:
    import discord
    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False

from utils.tournament_embeds import (
    build_standings_embed,
    build_pairings_embed,
    build_start_embed,
    EMBED_COLOR_STANDINGS,
    EMBED_COLOR_PAIRINGS,
    EMBED_COLOR_START,
    EMBED_COLOR_TOP8,
)


@pytest.fixture
def mock_entry():
    class MockEntry:
        def __init__(self, rank, player_id, name, deck, points, wins, losses, draws, omw):
            self.rank = rank
            self.player_id = player_id
            self.player_name = name
            self.deck_name = deck
            self.points = points
            self.wins = wins
            self.losses = losses
            self.draws = draws
            self.opponent_win_percent = omw
            self.game_win_percent = 0.5
            self.opponent_game_win_percent = 0.5
    return MockEntry


class TestBuildStandingsEmbed:

    def test_restituisce_embed(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        entries = []
        embed = build_standings_embed(
            tournament_name="Test",
            tournament_id=1,
            round_number=1,
            entries=entries,
            player_count=0,
        )
        assert isinstance(embed, discord.Embed)

    def test_colore_corretto(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        embed = build_standings_embed("Test", 1, 1, [], 0)
        assert embed.color.value == EMBED_COLOR_STANDINGS

    def test_titolo_con_nome_torneo(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        embed = build_standings_embed("MioTorneo", 1, 1, [], 0)
        assert "MioTorneo" in embed.title

    def test_titolo_senza_round(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        embed = build_standings_embed("Test", 1, 0, [], 0)
        assert "\U0001F3C6" in embed.title

    def test_titolo_con_round(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        embed = build_standings_embed("Test", 1, 3, [], 0)
        assert "\u26A1" in embed.title

    def test_footer_con_id(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        embed = build_standings_embed("Test", 42, 1, [], 0)
        assert "42" in embed.footer.text

    def test_numero_field_non_supera_25(self, mock_entry):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        entries = [
            mock_entry(i, i, f"Player{i}", f"Deck{i}", 3, 1, 0, 0, 0.5)
            for i in range(1, 51)
        ]
        embed = build_standings_embed("Test", 1, 1, entries, 50)
        assert len(embed.fields) <= 25

    def test_nessun_field_supera_1024(self, mock_entry):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        entries = [
            mock_entry(
                i, i,
                f"PlayerWithVeryLongName{i}" * 3,
                f"MazzoMoltoLungoConNomiStrani{i}" * 2,
                3, 1, 0, 0, 0.5
            )
            for i in range(1, 31)
        ]
        embed = build_standings_embed("Test", 1, 1, entries, 30)
        for field in embed.fields:
            assert len(field.value) <= 1024, (
                f"Field '{field.name}' supera 1024 caratteri: {len(field.value)}"
            )

    def test_giocatore_senza_deck_mostra_trattino(self, mock_entry):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        entries = [
            mock_entry(1, 1, "Alice", "", 3, 1, 0, 0, 0.5),
            mock_entry(2, 2, "Bob", None, 0, 0, 1, 0, 0.33),
        ]
        embed = build_standings_embed("Test", 1, 1, entries, 2)
        combined = "\n".join(f.value for f in embed.fields)
        assert "\u2014" in combined

    def test_omw_nel_field(self, mock_entry):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        entries = [
            mock_entry(1, 1, "Alice", "Deck", 3, 1, 0, 0, 0.44),
        ]
        embed = build_standings_embed("Test", 1, 1, entries, 1)
        combined = "\n".join(f.value for f in embed.fields)
        assert "OMW:" in combined


class TestBuildPairingsEmbed:

    def test_restituisce_embed(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        pairings = [
            {"table": 1, "player1": "Alice", "player2": "Bob"},
        ]
        embed = build_pairings_embed("Test", 1, 1, pairings)
        assert isinstance(embed, discord.Embed)

    def test_colore_corretto(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        embed = build_pairings_embed("Test", 1, 1, [])
        assert embed.color.value == EMBED_COLOR_PAIRINGS

    def test_titolo_con_round(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        embed = build_pairings_embed("Test", 1, 3, [])
        assert "Round 3" in embed.title

    def test_bye_in_fondo(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        pairings = [
            {"table": 1, "player1": "Alice", "player2": "Bob"},
            {"table": 2, "player1": "Charlie", "player2": None},
        ]
        embed = build_pairings_embed("Test", 1, 1, pairings)
        combined = "\n".join(f.value for f in embed.fields)
        assert "BYE" in combined


class TestBuildStartEmbed:

    def test_restituisce_embed(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        players = [("Alice", "Mono Red")]
        embed = build_start_embed("Test", 1, players, 4)
        assert isinstance(embed, discord.Embed)

    def test_colore_corretto(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        embed = build_start_embed("Test", 1, [], 0)
        assert embed.color.value == EMBED_COLOR_START

    def test_titolo_corretto(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        embed = build_start_embed("Test", 1, [], 0)
        assert "Torneo Iniziato" in embed.title

    def test_descrizione_con_nome(self):
        if not HAS_DISCORD:
            pytest.skip("discord.py non disponibile")

        embed = build_start_embed("MioTorneo", 1, [("Alice", "D")], 4)
        assert "MioTorneo" in embed.description
