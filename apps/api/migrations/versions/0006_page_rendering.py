"""Render jobs and append-only page/candidate writes by the runtime worker."""

from alembic import op

revision = "0006_page_rendering"
down_revision = "0005_private_io"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE student_data.jobs DROP CONSTRAINT jobs_kind_check")
    op.execute(
        "ALTER TABLE student_data.jobs ADD CONSTRAINT jobs_kind_check "
        "CHECK(kind IN ('verify_object','render_document'))"
    )
    op.execute("GRANT INSERT ON student_data.storage_objects TO tutorbot_runtime_worker")
    for table in ("document_pages", "document_regions"):
        op.execute(f"GRANT SELECT,INSERT ON student_data.{table} TO tutorbot_runtime_worker")
        op.execute(
            f"CREATE POLICY worker_scope ON student_data.{table} "
            "TO tutorbot_runtime_worker USING(true) WITH CHECK(true)"
        )


def downgrade() -> None:
    # Original documents/assessments and previously rendered page evidence are retained.
    op.execute("ALTER TABLE student_data.jobs NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM student_data.jobs WHERE kind='render_document'")
    op.execute("ALTER TABLE student_data.jobs FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE student_data.jobs DROP CONSTRAINT jobs_kind_check")
    op.execute(
        "ALTER TABLE student_data.jobs ADD CONSTRAINT jobs_kind_check CHECK(kind='verify_object')"
    )
    op.execute("REVOKE INSERT ON student_data.storage_objects FROM tutorbot_runtime_worker")
    for table in ("document_pages", "document_regions"):
        op.execute(f"DROP POLICY worker_scope ON student_data.{table}")
        op.execute(f"REVOKE SELECT,INSERT ON student_data.{table} FROM tutorbot_runtime_worker")
