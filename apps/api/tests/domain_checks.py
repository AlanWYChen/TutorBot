"""Synthetic schema fixtures; nothing is loaded into the app's live database."""

from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import Engine, inspect


def verify_domain(scratch_url: str, engine: Engine, service_url: str) -> None:
    inspector = inspect(engine)
    private = inspector.get_table_names(schema="student_data")
    global_tables = inspector.get_table_names(schema="global_knowledge")
    assert len(private) == 27
    assert len(global_tables) == 27
    for table in private:
        columns = {
            column["name"]: column for column in inspector.get_columns(table, schema="student_data")
        }
        assert columns["student_id"]["nullable"] is False
        assert "schema_version" in columns and "created_at" in columns
        for relation in inspector.get_foreign_keys(table, schema="student_data"):
            if relation["referred_schema"] == "student_data":
                assert "student_id" in relation["constrained_columns"]
    # Maintainer sources cannot acquire implicit student dependencies.
    for table in global_tables:
        assert all(
            fk["referred_schema"] != "student_data"
            for fk in inspector.get_foreign_keys(table, schema="global_knowledge")
        )
    a, b, subject, concept = (uuid4() for _ in range(4))
    doc_a, doc_b, page, profile_a, profile_b, memory = (uuid4() for _ in range(6))
    uid_by_student = {}
    with psycopg.connect(scratch_url, autocommit=True) as owner:
        for student in (a, b):
            user = uuid4()
            uid_by_student[student] = str(user)
            owner.execute(
                "INSERT INTO users (id,firebase_uid,role) VALUES (%s,%s,'student')",
                (user, str(user)),
            )
            owner.execute(
                "INSERT INTO student_accounts (id,user_id) VALUES (%s,%s)", (student, user)
            )
        owner.execute(
            "INSERT INTO global_knowledge.subjects (id,canonical_name,status) "
            "VALUES (%s,'synthetic mathematics','published')",
            (subject,),
        )
        owner.execute(
            "INSERT INTO global_knowledge.concepts (id,subject_id,canonical_name,status) "
            "VALUES (%s,%s,'synthetic algebra','published')",
            (concept, subject),
        )
        for student, doc, profile in [(a, doc_a, profile_a), (b, doc_b, profile_b)]:
            owner.execute(
                "INSERT INTO student_data.documents "
                "(id,student_id,kind,object_key,sha256,media_type,size_bytes,source_authority) "
                "VALUES (%s,%s,'marked_test',%s,%s,'application/pdf',100,'student')",
                (doc, student, str(doc), "b" * 64),
            )
            owner.execute(
                "INSERT INTO student_data.student_learning_profiles "
                "(id,student_id,subject_id,current_summary) VALUES (%s,%s,%s,'synthetic')",
                (profile, student, subject),
            )
        owner.execute(
            "INSERT INTO student_data.student_memory_chunks "
            "(id,student_id,text,profile_id) VALUES (%s,%s,'private synthetic memory',%s)",
            (memory, b, profile_b),
        )
        policies = owner.execute(
            "SELECT count(*) FROM pg_policies WHERE schemaname='student_data' "
            "AND policyname!='worker_scope'"
        ).fetchone()
        assert policies == (len(private),)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            owner.execute(
                "INSERT INTO student_data.document_pages "
                "(id,student_id,document_id,page_num,dimensions,image_object_key) "
                "VALUES (%s,%s,%s,1,'{}','synthetic')",
                (page, a, doc_b),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            owner.execute(
                "INSERT INTO student_data.student_concept_states "
                "(id,student_id,concept_id,context_scope,level,uncertainty) "
                "VALUES (%s,%s,%s,'algebra','proficient',1)",
                (uuid4(), a, concept),
            )
        global_release = owner.execute(
            "SELECT id FROM global_knowledge.knowledge_releases LIMIT 1"
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.ForeignKeyViolation, match="document_id"):
            owner.execute(
                "INSERT INTO global_knowledge.knowledge_chunks "
                "(id,publish_release_id,content_text,document_id) VALUES (%s,%s,'bad',%s)",
                (uuid4(), global_release, doc_a),
            )
        page_b, region_b, assessment_a = uuid4(), uuid4(), uuid4()
        owner.execute(
            "INSERT INTO student_data.document_pages "
            "(id,student_id,document_id,page_num,dimensions,image_object_key) "
            "VALUES (%s,%s,%s,1,'{}','fixture')",
            (page_b, a, doc_a),
        )
        owner.execute(
            "INSERT INTO student_data.document_regions "
            "(id,student_id,page_id,bbox,kind,extraction_confidence) "
            "VALUES (%s,%s,%s,'{}','question',1)",
            (region_b, a, page_b),
        )
        owner.execute(
            "INSERT INTO student_data.assessments "
            "(id,student_id,document_id,type) VALUES (%s,%s,%s,'marked_test')",
            (assessment_a, b, doc_b),
        )
        with pytest.raises(psycopg.errors.RaiseException, match="question source"):
            owner.execute(
                "INSERT INTO student_data.questions "
                "(id,student_id,assessment_id,region_id,prompt_text) "
                "VALUES (%s,%s,%s,%s,'cross-student')",
                (uuid4(), a, assessment_a, region_b),
            )
        second_doc = uuid4()
        owner.execute(
            "INSERT INTO student_data.documents "
            "(id,student_id,kind,object_key,sha256,media_type,size_bytes,source_authority) "
            "VALUES (%s,%s,'test',%s,%s,'application/pdf',100,'student')",
            (second_doc, a, str(second_doc), "c" * 64),
        )
        assessment_other_doc = uuid4()
        owner.execute(
            "INSERT INTO student_data.assessments "
            "(id,student_id,document_id,type) VALUES (%s,%s,%s,'marked_test')",
            (assessment_other_doc, a, second_doc),
        )
        with pytest.raises(psycopg.errors.RaiseException, match="question source"):
            owner.execute(
                "INSERT INTO student_data.questions "
                "(id,student_id,assessment_id,region_id,prompt_text) "
                "VALUES (%s,%s,%s,%s,'wrong-document')",
                (uuid4(), a, assessment_other_doc, region_b),
            )
        with pytest.raises(psycopg.errors.RaiseException, match="published releases"):
            owner.execute(
                "INSERT INTO student_data.tutoring_sessions "
                "(id,student_id,skill_release_id,knowledge_release_id) "
                "VALUES (%s,%s,%s,%s)",
                (uuid4(), a, uuid4(), uuid4()),
            )
    # Actual restricted runtime connection. Database name is scratch, credentials are runtime.

    runtime_url = service_url.rsplit("/", 1)[0] + "/" + scratch_url.rsplit("/", 1)[1]
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.auth.identity import Principal
    from app.domain.scope import StudentDomain

    scoped_engine = create_engine(runtime_url.replace("postgresql://", "postgresql+psycopg://"))
    with Session(scoped_engine) as session, session.begin():
        domain = StudentDomain(session, Principal(uid=uid_by_student[a], role="student"))
        assert domain.student_id == a
        assert [row["id"] for row in domain.profile_summaries()] == [profile_a]
        assert domain.memory_for_question(uuid4()) == []
    scoped_engine.dispose()
    with psycopg.connect(scratch_url, autocommit=True) as owner:
        draft_skill, published_skill = uuid4(), uuid4()
        for skill, status in ((draft_skill, "draft"), (published_skill, "published")):
            owner.execute(
                "INSERT INTO global_knowledge.skill_versions "
                "(id,name,version,status,content_hash) VALUES (%s,'fixture','v1',%s,'fixture')",
                (skill, status),
            )
    with psycopg.connect(runtime_url) as runtime:
        assert (
            runtime.execute("SELECT id FROM student_data.student_learning_profiles").fetchall()
            == []
        )
        runtime.execute("SELECT set_config('app.student_id',%s,true)", (str(a),))
        with (
            pytest.raises(psycopg.errors.RaiseException, match="published releases"),
            runtime.transaction(),
        ):
            runtime.execute(
                "INSERT INTO student_data.tutoring_sessions "
                "(id,student_id,skill_release_id,knowledge_release_id) "
                "VALUES (%s,%s,%s,%s)",
                (uuid4(), a, draft_skill, global_release),
            )
        runtime.execute(
            "INSERT INTO student_data.tutoring_sessions "
            "(id,student_id,skill_release_id,knowledge_release_id) "
            "VALUES (%s,%s,%s,%s)",
            (uuid4(), a, published_skill, global_release),
        )
        for table in global_tables:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), runtime.transaction():
                runtime.execute(f"SELECT * FROM global_knowledge.{table}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege), runtime.transaction():
                runtime.execute(f"UPDATE global_knowledge.{table} SET id=id")

        assert runtime.execute(
            "SELECT id FROM student_data.student_learning_profiles"
        ).fetchall() == [(profile_a,)]
        assert runtime.execute("SELECT id FROM student_data.student_memory_chunks").fetchall() == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege), runtime.transaction():
            runtime.execute(
                "INSERT INTO student_data.student_memory_chunks "
                "(id,student_id,text,profile_id) VALUES (%s,%s,'cross-scope',%s)",
                (uuid4(), b, profile_b),
            )
        for table in [
            "concept_evidence",
            "fingerprint_observations",
            "student_profile_revisions",
            "tutoring_messages",
            "marking_observations",
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), runtime.transaction():
                runtime.execute(f"UPDATE student_data.{table} SET id=id")
            with pytest.raises(psycopg.errors.InsufficientPrivilege), runtime.transaction():
                runtime.execute(f"DELETE FROM student_data.{table}")
        runtime.commit()
        assert (
            runtime.execute("SELECT id FROM student_data.student_learning_profiles").fetchall()
            == []
        )
        runtime.execute("SELECT set_config('app.student_id',%s,true)", (str(b),))
        assert runtime.execute("SELECT id FROM student_data.student_memory_chunks").fetchall() == [
            (memory,)
        ]
        for table in ("evaluation_cases", "evaluation_runs"):
            with pytest.raises(psycopg.errors.UndefinedTable), runtime.transaction():
                runtime.execute(f"SELECT * FROM published_knowledge.{table}")
        runtime.rollback()
        assert runtime.execute("SELECT id FROM student_data.student_memory_chunks").fetchall() == []
    import os

    admin_url = (
        os.environ["ADMIN_DATABASE_URL"].rsplit("/", 1)[0] + "/" + scratch_url.rsplit("/", 1)[1]
    )
    with psycopg.connect(admin_url, autocommit=True) as admin:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            admin.execute("SELECT * FROM student_data.student_memory_chunks")
