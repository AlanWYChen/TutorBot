from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.identity import Principal
from app.students.models import StudentAccount, User


class StudentAccounts:
    """All reads bind ownership to an already verified server-side principal."""

    def __init__(self, session: Session, principal: Principal):
        if principal.role != "student":
            raise PermissionError("student principal required")
        self.session = session
        self.uid = principal.uid

    def own_account(self) -> StudentAccount:
        self.session.execute(
            insert(User)
            .values(id=uuid4(), firebase_uid=self.uid, role="student")
            .on_conflict_do_nothing(index_elements=[User.firebase_uid])
        )
        user_id = self.session.scalar(select(User.id).where(User.firebase_uid == self.uid))
        if user_id is None:
            raise RuntimeError("account provisioning failed")
        self.session.execute(
            insert(StudentAccount)
            .values(id=uuid4(), user_id=user_id)
            .on_conflict_do_nothing(index_elements=[StudentAccount.user_id])
        )
        account = self.session.scalar(
            select(StudentAccount).where(StudentAccount.user_id == user_id)
        )
        if account is None:
            raise RuntimeError("account provisioning failed")
        return account

    def get_owned(self, account_id: UUID) -> StudentAccount | None:
        return self.session.scalar(
            select(StudentAccount)
            .join(User)
            .where(StudentAccount.id == account_id, User.firebase_uid == self.uid)
        )
