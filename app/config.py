import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = f"sqlite:///{BASE_DIR / 'exercises.db'}"
# مجلد خارجي لملفات JSON الكاملة للتمارين (يمكن ضبطه في .env)
EXERCISE_EXPORT_DIR = Path(
    os.getenv("EXERCISE_EXPORT_DIR", str(BASE_DIR / "exercise_store"))
).resolve()
# ملفات PDF لقوائم المعاضل (حسب مستوى الوحدة) — لا تُعرض مباشرة عبر /static
DILEMMA_PDF_DIR = Path(
    os.getenv("DILEMMA_PDF_DIR", str(BASE_DIR / "instance" / "dilemma_pdfs"))
).resolve()
# ملفات Excel لقوائم التقييم (.xlsx حسب مستوى الوحدة) — تخزين آمن خارج /static
EVALUATION_LIST_XLSX_DIR = Path(
    os.getenv(
        "EVALUATION_LIST_XLSX_DIR",
        str(BASE_DIR / "instance" / "evaluation_list_xlsx"),
    )
).resolve()
# مرفقات غرف المحادثة (خارج /static)
CHAT_UPLOAD_DIR = Path(
    os.getenv("CHAT_UPLOAD_DIR", str(BASE_DIR / "instance" / "chat_uploads"))
).resolve()
# مرفقات التوثيق المرئي (صور/فيديو/صوت) — خارج /static
VISUAL_DOC_DIR = Path(
    os.getenv("VISUAL_DOC_DIR", str(BASE_DIR / "instance" / "visual_docs"))
).resolve()
# بنك المعلومات (PDF/Excel) — خارج /static
INFO_BANK_DIR = Path(
    os.getenv("INFO_BANK_DIR", str(BASE_DIR / "instance" / "information_bank"))
).resolve()
# حزم التخطيط: ربط مجرى الأحداث (PDF/Word) بعدة قوائم تقييم إجراءات (Excel) لكل تمرين
PLANNER_FLOW_BUNDLE_DIR = Path(
    os.getenv(
        "PLANNER_FLOW_BUNDLE_DIR",
        str(BASE_DIR / "instance" / "planner_flow_bundles"),
    )
).resolve()
SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-secret-change-in-production")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
