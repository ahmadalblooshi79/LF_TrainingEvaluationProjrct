from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import (
    User,
    RoleKey,
    RoleDef,
)

ROLE_DUTIES: list[tuple[str, str, str]] = [
    (
        RoleKey.SYSTEM_ADMIN.value,
        "إدارة النظام",
        "إدارة المستخدمين، الصلاحيات، إعدادات الخادم، النسخ الاحتياطي، ومراقبة الاستقرار. لا يتدخل في مضمون التمرين بقدر تقليل الصلاحيات الافتراضية، مع ترك تنفيذ الميدان لأصحاب الاختصاص فيه.",
    ),
    (
        RoleKey.ANALYST.value,
        "المحللين",
        "متابعة البيانات بعد التمرين، مؤشرات الأداء، تلخيص الأنماط، إعداد التقارير لصناع القرار، وربط النتائج بالمراجع دون تعديل المعايير.",
    ),
    (
        RoleKey.PLANNER.value,
        "التخطيط",
        "تصميم وثائق التمرين، جدول الأحداث، الربط بالمراجع، وتحديد الافتراضات والمخرجات المتوقعة. التنسيق مع مكتبة المعايير والتأكد من اكتمال القوائم قبل التنفيذ.",
    ),
    (
        RoleKey.JUDGE.value,
        "المحكمين",
        "تطبيق قوائم التقييم بموضوعية، تدوين الملاحظات بسرعة ودقة، الالتزام بالتعليمات، وعدم اختلاق معايير جديدة خارج مكتبة المراجع المعتمدة.",
    ),
    (
        RoleKey.STANDARDS_LIBRARY.value,
        "مكتبة المراجع والمعايير",
        "حفظ وصيانة وتحديث الأدلة، اللوائح، النماذج، وربط إصدارات المستندات بتمارين محددة. مسار الموافقات لإدخال مرجع جديد وتوثيق المصدر.",
    ),
    (
        RoleKey.CONTROL.value,
        "السيطرة",
        "الرقابة السيريّة للتمرين، اعتماد مسار الأحداث، تتبع المشكلات، مواءمة مخرجات التقييم مع خطة التمرين، وإسناد الاعتمادات النهائية لإغلاق الملف.",
    ),
]

DEMO_PASSWORD = "demo123"  # للتجربة فقط — عيّن كلمات مرور قوية عند التشغيل


def seed_all(db: Session) -> None:
    if not db.query(RoleDef).first():
        for rk, title, duties in ROLE_DUTIES:
            db.add(RoleDef(role_key=rk, title_ar=title, duties_ar=duties))
        db.commit()

    for rk, title, duties in ROLE_DUTIES:
        row = db.query(RoleDef).filter(RoleDef.role_key == rk).first()
        if row:
            row.title_ar = title
            row.duties_ar = duties
    db.commit()

    if not db.query(User).first():
        # مستخدم اختياري لكل دور — كلمة مرور موحّدة في التجربة
        roles_users = [
            (RoleKey.SYSTEM_ADMIN, "admin"),
            (RoleKey.ANALYST, "analyst"),
            (RoleKey.PLANNER, "planner"),
            (RoleKey.JUDGE, "judge"),
            (RoleKey.STANDARDS_LIBRARY, "standards"),
            (RoleKey.CONTROL, "control"),
        ]
        ph = hash_password(DEMO_PASSWORD)
        for rk, uname in roles_users:
            rtitle = next((t[1] for t in ROLE_DUTIES if t[0] == rk.value), uname)
            db.add(
                User(
                    username=uname,
                    full_name=rtitle,
                    password_hash=ph,
                    role_key=rk.value,
                )
            )
        db.commit()

    _demo_usernames = {"admin", "analyst", "planner", "judge", "standards", "control"}
    for u in db.query(User).filter(User.username.in_(_demo_usernames)):
        t = next((pair[1] for pair in ROLE_DUTIES if pair[0] == u.role_key), None)
        if t:
            u.full_name = t
        # حافظ على حسابات التجربة قابلة للدخول حتى لو تغيّر نظام التشفير.
        u.password_hash = hash_password(DEMO_PASSWORD)
    db.commit()
