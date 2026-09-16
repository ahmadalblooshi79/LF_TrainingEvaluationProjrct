"""حماية صفحات إدخال التقييم من إعادة التحميل التلقائي لنَبْض الخادم."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
PANEL = (
    ROOT / "app" / "templates" / "partials" / "evaluation_list_structured_panel.html"
).read_text(encoding="utf-8")


class EvalEntryAutoRefreshGuardTests(unittest.TestCase):
    def test_base_identifies_editable_evaluation_entry_pages(self):
        self.assertIn("function isEvaluationEntryPage()", BASE)
        self.assertIn('getElementById("eval-structured-root")', BASE)
        self.assertIn('data-eval-entry', BASE)
        self.assertIn("if (isEvaluationEntryPage()) return false;", BASE)

    def test_do_reload_skips_evaluation_entry_and_dirty_state(self):
        self.assertIn("if (isEvaluationEntryPage()) return;", BASE)
        self.assertIn("if (window.__lfEvalEntryDirty) return;", BASE)

    def test_panel_marks_eval_entry_when_editable(self):
        self.assertIn('data-eval-entry="{% if eval_can_edit|default(false) %}1{% else %}0{% endif %}"', PANEL)

    def test_panel_tracks_dirty_on_field_changes(self):
        self.assertIn("window.__lfEvalEntryDirty = false;", PANEL)
        self.assertIn("function markEvalDirty()", PANEL)
        self.assertIn("function markEvalClean()", PANEL)
        self.assertIn("markEvalDirty();", PANEL)
        self.assertIn("beforeunload", PANEL)

    def test_successful_save_clears_dirty_then_navigates(self):
        self.assertIn("markEvalClean();", PANEL)
        self.assertIn("location.replace(target);", PANEL)
        idx_clean = PANEL.find("markEvalClean();")
        idx_replace = PANEL.find("location.replace(target);")
        self.assertGreater(idx_clean, 0)
        self.assertGreater(idx_replace, idx_clean)

    def test_failed_save_does_not_reload(self):
        save_fn = PANEL.split("function submitEvalSaveForm", 1)[1]
        save_fn = save_fn.split("function submitEvalActionForm", 1)[0]
        self.assertNotIn("navigateEvalResponse", save_fn)
        self.assertIn("تعذّر تنفيذ العملية", save_fn)
        self.assertIn(".catch(function () {", save_fn)

    def test_media_upload_does_not_full_reload(self):
        self.assertNotIn("return location.reload();", PANEL)
