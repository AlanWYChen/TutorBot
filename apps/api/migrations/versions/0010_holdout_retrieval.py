"""Exclude held-out sources/examples from every source-bearing runtime view."""

from alembic import op

revision = "0010_holdout_retrieval"
down_revision = "0009_annotation_datasets"
branch_labels = None
depends_on = None


def replace_views(exclude: bool) -> None:
    guard = (
        (
            " AND NOT EXISTS (SELECT 1 FROM global_knowledge.dataset_source_partitions h "
            "WHERE h.source_sha256=d.sha256 AND h.partition='holdout')"
        )
        if exclude
        else ""
    )
    op.execute(
        "CREATE OR REPLACE VIEW published_knowledge.documents WITH (security_barrier=true) "
        "AS SELECT d.* FROM global_knowledge.documents d WHERE d.status='published'" + guard
    )
    for name, joins, condition in (
        (
            "document_pages",
            "JOIN global_knowledge.documents d ON c.document_id=d.id",
            "c.status='published' AND d.status='published'",
        ),
        (
            "document_regions",
            "JOIN global_knowledge.document_pages p ON c.page_id=p.id "
            "JOIN global_knowledge.documents d ON p.document_id=d.id",
            "c.status='published' AND p.status='published' AND d.status='published' "
            "AND c.kind<>'maintainer_annotation'",
        ),
        (
            "knowledge_chunks",
            "JOIN global_knowledge.knowledge_releases r ON c.publish_release_id=r.id "
            "JOIN global_knowledge.documents d ON c.document_id=d.id",
            "r.status='published' AND d.status='published'",
        ),
    ):
        op.execute(
            f"CREATE OR REPLACE VIEW published_knowledge.{name} WITH (security_barrier=true) "
            f"AS SELECT c.* FROM global_knowledge.{name} c {joins} WHERE {condition}" + guard
        )
    # Teaching demonstrations have no runtime view or grants; keep them private.


def upgrade() -> None:
    replace_views(True)


def downgrade() -> None:
    replace_views(False)
