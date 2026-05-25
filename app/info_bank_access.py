"""بوابات الوصول المحمية بكلمة مرور إدارة النظام."""

import re

INFO_BANK_GATE_SESSION_KEY = "info_bank_gate_ok"
EVAL_SAVED_RESULTS_GATE_SESSION_KEY = "eval_saved_results_gate_ok"

INFO_BANK_PATH_PREFIX = "/admin/information-bank"
IBANK_INCLUDED_SAVE_HEADER = "X-IBank-Included-Save"


def is_information_bank_path(path: str | None) -> bool:
    p = (path or "").strip()
    return p == INFO_BANK_PATH_PREFIX or p.startswith(INFO_BANK_PATH_PREFIX + "/")


_TREE_DELETE_PATH_RE = re.compile(
    r"^/admin/information-bank/tree/\d+/delete$"
)


def is_information_bank_tree_manage_path(path: str | None) -> bool:
    """إدارة الشجرة (حذف، نقل، إضافة مجلد، رفع) — دون إعادة إدخال كلمة مرور البوابة."""
    p = (path or "").strip()
    if p == INFO_BANK_PATH_PREFIX + "/tree/move":
        return True
    if p in (
        INFO_BANK_PATH_PREFIX + "/tree/folder",
        INFO_BANK_PATH_PREFIX + "/tree/upload",
    ):
        return True
    return bool(_TREE_DELETE_PATH_RE.match(p))


def is_information_bank_gate_exempt_path(path: str | None) -> bool:
    """مسارات لا تتطلب جلسة البوابة (الدخول، الخروج، حفظ التحديدات بصلاحية إدارة النظام)."""
    p = (path or "").strip()
    return (
        p.startswith(INFO_BANK_PATH_PREFIX + "/gate")
        or p.startswith(INFO_BANK_PATH_PREFIX + "/exit")
        or is_information_bank_tree_manage_path(p)
        or p.endswith("/manifest.json")
        or p.endswith("/phases/included")
        or p.endswith("/units/included")
    )


def clear_information_bank_gate(session) -> None:
    session.pop(INFO_BANK_GATE_SESSION_KEY, None)


def information_bank_gate_ok(session) -> bool:
    return bool(session.get(INFO_BANK_GATE_SESSION_KEY))


def is_ibank_included_save_request() -> bool:
    """طلب حفظ جدول «مدرج في التمرين» عبر fetch من واجهة بنك المعلومات."""
    from flask import request

    return (request.headers.get(IBANK_INCLUDED_SAVE_HEADER) or "").strip() == "1"
