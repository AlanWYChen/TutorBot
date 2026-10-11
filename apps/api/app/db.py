from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import Settings


@lru_cache
def engine() -> Engine:
    url = (
        Settings()
        .database_url.get_secret_value()
        .replace("postgresql://", "postgresql+psycopg://", 1)
    )
    return create_engine(url, pool_pre_ping=True, echo=False)


def database_session() -> Iterator[Session]:
    with Session(engine()) as session, session.begin():
        yield session
