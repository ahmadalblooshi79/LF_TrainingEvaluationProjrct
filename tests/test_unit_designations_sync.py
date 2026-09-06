# -*- coding: utf-8 -*-
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.domain import (
    InformationBankUnitLevel,
    UnitDesignation,
    UnitDesignationAlias,
)
from app.unit_designations import (
    alias_matches_canonical,
    generated_aliases_for_canonical,
    infer_unit_type,
    is_dropped_template_battalion_label,
    sync_designations_from_organization,
)


class AliasMatchTests(unittest.TestCase):
    def test_company_alias_must_use_same_battalion(self):
        canon = "كتيبة المشاة الآلية/12 - السرية/1"
        self.assertTrue(
            alias_matches_canonical("محكم السرية/1 من كتيبة المشاة الآلية/12", canon)
        )
        self.assertFalse(
            alias_matches_canonical("محكم السرية/1 من كتيبة المشاة الآلية/32", canon)
        )

    def test_generated_company_aliases_follow_canonical(self):
        aliases = generated_aliases_for_canonical("كتيبة المشاة الآلية/12 - السرية/1")
        self.assertIn("محكم السرية/1 من كتيبة المشاة الآلية/12", aliases)
        self.assertNotIn("محكم السرية/1 من كتيبة المشاة الآلية/32", aliases)

    def test_generated_bn_aliases_use_canonical_number(self):
        aliases = generated_aliases_for_canonical("قيادة كتيبة المشاة الآلية/12")
        self.assertIn("محكم مجموعة القتال/12", aliases)
        self.assertNotIn("محكم مجموعة القتال/32", aliases)

    def test_infer_type(self):
        self.assertEqual(infer_unit_type("قيادة كتيبة المشاة الآلية/12"), "قيادة")
        self.assertEqual(infer_unit_type("كتيبة المشاة الآلية/12 - السرية/1"), "سرية")

    def test_dropped_template_battalions_only_11_to_14(self):
        self.assertTrue(is_dropped_template_battalion_label("قيادة كتيبة المشاة الراجلة/11"))
        self.assertTrue(is_dropped_template_battalion_label("كتيبة المشاة الآلية/12 - السرية/1"))
        self.assertTrue(is_dropped_template_battalion_label("قيادة كتيبة المشاة الآلية/13"))
        self.assertTrue(is_dropped_template_battalion_label("قيادة كتيبة الدبابات/14"))
        self.assertFalse(is_dropped_template_battalion_label("قيادة كتيبة المشاة الآلية/32"))
        self.assertFalse(is_dropped_template_battalion_label("كتيبة المشاة الآلية/32 - السرية/1"))
        self.assertFalse(is_dropped_template_battalion_label("سرية الاستطلاع"))


class SyncFromOrganizationTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add(
            InformationBankUnitLevel(
                ibank_section="wargames",
                key="ul_mech2_bn_cmd",
                label="قيادة كتيبة المشاة الآلية/12",
                brigade_group="1",
                sort_order=1,
            )
        )
        self.db.add(
            InformationBankUnitLevel(
                ibank_section="wargames",
                key="ul_mech2_bn_c1",
                label="كتيبة المشاة الآلية/12 - السرية/1",
                brigade_group="1",
                sort_order=2,
            )
        )
        self.db.add(
            InformationBankUnitLevel(
                ibank_section="mission-readiness",
                key="ul_mech2_bn_cmd",
                label="قيادة كتيبة المشاة الآلية/32",
                brigade_group="1",
                sort_order=1,
            )
        )
        self.db.add(
            InformationBankUnitLevel(
                ibank_section="mission-readiness",
                key="ul_mech2_bn_c1",
                label="كتيبة المشاة الآلية/32 - السرية/1",
                brigade_group="1",
                sort_order=2,
            )
        )
        self.db.add(
            UnitDesignation(
                unit_id="U003",
                canonical_label="قيادة كتيبة المشاة الآلية/12",
                unit_type="كتيبة",
                sort_order=1,
            )
        )
        self.db.add(
            UnitDesignation(
                unit_id="U004",
                canonical_label="كتيبة المشاة الآلية/12 - السرية/1",
                unit_type="سرية",
                sort_order=2,
            )
        )
        self.db.add(
            UnitDesignationAlias(
                alias_id="A1",
                unit_id="U003",
                alias_label="قيادة كتيبة المشاة الآلية/32",
                alias_label_norm="قياده كتيبه المشاه الاليه/32",
            )
        )
        self.db.add(
            UnitDesignationAlias(
                alias_id="A2",
                unit_id="U004",
                alias_label="محكم السرية/1 من كتيبة المشاة الآلية/32",
                alias_label_norm="محكم السريه/1 من كتيبه المشاه الاليه/32",
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_sync_splits_mismatched_aliases_and_adds_org_units(self):
        from app.unit_designations import normalize_designation_text

        # صحّح norm ليطابق المنطق الفعلي
        for a in self.db.query(UnitDesignationAlias).all():
            a.alias_label_norm = normalize_designation_text(a.alias_label)
        self.db.commit()

        stats = sync_designations_from_organization(self.db)
        self.db.commit()
        self.assertGreater(stats["created"], 0)

        rows = {m.canonical_label: m for m in self.db.query(UnitDesignation).all()}
        self.assertNotIn("قيادة كتيبة المشاة الآلية/12", rows)
        self.assertNotIn("كتيبة المشاة الآلية/12 - السرية/1", rows)
        self.assertIn("قيادة كتيبة المشاة الآلية/32", rows)
        self.assertIn("كتيبة المشاة الآلية/32 - السرية/1", rows)

        by_unit: dict[str, list[str]] = {}
        for a in self.db.query(UnitDesignationAlias).all():
            by_unit.setdefault(a.unit_id, []).append(a.alias_label)

        aliases_32 = by_unit[rows["قيادة كتيبة المشاة الآلية/32"].unit_id]
        aliases_32c = by_unit[rows["كتيبة المشاة الآلية/32 - السرية/1"].unit_id]
        self.assertTrue(any("/32" in x for x in aliases_32))
        self.assertFalse(any("/12" in x for x in aliases_32))
        self.assertIn("محكم السرية/1 من كتيبة المشاة الآلية/32", aliases_32c)
        self.assertFalse(any("/12" in x for x in aliases_32c))


if __name__ == "__main__":
    unittest.main()
