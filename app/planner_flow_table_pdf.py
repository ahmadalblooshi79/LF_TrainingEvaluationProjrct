"""PDF احتياطي لجدول المجرى إن تعذر تحويل ملف Word نفسه."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

try:
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    _HAS_REPORTLAB = True
except ImportError:
    _HAS_REPORTLAB = False

_FONT_REG = "PlannerFlowAr"
_FONT_BOLD = "PlannerFlowArBold"
_FONTS_REGISTERED = False

_HEADERS = [
    "ت",
    "التوقيت الحقيقي",
    "توقيت نظام كورا",
    "من",
    "إلى",
    "أنظمة التبليغ",
    "وصف المعضلة/الحدث",
    "المكلف بالإجراء والمتابعة",
    "رد الفعل المتوقع",
    "الملاحظات",
]


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
    raw = (text or "").replace("\r\n", "\n")
    if not raw.strip():
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
        .replace("\n", "<br/>")
    )


def _cell(text: str, style):
    return Paragraph(_escape(_shape_ar(text)), style)


def build_planner_flow_table_pdf(
    *,
    day_label: str,
    note: str,
    rows: list[dict],
) -> bytes | None:
    if not _HAS_REPORTLAB:
        return None
    try:
        _ensure_fonts()
    except Exception:
        return None
    buf = BytesIO()
    page = landscape(A3)
    doc = SimpleDocTemplate(
        buf,
        pagesize=page,
        rightMargin=0.7 * cm,
        leftMargin=0.7 * cm,
        topMargin=0.7 * cm,
        bottomMargin=0.7 * cm,
        title=f"مجرى الأحداث والمعاضل — {day_label}",
        author="نظام إدارة التمارين",
    )
    title_style = ParagraphStyle(
        "pfPdfTitle",
        fontName=_FONT_BOLD,
        fontSize=12,
        leading=16,
        alignment=TA_CENTER,
        textColor=HexColor("#5c4033"),
        spaceAfter=4,
    )
    note_style = ParagraphStyle(
        "pfPdfNote",
        fontName=_FONT_REG,
        fontSize=8,
        leading=11,
        alignment=TA_RIGHT,
        textColor=HexColor("#2a241c"),
        spaceAfter=6,
    )
    cell_style = ParagraphStyle(
        "pfPdfCell",
        fontName=_FONT_REG,
        fontSize=6.5,
        leading=9,
        alignment=TA_RIGHT,
        textColor=HexColor("#1a1510"),
    )
    head_style = ParagraphStyle(
        "pfPdfHead",
        fontName=_FONT_BOLD,
        fontSize=6.5,
        leading=9,
        alignment=TA_CENTER,
        textColor=white,
    )
    merged_style = ParagraphStyle(
        "pfPdfMerged",
        fontName=_FONT_BOLD,
        fontSize=8,
        leading=11,
        alignment=TA_RIGHT,
        textColor=HexColor("#1a1510"),
    )

    story: list = [
        _cell(f"جدول مجرى الأحداث والمعاضل — {day_label}", title_style),
    ]
    if (note or "").strip():
        story.append(_cell(note, note_style))
    else:
        story.append(Spacer(1, 0.15 * cm))

    n_cols = len(_HEADERS)
    data: list[list] = [[_cell(h, head_style) for h in reversed(_HEADERS)]]
    span_cmds: list = []
    bg_cmds: list = []
    seq = 0
    for item in rows or []:
        kind = str((item or {}).get("kind") or "row").strip().lower()
        ridx = len(data)
        if kind in ("event", "dilemma"):
            text = str((item or {}).get("text") or "")
            merged = [_cell(text, merged_style)] + [""] * (n_cols - 1)
            data.append(merged)
            span_cmds.append(("SPAN", (0, ridx), (-1, ridx)))
            color = "#fff9c4" if kind == "event" else "#ffcdd2"
            bg_cmds.append(("BACKGROUND", (0, ridx), (-1, ridx), HexColor(color)))
            continue
        seq += 1
        values = [
            str(seq),
            str((item or {}).get("time") or ""),
            str((item or {}).get("time_kora") or ""),
            str((item or {}).get("time_from") or ""),
            str((item or {}).get("time_to") or ""),
            str((item or {}).get("report_systems") or ""),
            str((item or {}).get("description") or ""),
            str((item or {}).get("assignee") or ""),
            str((item or {}).get("reaction") or ""),
            str((item or {}).get("notes") or ""),
        ]
        data.append([_cell(v, cell_style) for v in reversed(values)])

    usable = page[0] - 1.4 * cm
    widths = [usable * x for x in (0.09, 0.11, 0.13, 0.16, 0.12, 0.07, 0.06, 0.08, 0.10, 0.08)]
    table = Table(data, colWidths=widths, repeatRows=1)
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#6b5344")),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#8a7a6c")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    style_cmds.extend(span_cmds)
    style_cmds.extend(bg_cmds)
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    try:
        doc.build(story)
    except Exception:
        return None
    out = buf.getvalue()
    return out if out[:4] == b"%PDF" else None
