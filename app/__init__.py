import os

from flask import Flask, g, request

from app.config import SECRET_KEY
from app.database import (
    Base,
    SessionLocal,
    engine,
    ensure_battle_unit_personnel_judge_columns,
    ensure_dilemma_eval_exercise_phase_columns,
    ensure_dilemma_items_pdf_relpath_column,
    ensure_evaluation_saved_results_approval_columns,
    ensure_exercise_extended_columns,
    ensure_exercise_roster_unit_level_key_column,
    ensure_file_items_exercise_id_columns,
    ensure_judge_trainee_assignment_planner_bundle_column,
)

# تسجيل النماذج لضمان اكتمال metadata
import app.models  # noqa: F401


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
        static_url_path="/static",
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    )
    app.config["SECRET_KEY"] = SECRET_KEY

    with app.app_context():
        Base.metadata.create_all(bind=engine)
        ensure_exercise_extended_columns()
        ensure_battle_unit_personnel_judge_columns()
        ensure_dilemma_items_pdf_relpath_column()
        ensure_file_items_exercise_id_columns()
        ensure_dilemma_eval_exercise_phase_columns()
        ensure_exercise_roster_unit_level_key_column()
        ensure_evaluation_saved_results_approval_columns()
        ensure_judge_trainee_assignment_planner_bundle_column()
        from app.seed import seed_all
        db = SessionLocal()
        try:
            seed_all(db)
        finally:
            db.close()

    @app.before_request
    def _open_db():
        if request.path.startswith("/static/"):
            return
        g.db = SessionLocal()

    @app.teardown_request
    def _close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    from app import views
    app.register_blueprint(views.bp)

    from app.template_context import inject_header_exercise

    app.context_processor(inject_header_exercise)

    from app.mil_symbols import resolve_military_symbol_static_path

    @app.context_processor
    def inject_military_symbol_url():
        from flask import url_for

        def mil_symbol_url_for_symbol(symbol):
            rel = resolve_military_symbol_static_path(symbol or {})
            if rel is None:
                return None
            return url_for("static", filename=rel)

        return dict(mil_symbol_url_for_symbol=mil_symbol_url_for_symbol)

    return app
