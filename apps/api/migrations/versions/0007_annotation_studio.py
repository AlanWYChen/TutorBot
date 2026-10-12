"""Private maintainer rendering and versioned structured annotations."""

from alembic import op

revision = "0007_annotation_studio"
down_revision = "0006_page_rendering"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE global_knowledge.jobs DROP CONSTRAINT jobs_kind_check")
    op.execute(
        "ALTER TABLE global_knowledge.jobs ADD CONSTRAINT jobs_kind_check "
        "CHECK(kind IN ('verify_object','render_document'))"
    )
    op.execute("GRANT INSERT ON global_knowledge.storage_objects TO tutorbot_admin_worker")
    for table in ("document_pages", "document_regions"):
        op.execute(f"GRANT SELECT,INSERT ON global_knowledge.{table} TO tutorbot_admin_worker")
    # Annotation working data never becomes runtime retrieval, even via a status flag.
    op.execute("DROP VIEW published_knowledge.maintainer_annotations")

    op.execute(
        "ALTER TABLE global_knowledge.maintainer_annotations "
        "ADD COLUMN payload jsonb NOT NULL DEFAULT '{}', "
        "ADD COLUMN revision integer NOT NULL DEFAULT 1 CHECK(revision>0), "
        "ADD COLUMN crop_manifest_id uuid REFERENCES global_knowledge.storage_objects(id), "
        "ADD COLUMN source_sha256 text"
    )
    op.execute("""
        CREATE TABLE global_knowledge.annotation_revisions (
            id uuid PRIMARY KEY,
            annotation_id uuid NOT NULL REFERENCES global_knowledge.maintainer_annotations(id),
            revision integer NOT NULL CHECK(revision>0),
            payload jsonb NOT NULL, created_by_admin_uid text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version=1),
            UNIQUE(annotation_id,revision)
        )
    """)
    op.execute("GRANT SELECT,INSERT ON global_knowledge.annotation_revisions TO tutorbot_admin")
    op.execute("REVOKE ALL ON global_knowledge.annotation_revisions FROM PUBLIC")
    op.execute("""
        CREATE FUNCTION global_knowledge.prevent_revision_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'annotation revisions are append only'; END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION global_knowledge.prevent_revision_mutation() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER annotation_revision_history BEFORE UPDATE OR DELETE ON "
        "global_knowledge.annotation_revisions FOR EACH ROW EXECUTE FUNCTION "
        "global_knowledge.prevent_revision_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE global_knowledge.annotation_revisions")
    op.execute("DROP FUNCTION global_knowledge.prevent_revision_mutation()")
    op.execute(
        "ALTER TABLE global_knowledge.maintainer_annotations DROP COLUMN source_sha256, "
        "DROP COLUMN crop_manifest_id, DROP COLUMN revision, DROP COLUMN payload"
    )
    op.execute(
        "CREATE VIEW published_knowledge.maintainer_annotations WITH (security_barrier=true) "
        "AS SELECT * FROM global_knowledge.maintainer_annotations WHERE status='published'"
    )
    op.execute("GRANT SELECT ON published_knowledge.maintainer_annotations TO tutorbot_runtime")
    op.execute("DELETE FROM global_knowledge.jobs WHERE kind='render_document'")
    op.execute("ALTER TABLE global_knowledge.jobs DROP CONSTRAINT jobs_kind_check")
    op.execute(
        "ALTER TABLE global_knowledge.jobs ADD CONSTRAINT jobs_kind_check "
        "CHECK(kind='verify_object')"
    )
    op.execute("REVOKE INSERT ON global_knowledge.storage_objects FROM tutorbot_admin_worker")
    for table in ("document_pages", "document_regions"):
        op.execute(f"REVOKE SELECT,INSERT ON global_knowledge.{table} FROM tutorbot_admin_worker")
