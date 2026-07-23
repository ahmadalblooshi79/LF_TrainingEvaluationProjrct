"""مكتبة التقارير الذكية — المرحلة الثانية."""

__all__ = ["store_new_report", "process_report"]


def __getattr__(name: str):
    if name == "store_new_report":
        from app.ai_report_library.services.storage_service import store_new_report as fn

        return fn
    if name == "process_report":
        from app.ai_report_library.services.processing_pipeline import process_report as fn

        return fn
    raise AttributeError(name)
