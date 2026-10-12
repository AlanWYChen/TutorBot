"""Reversible studio deletion and approvals bound to the current labels."""

from alembic import op
from sqlalchemy import text

revision = "0011_studio_workflow"
down_revision = "0010_holdout_retrieval"
branch_labels = None
depends_on = None


def views(live: bool) -> None:
    guard = (
        " AND NOT EXISTS (SELECT 1 FROM global_knowledge.dataset_source_partitions h "
        "WHERE h.source_sha256=d.sha256 AND h.partition='holdout')"
    )
    if live:
        guard += (
            " AND NOT EXISTS (SELECT 1 FROM global_knowledge.storage_objects o "
            "WHERE o.id=d.id AND o.deleted_at IS NOT NULL)"
        )
    for table, joins, condition in (
        ("documents", "", "d.status='published'"),
        (
            "document_pages",
            "JOIN global_knowledge.documents d ON c.document_id=d.id",
            "c.status='published' AND d.status='published'"
            + (" AND c.deleted_at IS NULL" if live else ""),
        ),
        (
            "document_regions",
            "JOIN global_knowledge.document_pages p ON c.page_id=p.id "
            "JOIN global_knowledge.documents d ON p.document_id=d.id",
            "c.status='published' AND p.status='published' AND d.status='published' "
            "AND c.kind<>'maintainer_annotation'" + (" AND p.deleted_at IS NULL" if live else ""),
        ),
        (
            "knowledge_chunks",
            "JOIN global_knowledge.knowledge_releases r ON c.publish_release_id=r.id "
            "JOIN global_knowledge.documents d ON c.document_id=d.id",
            "r.status='published' AND d.status='published'",
        ),
    ):
        alias = "d" if table == "documents" else "c"
        # Preserve the public view's existing column contract, including on downgrade.
        columns = (
            op.get_bind()
            .execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='published_knowledge' AND table_name=:table "
                    "ORDER BY ordinal_position"
                ),
                {"table": table},
            )
            .scalars()
        )
        select = ",".join(f'{alias}."{column}"' for column in columns)
        op.execute(
            f"CREATE OR REPLACE VIEW published_knowledge.{table} WITH (security_barrier=true) "
            f"AS SELECT {select} FROM global_knowledge.{table} {alias} {joins} "
            f"WHERE {condition}" + guard
        )


def upgrade() -> None:
    for table in ("document_pages", "maintainer_annotations"):
        op.execute(f"ALTER TABLE global_knowledge.{table} ADD COLUMN deleted_at timestamptz")
    op.execute("DROP TRIGGER immutable_dataset ON global_knowledge.dataset_case_reviews")
    op.execute(
        "ALTER TABLE global_knowledge.dataset_case_reviews ADD COLUMN "
        "annotation_revision integer NOT NULL DEFAULT 1 CHECK(annotation_revision>=1)"
    )
    op.execute(
        "UPDATE global_knowledge.dataset_case_reviews r SET "
        "annotation_revision=c.annotation_revision "
        "FROM global_knowledge.dataset_cases c WHERE c.dataset_id=r.dataset_id AND c.id=r.case_id"
    )
    op.execute(
        "ALTER TABLE global_knowledge.dataset_case_reviews DROP CONSTRAINT "
        "dataset_case_reviews_dataset_id_case_id_key"
    )
    op.execute(
        "ALTER TABLE global_knowledge.dataset_case_reviews ADD UNIQUE "
        "(dataset_id,case_id,annotation_revision)"
    )
    op.execute(
        "CREATE TRIGGER immutable_dataset BEFORE UPDATE OR DELETE ON "
        "global_knowledge.dataset_case_reviews FOR EACH ROW EXECUTE FUNCTION "
        "global_knowledge.prevent_revision_mutation()"
    )
    views(True)


def downgrade() -> None:
    views(False)
    op.execute("DROP TRIGGER immutable_dataset ON global_knowledge.dataset_case_reviews")
    op.execute(
        "DELETE FROM global_knowledge.dataset_case_reviews r USING "
        "global_knowledge.dataset_cases c WHERE r.dataset_id=c.dataset_id AND r.case_id=c.id "
        "AND r.annotation_revision<>c.annotation_revision"
    )
    op.execute(
        "ALTER TABLE global_knowledge.dataset_case_reviews DROP CONSTRAINT "
        "dataset_case_reviews_dataset_id_case_id_annotation_revision_key"
    )
    op.execute("ALTER TABLE global_knowledge.dataset_case_reviews DROP COLUMN annotation_revision")
    op.execute("ALTER TABLE global_knowledge.dataset_case_reviews ADD UNIQUE(dataset_id,case_id)")
    op.execute(
        "CREATE TRIGGER immutable_dataset BEFORE UPDATE OR DELETE ON "
        "global_knowledge.dataset_case_reviews FOR EACH ROW EXECUTE FUNCTION "
        "global_knowledge.prevent_revision_mutation()"
    )
    for table in ("maintainer_annotations", "document_pages"):
        op.execute(f"ALTER TABLE global_knowledge.{table} DROP COLUMN deleted_at")
