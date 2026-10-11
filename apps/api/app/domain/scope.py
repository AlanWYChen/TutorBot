from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.identity import Principal
from app.students.repository import StudentAccounts


class StudentDomain:
    """Transaction-local DB scope is resolved from a verified identity, never a request ID.

    Use a fresh database_session per request. The transaction must remain open for
    all domain reads/writes; PostgreSQL clears this setting on commit/rollback.
    """

    def __init__(self, session: Session, principal: Principal):
        if not session.in_transaction():
            raise RuntimeError("student domain requires an active transaction")
        self.session = session
        self.student_id: UUID = StudentAccounts(session, principal).own_account().id
        session.execute(
            text("SELECT set_config('app.student_id', :scope, true)"),
            {"scope": str(self.student_id)},
        )

    def profile_summaries(self) -> list[dict[str, object]]:
        rows = self.session.execute(
            text(
                "SELECT id,subject_id,current_summary,summary_version,revised_at "
                "FROM student_data.student_learning_profiles WHERE student_id=:student"
            ),
            {"student": self.student_id},
        ).mappings()
        return [dict(row) for row in rows]

    def memory_for_question(self, question_id: UUID) -> list[dict[str, object]]:
        rows = self.session.execute(
            text(
                "SELECT id,text,embedding_version FROM student_data.student_memory_chunks "
                "WHERE student_id=:student AND question_id=:question "
                "ORDER BY created_at DESC LIMIT 20"
            ),
            {"student": self.student_id, "question": question_id},
        ).mappings()
        return [dict(row) for row in rows]
