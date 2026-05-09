"""شجرة تجريبية لتنظيم المعركة (هيكل الوحدات). بيانات القائد تُخزَّن في قاعدة البيانات لكل تمرين ومعرّف وحدة (unit_id)."""

# echelon: brigade | battalion | company | platoon | squad
# branch: mech_inf | infantry | armor | artillery
BATTLE_ORG_DEMO_ROOT: dict = {
    "id": "u-bde",
    "label": "لواء مشاة ميكانيكي — عرض تجريبي",
    "symbol": {"echelon": "brigade", "branch": "mech_inf"},
    "children": [
        {
            "id": "u-bn-1",
            "label": "الكتيبة الأولى — مشاة",
            "symbol": {"echelon": "battalion", "branch": "infantry"},
            "children": [
                {
                    "id": "u-bn1-c-a",
                    "label": "السرية أ",
                    "symbol": {"echelon": "company", "branch": "infantry"},
                    "children": [
                        {
                            "id": "u-bn1-c-a-p1",
                            "label": "المعدية ١",
                            "symbol": {"echelon": "platoon", "branch": "infantry"},
                            "children": [],
                        },
                        {
                            "id": "u-bn1-c-a-p2",
                            "label": "المعدية ٢",
                            "symbol": {"echelon": "platoon", "branch": "infantry"},
                            "children": [],
                        },
                    ],
                },
                {
                    "id": "u-bn1-c-b",
                    "label": "السرية ب",
                    "symbol": {"echelon": "company", "branch": "infantry"},
                    "children": [],
                },
                {
                    "id": "u-bn1-c-c",
                    "label": "السرية ج",
                    "symbol": {"echelon": "company", "branch": "infantry"},
                    "children": [],
                },
            ],
        },
        {
            "id": "u-bn-2",
            "label": "الكتيبة الثانية — مشاة",
            "symbol": {"echelon": "battalion", "branch": "infantry"},
            "children": [
                {
                    "id": "u-bn2-c-a",
                    "label": "السرية أ",
                    "symbol": {"echelon": "company", "branch": "infantry"},
                    "children": [],
                },
                {
                    "id": "u-bn2-c-b",
                    "label": "السرية ب",
                    "symbol": {"echelon": "company", "branch": "infantry"},
                    "children": [],
                },
                {
                    "id": "u-bn2-c-c",
                    "label": "السرية ج",
                    "symbol": {"echelon": "company", "branch": "infantry"},
                    "children": [],
                },
            ],
        },
        {
            "id": "u-bn-3",
            "label": "الكتيبة الثالثة — مدرعات",
            "symbol": {"echelon": "battalion", "branch": "armor"},
            "children": [
                {
                    "id": "u-bn3-c-a",
                    "label": "السرية أ",
                    "symbol": {"echelon": "company", "branch": "armor"},
                    "children": [],
                },
                {
                    "id": "u-bn3-c-b",
                    "label": "السرية ب",
                    "symbol": {"echelon": "company", "branch": "armor"},
                    "children": [],
                },
                {
                    "id": "u-bn3-c-c",
                    "label": "السرية ج",
                    "symbol": {"echelon": "company", "branch": "armor"},
                    "children": [],
                },
            ],
        },
        {
            "id": "u-bn-4",
            "label": "الكتيبة الرابعة — مدفعية",
            "symbol": {"echelon": "battalion", "branch": "artillery"},
            "children": [
                {
                    "id": "u-bn4-b-a",
                    "label": "البطارية أ",
                    "symbol": {"echelon": "company", "branch": "artillery"},
                    "children": [],
                },
                {
                    "id": "u-bn4-b-b",
                    "label": "البطارية ب",
                    "symbol": {"echelon": "company", "branch": "artillery"},
                    "children": [],
                },
                {
                    "id": "u-bn4-b-c",
                    "label": "البطارية ج",
                    "symbol": {"echelon": "company", "branch": "artillery"},
                    "children": [],
                },
            ],
        },
    ],
}
