"""Keep annotation source regions out of runtime retrieval regardless of status flags."""

from alembic import op

revision = "0008_private_annotation_regions"
down_revision = "0007_annotation_studio"
branch_labels = None
depends_on = None


def view(predicate: str) -> None:
    op.execute(f"""
        CREATE OR REPLACE VIEW published_knowledge.document_regions
        WITH (security_barrier=true) AS SELECT c.* FROM global_knowledge.document_regions c
        JOIN global_knowledge.document_pages p ON c.page_id=p.id
        JOIN global_knowledge.documents d ON p.document_id=d.id
        WHERE c.status='published' AND p.status='published' AND d.status='published'
        {predicate}
    """)


def upgrade() -> None:
    view("AND c.kind<>'maintainer_annotation'")


def downgrade() -> None:
    view("")
