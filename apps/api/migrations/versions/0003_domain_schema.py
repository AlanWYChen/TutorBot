"""Initial domain schema. This migration is a frozen schema snapshot."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import SchemaItem

revision = "0003_domain_schema"
down_revision = "0002_service_boundaries"
branch_labels = None
depends_on = None
G = "global_knowledge"
S = "student_data"
STATUSES = "'draft','evaluating','approved','published','retired'"
GLOBAL: list[str] = []
PRIVATE: list[str] = []
APPEND_ONLY = {
    "student_responses",
    "marking_observations",
    "mistake_observations",
    "fingerprint_observations",
    "concept_evidence",
    "student_profile_revisions",
    "profile_revision_evidence",
    "hypothesis_evidence",
    "tutoring_messages",
    "student_interventions",
    "response_regions",
}


def col(
    name: str, kind: sa.types.TypeEngine, nullable: bool = False, default: str | None = None
) -> sa.Column:
    return sa.Column(
        name, kind, nullable=nullable, server_default=sa.text(default) if default else None
    )


def txt(name: str, nullable: bool = False) -> sa.Column:
    return col(name, sa.Text(), nullable)


def uid(name: str, nullable: bool = False) -> sa.Column:
    return col(name, sa.Uuid(), nullable)


def js(name: str, default: str = "'{}'::jsonb") -> sa.Column:
    return col(name, JSONB(), default=default)


def integer(name: str, default: str | None = None) -> sa.Column:
    return col(name, sa.Integer(), default=default)


def probability(name: str, nullable: bool = False) -> sa.Column:
    return col(name, sa.Float(), nullable)


def fk(name: str, target: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target), nullable=nullable)


def owned(name: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["student_id", name], [f"{S}.{target}.student_id", f"{S}.{target}.id"]
    )


def check(expression: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(expression)


def enum(name: str, values: str, default: str | None = None) -> list:
    return [col(name, sa.String(32), default=default), check(f"{name} IN ({values})")]


def table(schema: str, name: str, *fields: SchemaItem) -> None:
    common = [
        sa.Column("id", sa.Uuid(), primary_key=True),
        col("created_at", sa.DateTime(timezone=True), default="now()"),
        integer("schema_version", "1"),
        check("schema_version = 1"),
    ]
    if schema == S:
        common += [
            fk("student_id", "public.student_accounts.id"),
            sa.UniqueConstraint("student_id", "id"),
        ]
        PRIVATE.append(name)
    else:
        common += enum("status", STATUSES, "'draft'")
        GLOBAL.append(name)
    op.create_table(name, *common, *fields, schema=schema)
    if schema == S:
        op.create_index(f"ix_{name}_student", name, ["student_id"], schema=S)


def upgrade() -> None:
    GLOBAL.clear()
    PRIVATE.clear()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(f"CREATE SCHEMA {S}")
    for name in ("users", "student_accounts", "audit_events"):
        op.add_column(name, integer("schema_version", "1"))
        op.create_check_constraint(f"ck_{name}_schema_version", name, "schema_version=1")
    table(G, "subjects", txt("canonical_name"), sa.UniqueConstraint("canonical_name"))
    table(G, "programs", txt("organization"), txt("jurisdiction"))
    table(
        G,
        "curricula",
        fk("program_id", f"{G}.programs.id"),
        txt("course_code"),
        txt("course_name"),
        txt("level", True),
        integer("first_assessment"),
        col("last_assessment", sa.Integer(), True),
        txt("version"),
        check("last_assessment IS NULL OR last_assessment >= first_assessment"),
        sa.UniqueConstraint("program_id", "course_code", "version"),
    )
    op.add_column("student_accounts", fk("default_curriculum_id", f"{G}.curricula.id", True))
    # Alembic creates the foreign key when adding the column.
    table(
        G,
        "concepts",
        fk("subject_id", f"{G}.subjects.id"),
        txt("canonical_name"),
        sa.UniqueConstraint("subject_id", "canonical_name"),
    )
    table(
        G,
        "concept_prerequisites",
        fk("parent_id", f"{G}.concepts.id"),
        fk("child_id", f"{G}.concepts.id"),
        check("parent_id <> child_id"),
        sa.UniqueConstraint("parent_id", "child_id"),
    )
    table(
        G,
        "curriculum_concepts",
        fk("curriculum_id", f"{G}.curricula.id"),
        fk("concept_id", f"{G}.concepts.id"),
        txt("expected_depth"),
        sa.UniqueConstraint("curriculum_id", "concept_id"),
    )
    table(
        G,
        "fingerprint_traits",
        fk("subject_id", f"{G}.subjects.id"),
        txt("code"),
        txt("definition"),
        sa.UniqueConstraint("subject_id", "code"),
    )
    for schema in (G, S):
        extra = [txt("created_by_admin_uid")] if schema == G else []
        # Global provenance is an explicit maintainer author; private provenance is its account.
        if schema == G:
            state = []
        else:
            state = enum(
                "status", "'uploaded','processing','needs_review','ready','failed'", "'uploaded'"
            )
        table(
            schema,
            "documents",
            *extra,
            *state,
            txt("kind"),
            txt("object_key"),
            col("sha256", sa.String(64)),
            txt("media_type"),
            col("size_bytes", sa.BigInteger()),
            txt("source_authority"),
            js("license_metadata"),
            js("retention_metadata"),
            fk("curriculum_id", f"{G}.curricula.id", True),
            js("cohort_range"),
            check("sha256 ~ '^[0-9a-f]{64}$'"),
            check("size_bytes > 0"),
            sa.UniqueConstraint("object_key"),
        )
        document_fk = (
            owned("document_id", "documents")
            if schema == S
            else sa.ForeignKeyConstraint(["document_id"], [f"{G}.documents.id"])
        )
        table(
            schema,
            "document_pages",
            uid("document_id"),
            document_fk,
            integer("page_num"),
            js("dimensions"),
            txt("image_object_key"),
            check("page_num > 0"),
            sa.UniqueConstraint("document_id", "page_num"),
        )
        page_fk = (
            owned("page_id", "document_pages")
            if schema == S
            else sa.ForeignKeyConstraint(["page_id"], [f"{G}.document_pages.id"])
        )
        table(
            schema,
            "document_regions",
            uid("page_id"),
            page_fk,
            js("bbox"),
            txt("kind"),
            txt("crop_key", True),
            probability("extraction_confidence"),
            check("extraction_confidence BETWEEN 0 AND 1"),
        )
    for name in (
        "knowledge_releases",
        "skill_versions",
        "knowledge_chunks",
        "teaching_demonstrations",
    ):
        op.add_column(
            name, col("created_at", sa.DateTime(timezone=True), default="now()"), schema=G
        )
        op.add_column(name, integer("schema_version", "1"), schema=G)
        op.create_check_constraint(f"ck_{name}_schema_version", name, "schema_version=1", schema=G)
    for name, fields in {
        "knowledge_releases": [
            txt("manifest_hash", True),
            col("published_at", sa.DateTime(timezone=True), True),
            js("manifest"),
        ],
        "skill_versions": [
            txt("artifact_key", True),
            txt("approved_by", True),
            col("published_at", sa.DateTime(timezone=True), True),
        ],
        "knowledge_chunks": [
            fk("document_id", f"{G}.documents.id", True),
            txt("section", True),
            js("page_range"),
            fk("parent_chunk_id", f"{G}.knowledge_chunks.id", True),
            js("source_locator"),
            txt("embedding_version", True),
        ],
        "teaching_demonstrations": [
            fk("source_document_id", f"{G}.documents.id", True),
            fk("concept_id", f"{G}.concepts.id", True),
            txt("intervention", True),
            txt("rationale", True),
            js("provenance"),
        ],
    }.items():
        for field in fields:
            op.add_column(name, field, schema=G)
    op.execute(f"ALTER TABLE {G}.knowledge_chunks ADD COLUMN embedding vector")
    op.execute(
        f"ALTER TABLE {G}.knowledge_chunks ADD CONSTRAINT ck_chunk_document CHECK "
        f"(document_id IS NOT NULL) NOT VALID"
    )
    op.execute(
        f"ALTER TABLE {G}.teaching_demonstrations ADD CONSTRAINT "
        "ck_demonstration_source CHECK (source_document_id IS NOT NULL) NOT VALID"
    )
    table(
        G,
        "maintainer_annotations",
        fk("region_id", f"{G}.document_regions.id"),
        txt("created_by_admin_uid"),
        txt("annotation"),
        txt("rationale"),
    )
    table(
        G,
        "teaching_strategies",
        fk("skill_id", f"{G}.skill_versions.id"),
        txt("trigger"),
        js("steps", "'[]'::jsonb"),
        js("evidence_links", "'[]'::jsonb"),
        txt("admin_approval", True),
    )
    table(
        G,
        "rubric_versions",
        fk("curriculum_id", f"{G}.curricula.id"),
        txt("assignment_type"),
        js("cohort_range"),
        fk("source_document_id", f"{G}.documents.id"),
        js("criteria"),
        txt("version"),
    )
    table(
        G,
        "evaluation_cases",
        txt("task"),
        js("expected_result"),
        fk("source_document_id", f"{G}.documents.id", True),
        fk("demonstration_id", f"{G}.teaching_demonstrations.id", True),
        *enum("partition", "'development','holdout'"),
        check("num_nonnulls(source_document_id, demonstration_id) = 1"),
    )
    table(
        G,
        "evaluation_runs",
        fk("release_candidate", f"{G}.skill_versions.id"),
        fk("knowledge_release_id", f"{G}.knowledge_releases.id", True),
        js("metric_results"),
        *enum("verdict", "'pending','passed','failed'", "'pending'"),
    )
    table(S, "examiners", txt("display_label"))
    table(
        S,
        "assessments",
        uid("document_id"),
        owned("document_id", "documents"),
        uid("examiner_id", True),
        owned("examiner_id", "examiners"),
        fk("curriculum_id", f"{G}.curricula.id", True),
        txt("type"),
        *enum("verified_state", "'unverified','needs_review','verified'", "'unverified'"),
    )
    table(
        S,
        "questions",
        uid("assessment_id"),
        owned("assessment_id", "assessments"),
        uid("region_id"),
        owned("region_id", "document_regions"),
        txt("prompt_text"),
        col("marks_possible", sa.Numeric(10, 2), True),
        check("marks_possible >= 0"),
    )
    table(
        S,
        "question_concepts",
        uid("question_id"),
        owned("question_id", "questions"),
        fk("concept_id", f"{G}.concepts.id"),
        sa.UniqueConstraint("question_id", "concept_id"),
    )
    table(
        S,
        "student_responses",
        uid("question_id"),
        owned("question_id", "questions"),
        txt("response_text"),
        js("ordered_steps", "'[]'::jsonb"),
        *enum(
            "correctness_status", "'unknown','correct','partially_correct','incorrect'", "'unknown'"
        ),
        uid("supersedes_id", True),
        owned("supersedes_id", "student_responses"),
    )
    table(
        S,
        "response_regions",
        uid("response_id"),
        owned("response_id", "student_responses"),
        uid("region_id"),
        owned("region_id", "document_regions"),
        sa.UniqueConstraint("response_id", "region_id"),
    )
    table(
        S,
        "marking_observations",
        uid("question_id"),
        owned("question_id", "questions"),
        col("marks_awarded", sa.Numeric(10, 2), True),
        txt("raw_annotation"),
        uid("source_region"),
        owned("source_region", "document_regions"),
        txt("explicit_reason", True),
        txt("verified_by", True),
        check("marks_awarded >= 0"),
        uid("supersedes_id", True),
        owned("supersedes_id", "marking_observations"),
    )
    for name in ("mistake_observations", "fingerprint_observations"):
        extra = (
            [
                txt("error_type"),
                fk("concept_id", f"{G}.concepts.id"),
                txt("interpretation"),
                probability("confidence"),
                check("confidence BETWEEN 0 AND 1"),
                *enum("review_status", "'unreviewed','verified','rejected'", "'unreviewed'"),
            ]
            if name == "mistake_observations"
            else [
                fk("trait_id", f"{G}.fingerprint_traits.id"),
                txt("dimension"),
                txt("value"),
                probability("certainty"),
                check("certainty BETWEEN 0 AND 1"),
                *enum("observed_vs_inferred", "'observed','inferred','not_observed'"),
            ]
        )
        table(
            S,
            name,
            uid("question_id"),
            owned("question_id", "questions"),
            uid("evidence_region"),
            owned("evidence_region", "document_regions"),
            *extra,
            uid("supersedes_id", True),
            owned("supersedes_id", name),
        )
    table(
        S,
        "student_learning_profiles",
        fk("subject_id", f"{G}.subjects.id"),
        txt("current_summary"),
        integer("summary_version", "0"),
        col("revised_at", sa.DateTime(timezone=True), default="now()"),
        check("summary_version >= 0"),
        sa.UniqueConstraint("student_id", "subject_id"),
    )
    table(
        S,
        "assignments",
        uid("document_id", True),
        owned("document_id", "documents"),
        fk("curriculum_id", f"{G}.curricula.id", True),
        txt("assignment_type"),
        txt("stage", True),
        fk("rubric_release_id", f"{G}.rubric_versions.id", True),
        probability("classification_confidence"),
        check("classification_confidence BETWEEN 0 AND 1"),
        col("confirmed_by_user", sa.Boolean(), default="false"),
        js("resolved_context"),
    )
    table(
        S,
        "tutoring_sessions",
        fk("skill_release_id", f"{G}.skill_versions.id"),
        fk("knowledge_release_id", f"{G}.knowledge_releases.id"),
        uid("assignment_id", True),
        owned("assignment_id", "assignments"),
    )
    table(
        S,
        "tutoring_messages",
        uid("session_id"),
        owned("session_id", "tutoring_sessions"),
        *enum("role", "'student','tutor'"),
        txt("content"),
        js("citations", "'[]'::jsonb"),
    )
    table(
        S,
        "concept_evidence",
        uid("question_id", True),
        owned("question_id", "questions"),
        uid("session_id", True),
        owned("session_id", "tutoring_sessions"),
        fk("concept_id", f"{G}.concepts.id"),
        txt("observed_performance"),
        probability("quality"),
        check("quality BETWEEN 0 AND 1"),
        check("num_nonnulls(question_id, session_id) = 1"),
    )
    for name, key, target in [
        ("student_concept_states", "concept_id", "concepts"),
        ("student_trait_states", "trait_id", "fingerprint_traits"),
    ]:
        table(
            S,
            name,
            fk(key, f"{G}.{target}.id"),
            fk("course_id", f"{G}.curricula.id", True),
            txt("context_scope"),
            *enum(
                "level",
                "'proficient','developing','needs_support','not_observed','insufficient_evidence'",
                "'insufficient_evidence'",
            ),
            *enum("trend", "'unknown','stable','improving','declining'", "'unknown'"),
            integer("evidence_count", "0"),
            probability("uncertainty"),
            col("updated_at", sa.DateTime(timezone=True), default="now()"),
            check("evidence_count >= 0"),
            check("uncertainty BETWEEN 0 AND 1"),
            check("evidence_count > 0 OR level IN ('not_observed','insufficient_evidence')"),
        )
        op.execute(
            f"CREATE UNIQUE INDEX uq_{name}_context ON {S}.{name} "
            f"(student_id,{key},course_id,context_scope) NULLS NOT DISTINCT"
        )
    table(
        S,
        "student_profile_revisions",
        uid("profile_id"),
        owned("profile_id", "student_learning_profiles"),
        integer("revision"),
        txt("summary"),
        txt("algorithm_version"),
        check("revision > 0"),
        sa.UniqueConstraint("profile_id", "revision"),
    )
    table(
        S,
        "profile_revision_evidence",
        uid("revision_id"),
        owned("revision_id", "student_profile_revisions"),
        uid("concept_evidence_id", True),
        owned("concept_evidence_id", "concept_evidence"),
        uid("mistake_id", True),
        owned("mistake_id", "mistake_observations"),
        uid("fingerprint_id", True),
        owned("fingerprint_id", "fingerprint_observations"),
        check("num_nonnulls(concept_evidence_id,mistake_id,fingerprint_id) = 1"),
    )
    table(
        S,
        "student_interventions",
        uid("session_id"),
        owned("session_id", "tutoring_sessions"),
        fk("strategy_id", f"{G}.teaching_strategies.id"),
        txt("rationale"),
        txt("observed_outcome", True),
        uid("evidence_id", True),
        owned("evidence_id", "concept_evidence"),
    )
    table(
        S,
        "student_memory_chunks",
        txt("text"),
        txt("embedding_version", True),
        uid("question_id", True),
        owned("question_id", "questions"),
        uid("session_id", True),
        owned("session_id", "tutoring_sessions"),
        uid("profile_id", True),
        owned("profile_id", "student_learning_profiles"),
        *enum("access_scope", "'student'", "'student'"),
        check("num_nonnulls(question_id,session_id,profile_id) = 1"),
    )
    op.execute(f"ALTER TABLE {S}.student_memory_chunks ADD COLUMN embedding vector")
    table(
        S,
        "examiner_hypotheses",
        uid("examiner_id"),
        owned("examiner_id", "examiners"),
        fk("curriculum_id", f"{G}.curricula.id"),
        txt("rule"),
        js("context"),
        integer("evidence_count", "0"),
        integer("contradiction_count", "0"),
        txt("version"),
        *enum("status", "'tentative','supported','contradicted','retired'", "'tentative'"),
        check("evidence_count >= 0 AND contradiction_count >= 0"),
    )
    table(
        S,
        "hypothesis_evidence",
        uid("hypothesis_id"),
        owned("hypothesis_id", "examiner_hypotheses"),
        uid("marking_observation_id"),
        owned("marking_observation_id", "marking_observations"),
        *enum("polarity", "'supports','contradicts'"),
        sa.UniqueConstraint("hypothesis_id", "marking_observation_id"),
    )
    for name in PRIVATE:
        op.execute(f"ALTER TABLE {S}.{name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {S}.{name} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY student_scope ON {S}.{name} TO tutorbot_runtime USING "
            f"(student_id = nullif(current_setting('app.student_id', "
            f"true),'')::uuid) WITH CHECK (student_id = "
            f"nullif(current_setting('app.student_id', true),'')::uuid)"
        )
        grants = "SELECT, INSERT" if name in APPEND_ONLY else "SELECT, INSERT, UPDATE, DELETE"
        op.execute(f"GRANT {grants} ON {S}.{name} TO tutorbot_runtime")
    op.execute(f"REVOKE ALL ON SCHEMA {S} FROM PUBLIC")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {S} FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA {S} TO tutorbot_runtime")
    for name in GLOBAL:
        if name in {"document_pages", "document_regions"}:
            continue
        op.execute(
            f"CREATE VIEW published_knowledge.{name} WITH (security_barrier=true) "
            f"AS SELECT * FROM {G}.{name} WHERE status='published'"
        )
    for name, joins in {
        "document_pages": f"JOIN {G}.documents d ON c.document_id=d.id",
        "document_regions": (
            f"JOIN {G}.document_pages p ON c.page_id=p.id "
            f"JOIN {G}.documents d ON p.document_id=d.id"
        ),
    }.items():
        op.execute(
            f"CREATE VIEW published_knowledge.{name} WITH (security_barrier=true) "
            f"AS SELECT c.* FROM {G}.{name} c {joins} "
            "WHERE c.status='published' AND d.status='published'"
        )
    # Views retain existing column order; append new columns with CREATE OR REPLACE.
    for name in ("knowledge_releases", "skill_versions"):
        op.execute(
            f"CREATE OR REPLACE VIEW published_knowledge.{name} WITH "
            f"(security_barrier=true) AS SELECT * FROM {G}.{name} WHERE "
            f"status='published'"
        )
    op.execute(
        f"CREATE OR REPLACE VIEW published_knowledge.knowledge_chunks WITH "
        f"(security_barrier=true) AS SELECT c.* FROM {G}.knowledge_chunks c JOIN "
        f"{G}.knowledge_releases r ON c.publish_release_id=r.id JOIN {G}.documents "
        f"d ON c.document_id=d.id WHERE r.status='published' AND "
        f"d.status='published'"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {G} TO tutorbot_admin"
    )
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA published_knowledge TO tutorbot_runtime")
    for schema, name, columns in [
        (G, "knowledge_chunks", ["document_id", "publish_release_id"]),
        (G, "documents", ["curriculum_id", "status"]),
        (S, "concept_evidence", ["student_id", "concept_id", "created_at"]),
        (S, "fingerprint_observations", ["student_id", "trait_id", "created_at"]),
        (S, "questions", ["student_id", "assessment_id"]),
        (S, "tutoring_messages", ["student_id", "session_id", "created_at"]),
    ]:
        op.create_index(f"ix_{name}_retrieval", name, columns, schema=schema)


def downgrade() -> None:
    op.execute("DROP SCHEMA published_knowledge CASCADE")
    op.execute(f"DROP SCHEMA {S} CASCADE")
    for name in ("users", "student_accounts", "audit_events"):
        op.drop_column(name, "schema_version")
    op.drop_column("student_accounts", "default_curriculum_id")
    # Drop new global tables in reverse dependency order.
    for name in [
        "evaluation_runs",
        "evaluation_cases",
        "rubric_versions",
        "teaching_strategies",
        "maintainer_annotations",
        "document_regions",
        "document_pages",
        "documents",
        "fingerprint_traits",
        "curriculum_concepts",
        "concept_prerequisites",
        "concepts",
        "curricula",
        "programs",
        "subjects",
    ]:
        op.execute(f"DROP TABLE {G}.{name} CASCADE")
    for name, fields in {
        "knowledge_releases": ["manifest_hash", "published_at", "manifest"],
        "skill_versions": ["artifact_key", "approved_by", "published_at"],
        "knowledge_chunks": [
            "document_id",
            "section",
            "page_range",
            "parent_chunk_id",
            "source_locator",
            "embedding_version",
            "embedding",
        ],
        "teaching_demonstrations": [
            "source_document_id",
            "concept_id",
            "intervention",
            "rationale",
            "provenance",
        ],
    }.items():
        for field in fields + ["created_at", "schema_version"]:
            op.drop_column(name, field, schema=G)
    op.execute("CREATE SCHEMA published_knowledge")
    op.execute("REVOKE ALL ON SCHEMA published_knowledge FROM PUBLIC")
    for name in ("knowledge_releases", "skill_versions"):
        op.execute(
            f"CREATE VIEW published_knowledge.{name} WITH (security_barrier=true) "
            f"AS SELECT * FROM {G}.{name} WHERE status='published'"
        )
    op.execute(
        f"CREATE VIEW published_knowledge.knowledge_chunks WITH "
        f"(security_barrier=true) AS SELECT c.* FROM {G}.knowledge_chunks c JOIN "
        f"{G}.knowledge_releases r ON c.publish_release_id=r.id WHERE "
        f"r.status='published'"
    )
    op.execute("GRANT USAGE ON SCHEMA published_knowledge TO tutorbot_runtime")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA published_knowledge TO tutorbot_runtime")
