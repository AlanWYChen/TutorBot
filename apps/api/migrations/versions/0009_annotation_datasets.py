"""Private immutable annotation snapshots and globally locked dataset splits."""

from alembic import op

revision = "0009_annotation_datasets"
down_revision = "0008_private_annotation_regions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE global_knowledge.annotation_datasets (
            id uuid PRIMARY KEY, created_by_admin_uid text NOT NULL,
            name text NOT NULL, version text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version=1),
            UNIQUE(created_by_admin_uid,name,version)
        )
    """)
    for table, key in (
        ("dataset_source_partitions", "source_sha256"),
        ("dataset_question_partitions", "question_hash"),
    ):
        op.execute(f"""
            CREATE TABLE global_knowledge.{table} (
                {key} text PRIMARY KEY CHECK({key} ~ '^[a-f0-9]{{64}}$'),
                partition text NOT NULL CHECK(partition IN ('development','holdout')),
                UNIQUE({key},partition),
                created_at timestamptz NOT NULL DEFAULT now(),
                schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version=1)
            )
        """)
    op.execute("""
        CREATE TABLE global_knowledge.dataset_cases (
            dataset_id uuid NOT NULL REFERENCES global_knowledge.annotation_datasets(id),
            id uuid NOT NULL, document_id uuid NOT NULL REFERENCES global_knowledge.documents(id),
            annotation_id uuid NOT NULL REFERENCES global_knowledge.maintainer_annotations(id),
            annotation_revision integer NOT NULL, record jsonb NOT NULL,
            source_sha256 text NOT NULL,
            question_hash text NOT NULL,
            partition text NOT NULL CHECK(partition IN ('development','holdout')),
            created_at timestamptz NOT NULL DEFAULT now(),
            schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version=1),
            PRIMARY KEY(dataset_id,id),
            FOREIGN KEY(source_sha256,partition)
                REFERENCES global_knowledge.dataset_source_partitions(source_sha256,partition),
            FOREIGN KEY(question_hash,partition)
                REFERENCES global_knowledge.dataset_question_partitions(question_hash,partition),
            UNIQUE(dataset_id,annotation_id,annotation_revision),
            FOREIGN KEY(annotation_id,annotation_revision)
                REFERENCES global_knowledge.annotation_revisions(annotation_id,revision)
        )
    """)
    op.execute("""
        CREATE TABLE global_knowledge.dataset_case_reviews (
            id uuid PRIMARY KEY, dataset_id uuid NOT NULL, case_id uuid NOT NULL,
            reviewed_by_admin_uid text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
            schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version=1),
            FOREIGN KEY(dataset_id,case_id)
                REFERENCES global_knowledge.dataset_cases(dataset_id,id),
            UNIQUE(dataset_id,case_id)
        )
    """)
    tables = (
        "annotation_datasets",
        "dataset_source_partitions",
        "dataset_question_partitions",
        "dataset_cases",
        "dataset_case_reviews",
    )
    for table in tables:
        op.execute(f"REVOKE ALL ON global_knowledge.{table} FROM PUBLIC")
        op.execute(f"GRANT SELECT,INSERT ON global_knowledge.{table} TO tutorbot_admin")
        op.execute(
            f"CREATE TRIGGER immutable_dataset BEFORE UPDATE OR DELETE ON "
            f"global_knowledge.{table} FOR EACH ROW EXECUTE FUNCTION "
            "global_knowledge.prevent_revision_mutation()"
        )


def downgrade() -> None:
    for table in (
        "dataset_case_reviews",
        "dataset_cases",
        "dataset_source_partitions",
        "dataset_question_partitions",
        "annotation_datasets",
    ):
        op.execute(f"DROP TABLE global_knowledge.{table}")
