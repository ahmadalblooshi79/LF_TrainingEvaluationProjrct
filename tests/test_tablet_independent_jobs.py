import unittest

from app.tablet_transfer_ops import READY_LABELS, device_ui_status


class _Dev:
    def __init__(self, status="online", ip="10.0.0.5", token="abc"):
        self.status = status
        self.device_ip = ip
        self.local_api_token = token
        self.local_pending_saves = 0
        self.local_saved_count = 0
        self.device_id = "TAB"


class IndependentTabletJobsTests(unittest.TestCase):
    def test_ethernet_without_api_is_not_ready(self):
        row = _Dev()
        code, label = device_ui_status(row, {"ready": False, "status": "UNREACHABLE"})
        self.assertNotEqual(code, "READY")
        self.assertEqual(label, READY_LABELS["FAILED"])

    def test_ready_requires_app_health(self):
        row = _Dev()
        code, label = device_ui_status(row, {"ready": True, "pending_saves": 0, "saved_count": 0})
        self.assertEqual(code, "READY")
        self.assertEqual(label, "جاهز")

    def test_six_tablets_independent_status(self):
        results = []
        for i in range(6):
            probe = {"ready": i != 2, "status": "UNREACHABLE" if i == 2 else "READY"}
            if i == 2:
                probe["ready"] = False
            code, _ = device_ui_status(_Dev(), probe)
            results.append(code)
        self.assertEqual(results[2], "FAILED")
        self.assertEqual(sum(1 for c in results if c == "READY"), 5)
        # فشل جهاز لا يغيّر حالة الباقي
        self.assertTrue(all(c == "READY" for i, c in enumerate(results) if i != 2))


if __name__ == "__main__":
    unittest.main()
