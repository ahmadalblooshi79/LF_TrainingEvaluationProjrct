# -*- coding: utf-8 -*-
"""Generate educational PNG illustrations for the user manual.

Run from project root:
  .venv\\Scripts\\python.exe scripts/generate_user_manual_images.py
"""
from __future__ import annotations

from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "app" / "static" / "user_manual"

BG = (245, 239, 230)
CARD = (255, 252, 248)
BORDER = (196, 169, 144)
BROWN = (92, 64, 51)
ACCENT = (139, 69, 19)
MUTED = (109, 90, 78)
WHITE = (255, 255, 255)
SOFT = (247, 240, 228)
GREEN = (70, 120, 80)


def ar(t: str) -> str:
    return get_display(arabic_reshaper.reshape(t))


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def new(w: int, h: int):
    img = Image.new("RGB", (w, h), BG)
    return img, ImageDraw.Draw(img)


def round_rect(d, box, fill, outline=None, width=2, r=14):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def caption(d, text: str, y: int, w: int):
    f = font(22, True)
    t = ar(text)
    tw = d.textbbox((0, 0), t, font=f)[2]
    d.text(((w - tw) // 2, y), t, fill=BROWN, font=f)


def save(img: Image.Image, name: str):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    img.save(p, "PNG", optimize=True)
    print("wrote", p)


def make_all() -> None:
    # 01 login
    img, d = new(900, 520)
    caption(d, "شاشة تسجيل الدخول", 18, 900)
    round_rect(d, (220, 80, 680, 470), CARD, BORDER, 2, 18)
    t = ar("نظام إدارة التمارين")
    f = font(26, True)
    tw = d.textbbox((0, 0), t, font=f)[2]
    d.text(((900 - tw) // 2, 115), t, fill=ACCENT, font=f)
    for i, label in enumerate(["اسم المستخدم", "كلمة المرور"]):
        y = 190 + i * 85
        lt = ar(label)
        d.text((640 - d.textbbox((0, 0), lt, font=font(18))[2], y), lt, fill=MUTED, font=font(18))
        round_rect(d, (280, y + 28, 620, y + 68), WHITE, BORDER, 2, 8)
    round_rect(d, (340, 380, 560, 430), ACCENT, ACCENT, 0, 10)
    bt = ar("دخول")
    bw = d.textbbox((0, 0), bt, font=font(22, True))[2]
    d.text((450 - bw // 2, 392), bt, fill=WHITE, font=font(22, True))
    round_rect(d, (30, 240, 70, 280), ACCENT, None, 0, 20)
    d.text((42, 248), ar("1"), fill=WHITE, font=font(20, True))
    d.text((80, 248), ar("أدخل البيانات ثم اضغط دخول"), fill=BROWN, font=font(16))
    save(img, "01_login.png")

    # 02 home
    img, d = new(980, 560)
    caption(d, "الصفحة الرئيسية — اختر بطاقة دورك", 16, 980)
    roles = ["إدارة النظام", "التخطيط", "المحكمين", "كبير المحكمين", "السيطرة", "المحللين"]
    for i, role in enumerate(roles):
        x = 40 + (i % 3) * 310
        y = 80 + (i // 3) * 220
        round_rect(d, (x, y, x + 280, y + 180), CARD, BORDER, 2, 16)
        rt = ar(role)
        rw = d.textbbox((0, 0), rt, font=font(22, True))[2]
        d.text((x + (280 - rw) // 2, y + 40), rt, fill=BROWN, font=font(22, True))
        round_rect(d, (x + 70, y + 110, x + 210, y + 150), ACCENT, None, 0, 10)
        bt = ar("ابدأ")
        bw = d.textbbox((0, 0), bt, font=font(18, True))[2]
        d.text((x + (280 - bw) // 2, y + 118), bt, fill=WHITE, font=font(18, True))
    d.rounded_rectangle((36, 76, 324, 264), radius=18, outline=(180, 90, 40), width=4)
    d.text((40, 500), ar("اضغط بطاقة دورك ثم «ابدأ» للدخول إلى مساحة العمل"), fill=MUTED, font=font(17))
    save(img, "02_home_roles.png")

    # 03 admin shell
    img, d = new(980, 620)
    caption(d, "إدارة النظام — أوامر العمل", 16, 980)
    round_rect(d, (40, 70, 680, 580), CARD, BORDER, 2, 14)
    d.text((520, 90), ar("مساحة العمل"), fill=BROWN, font=font(20, True))
    round_rect(d, (80, 140, 640, 520), SOFT, BORDER, 1, 10)
    d.text((430, 280), ar("محتوى الصفحة المختارة"), fill=MUTED, font=font(18))
    round_rect(d, (710, 70, 940, 580), CARD, BORDER, 2, 14)
    d.text((780, 90), ar("أوامر العمل"), fill=ACCENT, font=font(18, True))
    items = [
        "إنشاء تمرين جديد",
        "الأهداف التدريبية",
        "بنك المعلومات",
        "قائمة الوحدة المتدربة",
        "قائمة المحكمين",
        "تنظيم المعركة",
        "إدارة المستخدمين",
        "دليل المستخدم",
        "مسح بيانات التمرين",
    ]
    for i, it in enumerate(items):
        y = 130 + i * 45
        fill = (255, 236, 214) if i == 0 else SOFT
        outline = ACCENT if i == 0 else BORDER
        round_rect(d, (730, y, 920, y + 36), fill, outline, 2 if i == 0 else 1, 8)
        t = ar(it)
        d.text((910 - d.textbbox((0, 0), t, font=font(14))[2], y + 8), t, fill=BROWN, font=font(14))
    d.text((40, 590), ar("اختر الأمر من الشريط الجانبي لفتح الصفحة المناسبة"), fill=MUTED, font=font(16))
    save(img, "03_admin_shell.png")

    # 04 create exercise
    img, d = new(900, 560)
    caption(d, "إنشاء تمرين جديد — تعبئة البيانات ثم الحفظ", 14, 900)
    round_rect(d, (80, 70, 820, 500), CARD, BORDER, 2, 14)
    fields = [
        "اسم الوحدة المتدربة",
        "مكان التمرين",
        "اسم التمرين",
        "نوع / مستوى التمرين",
        "المهمة",
        "تاريخ البداية والنهاية",
    ]
    for i, lab in enumerate(fields):
        y = 100 + i * 48
        t = ar(lab)
        d.text((780 - d.textbbox((0, 0), t, font=font(16))[2], y), t, fill=MUTED, font=font(16))
        round_rect(d, (120, y + 22, 760, y + 46), WHITE, BORDER, 1, 6)
    round_rect(d, (330, 430, 570, 475), ACCENT, None, 0, 10)
    bt = ar("حفظ التمرين")
    bw = d.textbbox((0, 0), bt, font=font(18, True))[2]
    d.text((450 - bw // 2, 442), bt, fill=WHITE, font=font(18, True))
    save(img, "04_create_exercise.png")

    # 05 ibank
    img, d = new(960, 420)
    caption(d, "بنك المعلومات — التبويبات الرئيسية", 16, 960)
    tabs = ["مراحل التمرين", "مستويات الوحدات", "مجرى الأحداث والمعاضل", "قوائم تقييم الإجراءات", "قوائم التقييم"]
    x = 30
    for i, tab in enumerate(tabs):
        t = ar(tab)
        tw = d.textbbox((0, 0), t, font=font(14, True))[2] + 28
        fill = ACCENT if i == 2 else CARD
        tc = WHITE if i == 2 else BROWN
        round_rect(d, (x, 80, x + tw, 120), fill, BORDER, 1, 8)
        d.text((x + 14, 90), t, fill=tc, font=font(14, True))
        x += tw + 10
    round_rect(d, (30, 140, 930, 370), CARD, BORDER, 2, 12)
    headers = ["اليوم", "الحدث", "المعضلة", "المكلّف"]
    for i, h in enumerate(headers):
        d.text((80 + i * 200, 170), ar(h), fill=ACCENT, font=font(16, True))
    for r in range(3):
        y = 210 + r * 45
        round_rect(d, (60, y, 900, y + 38), SOFT if r % 2 == 0 else WHITE, BORDER, 1, 6)
        for i, val in enumerate([f"ي{r + 1}", f"حدث {r + 1}", f"م{r + 1}", "وحدة"]):
            d.text((80 + i * 200, y + 8), ar(val), fill=BROWN, font=font(15))
    save(img, "05_ibank.png")

    # 06 planner
    img, d = new(920, 500)
    caption(d, "التخطيط — المجرى ثم التوزيع ثم النشر", 16, 920)
    steps = [
        ("1", "مجرى الأحداث", "الحفظ"),
        ("2", "توزيع للمحكمين", "توزيع"),
        ("3", "قوائم تقييم الإجراءات", "نشر القوائم"),
        ("4", "قوائم التقييم", "نشر القوائم"),
    ]
    for i, (n, title, act) in enumerate(steps):
        x = 40 + i * 220
        round_rect(d, (x, 100, x + 200, 380), CARD, BORDER, 2, 14)
        round_rect(d, (x + 75, 130, x + 125, 180), ACCENT, None, 0, 25)
        nt = ar(n)
        nw = d.textbbox((0, 0), nt, font=font(24, True))[2]
        d.text((x + 100 - nw // 2, 140), nt, fill=WHITE, font=font(24, True))
        d.text((x + 20, 210), ar(title), fill=BROWN, font=font(15, True))
        round_rect(d, (x + 30, 300, x + 170, 340), (255, 236, 214), ACCENT, 2, 8)
        at = ar(act)
        aw = d.textbbox((0, 0), at, font=font(14, True))[2]
        d.text((x + 100 - aw // 2, 310), at, fill=ACCENT, font=font(14, True))
        if i < 3:
            d.polygon([(x + 205, 230), (x + 218, 240), (x + 205, 250)], fill=ACCENT)
    d.text((40, 430), ar("الترتيب مهم: لا تنشر القوائم قبل حفظ المجرى وتوزيعه"), fill=MUTED, font=font(16))
    save(img, "06_planner.png")

    # 07 judge
    img, d = new(960, 540)
    caption(d, "المحكم — فتح القائمة ثم الحفظ ثم الاعتماد", 16, 960)
    round_rect(d, (30, 70, 260, 500), CARD, BORDER, 2, 12)
    for i, it in enumerate(["مجرى الأحداث", "قوائم تقييم الإجراءات", "قوائم التقييم", "مهام غير مكتملة"]):
        y = 110 + i * 55
        fill = (255, 236, 214) if i == 2 else SOFT
        round_rect(d, (50, y, 240, y + 42), fill, ACCENT if i == 2 else BORDER, 2 if i == 2 else 1, 8)
        t = ar(it)
        d.text((230 - d.textbbox((0, 0), t, font=font(13))[2], y + 12), t, fill=BROWN, font=font(13))
    round_rect(d, (280, 70, 930, 500), CARD, BORDER, 2, 12)
    d.text((700, 95), ar("قائمة التقييم — المرحلة"), fill=BROWN, font=font(18, True))
    for i in range(4):
        y = 150 + i * 55
        round_rect(d, (310, y, 900, y + 45), SOFT, BORDER, 1, 6)
        d.text((820, y + 12), ar(f"بند تقييمي {i + 1}"), fill=BROWN, font=font(14))
        round_rect(d, (330, y + 8, 420, y + 36), WHITE, BORDER, 1, 6)
        d.text((360, y + 12), ar("درجة"), fill=MUTED, font=font(12))
    round_rect(d, (520, 430, 700, 475), GREEN, None, 0, 10)
    t1 = ar("حفظ نتائج التقييم")
    d.text((610 - d.textbbox((0, 0), t1, font=font(14, True))[2] // 2, 442), t1, fill=WHITE, font=font(14, True))
    round_rect(d, (720, 430, 900, 475), ACCENT, None, 0, 10)
    t2 = ar("اعتماد المحكم")
    d.text((810 - d.textbbox((0, 0), t2, font=font(14, True))[2] // 2, 442), t2, fill=WHITE, font=font(14, True))
    save(img, "07_judge_eval.png")

    # 08 approval
    img, d = new(980, 420)
    caption(d, "مسار الاعتماد: محكم ← كبير محكمين ← سيطرة", 16, 980)
    nodes = [
        (80, "المحكم", "حفظ + اعتماد المحكم", ACCENT),
        (380, "كبير المحكمين", "اعتماد أو إعادة", (120, 80, 50)),
        (680, "السيطرة", "متابعة واعتماد نهائي", GREEN),
    ]
    for i, (x, title, sub, color) in enumerate(nodes):
        round_rect(d, (x, 120, x + 220, 300), CARD, color, 3, 16)
        round_rect(d, (x + 85, 145, x + 135, 195), color, None, 0, 25)
        nt = ar(str(i + 1))
        nw = d.textbbox((0, 0), nt, font=font(22, True))[2]
        d.text((x + 110 - nw // 2, 155), nt, fill=WHITE, font=font(22, True))
        tt = ar(title)
        tw = d.textbbox((0, 0), tt, font=font(18, True))[2]
        d.text((x + 110 - tw // 2, 215), tt, fill=BROWN, font=font(18, True))
        st = ar(sub)
        sw = d.textbbox((0, 0), st, font=font(13))[2]
        d.text((x + 110 - sw // 2, 250), st, fill=MUTED, font=font(13))
        if i < 2:
            d.polygon([(x + 230, 200), (x + 255, 215), (x + 230, 230)], fill=ACCENT)
    d.text(
        (80, 340),
        ar("إذا أعاد كبير المحكمين القائمة: تصل إشعاراً وتعود «لم ينجز» حتى تعيد الحفظ"),
        fill=MUTED,
        font=font(15),
    )
    save(img, "08_approval_flow.png")

    # 09 control
    img, d = new(920, 480)
    caption(d, "السيطرة — متابعة النتائج وموقف القوائم", 16, 920)
    cards = ["عرض نتائج التقييم", "موقف القوائم والمهام", "الإيجابيات والسلبيات", "التوثيق المرئي"]
    for i, c in enumerate(cards):
        x = 40 + (i % 2) * 440
        y = 90 + (i // 2) * 170
        round_rect(d, (x, y, x + 400, y + 140), CARD, BORDER, 2, 14)
        t = ar(c)
        tw = d.textbbox((0, 0), t, font=font(20, True))[2]
        d.text((x + (400 - tw) // 2, y + 55), t, fill=BROWN, font=font(20, True))
    save(img, "09_control.png")

    # 10 analyst
    img, d = new(920, 480)
    caption(d, "المحلل — المعايير والتقارير", 16, 920)
    tools = ["معايير التقييم", "التقييم نهائي", "عرض النتائج", "تحليل المحكمين", "الإيجابيات والسلبيات", "التوثيق المرئي"]
    for i, c in enumerate(tools):
        x = 40 + (i % 3) * 290
        y = 90 + (i // 3) * 170
        round_rect(d, (x, y, x + 270, y + 140), CARD, BORDER, 2, 14)
        t = ar(c)
        tw = d.textbbox((0, 0), t, font=font(18, True))[2]
        d.text((x + (270 - tw) // 2, y + 55), t, fill=BROWN, font=font(18, True))
    save(img, "10_analyst.png")

    # 11 shared
    img, d = new(980, 280)
    caption(d, "الشريط العلوي — أدوات مشتركة", 16, 980)
    round_rect(d, (30, 80, 950, 200), CARD, BORDER, 2, 12)
    items = ["الصفحة الرئيسية", "غرفة المحادثة", "معلومات التمرين", "المكتبة", "الإشعارات", "خروج"]
    x = 50
    for it in items:
        t = ar(it)
        tw = d.textbbox((0, 0), t, font=font(14, True))[2] + 24
        round_rect(d, (x, 120, x + tw, 165), SOFT, BORDER, 1, 8)
        d.text((x + 12, 132), t, fill=BROWN, font=font(14, True))
        x += tw + 12
    d.text((40, 230), ar("استخدم هذه الروابط للتنقل السريع أثناء العمل"), fill=MUTED, font=font(16))
    save(img, "11_shared_tools.png")

    # 12 checklist
    img, d = new(900, 480)
    caption(d, "قائمة تحقق قبل التقييم الميداني", 16, 900)
    checks = [
        "التمرين الحالي ظاهر في الرأس",
        "المحكم مربوط بمستوى وحدة",
        "المجرى موزّع والقوائم منشورة",
        "تجربة اعتماد كاملة نجحت مرة واحدة",
    ]
    for i, c in enumerate(checks):
        y = 90 + i * 85
        round_rect(d, (60, y, 840, y + 70), CARD, BORDER, 2, 12)
        round_rect(d, (760, y + 15, 810, y + 55), GREEN, None, 0, 8)
        d.text((775, y + 22), ar("✓"), fill=WHITE, font=font(22, True))
        t = ar(f"{i + 1}. {c}")
        d.text((720 - d.textbbox((0, 0), t, font=font(18))[2], y + 22), t, fill=BROWN, font=font(18))
    save(img, "12_checklist.png")


if __name__ == "__main__":
    make_all()
    print("done", len(list(OUT.glob("*.png"))))
