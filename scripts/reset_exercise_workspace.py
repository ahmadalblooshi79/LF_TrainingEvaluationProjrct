"""مسح التمرين الحالي وملفاته وإنشاء تمرين تجريبي فارغ + صيانة خفيفة.

لا يمس بنك المعلومات ولا المستخدمين.
تشغيل: .venv\\Scripts\\python.exe scripts/reset_exercise_workspace.py
"""
from __future__ import annotations

import shutil
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from app import exercise_options as ex_opts
from app.config import DATABASE_URL
from app.database import SessionLocal, engine
from app.exercise_store import (
    FILE_BUCKET_ROOTS,
    export_directory,
    purge_exercise_export_archives,
    wipe_exercise_from_system,
    write_exercise_json_file,
    _reset_upload_directory,
)
from app.models.domain import Exercise, ExerciseStatus
from app.models.user import RoleKey, User
from app.paths import APP_DIR


def _clean_pycache() -> int:
    removed = 0
    for d in APP_DIR.rglob("__pycache__"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed


def _clean_local_logs() -> int:
    removed = 0
    for pattern in ("server-*.log", "_server_*.txt", "_transcript_snippets.txt"):
        for p in APP_DIR.glob(pattern):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _vacuum_sqlite() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as conn:
        conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        conn.execute(text("VACUUM"))
        conn.execute(text("ANALYZE"))
        conn.commit()


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 2)


def main() -> int:
    db = SessionLocal()
    try:
        exercise_ids = [int(r[0]) for r in db.query(Exercise.id).all()]
        print(f"تمارين قبل المسح: {len(exercise_ids)}")
        for eid in exercise_ids:
            ex = db.get(Exercise, eid)
            title = (ex.title if ex else str(eid))[:80]
            if not wipe_exercise_from_system(db, eid):
                print(f"  تعذر مسح التمرين {eid}")
            else:
                print(f"  مسح: {title} (id={eid})")

        for root in FILE_BUCKET_ROOTS.values():
            _reset_upload_directory(root)
        purge_exercise_export_archives()
        db.commit()

        owner = (
            db.query(User)
            .filter(User.role_key == RoleKey.SYSTEM_ADMIN.value)
            .order_by(User.id)
            .first()
        )
        if owner is None:
            owner = db.query(User).order_by(User.id).first()
        if owner is None:
            print("خطأ: لا يوجد مستخدم في النظام.")
            return 1

        now = datetime.utcnow()
        ex = Exercise(
            code=f"EX-{uuid.uuid4().hex[:8].upper()}",
            title="تمرين تجريبي",
            description="",
            exercise_type=ex_opts.EXERCISE_TYPES[0],
            exercise_level=ex_opts.EXERCISE_LEVELS[0],
            mission_label=ex_opts.MISSIONS[0],
            trained_unit="وحدة تجريبية",
            location_label="موقع تجريبي",
            status=ExerciseStatus.DRAFT.value,
            owner_id=owner.id,
            planned_start=now,
            planned_end=now + timedelta(days=3),
        )
        db.add(ex)
        db.commit()
        db.refresh(ex)
        write_exercise_json_file(db, ex.id)
        db.commit()
        print(f"تمرين جديد: id={ex.id} code={ex.code} title={ex.title}")
    except Exception as exc:
        db.rollback()
        print(f"خطأ: {exc}")
        return 1
    finally:
        db.close()

    pyc = _clean_pycache()
    logs = _clean_local_logs()
    _vacuum_sqlite()

    print(f"حذف مجلدات __pycache__: {pyc}")
    print(f"حذف ملفات سجل محلية: {logs}")
    print("تم VACUUM و ANALYZE لقاعدة البيانات.")
    print("أحجام المجلدات بعد الصيانة:")
    for label, path in (
        ("instance (تمرين)", ROOT / "instance"),
        ("exercise_store", export_directory()),
        ("information_bank", ROOT / "instance" / "information_bank"),
    ):
        print(f"  {label}: {_dir_size_mb(path)} MB")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
