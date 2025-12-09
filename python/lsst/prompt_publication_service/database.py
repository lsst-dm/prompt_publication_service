from sqlalchemy import Insert
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, AsyncIterator


class Database(AbstractAsyncContextManager):
    def __init__(self, database_uri: str) -> None:
        self._engine = create_async_engine(database_uri)
        self._session_maker = async_sessionmaker(self._engine)

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        await self._engine.dispose()
        return None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_maker() as session:
            yield session

    def insert_if_not_exists(self, table: type[DeclarativeBase]) -> Insert:
        """Returns a SQLAlchemy Insert object for the given table configured
        with 'ON CONFLICT IGNORE' to skip inserting rows that conflict with
        existing primary keys or unique indexes.

        This makes the insert idempotent.
        """
        dialect = self._engine.dialect.name
        if dialect == "postgresql":
            import sqlalchemy.dialects.postgresql

            return sqlalchemy.dialects.postgresql.insert(table).on_conflict_do_nothing()
        elif dialect == "sqlite":
            import sqlalchemy.dialects.sqlite

            return sqlalchemy.dialects.sqlite.insert(table).on_conflict_do_nothing()
        else:
            raise RuntimeError(f"Unhandled database engine '{dialect}'")
