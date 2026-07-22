# -*- coding: utf-8 -*-
"""تصدير دليل المستخدم التفصيلي إلى ملف PDF (عربي RTL)."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image as RLImage,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from app.user_manual import MANUAL_TITLE, manual_sections

_FONT_REG = "UserManualAr"
_FONT_BOLD = "UserManualArBold"
_FONTS_REGISTERED = False
_STATIC_MANUAL = Path(__file__).resolve().parent / "static" / "user_manual"


def _win_font(*names: str) -> Path | None:
    fonts = Path(r"C:\Windows\Fonts")
    for name in names:
        p = fonts / name
        if p.is_file():
            return p
    return None


def _ensure_fonts() -> None:
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    regular = _win_font("segoeui.ttf", "arial.ttf", "trado.ttf")
    bold = _win_font("segoeuib.ttf", "arialbd.ttf", "tradbdo.ttf") or regular
    if regular is None:
        raise RuntimeError("لم يُعثر على خط عربي مناسب في Windows Fonts.")
    pdfmetrics.registerFont(TTFont(_FONT_REG, str(regular)))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(bold)))
    _FONTS_REGISTERED = True


def _shape_ar(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(raw))
    except Exception:
        return raw


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_escape(_shape_ar(text)), style)


def build_user_manual_pdf() -> bytes:
    """يبني دليل المستخدم PDF ويعيد البايتات."""
    _ensure_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.5 * cm,
        title=MANUAL_TITLE,
        author="نظام إدارة التمارين",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "umTitle",
        parent=styles["Title"],
        fontName=_FONT_BOLD,
        fontSize=15,
        leading=21,
        alignment=TA_CENTER,
        textColor=HexColor("#5c4033"),
        spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        "umSub",
        parent=styles["Normal"],
        fontName=_FONT_REG,
        fontSize=10,
        leading=15,
        alignment=TA_CENTER,
        textColor=HexColor("#6d5a4e"),
        spaceAfter=14,
    )
    h_style = ParagraphStyle(
        "umH",
        parent=styles["Heading2"],
        fontName=_FONT_BOLD,
        fontSize=12,
        leading=17,
        alignment=TA_RIGHT,
        textColor=HexColor("#8b4513"),
        spaceBefore=12,
        spaceAfter=4,
    )
    aud_style = ParagraphStyle(
        "umAud",
        parent=styles["Normal"],
        fontName=_FONT_BOLD,
        fontSize=9,
        leading=13,
        alignment=TA_RIGHT,
        textColor=HexColor("#6d5a4e"),
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "umBody",
        parent=styles["Normal"],
        fontName=_FONT_REG,
        fontSize=9.5,
        leading=15,
        alignment=TA_RIGHT,
        textColor=HexColor("#2c241e"),
        spaceAfter=4,
    )
    step_title = ParagraphStyle(
        "umStepTitle",
        parent=styles["Normal"],
        fontName=_FONT_BOLD,
        fontSize=10,
        leading=14,
        alignment=TA_RIGHT,
        textColor=HexColor("#3e3229"),
        spaceBefore=6,
        spaceAfter=2,
    )
    step_meta = ParagraphStyle(
        "umStepMeta",
        parent=styles["Normal"],
        fontName=_FONT_REG,
        fontSize=9,
        leading=13,
        alignment=TA_RIGHT,
        textColor=HexColor("#4a3f36"),
        spaceAfter=2,
        rightIndent=6,
    )
    tip_style = ParagraphStyle(
        "umTip",
        parent=body_style,
        fontName=_FONT_REG,
        fontSize=9,
        leading=13,
        alignment=TA_RIGHT,
        leftIndent=10,
        rightIndent=6,
    )

    story: list = [
        _p(MANUAL_TITLE, title_style),
        Spacer(1, 8),
    ]

    for sec in manual_sections():
        story.append(_p(sec["title"], h_style))
        if sec.get("audience"):
            story.append(_p(f"الجمهور: {sec['audience']}", aud_style))
        if sec.get("intro"):
            story.append(_p(sec["intro"], body_style))

        for img in sec.get("images") or []:
            img_path = _STATIC_MANUAL / (img.get("file") or "")
            if not img_path.is_file():
                continue
            # عرض الصورة بعرض مناسب لصفحة A4
            story.append(Spacer(1, 4))
            story.append(
                RLImage(
                    str(img_path),
                    width=16.5 * cm,
                    height=9.2 * cm,
                    kind="proportional",
                )
            )
            if img.get("caption"):
                story.append(_p(img["caption"], tip_style))
            story.append(Spacer(1, 4))

        prereqs = [x for x in (sec.get("prerequisites") or []) if x]
        if prereqs:
            story.append(_p("قبل البدء:", aud_style))
            items = [ListItem(_p(x, tip_style), leftIndent=6, bulletColor=HexColor("#8b4513")) for x in prereqs]
            story.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    start="•",
                    bulletFontName=_FONT_REG,
                    bulletFontSize=9,
                    leftIndent=14,
                )
            )

        for st in sec.get("steps") or []:
            n = st.get("n") or ""
            story.append(_p(f"الخطوة {n}: {st.get('title') or ''}", step_title))
            if st.get("where"):
                story.append(_p(f"أين: {st['where']}", step_meta))
            if st.get("detail"):
                story.append(_p(st["detail"], step_meta))
            if st.get("action"):
                story.append(_p(f"افعل: {st['action']}", step_meta))
            if st.get("note"):
                story.append(_p(f"ملاحظة: {st['note']}", step_meta))

        tips = [x for x in (sec.get("tips") or []) if x]
        if tips:
            story.append(_p("نصائح:", aud_style))
            items = [ListItem(_p(x, tip_style), leftIndent=6, bulletColor=HexColor("#8b4513")) for x in tips]
            story.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    start="•",
                    bulletFontName=_FONT_REG,
                    bulletFontSize=9,
                    leftIndent=14,
                )
            )
            story.append(Spacer(1, 3))

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont(_FONT_REG, 8)
        canvas.setFillColor(HexColor("#6d5a4e"))
        label = _shape_ar(f"صفحة {_doc.page}")
        canvas.drawCentredString(A4[0] / 2, 1.0 * cm, label)
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
