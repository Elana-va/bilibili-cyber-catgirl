from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def create_session_factory(database_url: str):
    engine_kwargs: dict = {}
    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    if database_url.endswith(":memory:"):
        engine_kwargs["poolclass"] = StaticPool

    engine = create_engine(database_url, **engine_kwargs)

    from cyber_catgirl import models  # noqa: F401

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
