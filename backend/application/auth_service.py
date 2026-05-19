from __future__ import annotations

from dataclasses import dataclass

from backend.infrastructure.repositories import SessionInfo, SessionRepository, UserRepository
from backend.infrastructure.security import hash_password, new_session_token, verify_password


@dataclass
class AuthUser:
    id: int
    username: str
    role: str


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        sessions: SessionRepository,
        session_ttl_hours: int,
    ) -> None:
        self.users = users
        self.sessions = sessions
        self.session_ttl_hours = session_ttl_hours

    def ensure_default_user(self, *, username: str, password: str, role: str) -> None:
        existing = self.users.get_by_username(username)
        if existing is not None:
            return
        self.users.create_user(username=username, password_hash=hash_password(password), role=role)

    def login(self, *, username: str, password: str) -> tuple[str, AuthUser, str]:
        user = self.users.get_by_username(username)
        if user is None:
            raise ValueError("invalid username or password")
        if not verify_password(password, str(user["password_hash"])):
            raise ValueError("invalid username or password")
        token = new_session_token()
        expires_at = self.sessions.create_session(
            token=token,
            user_id=int(user["id"]),
            ttl_hours=self.session_ttl_hours,
        )
        return (
            token,
            AuthUser(id=int(user["id"]), username=str(user["username"]), role=str(user["role"])),
            expires_at,
        )

    def logout(self, token: str) -> None:
        self.sessions.revoke(token)

    def get_user_by_token(self, token: str) -> AuthUser | None:
        info: SessionInfo | None = self.sessions.get_active_session(token)
        if info is None:
            return None
        return AuthUser(id=info.user_id, username=info.username, role=info.role)

