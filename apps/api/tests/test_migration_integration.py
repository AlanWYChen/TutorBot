"""Up/down and constraints in a disposable database, never the app database."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from tests.domain_checks import verify_domain

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_AUTH_INTEGRATION") != "1", reason="Requires local PostgreSQL"
)


def test_domain_migration_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    service_url = Settings().database_url.get_secret_value()
    url = os.environ["BOOTSTRAP_DATABASE_URL"]
    db_name = "identity_test_" + uuid4().hex
    admin_engine = create_engine(
        url.replace("postgresql://", "postgresql+psycopg://"), isolation_level="AUTOCOMMIT"
    )
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{db_name}"'))
    scratch_url = url.rsplit("/", 1)[0] + "/" + db_name
    monkeypatch.setenv("DATABASE_URL", scratch_url)
    scratch = create_engine(scratch_url.replace("postgresql://", "postgresql+psycopg://"))
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "0002_service_boundaries")
        legacy_release, legacy_chunk = uuid4(), uuid4()
        with scratch.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO global_knowledge.knowledge_releases "
                    "(id,name,version,status,content_hash) "
                    "VALUES (:id,'legacy','v0','published','legacy')"
                ),
                {"id": legacy_release},
            )
            connection.execute(
                text(
                    "INSERT INTO global_knowledge.knowledge_chunks "
                    "(id,publish_release_id,content_text) VALUES (:id,:release,'legacy synthetic')"
                ),
                {"id": legacy_chunk, "release": legacy_release},
            )
        command.upgrade(config, "head")
        with scratch.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM published_knowledge.knowledge_chunks WHERE id=:id"),
                    {"id": legacy_chunk},
                )
                == 0
            )
        assert {"users", "student_accounts"}.issubset(inspect(scratch).get_table_names())
        with pytest.raises(IntegrityError), scratch.begin() as connection:
            connection.execute(
                text("INSERT INTO student_accounts (id,user_id) VALUES (:id,:owner)"),
                {"id": uuid4(), "owner": uuid4()},
            )
        with pytest.raises(IntegrityError), scratch.begin() as connection:
            connection.execute(
                text("INSERT INTO users (id,firebase_uid,role) VALUES (:id,'bad-role','root')"),
                {"id": uuid4()},
            )
        verify_domain(scratch_url, scratch, service_url)
        command.downgrade(config, "0002_service_boundaries")
        assert "student_data" not in inspect(scratch).get_schema_names()
        assert "documents" not in inspect(scratch).get_table_names(schema="global_knowledge")
        assert len(inspect(scratch).get_columns("knowledge_chunks", schema="global_knowledge")) == 3
        with scratch.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM global_knowledge.knowledge_chunks WHERE id=:id"),
                    {"id": legacy_chunk},
                )
                == 1
            )
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        assert "users" not in inspect(scratch).get_table_names()
        command.upgrade(config, "head")
        assert "student_accounts" in inspect(scratch).get_table_names()
    finally:
        scratch.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{db_name}" WITH (FORCE)'))
        admin_engine.dispose()
