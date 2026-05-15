import enum
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RoleKey(str, enum.Enum):
    """الأدوار الرئيسية في النظام"""

    SYSTEM_ADMIN = "system_admin"  # إدارة النظام
    ANALYST = "analyst"  # المحللين
    PLANNER = "planner"  # التخطيط
    JUDGE = "judge"  # المحكمين
    CHIEF_JUDGE = "chief_judge"  # كبير المحكمين
    STANDARDS_LIBRARY = "standards_library"  # مكتبة المراجع والمعايير
    CONTROL = "control"  # السيطرة

    @classmethod
    def from_value(cls, v: str) -> "RoleKey":
        for m in cls:
            if m.value == v:
                return m
        return cls.JUDGE


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(256), default="")
    full_name: Mapped[str] = mapped_column(String(256), default="")
    password_hash: Mapped[str] = mapped_column(String(256))
    # جدول SQLite: تخزين نصي للتفادي تعارض أنواع Enum
    role_key: Mapped[str] = mapped_column(
        String(32),
        default=RoleKey.JUDGE.value,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    exercises_owned = relationship("Exercise", back_populates="owner", foreign_keys="Exercise.owner_id")
