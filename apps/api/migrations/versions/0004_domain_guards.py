"""Guard source relationships, session release pins and evaluation partitions."""

from alembic import op

revision = "0004_domain_guards"
down_revision = "0003_domain_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Evaluation cases/runs are maintainer-only, including published holdout cases.
    for name in ("evaluation_cases", "evaluation_runs"):
        op.execute(f"DROP VIEW published_knowledge.{name}")
    op.execute("""
        CREATE FUNCTION student_data.check_question_source() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM student_data.assessments a
            JOIN student_data.document_regions r ON r.id=NEW.region_id
              AND r.student_id=NEW.student_id
            JOIN student_data.document_pages p ON p.id=r.page_id
              AND p.student_id=NEW.student_id
            WHERE a.id=NEW.assessment_id AND a.student_id=NEW.student_id
              AND a.document_id=p.document_id
          ) THEN RAISE EXCEPTION 'question source must belong to its assessment'; END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER question_source BEFORE INSERT OR UPDATE ON student_data.questions
        FOR EACH ROW EXECUTE FUNCTION student_data.check_question_source()
    """)
    op.execute("""
        CREATE FUNCTION student_data.check_session_releases() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM published_knowledge.skill_versions
                         WHERE id=NEW.skill_release_id)
            OR NOT EXISTS (SELECT 1 FROM published_knowledge.knowledge_releases
                           WHERE id=NEW.knowledge_release_id)
          THEN RAISE EXCEPTION 'session requires published releases'; END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER session_releases BEFORE INSERT OR UPDATE ON student_data.tutoring_sessions
        FOR EACH ROW EXECUTE FUNCTION student_data.check_session_releases()
    """)
    for function in ("check_question_source", "check_session_releases"):
        op.execute(f"REVOKE ALL ON FUNCTION student_data.{function}() FROM PUBLIC")
    # A published region cannot reveal a page from a draft document or draft page.
    op.execute("""
        CREATE OR REPLACE VIEW published_knowledge.document_regions
        WITH (security_barrier=true) AS SELECT c.* FROM global_knowledge.document_regions c
        JOIN global_knowledge.document_pages p ON c.page_id=p.id
        JOIN global_knowledge.documents d ON p.document_id=d.id
        WHERE c.status='published' AND p.status='published' AND d.status='published'
    """)


def downgrade() -> None:
    for name, table in (
        ("question_source", "questions"),
        ("session_releases", "tutoring_sessions"),
    ):
        op.execute(f"DROP TRIGGER {name} ON student_data.{table}")
    for function in ("check_question_source", "check_session_releases"):
        op.execute(f"DROP FUNCTION student_data.{function}()")
    for name in ("evaluation_cases", "evaluation_runs"):
        op.execute(
            f"CREATE VIEW published_knowledge.{name} WITH (security_barrier=true) "
            f"AS SELECT * FROM global_knowledge.{name} WHERE status='published'"
        )
        op.execute(f"GRANT SELECT ON published_knowledge.{name} TO tutorbot_runtime")
    op.execute("""
        CREATE OR REPLACE VIEW published_knowledge.document_regions
        WITH (security_barrier=true) AS SELECT c.* FROM global_knowledge.document_regions c
        JOIN global_knowledge.document_pages p ON c.page_id=p.id
        JOIN global_knowledge.documents d ON p.document_id=d.id
        WHERE c.status='published' AND d.status='published'
    """)
