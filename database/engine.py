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


# (tabella, colonna, DDL): ogni voce aggiunge una colonna mancante a uno schema
# esistente. Elenco cumulativo, mai rimosso — vedi database.md "Migrazioni Automatiche".
_SCHEMA_MIGRATIONS: list[tuple[str, str, str]] = [
    ("tournament_players", "deck_name", "ALTER TABLE tournament_players ADD COLUMN deck_name VARCHAR(200)"),
    ("matches", "p1_game_wins", "ALTER TABLE matches ADD COLUMN p1_game_wins INTEGER"),
    ("matches", "p2_game_wins", "ALTER TABLE matches ADD COLUMN p2_game_wins INTEGER"),
    ("users", "rating", "ALTER TABLE users ADD COLUMN rating FLOAT DEFAULT 1500.0"),
    ("users", "rating_deviation", "ALTER TABLE users ADD COLUMN rating_deviation FLOAT DEFAULT 350.0"),
    ("users", "rating_volatility", "ALTER TABLE users ADD COLUMN rating_volatility FLOAT DEFAULT 0.06"),
    ("users", "rating_matches", "ALTER TABLE users ADD COLUMN rating_matches INTEGER DEFAULT 0"),
    ("users", "last_rated_at", "ALTER TABLE users ADD COLUMN last_rated_at TIMESTAMP"),
]


async def _table_columns(conn, table: str) -> set[str]:
    result = await conn.execute(sa_text(f"PRAGMA table_info({table})"))
    return {row[1] for row in result.fetchall()}


async def _migrate_schema():
    engine = get_engine()
    async with engine.begin() as conn:
        for table, column, ddl in _SCHEMA_MIGRATIONS:
            if column in await _table_columns(conn, table):
                continue
            try:
                await conn.execute(sa_text(ddl))
                print(f"Migrazione: aggiunta colonna {column} a {table}")
            except Exception as exc:
                print(
                    f"ERRORE migrazione: impossibile aggiungere {column} a {table}: {exc}"
                )


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
