"""تنسيق عمود «عناصر التقييم»: مستوى الإزاحة ولون نوع الترقيم (أرقام / حروف / بين قوسين …)."""

from __future__ import annotations

import re
import unicodedata

# أرقام عربية شرقية → غربية للتحقق
_AR_DIGIT_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

_RE_WS = re.compile(r"\s+")


def _strip_bidi(s: str) -> str:
    return (
        (s or "")
        .replace("\u200f", "")
        .replace("\u200e", "")
        .replace("\ufeff", "")
        .strip()
    )


def _is_ascii_digits(t: str) -> bool:
    if not t:
        return False
    return bool(re.fullmatch(r"[0-9]+", t.translate(_AR_DIGIT_TRANS)))


def _only_arabic_letters(t: str) -> bool:
    if not t:
        return False
    if re.search(r"[0-9]", t.translate(_AR_DIGIT_TRANS)):
        return False
    return bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", t))


def _paren_inner_is_single_abjad_letter(inner: str) -> bool:
    """(أ) (ب) (جـ) — حرف أبجدي واحد داخل القوس؛ ليس كلمة وليس النمط المزدوج."""
    t = unicodedata.normalize("NFC", (inner or "").strip())
    if not t or _RE_WS.search(t) or not _only_arabic_letters(t):
        return False
    # إزالة التطويل لاعتبار «جـ» حرفًا واحداً تقريبيًا مقابل «جد»
    condensed = t.replace("\u0640", "")
    if not condensed:
        return False
    # بعد إزالة التطويل يجب أن يبقى رمز واحد ضمن مجموعة العربية والأشكال المشتركة للحرف الواحد
    return (
        len(condensed) == 1 and _only_arabic_letters(condensed)
    )


def _is_paren_double_arabic(inner: str) -> bool:
    """(أأ) أو (ب ب) أو (جـ جـ) — ليس أي سلسلة حروف طويلة بين قوسين."""
    t = (inner or "").strip()
    if not t:
        return False
    if _RE_WS.search(t):
        parts = [p for p in _RE_WS.split(t) if p]
        if len(parts) != 2:
            return False
        p0 = unicodedata.normalize("NFC", parts[0])
        p1 = unicodedata.normalize("NFC", parts[1])
        # (ب ب) (جـ جـ) وليس صيغتي كلمتين مختلفتين
        return (
            _paren_inner_is_single_abjad_letter(p0)
            and _paren_inner_is_single_abjad_letter(p1)
            and p0.replace("\u0640", "") == p1.replace("\u0640", "")
        )
    t_n = unicodedata.normalize("NFC", t)
    if not _only_arabic_letters(t_n) or len(t_n) < 2 or len(t_n) % 2 != 0:
        return False
    half = len(t_n) // 2
    return t_n[:half] == t_n[half:]


def split_evaluation_element(element: str | None) -> dict[str, object]:
    """
    يُحدد بادئة الترقيم وبقية النص ومستوى الإزاحة (0–4) وفئة اللون.

    الإزاحة التراكمية من سطر الأرقام البسيط:
    0 — 1. / 2 / 3 –
    1 — أ. / أ – / أ (مسافة) مع حرف أبجدي واحد
    2 — (1)
    3 — (أ)
    4 — (أأ) أو (ب ب)
    """
    s = _strip_bidi(element or "")
    if not s:
        return {
            "element_prefix": "",
            "element_rest": "",
            "element_indent": 0,
            "element_prefix_kind": "plain",
        }

    # أرقام بين قوسين — برتقالي، مستوى 2
    m = re.match(r"^(\s*\(\s*[0-9٠-٩]+\s*\)\s*)", s)
    if m:
        pref = m.group(1)
        return {
            "element_prefix": pref,
            "element_rest": s[len(pref) :],
            "element_indent": 2,
            "element_prefix_kind": "pnum",
        }

    # أي محتوى بين قوسين — حروف أو مزدوج
    m = re.match(r"^(\s*\(\s*[^)]+\s*\)\s*)", s)
    if m:
        pref = m.group(1)
        inner_m = re.search(r"\(\s*([^)]*)\s*\)", pref)
        inner = (inner_m.group(1) if inner_m else "").strip()

        if inner and _is_ascii_digits(inner):
            # مثل (12) لو فات الفرع الأول — نعتبره أرقاماً بقوسين
            return {
                "element_prefix": pref,
                "element_rest": s[len(pref) :],
                "element_indent": 2,
                "element_prefix_kind": "pnum",
            }

        elif inner:
            if _is_paren_double_arabic(inner):
                return {
                    "element_prefix": pref,
                    "element_rest": s[len(pref) :],
                    "element_indent": 4,
                    "element_prefix_kind": "pdouble",
                }
            # حرف واحد أو (جـ) أو مقطع عربي؛ ليس النمط المزدوج أعلاه
            if _paren_inner_is_single_abjad_letter(inner):
                return {
                    "element_prefix": pref,
                    "element_rest": s[len(pref) :],
                    "element_indent": 3,
                    "element_prefix_kind": "pletter",
                }
        # أقواس غير مطابقة للأنماط — لا نستهلك؛ نتابع كنسخة عادية
        # (نترك s كما هو للفروع التالية)

    # حرف أبجدي واحد — مستوى 1 — ثم «.» أو شرطة أو مسافة واحدة قبل بقية النص
    m_ld = re.match(
        r"^(\s*[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\u0640]+\s*(?:[.]\s*|\s*[-–—]\s*))",
        s,
    )
    m_ws = (
        None
        if m_ld
        else re.match(r"^(\s*[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\u0640]+\s+)", s)
    )
    m_abjad = m_ld or m_ws
    if m_abjad:
        pref = m_abjad.group(1)
        head_m = re.match(
            r"^\s*([\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\u0640]+)",
            pref.strip() or "",
        )
        lr = head_m.group(1) if head_m else ""
        if lr and _paren_inner_is_single_abjad_letter(lr):
            return {
                "element_prefix": pref,
                "element_rest": s[len(pref) :],
                "element_indent": 1,
                "element_prefix_kind": "letter",
            }

    # أرقام مع فاصل — أسود Bold، مستوى 0
    m = re.match(
        r"^(\s*[0-9٠-٩]+\s*(?:[.)\]:：،,]|\s*[-–—]\s*)?\s*)",
        s,
    )
    if m:
        pref = m.group(1)
        core = pref.translate(_AR_DIGIT_TRANS).strip()
        if core and core[0].isdigit():
            return {
                "element_prefix": pref,
                "element_rest": s[len(pref) :],
                "element_indent": 0,
                "element_prefix_kind": "num",
            }

    return {
        "element_prefix": "",
        "element_rest": s,
        "element_indent": 0,
        "element_prefix_kind": "plain",
    }


def enrich_eval_rows_element_styles(rows: list[dict]) -> list[dict]:
    """يُضاف لكل صف حقول العرض للترقيم."""
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        row = dict(r)
        row.update(split_evaluation_element(row.get("element")))
        out.append(row)
    return out
