from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from cyber_catgirl.services.migrations import upgrade_database


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def execute(url: str, sql: str) -> None:
    with create_engine(url).begin() as connection:
        connection.execute(text(sql))


def scalar(url: str, sql: str):
    with create_engine(url).connect() as connection:
        return connection.scalar(text(sql))


def table_exists(url: str, name: str) -> bool:
    return name in inspect(create_engine(url)).get_table_names()


def column_exists(url: str, table: str, name: str) -> bool:
    columns = inspect(create_engine(url)).get_columns(table)
    return name in {column["name"] for column in columns}


def create_legacy_schema(url: str) -> None:
    statements = (
        """
        create table events (
            id integer primary key,
            event_id varchar(128) unique not null,
            event_type varchar(64) not null,
            payload_json text not null default '{}',
            status varchar(32) not null default 'new',
            created_at datetime
        )
        """,
        """
        create table drafts (
            id integer primary key,
            content_key varchar(128) unique,
            event_id integer,
            draft_type varchar(32) not null,
            content text not null,
            risk_level varchar(16) not null,
            review_status varchar(32) not null default 'pending',
            agent_version varchar(64) not null default 'catgirl-v1',
            stats_snapshot_json text not null default '{}',
            created_at datetime
        )
        """,
        """
        create table publish_jobs (
            id integer primary key,
            draft_id integer,
            idempotency_key varchar(192) unique not null,
            status varchar(32) not null,
            platform_id varchar(128),
            attempts integer not null default 0,
            created_at datetime
        )
        """,
    )
    with create_engine(url).begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def stamp_baseline(url: str) -> None:
    command.stamp(alembic_config(url), "20260715_01")


def test_upgrade_from_baseline_preserves_existing_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    create_legacy_schema(url)
    stamp_baseline(url)
    execute(
        url,
        """
        insert into events (event_id, event_type, payload_json, status)
        values ('comment_1', 'new_comment', '{}', 'new')
        """,
    )

    upgrade_database(url)

    assert scalar(url, "select event_id from events") == "comment_1"
    assert table_exists(url, "monitored_contents")
    assert table_exists(url, "monitor_checkpoints")
    assert column_exists(url, "events", "priority")
    assert column_exists(url, "publish_jobs", "next_attempt_at")


def test_unversioned_legacy_database_is_stamped_then_upgraded(tmp_path):
    url = f"sqlite:///{tmp_path / 'unversioned.db'}"
    create_legacy_schema(url)

    upgrade_database(url)

    assert scalar(url, "select version_num from alembic_version") == "20260715_02"


def test_file_database_is_backed_up_before_schema_upgrade(tmp_path):
    path = tmp_path / "live.db"
    url = f"sqlite:///{path}"
    create_legacy_schema(url)

    upgrade_database(url)

    backups = list((tmp_path / "backups").glob("live-*.db"))
    assert len(backups) == 1


def test_fresh_file_database_is_created_at_head_without_backup(tmp_path):
    path = tmp_path / "fresh.db"
    url = f"sqlite:///{path}"

    upgrade_database(url)

    assert table_exists(url, "events")
    assert table_exists(url, "monitored_contents")
    assert scalar(url, "select version_num from alembic_version") == "20260715_02"
    assert not (tmp_path / "backups").exists()
