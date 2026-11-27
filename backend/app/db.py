import os

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


engine = create_engine(
    URL.create("postgresql+psycopg", "platform_app", os.environ["PLATFORM_DB_PASSWORD"],
               "postgres", 5432, "platform"),
    pool_pre_ping=True,
    pool_size=4,
    max_overflow=4,
    pool_timeout=4,
    connect_args={"connect_timeout": 3, "options": "-c statement_timeout=8000"},
)


def get_db():
    with Session(engine) as db:
        yield db
