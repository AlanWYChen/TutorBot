"""Local-only privileged bootstrap. This credential is never passed to either API."""

import os

import psycopg
from psycopg import sql

if os.environ.get("APP_ENV") != "local":
    raise RuntimeError("Local role bootstrap requires APP_ENV=local")
with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
    for role, key in [
        ("tutorbot_migrator", "MIGRATOR_DB_PASSWORD"),
        ("tutorbot_runtime", "RUNTIME_DB_PASSWORD"),
        ("tutorbot_admin", "ADMIN_DB_PASSWORD"),
    ]:
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
            connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
        connection.execute(
            sql.SQL(
                "ALTER ROLE {} WITH PASSWORD {} NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(role), sql.Literal(os.environ[key]))
        )
    connection.execute("REVOKE ALL ON DATABASE tutorbot FROM PUBLIC")
    connection.execute(
        "GRANT CONNECT ON DATABASE tutorbot TO tutorbot_migrator, tutorbot_runtime, tutorbot_admin"
    )
    connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    connection.execute("GRANT USAGE, CREATE ON SCHEMA public TO tutorbot_migrator")
    connection.execute("GRANT CREATE ON DATABASE tutorbot TO tutorbot_migrator")
    connection.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE tutorbot_migrator "
        "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
    )
    for table in ["users", "student_accounts", "alembic_version"]:
        if connection.execute("SELECT to_regclass(%s)", ("public." + table,)).fetchone()[0]:
            connection.execute(
                sql.SQL("ALTER TABLE public.{} OWNER TO tutorbot_migrator").format(
                    sql.Identifier(table)
                )
            )
print("Local database roles configured.")
