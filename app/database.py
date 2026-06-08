from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)


if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _connection_record):
        """قراءة/كتابة متزامنة أفضل بين خيوط Waitress والعملاء على LAN/Wi‑Fi."""
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()


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
    """مرحلة التمرين لمعاضل التقييم — إضافة للجداول القديمة."""
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
                    "ADD COLUMN exercise_phase VARCHAR(32) DEFAULT 'preparation'"
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


_EVAL_WORKFLOW_COLUMN_SPECS: tuple[tuple[str, str], ...] = (
    ("reopened_for_judge", "BOOLEAN DEFAULT 0"),
    ("is_chief_approved", "BOOLEAN DEFAULT 0"),
    ("chief_approved_by_id", "INTEGER"),
    ("chief_approved_at", "DATETIME"),
    ("is_control_approved", "BOOLEAN DEFAULT 0"),
    ("control_approved_by_id", "INTEGER"),
    ("control_approved_at", "DATETIME"),
)


def _ensure_table_workflow_columns(table_name: str) -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if table_name not in insp.get_table_names():
            return
        cols = {c["name"] for c in insp.get_columns(table_name)}
    except Exception:
        return
    stmts = [
        f"ALTER TABLE {table_name} ADD COLUMN {name} {typ}"
        for name, typ in _EVAL_WORKFLOW_COLUMN_SPECS
        if name not in cols
    ]
    if not stmts:
        return
    with engine.begin() as conn:
        for sql in stmts:
            conn.execute(text(sql))


def ensure_evaluation_workflow_columns() -> None:
    """اعتماد المحكم → كبير المحكمين → السيطرة؛ وإعادة فتح التعديل للمحكم."""
    _ensure_table_workflow_columns("evaluation_list_saved_results")
    _ensure_table_workflow_columns("planner_flow_bundle_eval_saved_results")


def ensure_information_bank_tree_nodes_table() -> None:
    """جدول الشجرة يُنشأ عبر create_all؛ لا إجراء إضافي لـ SQLite."""
    return


def ensure_information_bank_tree_suppressions_table() -> None:
    """منع إعادة إنشاء مجلدات مرحلة/وحدة بعد حذفها يدوياً من الشجرة."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS information_bank_tree_suppressions (
                    kind VARCHAR(32) NOT NULL,
                    catalog_phase_key VARCHAR(64) NOT NULL DEFAULT '',
                    catalog_unit_key VARCHAR(128) NOT NULL DEFAULT '',
                    PRIMARY KEY (kind, catalog_phase_key, catalog_unit_key)
                )
                """
            )
        )


def ensure_planner_bundle_action_eval_event_flow_column() -> None:
    """ربط قائمة تقييم الإجراءات بملف مجرى أحداث محدد ضمن الحزمة."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if "exercise_planner_flow_bundle_action_evals" not in insp.get_table_names():
            return
    except Exception:
        return
    cols = {
        c["name"]
        for c in insp.get_columns("exercise_planner_flow_bundle_action_evals")
    }
    if "event_flow_item_id" in cols:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE exercise_planner_flow_bundle_action_evals "
                "ADD COLUMN event_flow_item_id INTEGER"
            )
        )


def ensure_planner_bundle_flow_table_json_column() -> None:
    """جدول مجرى الأحداث والمعاضل التحريري ضمن حزمة التخطيط."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if "exercise_planner_flow_bundles" not in insp.get_table_names():
            return
    except Exception:
        return
    cols = {c["name"] for c in insp.get_columns("exercise_planner_flow_bundles")}
    if "flow_table_json" in cols:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE exercise_planner_flow_bundles "
                "ADD COLUMN flow_table_json TEXT NOT NULL DEFAULT ''"
            )
        )


def ensure_judge_trainee_assignment_planner_bundle_column() -> None:
    """ربط المحكم بحزمة مجرى الأحداث وتقييم الإجراءات (مساحة التخطيط)."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if "judge_trainee_assignments" not in insp.get_table_names():
            return
    except Exception:
        return
    cols = {c["name"] for c in inspect(engine).get_columns("judge_trainee_assignments")}
    if "planner_flow_bundle_id" in cols:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE judge_trainee_assignments "
                "ADD COLUMN planner_flow_bundle_id INTEGER"
            )
        )


def ensure_information_bank_phase_included_column() -> None:
    """عمود «مدرج في التمرين» لمراحل التمرين في بنك المعلومات."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if "information_bank_training_phases" not in insp.get_table_names():
            return
    except Exception:
        return
    cols = {c["name"] for c in insp.get_columns("information_bank_training_phases")}
    if "included_in_exercise" in cols:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE information_bank_training_phases "
                "ADD COLUMN included_in_exercise BOOLEAN DEFAULT 0 NOT NULL"
            )
        )


def ensure_information_bank_unit_brigade_group_column() -> None:
    """مجموعة اللواء (1 / 3 / 4 / 5) لصفوف مستويات الوحدات."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if "information_bank_unit_levels" not in insp.get_table_names():
            return
    except Exception:
        return
    cols = {c["name"] for c in insp.get_columns("information_bank_unit_levels")}
    if "brigade_group" in cols:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE information_bank_unit_levels "
                "ADD COLUMN brigade_group VARCHAR(16) DEFAULT '1' NOT NULL"
            )
        )


def ensure_information_bank_unit_included_column() -> None:
    """عمود «مدرج في التمرين» لمستويات الوحدات في بنك المعلومات."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        insp = inspect(engine)
        if "information_bank_unit_levels" not in insp.get_table_names():
            return
    except Exception:
        return
    cols = {c["name"] for c in insp.get_columns("information_bank_unit_levels")}
    if "included_in_exercise" in cols:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE information_bank_unit_levels "
                "ADD COLUMN included_in_exercise BOOLEAN DEFAULT 0 NOT NULL"
            )
        )


def ensure_analyst_final_eval_manual_tables() -> None:
    """جداول علامات القصوى اليدوية في التقييم النهائي (SQLite)."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS analyst_final_eval_phase_allocated_max (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exercise_id INTEGER NOT NULL,
                    unit_level_key VARCHAR(64) DEFAULT '',
                    phase_key VARCHAR(32) DEFAULT '',
                    max_mark FLOAT,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE CASCADE,
                    UNIQUE (exercise_id, unit_level_key, phase_key)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS analyst_final_eval_allocated_max (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exercise_id INTEGER NOT NULL,
                    evaluation_item_id INTEGER NOT NULL,
                    unit_level_key VARCHAR(64) DEFAULT '',
                    phase_key VARCHAR(32) DEFAULT '',
                    max_mark FLOAT,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE CASCADE,
                    FOREIGN KEY(evaluation_item_id) REFERENCES evaluation_list_pdf_items (id) ON DELETE CASCADE,
                    UNIQUE (exercise_id, evaluation_item_id)
                )
                """
            )
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
