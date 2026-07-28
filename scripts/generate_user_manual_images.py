# -*- coding: utf-8 -*-
"""Capture real UI screenshots for the user manual and add Arabic callouts.

Requires the app running locally (default http://127.0.0.1:8005).

Run from project root:
  .venv\\Scripts\\python.exe scripts/generate_user_manual_images.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).resolve().parents[1] / "app" / "static" / "user_manual"
DEFAULT_BASE = "http://127.0.0.1:8005"
DEMO_USER = "admin"
DEMO_PASSWORD = "demo123"

VIEWPORT = {"width": 1440, "height": 900}
# Keep 1.0 so screenshot pixels match locator bounding boxes.
DEVICE_SCALE = 1.0

ACCENT = (139, 69, 19)
WHITE = (255, 255, 255)
BANNER_BG = (245, 239, 230)
BANNER_FG = (92, 64, 51)
RING = (180, 90, 40)


def ar(t: str) -> str:
    return get_display(arabic_reshaper.reshape(t or ""))


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def save(img: Image.Image, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    # Keep manual images reasonably sized for HTML/PDF.
    max_w = 1280
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)), Image.Resampling.LANCZOS)
    img.save(path, "PNG", optimize=True)
    print("wrote", path)


def login(page: Page, base: str, username: str = DEMO_USER, password: str = DEMO_PASSWORD) -> None:
    page.goto(f"{base}/logout", wait_until="domcontentloaded")
    page.goto(f"{base}/login", wait_until="networkidle")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


def shot(page: Page, full_page: bool = False, *, reset_scroll: bool = True) -> Image.Image:
    if reset_scroll:
        page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(250)
    raw = page.screenshot(full_page=full_page, type="png")
    from io import BytesIO

    return Image.open(BytesIO(raw)).convert("RGB")


def boxes_scaled(
    page: Page, selector: str, *, viewport: bool = False
) -> tuple[float, float, float, float] | None:
    """Bounding box in screenshot pixel space.

    viewport=True  → getBoundingClientRect (non-full-page shots)
    viewport=False → document coords (full_page shots)
    """
    loc = page.locator(selector).first
    if loc.count() == 0:
        return None
    try:
        if not loc.is_visible():
            return None
        handle = loc.element_handle()
        if handle is None:
            return None
        box = page.evaluate(
            """(el) => {
              const r = el.getBoundingClientRect();
              return {
                x: r.left,
                y: r.top,
                docX: r.left + window.scrollX,
                docY: r.top + window.scrollY,
                width: r.width,
                height: r.height
              };
            }""",
            handle,
        )
    except Exception:
        return None
    if not box or box.get("width", 0) <= 0:
        return None
    if viewport:
        return float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])
    return float(box["docX"]), float(box["docY"]), float(box["width"]), float(box["height"])


def box_of(
    page: Page, selector: str, *, viewport: bool = False
) -> tuple[float, float, float, float] | None:
    return boxes_scaled(page, selector, viewport=viewport)


def add_banner(img: Image.Image, title: str) -> Image.Image:
    """Top title strip describing the screenshot."""
    pad = 14
    f = font(22, True)
    text = ar(title)
    tw, th = ImageDraw.Draw(img).textbbox((0, 0), text, font=f)[2:]
    bar_h = th + pad * 2
    out = Image.new("RGB", (img.width, img.height + bar_h), BANNER_BG)
    out.paste(img, (0, bar_h))
    d = ImageDraw.Draw(out)
    d.rectangle((0, 0, out.width, bar_h), fill=BANNER_BG)
    d.line((0, bar_h - 1, out.width, bar_h - 1), fill=ACCENT, width=2)
    d.text(((out.width - tw) // 2, pad), text, fill=BANNER_FG, font=f)
    return out


def annotate(
    img: Image.Image,
    callouts: list[dict],
    *,
    banner: str | None = None,
) -> Image.Image:
    """Draw numbered callouts. Each callout: x,y,w,h,text[,side].

    Coordinates are relative to the raw screenshot (before banner).
    """
    bar_h = 0
    work = img
    if banner:
        work = add_banner(img, banner)
        # Measure banner height from difference
        bar_h = work.height - img.height

    d = ImageDraw.Draw(work)
    f_num = font(16, True)
    f_lab = font(15, True)
    for i, c in enumerate(callouts, start=1):
        x, y, w, h = float(c["x"]), float(c["y"]), float(c["w"]), float(c["h"])
        y += bar_h
        # Highlight ring
        pad = 4
        d.rounded_rectangle(
            (x - pad, y - pad, x + w + pad, y + h + pad),
            radius=10,
            outline=RING,
            width=3,
        )
        # Number badge
        cx = x + w + 18
        cy = y + 8
        side = (c.get("side") or "right").lower()
        if side == "left":
            cx = max(18, x - 22)
        elif side == "top":
            cx = x + w / 2
            cy = max(18, y - 22)
        elif side == "bottom":
            cx = x + w / 2
            cy = y + h + 18
        r = 14
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ACCENT, outline=WHITE, width=2)
        nt = ar(str(i))
        nb = d.textbbox((0, 0), nt, font=f_num)
        d.text((cx - (nb[2] - nb[0]) / 2, cy - (nb[3] - nb[1]) / 2 - 1), nt, fill=WHITE, font=f_num)

        label = ar(str(c.get("text") or ""))
        if not label:
            continue
        lb = d.textbbox((0, 0), label, font=f_lab)
        lw, lh = lb[2] - lb[0], lb[3] - lb[1]
        lx = cx + r + 10
        ly = cy - lh / 2
        if side == "left":
            lx = cx - r - 10 - lw
        elif side in ("top", "bottom"):
            lx = cx - lw / 2
            ly = cy + r + 6 if side == "bottom" else cy - r - 6 - lh
        # Keep on canvas
        lx = max(6, min(lx, work.width - lw - 10))
        ly = max(6 if not banner else bar_h + 4, min(ly, work.height - lh - 8))
        d.rounded_rectangle(
            (lx - 8, ly - 5, lx + lw + 8, ly + lh + 5),
            radius=8,
            fill=(255, 252, 248),
            outline=ACCENT,
            width=2,
        )
        d.text((lx, ly), label, fill=BANNER_FG, font=f_lab)
    return work


def callouts_from_selectors(
    page: Page,
    specs: list[tuple[str, str, str | None]],
    *,
    viewport: bool = False,
) -> list[dict]:
    out: list[dict] = []
    for selector, text, side in specs:
        b = box_of(page, selector, viewport=viewport)
        if not b:
            print(f"  warn: missing selector {selector!r}")
            continue
        x, y, w, h = b
        out.append({"x": x, "y": y, "w": w, "h": h, "text": text, "side": side or "right"})
    return out


def capture_all(base: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport=VIEWPORT,
            locale="ar",
            device_scale_factor=DEVICE_SCALE,
        )
        page = context.new_page()

        # --- 01 login ---
        page.goto(f"{base}/logout", wait_until="domcontentloaded")
        page.goto(f"{base}/login", wait_until="networkidle")
        img = shot(page)
        specs = [
            ("#username", "اسم المستخدم", "left"),
            ("#password", "كلمة المرور", "left"),
            ('button[type="submit"]', "ثم اضغط دخول", "bottom"),
        ]
        save(
            annotate(
                img,
                callouts_from_selectors(page, specs, viewport=True),
                banner="شاشة تسجيل الدخول",
            ),
            "01_login.png",
        )

        # --- 02 dashboard roles ---
        login(page, base, DEMO_USER, DEMO_PASSWORD)
        page.goto(f"{base}/dashboard", wait_until="networkidle")
        grid = page.locator(".role-grid").first
        if grid.count():
            grid.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
        img = shot(page, full_page=False, reset_scroll=False)
        role_box = box_of(page, ".role-grid", viewport=True)
        calls = []
        if role_box:
            calls.append(
                {
                    "x": role_box[0],
                    "y": role_box[1],
                    "w": role_box[2],
                    "h": role_box[3],
                    "text": "اختر بطاقة دورك ثم اضغط ابدأ",
                    "side": "bottom",
                }
            )
        save(annotate(img, calls, banner="الصفحة الرئيسية — بطاقات الأدوار"), "02_home_roles.png")

        # --- 03 admin shell ---
        page.goto(f"{base}/admin/exercises/create", wait_until="networkidle")
        img = shot(page, full_page=True)
        specs = [
            ("#app-sidebar", "أوامر العمل — اختر الصفحة من هنا", "left"),
            (".admin-shell__workspace", "مساحة العمل للمحتوى المختار", "right"),
        ]
        save(
            annotate(img, callouts_from_selectors(page, specs), banner="إدارة النظام — أوامر العمل"),
            "03_admin_shell.png",
        )

        # --- 04 create exercise ---
        img = shot(page, full_page=True)
        specs = [
            (".admin-shell__workspace form, .admin-shell__workspace .card, .admin-shell__workspace", "عبّئ بيانات التمرين", "right"),
            ('button[type="submit"], .btn-primary, form button.btn', "ثم احفظ التمرين", "bottom"),
        ]
        # Prefer first submit inside workspace
        boxes = []
        for sel, text, side in [
            (".admin-shell__workspace", "عبّئ الحقول ثم احفظ", "right"),
            ('form button[type="submit"]', "حفظ التمرين", "bottom"),
        ]:
            b = box_of(page, sel)
            if b:
                boxes.append({"x": b[0], "y": b[1], "w": b[2], "h": b[3], "text": text, "side": side})
        save(
            annotate(img, boxes, banner="إنشاء تمرين جديد — من الواجهة الفعلية"),
            "04_create_exercise.png",
        )

        # --- 05 information bank ---
        page.goto(f"{base}/admin/information-bank", wait_until="networkidle")
        # Prefer event-flow tab if present
        tab = page.locator(
            'a:has-text("مجرى الأحداث"), button:has-text("مجرى الأحداث"), [role="tab"]:has-text("مجرى")'
        ).first
        if tab.count() and tab.is_visible():
            try:
                tab.click()
                page.wait_for_timeout(500)
            except Exception:
                pass
        img = shot(page, full_page=True)
        specs = [
            (
                ".ibank-tabs, .tabs, .nav-tabs, [role='tablist'], .admin-shell__workspace",
                "تبويبات بنك المعلومات",
                "bottom",
            ),
        ]
        save(
            annotate(img, callouts_from_selectors(page, specs), banner="بنك المعلومات — الواجهة الفعلية"),
            "05_ibank.png",
        )

        # --- 06 planner hub ---
        page.goto(f"{base}/planner", wait_until="networkidle")
        img = shot(page, full_page=True)
        specs = [
            ('a.admin-action-btn[href*="/planner/new-flow"]', "أولاً: مجرى الأحداث", "bottom"),
            (
                'a.admin-action-btn[href*="/planner/new-action-eval-lists"]',
                "ثانياً: قوائم تقييم الإجراءات",
                "bottom",
            ),
            (
                'a.admin-action-btn[href*="/planner/new-evaluation-list"]',
                "ثالثاً: قوائم التقييم / النشر",
                "bottom",
            ),
        ]
        calls = callouts_from_selectors(page, specs)
        if not calls:
            calls = callouts_from_selectors(
                page, [(".role-hub-menu", "أوامر التخطيط بالترتيب", "left")]
            )
        save(annotate(img, calls, banner="التخطيط — أوامر العمل الفعلية"), "06_planner.png")

        # --- 07 judge eval lists ---
        page.goto(f"{base}/judge/evaluation-lists", wait_until="networkidle")
        img = shot(page, full_page=True)
        specs = [
            (".page-header h1, h1", "قوائم التقييم", "left"),
            ("table tbody, table, .card", "افتح قوائم الوحدة ثم عبّئ واحفظ واعتمد", "top"),
        ]
        calls = callouts_from_selectors(page, specs)
        if not calls:
            page.goto(f"{base}/judge", wait_until="networkidle")
            img = shot(page, full_page=True)
            calls = callouts_from_selectors(
                page,
                [
                    ('a.admin-action-btn[href*="evaluation-lists"]', "افتح قوائم التقييم", "bottom"),
                    ('a.admin-action-btn[href*="incomplete"]', "راجع المهام غير المكتملة", "bottom"),
                ],
            )
        save(annotate(img, calls, banner="المحكم — فتح القوائم ثم الحفظ والاعتماد"), "07_judge_eval.png")

        # --- 08 approval path (control status) ---
        page.goto(f"{base}/control/evaluation-lists-status", wait_until="networkidle")
        img = shot(page, full_page=True)
        specs = [
            (".page-header h1, h1", "موقف القوائم يوضح مسار الاعتماد", "left"),
            ("table, .card", "تابع الحالة: محكم ← كبير محكمين ← سيطرة", "top"),
        ]
        save(
            annotate(img, callouts_from_selectors(page, specs), banner="مسار الاعتماد من واجهة السيطرة"),
            "08_approval_flow.png",
        )

        # --- 09 control hub ---
        page.goto(f"{base}/control", wait_until="networkidle")
        img = shot(page, full_page=True)
        specs = [
            ('a.admin-action-btn[href*="evaluation-results"]', "عرض النتائج", "bottom"),
            ('a.admin-action-btn[href*="evaluation-lists-status"]', "موقف القوائم والمهام", "bottom"),
            ('a.admin-action-btn[href*="positives"]', "الإيجابيات والسلبيات", "bottom"),
        ]
        calls = callouts_from_selectors(page, specs)
        if not calls:
            calls = callouts_from_selectors(page, [(".role-hub-menu", "أوامر السيطرة", "left")])
        save(annotate(img, calls, banner="السيطرة — أوامر المتابعة"), "09_control.png")

        # --- 10 analyst hub ---
        page.goto(f"{base}/analyst", wait_until="networkidle")
        img = shot(page, full_page=True)
        specs = [
            ('a.admin-action-btn[href*="evaluation-criteria"]', "معايير التقييم", "bottom"),
            ('a.admin-action-btn[href*="evaluation-results"]', "عرض النتائج", "bottom"),
            ('a.admin-action-btn[href*="judges-eval"]', "تحليل المحكمين", "bottom"),
        ]
        calls = callouts_from_selectors(page, specs)
        if not calls:
            calls = callouts_from_selectors(page, [(".role-hub-menu", "أدوات المحللين", "left")])
        save(annotate(img, calls, banner="المحلل — الأدوات الفعلية"), "10_analyst.png")

        # --- 11 shared header tools ---
        page.goto(f"{base}/dashboard", wait_until="networkidle")
        header = page.locator("header#header-mobile-nav, header").first
        if header.count():
            raw = header.screenshot(type="png")
            from io import BytesIO

            img = Image.open(BytesIO(raw)).convert("RGB")
            # Boxes relative to header element
            hb = header.bounding_box() or {"x": 0, "y": 0}

            def header_callouts() -> list[dict]:
                specs_local = [
                    ('a[href="/dashboard"]', "الصفحة الرئيسية", "bottom"),
                    ("a:has-text('غرفة المحادثة')", "غرفة المحادثة", "bottom"),
                    ("a:has-text('معلومات التمرين')", "معلومات التمرين", "bottom"),
                    ('a[href="/library"]', "المكتبة", "bottom"),
                    ("#header-notif-link", "الإشعارات", "bottom"),
                    ('a.btn-nav-logout[href="/logout"], a[href="/logout"]', "خروج", "bottom"),
                ]
                out: list[dict] = []
                for sel, text, side in specs_local:
                    loc = page.locator(f"header {sel}").first
                    if not loc.count() or not loc.is_visible():
                        print(f"  warn: missing selector header {sel!r}")
                        continue
                    b = loc.bounding_box()
                    if not b:
                        continue
                    out.append(
                        {
                            "x": b["x"] - hb["x"],
                            "y": b["y"] - hb["y"],
                            "w": b["width"],
                            "h": b["height"],
                            "text": text,
                            "side": side,
                        }
                    )
                return out

            save(
                annotate(img, header_callouts(), banner="الشريط العلوي — أدوات مشتركة"),
                "11_shared_tools.png",
            )
        else:
            img = shot(page)
            specs = [
                ('a[href="/dashboard"]', "الصفحة الرئيسية", "bottom"),
                ("a:has-text('غرفة المحادثة')", "غرفة المحادثة", "bottom"),
                ("a:has-text('معلومات التمرين')", "معلومات التمرين", "bottom"),
                ('a[href="/library"]', "المكتبة", "bottom"),
                ("#header-notif-link", "الإشعارات", "bottom"),
                ('a[href="/logout"]', "خروج", "bottom"),
            ]
            save(
                annotate(
                    img,
                    callouts_from_selectors(page, specs, viewport=True),
                    banner="الشريط العلوي — أدوات مشتركة",
                ),
                "11_shared_tools.png",
            )

        # --- 12 checklist on real UI ---
        page.goto(f"{base}/admin/exercises/create", wait_until="networkidle")
        img = shot(page, full_page=True)
        specs = [
            (".header-workspace-exercise", "تحقق: التمرين الحالي ظاهر في الرأس", "bottom"),
            ('a.admin-action-btn[href*="judge-unit-roster"]', "تحقق: المحكمون مربوطون بالوحدات", "left"),
            ('a.admin-action-btn[href*="information-bank"]', "تحقق: المجرى والقوائم جاهزة", "left"),
            ('nav.header-bar__segment--center a[href="/planner"]', "تحقق: تجربة اعتماد عبر التخطيط/المحكمين", "bottom"),
        ]
        save(
            annotate(img, callouts_from_selectors(page, specs), banner="قائمة تحقق قبل التقييم الميداني"),
            "12_checklist.png",
        )

        browser.close()
    print("done", len(list(OUT.glob("*.png"))), "png files in", OUT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE, help="App base URL")
    args = ap.parse_args()
    try:
        capture_all(args.base.rstrip("/"))
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        print(
            "Make sure the app is running (run.bat / run.py) and Playwright Chromium is installed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
