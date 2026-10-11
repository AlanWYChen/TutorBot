"""Use actual service logins, not SET ROLE in a privileged session."""

import os
from uuid import uuid4

import httpx
import psycopg
import pytest

from app.config import Settings
from tests.test_auth_integration import login

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_AUTH_INTEGRATION") != "1", reason="Requires service DB roles and APIs"
)


def test_runtime_global_permissions_and_published_filter() -> None:
    release_ids, skill_ids, chunk_ids = [[uuid4(), uuid4()] for _ in range(3)]
    demonstration = uuid4()
    document_ids = [uuid4(), uuid4()]
    admin_url = os.environ["ADMIN_DATABASE_URL"]
    runtime_url = Settings().database_url.get_secret_value()
    with (
        psycopg.connect(admin_url, autocommit=True) as admin,
        psycopg.connect(runtime_url, autocommit=True) as runtime,
    ):
        try:
            for i, status in enumerate(["draft", "published"]):
                admin.execute(
                    "INSERT INTO global_knowledge.knowledge_releases "
                    "(id,name,version,status,content_hash) VALUES "
                    "(%s,'fixture','v1',%s,'synthetic-hash')",
                    (release_ids[i], status),
                )
                admin.execute(
                    "INSERT INTO global_knowledge.skill_versions "
                    "(id,name,version,status,content_hash) VALUES "
                    "(%s,'fixture','v1',%s,'synthetic-hash')",
                    (skill_ids[i], status),
                )
                admin.execute(
                    "INSERT INTO global_knowledge.documents "
                    "(id,created_by_admin_uid,kind,object_key,sha256,media_type,size_bytes,"
                    "source_authority,status) VALUES (%s,'fixture','reference',%s,%s,"
                    "'application/pdf',100,'supplemental',%s)",
                    (document_ids[i], "fixture/" + str(document_ids[i]), "a" * 64, status),
                )
                admin.execute(
                    "INSERT INTO global_knowledge.knowledge_chunks "
                    "(id,publish_release_id,content_text,document_id) VALUES (%s,%s,%s,%s)",
                    (chunk_ids[i], release_ids[i], status + " fixture", document_ids[i]),
                )
            admin.execute(
                "INSERT INTO global_knowledge.teaching_demonstrations "
                "(id,created_by_admin_uid,scenario,source_document_id) VALUES "
                "(%s,'synthetic-maintainer','synthetic scenario',%s)",
                (demonstration, document_ids[1]),
            )
            assert runtime.execute(
                "SELECT id FROM published_knowledge.knowledge_releases WHERE id=ANY(%s)",
                (release_ids,),
            ).fetchall() == [(release_ids[1],)]
            assert runtime.execute(
                "SELECT id FROM published_knowledge.skill_versions WHERE id=ANY(%s)", (skill_ids,)
            ).fetchall() == [(skill_ids[1],)]
            assert runtime.execute(
                "SELECT id FROM published_knowledge.knowledge_chunks WHERE id=ANY(%s)", (chunk_ids,)
            ).fetchall() == [(chunk_ids[1],)]
            for table in [
                "knowledge_releases",
                "skill_versions",
                "knowledge_chunks",
                "teaching_demonstrations",
            ]:
                for statement in [
                    f"SELECT * FROM global_knowledge.{table}",
                    f"INSERT INTO global_knowledge.{table} DEFAULT VALUES",
                    f"UPDATE global_knowledge.{table} SET id=id",
                    f"DELETE FROM global_knowledge.{table}",
                    f"TRUNCATE global_knowledge.{table}",
                ]:
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        runtime.execute(statement)
            for statement in [
                "UPDATE published_knowledge.skill_versions SET name='changed'",
                "DELETE FROM published_knowledge.knowledge_releases",
                "INSERT INTO published_knowledge.skill_versions DEFAULT VALUES",
                "SET ROLE tutorbot_admin",
                "CREATE TABLE public.forbidden (id int)",
                "CREATE TEMP TABLE forbidden (id int)",
                "SELECT * FROM public.audit_events",
                "UPDATE public.audit_events SET outcome='success'",
                "DELETE FROM public.audit_events",
                "TRUNCATE public.audit_events",
            ]:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    runtime.execute(statement)
            for statement in [
                "SELECT * FROM public.student_accounts",
                "UPDATE public.audit_events SET outcome='success'",
                "DELETE FROM public.audit_events",
                "TRUNCATE public.audit_events",
            ]:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    admin.execute(statement)
            flags = runtime.execute(
                "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM "
                "pg_roles WHERE rolname=current_user"
            ).fetchone()
            assert flags == (False, False, False, False)
        finally:
            admin.execute(
                "DELETE FROM global_knowledge.teaching_demonstrations WHERE id=%s", (demonstration,)
            )
            admin.execute(
                "DELETE FROM global_knowledge.knowledge_chunks WHERE id=ANY(%s)", (chunk_ids,)
            )
            admin.execute(
                "DELETE FROM global_knowledge.documents WHERE id=ANY(%s)", (document_ids,)
            )
            admin.execute(
                "DELETE FROM global_knowledge.skill_versions WHERE id=ANY(%s)", (skill_ids,)
            )
            admin.execute(
                "DELETE FROM global_knowledge.knowledge_releases WHERE id=ANY(%s)", (release_ids,)
            )


def test_actual_api_separation_and_append_only_audit() -> None:
    student = {"Authorization": "Bearer " + login("student-a@example.test")}
    maintainer = {"Authorization": "Bearer " + login("maintainer@example.test")}
    with httpx.Client(timeout=10) as client:
        assert client.get("http://api:8000/v1/admin/access", headers=maintainer).status_code == 404
        denied = client.get("http://admin-api:8000/v1/admin/access?token=secret", headers=student)
        assert denied.status_code == 403
        assert (
            client.get("http://admin-api:8000/v1/student/account", headers=maintainer).status_code
            == 404
        )
        audit = client.get("http://admin-api:8000/v1/admin/audit", headers=maintainer)
        assert audit.status_code == 200
        event = next(e for e in audit.json() if e["id"] == denied.headers["X-Request-ID"])
        assert event["actor_role"] == "student"
        assert event["target"] == "/v1/admin/access"
        assert event["outcome"] == "denied"
        assert "secret" not in audit.text
    with psycopg.connect(os.environ["BOOTSTRAP_DATABASE_URL"], autocommit=True) as owner:
        with pytest.raises(psycopg.errors.RaiseException, match="append only"):
            owner.execute(
                "UPDATE public.audit_events SET outcome='success' WHERE id=%s", (event["id"],)
            )
