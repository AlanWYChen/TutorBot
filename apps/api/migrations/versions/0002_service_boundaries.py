"""Protected global tables, published-only views, append-only audits and grants."""

import sqlalchemy as sa
from alembic import op

revision = "0002_service_boundaries"
down_revision = "0001_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA global_knowledge")
    op.execute("CREATE SCHEMA published_knowledge")
    for table in ["knowledge_releases", "skill_versions"]:
        op.create_table(
            table,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("version", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.CheckConstraint("status IN ('draft','evaluating','approved','published','retired')"),
            schema="global_knowledge",
        )
        op.execute(
            f"CREATE VIEW published_knowledge.{table} WITH "
            f"(security_barrier=true) AS SELECT * FROM global_knowledge.{table} "
            f"WHERE status='published'"
        )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "publish_release_id",
            sa.Uuid(),
            sa.ForeignKey("global_knowledge.knowledge_releases.id"),
            nullable=False,
        ),
        sa.Column("content_text", sa.Text(), nullable=False),
        schema="global_knowledge",
    )
    op.create_table(
        "teaching_demonstrations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_by_admin_uid", sa.String(128), nullable=False),
        sa.Column("scenario", sa.Text(), nullable=False),
        schema="global_knowledge",
    )
    op.execute(
        "CREATE VIEW published_knowledge.knowledge_chunks WITH "
        "(security_barrier=true) AS SELECT c.* FROM "
        "global_knowledge.knowledge_chunks c JOIN "
        "global_knowledge.knowledge_releases r ON "
        "c.publish_release_id=r.id WHERE r.status='published'"
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_uid", sa.String(128)),
        sa.Column("actor_role", sa.String(16)),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("actor_role IS NULL OR actor_role IN ('student','admin')"),
        sa.CheckConstraint("outcome IN ('success','denied','error')"),
        sa.CheckConstraint("status_code BETWEEN 100 AND 599"),
    )
    op.execute(
        "CREATE FUNCTION public.prevent_audit_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit history is "
        "append only'; END $$"
    )
    op.execute("REVOKE ALL ON FUNCTION public.prevent_audit_mutation() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON "
        "public.audit_events FOR EACH ROW EXECUTE FUNCTION "
        "public.prevent_audit_mutation()"
    )
    op.execute("REVOKE ALL ON SCHEMA global_knowledge, published_knowledge FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON ALL TABLES IN SCHEMA global_knowledge, published_knowledge FROM PUBLIC"
    )
    op.execute(
        "REVOKE ALL ON public.users, public.student_accounts, public.audit_events FROM PUBLIC"
    )
    op.execute("GRANT USAGE ON SCHEMA public, published_knowledge TO tutorbot_runtime")
    op.execute("GRANT SELECT, INSERT ON public.users, public.student_accounts TO tutorbot_runtime")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA published_knowledge TO tutorbot_runtime")
    op.execute("GRANT INSERT ON public.audit_events TO tutorbot_runtime, tutorbot_admin")
    op.execute("GRANT USAGE ON SCHEMA public, global_knowledge TO tutorbot_admin")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "
        "global_knowledge TO tutorbot_admin"
    )
    op.execute("GRANT SELECT ON public.audit_events TO tutorbot_admin")


def downgrade() -> None:
    op.execute("DROP SCHEMA published_knowledge CASCADE")
    op.execute("DROP SCHEMA global_knowledge CASCADE")
    op.drop_table("audit_events")
    op.execute("DROP FUNCTION public.prevent_audit_mutation()")
