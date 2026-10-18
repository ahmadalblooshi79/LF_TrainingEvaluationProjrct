import time
import unittest

from app.tablet_reconnect import issue_reconnect_ticket, verify_reconnect_ticket


class TabletReconnectTicketTests(unittest.TestCase):
    def test_issue_and_verify(self):
        token = issue_reconnect_ticket(12, "tablet-abc")
        self.assertTrue(verify_reconnect_ticket(token, 12, "tablet-abc"))

    def test_wrong_user_rejected(self):
        token = issue_reconnect_ticket(12, "tablet-abc")
        self.assertFalse(verify_reconnect_ticket(token, 99, "tablet-abc"))

    def test_wrong_device_rejected_when_bound(self):
        token = issue_reconnect_ticket(12, "tablet-abc")
        self.assertFalse(verify_reconnect_ticket(token, 12, "tablet-other"))

    def test_empty_device_on_verify_accepted_if_bound(self):
        token = issue_reconnect_ticket(12, "tablet-abc")
        self.assertTrue(verify_reconnect_ticket(token, 12, ""))

    def test_tamper_rejected(self):
        token = issue_reconnect_ticket(12, "")
        body, sig = token.rsplit(".", 1)
        self.assertFalse(verify_reconnect_ticket(f"{body}x.{sig}", 12, ""))

    def test_expired_rejected(self):
        import app.tablet_reconnect as mod

        old = mod.TICKET_TTL_SECONDS
        try:
            mod.TICKET_TTL_SECONDS = -10
            token = issue_reconnect_ticket(12, "")
            time.sleep(0.01)
            self.assertFalse(verify_reconnect_ticket(token, 12, ""))
        finally:
            mod.TICKET_TTL_SECONDS = old


if __name__ == "__main__":
    unittest.main()
