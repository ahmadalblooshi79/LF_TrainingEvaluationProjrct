from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def ensure_exercise_extended_columns() -> None:
    """لقواعد SQLite القديمة: إضافة أعمدة التمرين الموسّعة دون إعادة إنشاء الجدول."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if "exercises" not in insp.get_table_names():
            return
    except Exception:
        return
    cols = {c["name"] for c in insp.get_columns("exercises")}
    specs = [
        ("exercise_type", "VARCHAR(200)"),
        ("exercise_level", "VARCHAR(200)"),
        ("mission_label", "VARCHAR(400)"),
        ("trained_unit", "VARCHAR(400)"),
        ("location_label", "VARCHAR(400)"),
    ]
    stmts = [
        f"ALTER TABLE exercises ADD COLUMN {name} {typ} DEFAULT ''"
        for name, typ in specs
        if name not in cols
    ]
    if not stmts:
        return
    with engine.begin() as conn:
        for sql in stmts:
            conn.execute(text(sql))


def ensure_dilemma_items_pdf_relpath_column() -> None:
    """لقواعد SQLite القديمة: عمود ملف PDF الاختياري لكل معضلة."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if "dilemma_items" not in insp.get_table_names():
            return
    except Exception:
        return
    cols = {c["name"] for c in insp.get_columns("dilemma_items")}
    if "pdf_relpath" in cols:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE dilemma_items ADD COLUMN pdf_relpath VARCHAR(500) DEFAULT ''"
            )
        )


def ensure_battle_unit_personnel_judge_columns() -> None:
    """لقواعد SQLite القديمة: إضافة حقول محكم الوحدة دون إعادة إنشاء الجدول."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if "exercise_battle_unit_personnel" not in insp.get_table_names():
            return
    except Exception:
        return
    cols = {c["name"] for c in insp.get_columns("exercise_battle_unit_personnel")}
    specs = [
        ("judge_trainee_name", "VARCHAR(256)"),
        ("judge_rank_ar", "VARCHAR(256)"),
        ("judge_position_ar", "VARCHAR(512)"),
        ("trainee_military_number", "VARCHAR(128)"),
        ("judge_military_number", "VARCHAR(128)"),
    ]
    stmts = [
        f"ALTER TABLE exercise_battle_unit_personnel ADD COLUMN {name} {typ} DEFAULT ''"
        for name, typ in specs
        if name not in cols
    ]
    if not stmts:
        return
    with engine.begin() as conn:
        for sql in stmts:
            conn.execute(text(sql))


def ensure_file_items_exercise_id_columns() -> None:
    """لقواعد SQLite القديمة: ربط ملفات المعاضل والتقييم بالتمرين الحالي دون تغيير الواجهة."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        table_names = set(insp.get_table_names())
    except Exception:
        return
    specs = {
        "dilemma_items": "ALTER TABLE dilemma_items ADD COLUMN exercise_id INTEGER",
        "evaluation_list_pdf_items": "ALTER TABLE evaluation_list_pdf_items ADD COLUMN exercise_id INTEGER",
    }
    with engine.begin() as conn:
        for table, sql in specs.items():
            if table not in table_names:
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if "exercise_id" not in cols:
                conn.execute(text(sql))


def ensure_exercise_roster_unit_level_key_column() -> None:
    """ربط قوائم الوحدة بمستوى الوحدة الموحّد (مثل المعاضل والتقييم)."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if "exercise_roster_rows" not in insp.get_table_names():
            return
    except Exception:
        return
    cols = {c["name"] for c in inspect(engine).get_columns("exercise_roster_rows")}
    if "unit_level_key" in cols:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE exercise_roster_rows "
                "ADD COLUMN unit_level_key VARCHAR(64) DEFAULT ''"
            )
        )


def ensure_dilemma_eval_exercise_phase_columns() -> None:
    """مرحلة التمرين (رئيسي / إعادة التنظيم) لمعاضل التقييم — إضافة للجداول القديمة."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        table_names = set(insp.get_table_names())
    except Exception:
        return
    for table in ("dilemma_items", "evaluation_list_pdf_items"):
        if table not in table_names:
            continue
        cols = {c["name"] for c in inspect(engine).get_columns(table)}
        if "exercise_phase" in cols:
            continue
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"ALTER TABLE {table} "
                    "ADD COLUMN exercise_phase VARCHAR(32) DEFAULT 'main'"
                )
            )


def ensure_evaluation_saved_results_approval_columns() -> None:
    """إضافة حقول الاعتماد (Approved) لنتائج التقييم المحفوظة في SQLite القديمة."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if "evaluation_list_saved_results" not in insp.get_table_names():
            return
    except Exception:
        return
    cols = {c["name"] for c in inspect(engine).get_columns("evaluation_list_saved_results")}
    specs = [
        ("is_approved", "BOOLEAN"),
        ("approved_by_id", "INTEGER"),
        ("approved_at", "DATETIME"),
    ]
    stmts = [
        f"ALTER TABLE evaluation_list_saved_results ADD COLUMN {name} {typ}"
        for name, typ in specs
        if name not in cols
    ]
    if not stmts:
        return
    with engine.begin() as conn:
        for sql in stmts:
            conn.execute(text(sql))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
