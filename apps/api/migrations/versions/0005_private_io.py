"""Private object manifests and durable job outbox; narrow worker roles."""

from alembic import op

revision = "0005_private_io"
down_revision = "0004_domain_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for schema, service in (("student_data", "runtime"), ("global_knowledge", "admin")):
        owner = (
            "student_id uuid NOT NULL REFERENCES public.student_accounts(id),"
            if service == "runtime"
            else "owner_id uuid NOT NULL,"
        )
        buckets = (
            "'student-private'"
            if service == "runtime"
            else ("'teaching-private','curriculum-published'")
        )
        owner_col = "student_id" if service == "runtime" else "owner_id"
        op.execute(f"""
            CREATE TABLE {schema}.storage_objects (
                id uuid PRIMARY KEY, {owner}
                record jsonb NOT NULL, deleted_at timestamptz,
                schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version=1),
                created_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE ({owner_col},id),
                CHECK ((record->'ref'->>'owner_id')::uuid={owner_col}),
                CHECK ((record->'ref'->>'resource_id')::uuid=id),
                CHECK (record->'ref'->>'bucket' IN (
                    {buckets}
                ))
            )
        """)
        op.execute(f"""
            CREATE TABLE {schema}.jobs (
                id uuid PRIMARY KEY, {owner}
                object_id uuid NOT NULL,
                kind text NOT NULL DEFAULT 'verify_object' CHECK(kind='verify_object'),
                idempotency_key text NOT NULL CHECK(length(idempotency_key) BETWEEN 1 AND 128),
                state text NOT NULL DEFAULT 'queued'
                  CHECK(state IN ('queued','running','retry_wait',
                                   'succeeded','failed','cancelled')),
                attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
                lease_token uuid, lease_until timestamptz,
                available_at timestamptz NOT NULL DEFAULT now(), dispatched_at timestamptz,
                error_code text, created_at timestamptz NOT NULL DEFAULT now(),
                schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version=1),
                UNIQUE ({owner_col},idempotency_key),
                FOREIGN KEY({owner_col},object_id)
                    REFERENCES {schema}.storage_objects({owner_col},id)
            )
        """)
        op.execute(f"CREATE INDEX jobs_ready ON {schema}.jobs(state,available_at)")
        worker = f"tutorbot_{service}_worker"
        for table in ("storage_objects", "jobs"):
            op.execute(f"REVOKE ALL ON {schema}.{table} FROM PUBLIC")
            op.execute(f"GRANT SELECT, INSERT ON {schema}.{table} TO tutorbot_{service}")
            columns = "(deleted_at)" if table == "storage_objects" else ""
            op.execute(f"GRANT UPDATE {columns} ON {schema}.{table} TO tutorbot_{service}")
            if service == "runtime":
                op.execute(f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY")
                op.execute(f"ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY")
                op.execute(f"""
                    CREATE POLICY owner_scope ON {schema}.{table} TO tutorbot_runtime
                    USING (student_id=nullif(current_setting('app.student_id',true),'')::uuid)
                    WITH CHECK (student_id=nullif(current_setting('app.student_id',true),'')::uuid)
                """)
                op.execute(
                    f"CREATE POLICY worker_scope ON {schema}.{table} TO {worker} USING(true)"
                )
            op.execute(f"GRANT SELECT ON {schema}.{table} TO {worker}")
        op.execute(f"GRANT UPDATE ON {schema}.jobs TO {worker}")
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {worker}")


def downgrade() -> None:
    for schema in ("student_data", "global_knowledge"):
        op.execute(f"DROP TABLE {schema}.jobs")
        op.execute(f"DROP TABLE {schema}.storage_objects")
