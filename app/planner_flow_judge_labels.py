"""ربط صنف المحكم في عمود المكلف ↔ مستوى الوحدة (بنك المعلومات / قائمة المحكمين)."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.evaluation_list_ibank_sync import _resolve_unit_key
from app.info_bank_tree import _normalize_tree_label
from app.unit_levels_catalog import label_for_unit_level_key

_ASSIGNEE_TO_UNIT_LABEL: dict[str, str] = {
    'محكم كتيبة/14': 'قيادة كتيبة الدبابات/14',
    'محكم كتيبة/13': 'قيادة كتيبة المشاة الآلية/13',
    'محكم كتيبة/12': 'قيادة كتيبة المشاة الآلية/12',
    'محكم كتيبة/11': 'قيادة كتيبة المشاة الراجلة/11',
    'محكم قيادة اللواء': 'قيادة مجموعة اللواء',
    'محكم الهاون': 'سرية الهاون',
    'محكم المدفعية': 'قيادة كتيبة المدفعية',
    'محكم الطبية': 'السرية الطبية',
    'محكم الصيانة': 'سرية الصيانة',
    'محكم الشرطة العسكرية/الأمن': 'فصيل الشرطة العسكرية',
    'محكم الدفاع الجوي': 'سرية الدفاع الجوي',
    'محكم الاشارة': 'سرية الاشارة',
    'محكم الاستطلاع': 'سرية الاستطلاع',
    'محكم هيئة الركن': 'هيئة ركن مجموعة اللواء',
    'محكم السرية/1 من كتيبة المشاة الراجلة/11': 'كتيبة المشاة الراجلة/11 - السرية/1',
    'محكم السرية/2 من كتيبة المشاة الراجلة/11': 'كتيبة المشاة الراجلة/11 - السرية/2',
    'محكم السرية/3 من كتيبة المشاة الراجلة/11': 'كتيبة المشاة الراجلة/11 - السرية/3',
    'محكم السرية/1 من كتيبة المشاة الآلية/12': 'كتيبة المشاة الآلية/12 - السرية/1',
    'محكم السرية/2 من كتيبة المشاة الآلية/12': 'كتيبة المشاة الآلية/12 - السرية/2',
    'محكم السرية/3 من كتيبة المشاة الآلية/12': 'كتيبة المشاة الآلية/12 - السرية/3',
    'محكم السرية/1 من كتيبة المشاة الآلية/13': 'كتيبة المشاة الآلية/3 - السرية/1',
    'محكم السرية/2 من كتيبة المشاة الآلية/13': 'كتيبة المشاة الآلية/3 - السرية/2',
    'محكم السرية/3 من كتيبة المشاة الآلية/13': 'كتيبة المشاة الآلية/3 - السرية/3',
    'محكم السرية/1 من كتيبة الدبابات/14': 'كتيبة الدبابات/4 - السرية/1',
    'محكم السرية/2 من كتيبة الدبابات/14': 'كتيبة الدبابات/4 - السرية/2',
    'محكم السرية/3 من كتيبة الدبابات/14': 'كتيبة الدبابات/4 - السرية/3',
    'محكم السرية/1 من كتيبة/11': 'كتيبة المشاة الراجلة/11 - السرية/1',
    'محكم السرية/2 من كتيبة/11': 'كتيبة المشاة الراجلة/11 - السرية/2',
    'محكم السرية/3 من كتيبة/11': 'كتيبة المشاة الراجلة/11 - السرية/3',
    'محكم السرية/1 من كتيبة/12': 'كتيبة المشاة الآلية/12 - السرية/1',
    'محكم السرية/2 من كتيبة/12': 'كتيبة المشاة الآلية/12 - السرية/2',
    'محكم السرية/3 من كتيبة/12': 'كتيبة المشاة الآلية/12 - السرية/3',
    'محكم السرية/1 من كتيبة/13': 'كتيبة المشاة الآلية/3 - السرية/1',
    'محكم السرية/2 من كتيبة/13': 'كتيبة المشاة الآلية/3 - السرية/2',
    'محكم السرية/3 من كتيبة/13': 'كتيبة المشاة الآلية/3 - السرية/3',
    'محكم السرية/1 من كتيبة/14': 'كتيبة الدبابات/4 - السرية/1',
    'محكم السرية/2 من كتيبة/14': 'كتيبة الدبابات/4 - السرية/2',
    'محكم السرية/3 من كتيبة/14': 'كتيبة الدبابات/4 - السرية/3',
    'محكم م/د': 'سرية الـ م/د',
    'محكم السرية/1 من كتيبة المدفعية': 'قيادة كتيبة المدفعية - السرية/1',
    'محكم السرية/2 من كتيبة المدفعية': 'قيادة كتيبة المدفعية - السرية/2',
    'محكم السرية/3 من كتيبة المدفعية': 'قيادة كتيبة المدفعية - السرية/3',
    'محكم الهندسة': 'سرية الهندسة',
    'محكم القيادة والسيطرة': 'القيادة والسيطرة',
    'محكم  كتيبة الاسناد الإداري': 'كتيبة الاسناد الإداري',
    'محكم  سرية التزويد والنقل': 'سرية التزويد والنقل',
    'محكم  سرية الحرب الإلكترونية': 'سرية الحرب الإلكترونية',
    'محكم ضباط الصف': 'ضباط الصف',
}

_UNIT_LABEL_TO_ASSIGNEE: dict[str, str] = {v: k for k, v in _ASSIGNEE_TO_UNIT_LABEL.items()}


def _norm(s: str) -> str:
    return _normalize_tree_label((s or "").strip())


def _strip_bullet_line(s: str) -> str:
    return re.sub(r"^[\s•·\-–]+", "", (s or "").strip()).strip()


def parse_assignee_cell_lines(raw: str | None) -> list[str]:
    """أسطر عمود المكلف — كل سطر صنف محكم."""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    seen: set[str] = set()
    for line in text.split("\n"):
        lbl = _strip_bullet_line(line)
        if not lbl:
            continue
        n = _norm(lbl)
        if n in seen:
            continue
        seen.add(n)
        out.append(lbl)
    return out


_COMPANY_SHORT_RE = re.compile(
    r"^محكم السرية/(\d+)\s*من\s*كتيبة/(11|12|13|14)\s*$"
)
_COMPANY_UNIT_PREFIX = {
    "11": "كتيبة المشاة الراجلة/11 - السرية",
    "12": "كتيبة المشاة الآلية/12 - السرية",
    "13": "كتيبة المشاة الآلية/3 - السرية",
    "14": "كتيبة الدبابات/4 - السرية",
}


def _normalize_assignee_lookup(s: str) -> str:
    s = re.sub(r"(\d+)من", r"\1 من", (s or "").strip())
    return s


def _company_unit_label_from_short_match(m: re.Match[str]) -> str:
    n, bn = m.group(1), m.group(2)
    prefix = _COMPANY_UNIT_PREFIX.get(bn, "")
    return f"{prefix}/{n}" if prefix else ""


def unit_label_for_assignee_label(assignee_label: str) -> str:
    raw = _strip_bullet_line(assignee_label)
    if not raw:
        return ""
    candidates = [raw, _normalize_assignee_lookup(raw)]
    for cand in candidates:
        if cand in _ASSIGNEE_TO_UNIT_LABEL:
            return _ASSIGNEE_TO_UNIT_LABEL[cand]
        n = _norm(cand)
        for k, v in _ASSIGNEE_TO_UNIT_LABEL.items():
            if _norm(k) == n:
                return v
        m = _COMPANY_SHORT_RE.match(cand)
        if m:
            ul = _company_unit_label_from_short_match(m)
            if ul:
                return ul
    return ""


def unit_key_for_assignee_label(assignee_label: str, *, db: Session) -> str:
    ul = unit_label_for_assignee_label(assignee_label)
    if not ul:
        return ""
    return _resolve_unit_key(ul, db) or ul


def flow_assignee_label_for_unit_label(unit_label: str) -> str:
    raw = (unit_label or "").strip()
    if not raw:
        return ""
    if raw in _UNIT_LABEL_TO_ASSIGNEE:
        return _UNIT_LABEL_TO_ASSIGNEE[raw]
    n = _norm(raw)
    for k, v in _UNIT_LABEL_TO_ASSIGNEE.items():
        if _norm(k) == n:
            return v
    return ""


def flow_assignee_label_for_unit_key(unit_key: str, *, db: Session | None = None) -> str:
    ul = label_for_unit_level_key(unit_key, db=db) or unit_key
    return flow_assignee_label_for_unit_label(ul)

