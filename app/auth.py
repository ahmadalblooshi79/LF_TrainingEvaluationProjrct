from passlib.context import CryptContext
from flask import g, session
from sqlalchemy.orm import Session

from app.models import User

# NOTE:
# On some Windows/Python combinations, the `bcrypt` backend raises a ValueError for
# secrets longer than 72 bytes during Passlib's backend self-tests, which breaks login.
# `pbkdf2_sha256` is pure-python and stable across platforms.
password_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(p: str) -> str:
    return password_ctx.hash(p)


def verify_password(plain: str, hashed: str) -> bool:
    return password_ctx.verify(plain, hashed)


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return (
        db.query(User)
        .filter(User.id == user_id, User.is_active == True)  # noqa: E712
        .first()
    )


def get_session_user_id() -> int | None:
    return session.get("user_id")


def get_current_user_optional() -> User | None:
    if getattr(g, "_current_user_loaded", False):
        return getattr(g, "_current_user", None)
    uid = get_session_user_id()
    user = None
    if uid and hasattr(g, "db") and g.db is not None:
        user = get_user_by_id(g.db, uid)
    g._current_user_loaded = True
    g._current_user = user
    return user
