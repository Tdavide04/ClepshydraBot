import os
import os
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from database.models import Base
from config.config import DB_PATH


_engine = None
_async_session_maker = None


def get_db_url() -> str:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    return f"sqlite+aiosqlite:///{DB_PATH}"


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_db_url(),
            echo=False,
        )
    return _engine


BANLIST_FILE = "cards.txt"


async def init_db():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    global _async_session_maker
    _async_session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    await _migrate_banlist()
    await _migrate_schema()


async def _migrate_banlist():
    if not os.path.exists(BANLIST_FILE):
        return

    from repositories.banlist_repository import BanlistRepository

    session = get_session()
    if session is None:
        return
    try:
        repo = BanlistRepository(session)
        imported = await repo.import_from_file(BANLIST_FILE)
        if imported:
            print(f"Banlist: importate {imported} carte da {BANLIST_FILE}")
    finally:
        await session.close()


async def _migrate_schema():
    engine = get_engine()
    async with engine.begin() as conn:
        try:
            await conn.execute(
                sa_text("ALTER TABLE tournament_players ADD COLUMN deck_name VARCHAR(200)")
            )
            print("Migrazione: aggiunta colonna deck_name a tournament_players")
        except Exception:
            pass
        try:
            await conn.execute(
                sa_text("ALTER TABLE matches ADD COLUMN p1_game_wins INTEGER")
            )
            print("Migrazione: aggiunta colonna p1_game_wins a matches")
        except Exception:
            pass
        try:
            await conn.execute(
                sa_text("ALTER TABLE matches ADD COLUMN p2_game_wins INTEGER")
            )
            print("Migrazione: aggiunta colonna p2_game_wins a matches")
        except Exception:
            pass
        try:
            await conn.execute(
                sa_text("ALTER TABLE users ADD COLUMN rating FLOAT DEFAULT 1500.0")
            )
            print("Migrazione: aggiunta colonna rating a users")
        except Exception:
            pass
        try:
            await conn.execute(
                sa_text("ALTER TABLE users ADD COLUMN rating_deviation FLOAT DEFAULT 350.0")
            )
            print("Migrazione: aggiunta colonna rating_deviation a users")
        except Exception:
            pass
        try:
            await conn.execute(
                sa_text("ALTER TABLE users ADD COLUMN rating_volatility FLOAT DEFAULT 0.06")
            )
            print("Migrazione: aggiunta colonna rating_volatility a users")
        except Exception:
            pass
        try:
            await conn.execute(
                sa_text("ALTER TABLE users ADD COLUMN rating_matches INTEGER DEFAULT 0")
            )
            print("Migrazione: aggiunta colonna rating_matches a users")
        except Exception:
            pass
        try:
            await conn.execute(
                sa_text("ALTER TABLE users ADD COLUMN last_rated_at TIMESTAMP")
            )
            print("Migrazione: aggiunta colonna last_rated_at a users")
        except Exception:
            pass


async def close_db():
    global _engine, _async_session_maker
    if _engine:
        await _engine.dispose()
        _engine = None
        _async_session_maker = None


def get_session() -> AsyncSession | None:
    if _async_session_maker is None:
        return None
    return _async_session_maker()
