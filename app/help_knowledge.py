# -*- coding: utf-8 -*-
"""تشجير مساعدة النظام — إجراءات منسّقة حسب الأدوار والمهام."""
from __future__ import annotations

from app.user_manual import MANUAL_SECTIONS, MANUAL_TITLE

# تجميع مسارات الدليل داخل فروع الشجرة العملية
_BRANCH_SPECS: list[dict] = [
    {
        "id": "start",
        "title": "البدء والواجهة",
        "icon": "fa-right-to-bracket",
        "desc": "الدخول والخروج والتنقل في الشريط العلوي",
        "section_ids": ["login", "shared"],
    },
    {
        "id": "flow",
        "title": "ترتيب تشغيل التمرين",
        "icon": "fa-diagram-project",
        "desc": "التسلسل الصحيح من الإنشاء حتى الإغلاق",
        "section_ids": ["order", "checklist"],
    },
    {
        "id": "admin",
        "title": "إدارة النظام",
        "icon": "fa-screwdriver-wrench",
        "desc": "إنشاء التمرين، القوائم، بنك المعلومات، والمسح",
        "section_ids": ["admin-create", "admin-setup", "admin-ibank", "admin-close"],
    },
    {
        "id": "planner",
        "title": "التخطيط",
        "icon": "fa-calendar-check",
        "desc": "المجرى والتوزيع ونشر القوائم",
        "section_ids": ["planner"],
    },
    {
        "id": "judge",
        "title": "المحكم",
        "icon": "fa-gavel",
        "desc": "تعبئة التقييم والحفظ والاعتماد",
        "section_ids": ["judge"],
    },
    {
        "id": "chief",
        "title": "كبير المحكمين",
        "icon": "fa-stamp",
        "desc": "مراجعة الاعتماد أو الإعادة",
        "section_ids": ["chief"],
    },
    {
        "id": "control",
        "title": "السيطرة",
        "icon": "fa-binoculars",
        "desc": "متابعة النتائج وموقف القوائم",
        "section_ids": ["control"],
    },
    {
        "id": "analyst",
        "title": "المحلل",
        "icon": "fa-chart-line",
        "desc": "المعايير والتقارير والتحليل",
        "section_ids": ["analyst"],
    },
]


def _section_map() -> dict[str, dict]:
    return {str(s.get("id") or ""): s for s in MANUAL_SECTIONS}


def _procedure_node(sec: dict) -> dict:
    """إجراء واحد مع خطواته الفرعية."""
    steps = []
    for i, st in enumerate(sec.get("steps") or [], start=1):
        steps.append(
            {
                "id": f"{sec.get('id')}-step-{i}",
                "kind": "step",
                "n": i,
                "title": st.get("title") or f"الخطوة {i}",
                "where": st.get("where") or "",
                "detail": st.get("detail") or "",
                "action": st.get("action") or "",
                "note": st.get("note") or "",
                "children": [],
            }
        )

    children: list[dict] = []
    prereqs = [p for p in (sec.get("prerequisites") or []) if p]
    if prereqs:
        children.append(
            {
                "id": f"{sec.get('id')}-pre",
                "kind": "prereq",
                "title": "قبل البدء",
                "item_list": prereqs,
                "children": [],
            }
        )
    children.extend(steps)
    tips = [t for t in (sec.get("tips") or []) if t]
    if tips:
        children.append(
            {
                "id": f"{sec.get('id')}-tips",
                "kind": "tips",
                "title": "نصائح",
                "item_list": tips,
                "children": [],
            }
        )

    return {
        "id": sec.get("id") or "",
        "kind": "procedure",
        "title": sec.get("title") or "",
        "audience": sec.get("audience") or "",
        "intro": sec.get("intro") or "",
        "steps_count": len(steps),
        "children": children,
    }


def help_tree() -> dict:
    """شجرة المساعدة العملية: فرع دور ← إجراء ← خطوات."""
    smap = _section_map()
    branches = []
    procedure_count = 0
    step_count = 0

    for spec in _BRANCH_SPECS:
        procs = []
        for sid in spec["section_ids"]:
            sec = smap.get(sid)
            if not sec:
                continue
            node = _procedure_node(sec)
            procs.append(node)
            procedure_count += 1
            step_count += int(node.get("steps_count") or 0)
        if not procs:
            continue
        branches.append(
            {
                "id": spec["id"],
                "kind": "branch",
                "title": spec["title"],
                "icon": spec["icon"],
                "desc": spec["desc"],
                "children": procs,
            }
        )

    # فرع مسار الاعتماد السريع (إجراءات متسلسلة مختصرة)
    branches.insert(
        2,
        {
            "id": "approval-chain",
            "kind": "branch",
            "title": "مسار الاعتماد",
            "icon": "fa-check-double",
            "desc": "محكم ← كبير محكمين ← سيطرة",
            "children": [
                {
                    "id": "approval-chain-flow",
                    "kind": "procedure",
                    "title": "تسلسل اعتماد القوائم",
                    "audience": "محكم / كبير محكمين / سيطرة",
                    "intro": "اتبع الترتيب نفسه لكل قائمة تقييم أو قائمة تقييم إجراءات.",
                    "steps_count": 4,
                    "children": [
                        {
                            "id": "ac-1",
                            "kind": "step",
                            "n": 1,
                            "title": "التخطيط ينشر القائمة",
                            "where": "مساحة التخطيط ← أوامر التخطيط",
                            "detail": "بعد حفظ المجرى وتوزيعه، تُنشأ القوائم وتُنشر لليوم أو المرحلة.",
                            "action": "نشر القوائم",
                            "note": "",
                            "children": [],
                        },
                        {
                            "id": "ac-2",
                            "kind": "step",
                            "n": 2,
                            "title": "المحكم يعبّئ ويعتمد",
                            "where": "مساحة المحكمين ← القوائم",
                            "detail": "فتح القائمة، تعبئة الدرجات والملاحظات، ثم الحفظ.",
                            "action": "حفظ نتائج التقييم ← اعتماد المحكم",
                            "note": "",
                            "children": [],
                        },
                        {
                            "id": "ac-3",
                            "kind": "step",
                            "n": 3,
                            "title": "كبير المحكمين يراجع",
                            "where": "مساحة كبير المحكمين ← أوامر الاعتماد",
                            "detail": "مراجعة النتائج ثم الاعتماد أو الإعادة مع إشعار.",
                            "action": "اعتماد كبير المحكمين أو إعادة للمحكم",
                            "note": "عند الإعادة تعود القائمة غير منجزة حتى يعيد المحكم الحفظ.",
                            "children": [],
                        },
                        {
                            "id": "ac-4",
                            "kind": "step",
                            "n": 4,
                            "title": "السيطرة تتابع الاعتماد النهائي",
                            "where": "مساحة السيطرة ← موقف القوائم / النتائج",
                            "detail": "متابعة القوائم بانتظار اعتماد السيطرة واكتمال المسار.",
                            "action": "راجع الموقف والنتائج",
                            "note": "",
                            "children": [],
                        },
                    ],
                }
            ],
        },
    )
    step_count += 4
    procedure_count += 1

    return {
        "title": "تشجير إجراءات النظام",
        "subtitle": MANUAL_TITLE,
        "branches": branches,
        "branch_count": len(branches),
        "procedure_count": procedure_count,
        "step_count": step_count,
    }


def help_meta() -> dict:
    return {
        "title": "المساعدة",
        "subtitle": MANUAL_TITLE,
        "hint": "تشجير عملي للإجراءات حسب الأدوار والمهام.",
    }
