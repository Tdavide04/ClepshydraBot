from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime, ForeignKey, Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class TournamentStatus(str, enum.Enum):
    REGISTRATION = "registration"
    ACTIVE = "active"
    COMPLETED = "completed"


class MatchResult(str, enum.Enum):
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    discord_id = Column(Integer, unique=True, nullable=False, index=True)
    nickname_arena = Column(String(100), nullable=True)
    nome = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    rating = Column(Float, default=1500.0, nullable=False)
    rating_deviation = Column(Float, default=350.0, nullable=False)
    rating_volatility = Column(Float, default=0.06, nullable=False)
    rating_matches = Column(Integer, default=0, nullable=False)
    last_rated_at = Column(DateTime, nullable=True)

    tournament_players = relationship("TournamentPlayer", back_populates="user")

    def __repr__(self):
        return f"<User id={self.id} discord_id={self.discord_id}>"


class Tournament(Base):
    __tablename__ = "tournaments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    format = Column(String(50), nullable=False, default="Artisan")
    status = Column(
        SAEnum(TournamentStatus),
        default=TournamentStatus.REGISTRATION,
        nullable=False,
    )
    max_players = Column(Integer, nullable=True)
    round_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    players = relationship("TournamentPlayer", back_populates="tournament")
    matches = relationship("Match", back_populates="tournament")

    def __repr__(self):
        return f"<Tournament id={self.id} name={self.name!r} status={self.status}>"


class TournamentPlayer(Base):
    __tablename__ = "tournament_players"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    joined_at = Column(DateTime, default=datetime.now)
    dropped = Column(Boolean, default=False)
    seed = Column(Integer, nullable=True)
    deck_name = Column(String(200), nullable=True)

    tournament = relationship("Tournament", back_populates="players")
    user = relationship("User", back_populates="tournament_players")

    matches_as_player1 = relationship(
        "Match",
        foreign_keys="Match.player1_id",
        back_populates="player1",
    )
    matches_as_player2 = relationship(
        "Match",
        foreign_keys="Match.player2_id",
        back_populates="player2",
    )

    def __repr__(self):
        return f"<TournamentPlayer id={self.id} tournament={self.tournament_id} user={self.user_id}>"


class BannedCard(Base):
    __tablename__ = "banned_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    card_name = Column(String(200), nullable=False, unique=True, index=True)
    format = Column(String(50), nullable=False, default="Artisan")
    created_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<BannedCard id={self.id} name={self.card_name!r} format={self.format}>"


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=False)
    round_number = Column(Integer, nullable=False)
    player1_id = Column(
        Integer, ForeignKey("tournament_players.id"), nullable=False
    )
    player2_id = Column(
        Integer, ForeignKey("tournament_players.id"), nullable=True
    )
    winner_id = Column(
        Integer, ForeignKey("tournament_players.id"), nullable=True
    )
    result = Column(SAEnum(MatchResult), nullable=True)
    table_number = Column(Integer, nullable=True)
    p1_game_wins = Column(Integer, nullable=True)
    p2_game_wins = Column(Integer, nullable=True)

    tournament = relationship("Tournament", back_populates="matches")
    player1 = relationship(
        "TournamentPlayer",
        foreign_keys=[player1_id],
        back_populates="matches_as_player1",
    )
    player2 = relationship(
        "TournamentPlayer",
        foreign_keys=[player2_id],
        back_populates="matches_as_player2",
    )

    def __repr__(self):
        return (
            f"<Match id={self.id} round={self.round_number} "
            f"tournament={self.tournament_id}>"
        )
