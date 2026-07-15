from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from cyber_catgirl.db import Base


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASELINE_REVISION = "20260715_01"


def _alembic_config(database_url: str) -> Config:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _current_revision(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _backup_sqlite_database(database_url: str) -> Path | None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    source = Path(url.database).expanduser().resolve()
    if not source.is_file():
        return None
    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_dir / f"{source.stem}-{stamp}{source.suffix}"
    copy2(source, destination)
    return destination


def upgrade_database(database_url: str) -> None:
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    if not tables:
        from cyber_catgirl import models  # noqa: F401

        Base.metadata.create_all(engine)
        command.stamp(config, "head")
        engine.dispose()
        return
    if "alembic_version" not in tables:
        command.stamp(config, BASELINE_REVISION)
    current = _current_revision(engine)
    head = ScriptDirectory.from_config(config).get_current_head()
    if current == head:
        engine.dispose()
        return
    _backup_sqlite_database(database_url)
    engine.dispose()
    command.upgrade(config, "head")
