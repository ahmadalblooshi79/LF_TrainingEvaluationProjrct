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
    ensure_evaluation_workflow_columns,
    ensure_exercise_extended_columns,
    ensure_exercise_roster_unit_level_key_column,
    ensure_file_items_exercise_id_columns,
    ensure_judge_trainee_assignment_planner_bundle_column,
    ensure_planner_bundle_action_eval_event_flow_column,
    ensure_information_bank_tree_nodes_table,
    ensure_information_bank_tree_suppressions_table,
    ensure_information_bank_phase_included_column,
    ensure_information_bank_unit_included_column,
    ensure_information_bank_unit_brigade_group_column,
    ensure_analyst_final_eval_manual_tables,
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
        ensure_evaluation_workflow_columns()
        ensure_judge_trainee_assignment_planner_bundle_column()
        ensure_planner_bundle_action_eval_event_flow_column()
        ensure_information_bank_tree_nodes_table()
        ensure_information_bank_tree_suppressions_table()
        ensure_information_bank_phase_included_column()
        ensure_information_bank_unit_included_column()
        ensure_information_bank_unit_brigade_group_column()
        ensure_analyst_final_eval_manual_tables()
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
        # طلبات النبضات خفيفة ومتكررة على LAN/Wi‑Fi — لا حاجة لمزامنة الكتالوج في كل استعلام
        if request.path in ("/api/system/heartbeat", "/api/notifications/summary"):
            return
        from app.planning_catalog_sync import sync_planning_catalogs_from_db

        sync_planning_catalogs_from_db(g.db)

    @app.before_request
    def _protected_admin_gate_sessions():
        """إبطال بوابات الصفحات الحساسة عند مغادرتها؛ فرض كلمة المرور عند العودة."""
        from flask import jsonify, redirect, session, url_for

        from app.auth import get_current_user_optional
        from app.info_bank_access import (
            clear_information_bank_gate,
            information_bank_gate_ok,
            is_ibank_included_save_request,
            is_information_bank_gate_exempt_path,
            is_information_bank_path,
        )
        from app.permissions import can_manage_information_bank, can_view_information_bank

        path = request.path or ""

        if not is_information_bank_path(path):
            clear_information_bank_gate(session)

        if is_information_bank_path(path):
            if is_information_bank_gate_exempt_path(path):
                return
            if information_bank_gate_ok(session):
                return
            user = get_current_user_optional()
            if user is not None and can_manage_information_bank(user):
                return
            if user is None or not can_view_information_bank(user):
                return
            if is_ibank_included_save_request():
                return (
                    jsonify(
                        {
                            "ok": False,
                            "gate_required": True,
                            "error": (
                                "انتهت جلسة بنك المعلومات. أعد الدخول من قائمة "
                                "إدارة النظام وأدخل كلمة مرور إدارة النظام."
                            ),
                        }
                    ),
                    403,
                )
            return redirect(
                url_for("views.admin_information_bank_gate", next=request.full_path)
            )

    @app.teardown_request
    def _close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    from app import views
    app.register_blueprint(views.bp)

    @app.template_global()
    def report_phase_max_input_name(unit_key, phase_key):
        return views._report_phase_max_field_name(unit_key or "", phase_key or "")

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
