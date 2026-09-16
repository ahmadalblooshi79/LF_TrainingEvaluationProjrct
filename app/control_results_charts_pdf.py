# -*- coding: utf-8 -*-
"""تصدير تقرير نتائج التقييم إلى PDF بحجم A3 — ثلاث صفحات في ملف واحد."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

_FONT_REG = "CrChartsAr"
_FONT_BOLD = "CrChartsArBold"
_FONTS_REGISTERED = False

_TRACK = HexColor("#efe8e0")
_INK = HexColor("#2a241c")
_MUTED = HexColor("#6b5e52")
_LINE = HexColor("#d9d2b8")
_LINE_STRONG = HexColor("#3d3228")
_TITLE = HexColor("#5c4033")
_NUM_BG = HexColor("#f4efe8")
_HEAD_BG = HexColor("#f3eee6")
_PAGE = landscape(A3)


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


def _hex(value: str, fallback: str = "#eab308") -> HexColor:
    s = (value or "").strip() or fallback
    if not s.startswith("#"):
        s = fallback
    try:
        return HexColor(s)
    except Exception:
        return HexColor(fallback)


def _header(c: Canvas, page_w: float, page_h: float, title: str, subtitle: str) -> float:
    top = page_h - 26
    c.setFillColor(_TITLE)
    c.setFont(_FONT_BOLD, 13)
    c.drawCentredString(page_w / 2, top, _shape_ar(title))
    top -= 15
    if subtitle:
        c.setFillColor(_MUTED)
        c.setFont(_FONT_REG, 8)
        c.drawCentredString(page_w / 2, top, _shape_ar(subtitle))
        top -= 7
    c.setStrokeColor(_LINE)
    c.setLineWidth(0.8)
    c.line(22, top, page_w - 22, top)
    return top - 12


def _empty_note(c: Canvas, page_w: float, page_h: float, msg: str) -> None:
    c.setFillColor(_MUTED)
    c.setFont(_FONT_REG, 12)
    c.drawCentredString(page_w / 2, page_h / 2, _shape_ar(msg))


def _draw_groups_page(c: Canvas, *, title: str, subtitle: str, rows: list[dict]) -> None:
    page_w, page_h = _PAGE
    y = _header(c, page_w, page_h, title, subtitle)
    if not rows:
        _empty_note(c, page_w, page_h, "لا توجد نتائج محفوظة لعرض أداء المجموعات.")
        return

    n = len(rows)
    bottom = 22
    usable = max(80.0, y - bottom)
    row_h = min(22.0, usable / n)
    font_size = 9.0 if row_h >= 16 else (7.5 if row_h >= 12 else 6.2)
    margin = 28.0
    seq_w = 26.0
    gap = 8.0
    pct_reserve = 36.0

    c.setFont(_FONT_REG, font_size)
    max_name = 0.0
    for item in rows:
        max_name = max(max_name, c.stringWidth(_shape_ar(str(item.get("label") or "—")), _FONT_REG, font_size))
    name_w = min(max(max_name + 6, 80.0), page_w * 0.46)

    x_right = page_w - margin
    seq_right = x_right
    name_right = seq_right - seq_w - gap
    name_left = name_right - name_w
    bar_right = name_left - gap
    bar_left = margin + pct_reserve
    bar_w = max(40.0, bar_right - bar_left)

    y_cursor = y
    for item in rows:
        mid = y_cursor - row_h / 2
        box_h = max(11.0, row_h * 0.72)
        seq = str(item.get("seq") or "")
        c.setFillColor(_NUM_BG)
        c.setStrokeColor(_LINE)
        c.setLineWidth(0.5)
        c.roundRect(seq_right - seq_w, mid - box_h / 2, seq_w, box_h, 3, fill=1, stroke=1)
        c.setFillColor(_TITLE)
        c.setFont(_FONT_BOLD, font_size)
        c.drawCentredString(seq_right - seq_w / 2, mid - font_size * 0.32, seq)

        c.setFillColor(_INK)
        c.setFont(_FONT_BOLD, font_size)
        c.drawRightString(name_right, mid - font_size * 0.32, _shape_ar(str(item.get("label") or "—")))

        c.setFillColor(_TRACK)
        c.roundRect(bar_left, mid - box_h / 2, bar_w, box_h, box_h / 2, fill=1, stroke=0)
        pct = max(0.0, min(100.0, float(item.get("value") or 0)))
        fill_w = max(3.0, bar_w * pct / 100.0)
        c.setFillColor(_hex(str(item.get("color") or "")))
        c.roundRect(bar_right - fill_w, mid - box_h / 2, fill_w, box_h, box_h / 2, fill=1, stroke=0)
        c.setFillColor(_INK)
        c.setFont(_FONT_BOLD, max(6.0, font_size - 0.5))
        c.drawString(bar_left + 2, mid - font_size * 0.32, f"{int(pct)}%")
        y_cursor -= row_h


def _draw_phases_page(
    c: Canvas,
    *,
    title: str,
    subtitle: str,
    slices: list[dict],
    total_pct: str,
) -> None:
    page_w, page_h = _PAGE
    y = _header(c, page_w, page_h, title, subtitle)
    if not slices:
        _empty_note(c, page_w, page_h, "لا توجد نتائج محفوظة لعرض مراحل التمرين.")
        return

    cx = page_w / 2
    donut_d = min(page_w * 0.42, (y - 120) * 0.78, 360)
    cy = 120 + (y - 120) * 0.58
    r = donut_d / 2
    x1, y1, x2, y2 = cx - r, cy - r, cx + r, cy + r

    weights = [max(0.0, float(item.get("pct") or 0)) for item in slices]
    total_w = sum(weights)
    shares = (
        [w / total_w for w in weights]
        if total_w > 0
        else [1.0 / len(slices)] * len(slices)
    )

    start = 90.0
    c.setStrokeColor(white)
    c.setLineWidth(0.6)
    for item, share in zip(slices, shares):
        extent = -share * 360.0
        if abs(extent) < 0.05:
            continue
        c.setFillColor(_hex(str(item.get("color") or "#94a3b8"), "#94a3b8"))
        c.wedge(x1, y1, x2, y2, start, extent, stroke=1, fill=1)
        start += extent

    hole_r = r * 0.58
    c.setFillColor(HexColor("#fefdfb"))
    c.setStrokeColor(_LINE)
    c.setLineWidth(1)
    c.circle(cx, cy, hole_r, fill=1, stroke=1)
    c.setFillColor(_MUTED)
    c.setFont(_FONT_BOLD, 10)
    c.drawCentredString(cx, cy + 8, _shape_ar("المجموع العام"))
    c.setFillColor(_INK)
    c.setFont(_FONT_BOLD, 18)
    c.drawCentredString(cx, cy - 16, str(total_pct))

    legend_top = cy - r - 28
    row_h = 22
    box_w = min(420.0, page_w * 0.55)
    box_x = (page_w - box_w) / 2
    for i, item in enumerate(slices):
        ly = legend_top - i * row_h
        c.setFillColor(HexColor("#f7f3ee"))
        c.roundRect(box_x, ly - 6, box_w, 18, 4, fill=1, stroke=0)
        c.setFillColor(_hex(str(item.get("color") or "#94a3b8"), "#94a3b8"))
        c.circle(box_x + box_w - 14, ly + 3, 4.2, fill=1, stroke=0)
        c.setFillColor(_INK)
        c.setFont(_FONT_BOLD, 10)
        c.drawRightString(box_x + box_w - 26, ly, _shape_ar(str(item.get("label") or "—")))
        disp = item.get("pct_display")
        if disp is None:
            disp = item.get("pct")
        c.setFont(_FONT_BOLD, 10)
        c.drawString(box_x + 12, ly, f"{disp}%")


def _draw_detail_page(
    c: Canvas,
    *,
    title: str,
    subtitle: str,
    rows: list[dict],
    phase_headers: list[str],
    phase_max_dots: list[int],
    list_number_row: list[dict],
    grade_legend: list[dict],
) -> None:
    page_w, page_h = _PAGE
    y = _header(c, page_w, page_h, title, subtitle)
    if not rows:
        _empty_note(c, page_w, page_h, "لا توجد نتائج محفوظة لعرض الجدول التفصيلي.")
        return

    margin = 18.0
    legend_h = 22.0 if grade_legend else 0.0
    bottom = 16.0 + legend_h
    maxes = [max(1, int(n or 0)) for n in (phase_max_dots or [1])]
    if not maxes:
        maxes = [1]
    total_slots = sum(maxes) or 1
    n_rows = len(rows)

    head_h = 28.0
    usable = max(90.0, y - bottom - head_h)
    row_h = min(18.0, usable / n_rows)
    unit_font = 7.2 if row_h >= 14 else 6.0
    cell_font = 6.2 if row_h >= 14 else 5.2

    c.setFont(_FONT_REG, unit_font)
    max_name = 0.0
    for urow in rows:
        max_name = max(
            max_name,
            c.stringWidth(_shape_ar(str(urow.get("unit_label") or "—")), _FONT_REG, unit_font),
        )
    unit_w = min(max(72.0, max_name + 10), page_w * 0.22)
    grid_left = margin
    grid_right = page_w - margin
    slots_w = max(40.0, grid_right - grid_left - unit_w)
    slot_w = slots_w / total_slots
    unit_left = grid_right - unit_w
    table_top = y
    table_bottom = table_top - head_h - n_rows * row_h

    # خلفية رأس الجدول
    c.setFillColor(_HEAD_BG)
    c.rect(grid_left, table_top - head_h, grid_right - grid_left, head_h, fill=1, stroke=0)

    # عمود الوحدة
    c.setFillColor(_INK)
    c.setFont(_FONT_BOLD, 8)
    c.drawCentredString(unit_left + unit_w / 2, table_top - 18, _shape_ar("الوحدة"))

    # رؤوس المراحل والترقيم
    x = unit_left
    headers = list(phase_headers or [])
    nums_by_phase = list(list_number_row or [])
    for i, max_dots in enumerate(maxes):
        phase_w = slot_w * max_dots
        x -= phase_w
        label = headers[i] if i < len(headers) else ""
        c.setFillColor(_TITLE)
        c.setFont(_FONT_BOLD, 7.2)
        c.drawCentredString(x + phase_w / 2, table_top - 11, _shape_ar(str(label)))
        slots = []
        if i < len(nums_by_phase):
            slots = list((nums_by_phase[i] or {}).get("slots") or [])
        if not slots:
            slots = list(range(1, max_dots + 1))
        c.setFont(_FONT_BOLD, 6.2)
        c.setFillColor(_MUTED)
        for si, num in enumerate(slots[:max_dots]):
            cx = x + phase_w - (si + 0.5) * slot_w
            c.drawCentredString(cx, table_top - 23, str(num))

    # صفوف الوحدات
    y_row = table_top - head_h
    for urow in rows:
        y_row -= row_h
        c.setFillColor(_INK)
        c.setFont(_FONT_BOLD, unit_font)
        c.drawRightString(
            grid_right - 4,
            y_row + row_h * 0.32,
            _shape_ar(str(urow.get("unit_label") or "—")),
        )
        x = unit_left
        phases = list(urow.get("phases") or [])
        for i, max_dots in enumerate(maxes):
            dots = list((phases[i] if i < len(phases) else {}).get("dots") or [])
            for si in range(max_dots):
                x -= slot_w
                if si >= len(dots):
                    continue
                dot = dots[si] or {}
                try:
                    pct = int(dot.get("pct"))
                except (TypeError, ValueError):
                    continue
                c.setFillColor(_hex(str(dot.get("color") or "")))
                c.rect(x, y_row, slot_w, row_h, fill=1, stroke=0)
                c.setFillColor(_INK)
                c.setFont(_FONT_BOLD, cell_font)
                c.drawCentredString(x + slot_w / 2, y_row + row_h * 0.32, f"{pct}%")

    # شبكة وحدود المراحل
    c.setStrokeColor(_LINE)
    c.setLineWidth(0.35)
    c.rect(grid_left, table_bottom, grid_right - grid_left, table_top - table_bottom, fill=0, stroke=1)
    c.line(unit_left, table_top, unit_left, table_bottom)
    c.line(grid_left, table_top - head_h, grid_right, table_top - head_h)
    y_line = table_top - head_h
    for _ in rows:
        y_line -= row_h
        c.line(grid_left, y_line, grid_right, y_line)
    x = unit_left
    for i, max_dots in enumerate(maxes):
        for si in range(max_dots):
            x -= slot_w
            if si == 0:
                c.setStrokeColor(_LINE_STRONG)
                c.setLineWidth(1.4)
            else:
                c.setStrokeColor(_LINE)
                c.setLineWidth(0.3)
            c.line(x + slot_w, table_top, x + slot_w, table_bottom)

    if grade_legend:
        lx = grid_right
        ly = table_bottom - 14
        c.setFillColor(_MUTED)
        c.setFont(_FONT_BOLD, 7)
        label = _shape_ar("مفتاح الألوان")
        c.drawRightString(lx, ly, label)
        lx -= c.stringWidth(label, _FONT_BOLD, 7) + 10
        for item in grade_legend:
            c.setFillColor(_hex(str(item.get("color") or "")))
            c.circle(lx - 5, ly + 2.5, 4, fill=1, stroke=0)
            txt = _shape_ar(f"{item.get('label') or ''} — {item.get('range') or ''}")
            c.setFillColor(_INK)
            c.setFont(_FONT_REG, 6.5)
            c.drawRightString(lx - 12, ly, txt)
            lx -= c.stringWidth(txt, _FONT_REG, 6.5) + 22


def build_control_results_report_a3_pdf(report: dict) -> bytes:
    _ensure_fonts()
    buf = BytesIO()
    c = Canvas(buf, pagesize=_PAGE)
    c.setTitle("عرض نتائج التقييم")
    c.setAuthor("نظام إدارة التمارين")
    subtitle = " — ".join(str(x) for x in (report.get("meta") or []) if x)

    _draw_detail_page(
        c,
        title="أداء الوحدات التفصيلي حسب قوائم التقييم (مراحل التمرين)",
        subtitle=subtitle,
        rows=list(report.get("unit_detail_rows") or []),
        phase_headers=list(report.get("unit_detail_phase_headers") or []),
        phase_max_dots=list(report.get("unit_detail_phase_max_dots") or []),
        list_number_row=list(report.get("unit_detail_list_number_row") or []),
        grade_legend=list(report.get("grade_legend") or []),
    )
    c.showPage()
    _draw_groups_page(
        c,
        title="أداء المجموعات (متوسط النسبة العامة)",
        subtitle=subtitle,
        rows=list(report.get("group_scores") or []),
    )
    c.showPage()
    summary = report.get("phase_summary") or {}
    total = summary.get("exercise_pct")
    total_txt = f"{round(float(total), 2)}%" if total is not None else "—"
    _draw_phases_page(
        c,
        title="أداء الوحدات حسب مراحل التمرين",
        subtitle=subtitle,
        slices=list(report.get("distribution") or []),
        total_pct=total_txt,
    )
    c.save()
    return buf.getvalue()
