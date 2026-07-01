import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.info_bank_tree import reorder_tree_sibling, reorder_tree_sibling_step
from app.models import InformationBankTreeNode

KIND = "dilemma_eval"


class InfoBankTreeReorderTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.parent = InformationBankTreeNode(
            kind=KIND,
            parent_id=None,
            name="مرحلة",
            is_folder=True,
            catalog_phase_key="preparation",
            sort_order=0,
        )
        self.db.add(self.parent)
        self.db.flush()
        self.nodes = []
        for i, name in enumerate(("أول", "ثاني", "ثالث")):
            row = InformationBankTreeNode(
                kind=KIND,
                parent_id=int(self.parent.id),
                name=name,
                is_folder=True,
                sort_order=i,
            )
            self.nodes.append(row)
            self.db.add(row)
        self.db.commit()

    def _names(self):
        rows = (
            self.db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == int(self.parent.id))
            .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
            .all()
        )
        return [n.name for n in rows]

    def test_insert_before_reorders_siblings(self):
        reorder_tree_sibling(
            self.db,
            kind=KIND,
            node_id=int(self.nodes[2].id),
            anchor_id=int(self.nodes[0].id),
            position="before",
        )
        self.db.commit()
        self.assertEqual(self._names(), ["ثالث", "أول", "ثاني"])

    def test_insert_after_reorders_siblings(self):
        reorder_tree_sibling(
            self.db,
            kind=KIND,
            node_id=int(self.nodes[0].id),
            anchor_id=int(self.nodes[2].id),
            position="after",
        )
        self.db.commit()
        self.assertEqual(self._names(), ["ثاني", "ثالث", "أول"])

    def test_step_down_moves_folder(self):
        reorder_tree_sibling_step(
            self.db,
            kind=KIND,
            node_id=int(self.nodes[0].id),
            direction="down",
        )
        self.db.commit()
        self.assertEqual(self._names(), ["ثاني", "أول", "ثالث"])

    def test_reorder_nested_companies(self):
        battalion = InformationBankTreeNode(
            kind=KIND,
            parent_id=int(self.parent.id),
            name="كتيبة",
            is_folder=True,
            sort_order=9,
        )
        self.db.add(battalion)
        self.db.flush()
        companies = []
        for i, name in enumerate(("سرية 1", "سرية 2", "سرية 3")):
            c = InformationBankTreeNode(
                kind=KIND,
                parent_id=int(battalion.id),
                name=name,
                is_folder=True,
                sort_order=i,
            )
            companies.append(c)
            self.db.add(c)
        self.db.commit()
        reorder_tree_sibling(
            self.db,
            kind=KIND,
            node_id=int(companies[2].id),
            anchor_id=int(companies[0].id),
            position="before",
        )
        self.db.commit()
        ordered = (
            self.db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id == int(battalion.id))
            .order_by(InformationBankTreeNode.sort_order)
            .all()
        )
        self.assertEqual([n.name for n in ordered], ["سرية 3", "سرية 1", "سرية 2"])

    def test_step_down_moves_file(self):
        folder = InformationBankTreeNode(
            kind=KIND,
            parent_id=int(self.parent.id),
            name="مجلد ملفات",
            is_folder=True,
            sort_order=9,
        )
        self.db.add(folder)
        self.db.flush()
        file_a = InformationBankTreeNode(
            kind=KIND,
            parent_id=int(folder.id),
            name="ملف أ",
            is_folder=False,
            sort_order=0,
        )
        file_b = InformationBankTreeNode(
            kind=KIND,
            parent_id=int(folder.id),
            name="ملف ب",
            is_folder=False,
            sort_order=1,
        )
        self.db.add(file_a)
        self.db.add(file_b)
        self.db.commit()
        reorder_tree_sibling_step(
            self.db,
            kind=KIND,
            node_id=int(file_a.id),
            direction="down",
        )
        self.db.commit()
        ordered = (
            self.db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.parent_id == int(folder.id),
                InformationBankTreeNode.is_folder.is_(False),
            )
            .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
            .all()
        )
        self.assertEqual([n.name for n in ordered], ["ملف ب", "ملف أ"])

    def test_cannot_move_phase_root(self):
        with self.assertRaises(ValueError):
            reorder_tree_sibling_step(
                self.db,
                kind=KIND,
                node_id=int(self.parent.id),
                direction="down",
            )


if __name__ == "__main__":
    unittest.main()
