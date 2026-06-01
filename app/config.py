import os
from pathlib import Path

from dotenv import load_dotenv

from app.paths import APP_DIR, data_dir, ensure_data_directories, is_installed_mode

load_dotenv()

BASE_DIR = APP_DIR
_DATA = data_dir()
ensure_data_directories(_DATA)


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DATA / 'exercises.db'}")
# مجلد خارجي لملفات JSON الكاملة للتمارين (يمكن ضبطه في .env)
EXERCISE_EXPORT_DIR = Path(
    os.getenv("EXERCISE_EXPORT_DIR", str(_DATA / "exercise_store"))
).resolve()
# ملفات PDF لقوائم المعاضل (حسب مستوى الوحدة) — لا تُعرض مباشرة عبر /static
DILEMMA_PDF_DIR = Path(
    os.getenv("DILEMMA_PDF_DIR", str(_DATA / "instance" / "dilemma_pdfs"))
).resolve()
# ملفات Excel لقوائم التقييم (.xlsx حسب مستوى الوحدة) — تخزين آمن خارج /static
EVALUATION_LIST_XLSX_DIR = Path(
    os.getenv(
        "EVALUATION_LIST_XLSX_DIR",
        str(_DATA / "instance" / "evaluation_list_xlsx"),
    )
).resolve()
# مرفقات غرف المحادثة (خارج /static)
CHAT_UPLOAD_DIR = Path(
    os.getenv("CHAT_UPLOAD_DIR", str(_DATA / "instance" / "chat_uploads"))
).resolve()
# مرفقات التوثيق المرئي (صور/فيديو/صوت) — خارج /static
VISUAL_DOC_DIR = Path(
    os.getenv("VISUAL_DOC_DIR", str(_DATA / "instance" / "visual_docs"))
).resolve()
# صور/فيديو توثيق بنود قوائم التقييم (صف جدول المعايير) — خارج /static
EVAL_CRITERION_MEDIA_DIR = Path(
    os.getenv(
        "EVAL_CRITERION_MEDIA_DIR",
        str(_DATA / "instance" / "eval_criterion_media"),
    )
).resolve()
# بنك المعلومات (PDF/Excel) — خارج /static
INFO_BANK_DIR = Path(
    os.getenv("INFO_BANK_DIR", str(_DATA / "instance" / "information_bank"))
).resolve()
# مكتبة المراجع والمعايير — شجرة ملفات (PDF / Word / Excel)
LIBRARY_DIR = Path(
    os.getenv("LIBRARY_DIR", str(_DATA / "instance" / "library"))
).resolve()
# حزم التخطيط: ربط مجرى الأحداث (PDF/Word) بعدة قوائم تقييم إجراءات (Excel) لكل تمرين
PLANNER_FLOW_BUNDLE_DIR = Path(
    os.getenv(
        "PLANNER_FLOW_BUNDLE_DIR",
        str(_DATA / "instance" / "planner_flow_bundles"),
    )
).resolve()
SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-secret-change-in-production")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# فترات استطلاع التحديث التلقائي (ms) — أسرع في وضع التنصيب على السيرفر
_HEARTBEAT_DEFAULT = 2000 if is_installed_mode() else 3000
_HEARTBEAT_FAST_DEFAULT = 1000 if is_installed_mode() else 1500
HEARTBEAT_POLL_MS = _int_env("LF_HEARTBEAT_POLL_MS", _HEARTBEAT_DEFAULT)
HEARTBEAT_FAST_POLL_MS = _int_env("LF_HEARTBEAT_FAST_POLL_MS", _HEARTBEAT_FAST_DEFAULT)
