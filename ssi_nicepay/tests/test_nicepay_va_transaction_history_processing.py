# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import json

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

_MODEL = "nicepay_va_transaction_history"


@tagged("post_install", "-at_install")
class TestNicepayVaTransactionHistoryProcessing(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Notification = self.env[_MODEL]
        self.ICP = self.env["ir.config_parameter"].sudo()

        self.partner = self.env["res.partner"].create(
            {
                "name": "Test Nicepay Partner",
            }
        )
        self.journal = self.env["account.journal"].search(
            [("type", "=", "bank")], limit=1
        )
        if not self.journal:
            self.skipTest("No bank journal found in test environment")
        self.ICP.set_param("nicepay.journal_id", str(self.journal.id))

    def _make_payload(self, **overrides):
        payload = {
            "tXid": "TXN-TEST-1",
            "billingNm": self.partner.name,
            "amt": "150000",
            "transDt": "20260724",
            "bankCd": "014",
            "vacctNo": "1234567890",
        }
        payload.update(overrides)
        return payload

    def _create_notification(self, payload):
        vals = self.Notification._prepare_notification_data(payload)
        return self.Notification.create(vals)

    # ------------------------------------------------------------------
    # _prepare_notification_data — pure seam, no ORM writes besides create
    # ------------------------------------------------------------------

    def test_prepare_notification_data_uses_txid_as_name(self):
        payload = self._make_payload(tXid="TXN-ABC")
        vals = self.Notification._prepare_notification_data(payload)
        self.assertEqual(vals["name"], "TXN-ABC")
        self.assertEqual(vals["code"], "/")
        self.assertEqual(vals["state"], "draft")
        self.assertEqual(json.loads(vals["payload"]), payload)

    def test_prepare_notification_data_falls_back_when_no_txid(self):
        payload = self._make_payload()
        del payload["tXid"]
        vals = self.Notification._prepare_notification_data(payload)
        self.assertEqual(vals["name"], "/")

    # ------------------------------------------------------------------
    # _process_notification — success path
    # ------------------------------------------------------------------

    def test_process_notification_success_creates_payment(self):
        notif = self._create_notification(self._make_payload(tXid="TXN-SUCCESS"))
        notif._process_notification()
        self.assertEqual(notif.state, "done")
        self.assertTrue(notif.payment_id)
        self.assertFalse(notif.error_message)
        self.assertTrue(notif.processed_date)
        self.assertEqual(notif.payment_id.partner_id, self.partner)
        self.assertFalse(
            notif.payment_id.partner_bank_id,
            "Nicepay's VA number is not a res.partner.bank account (it "
            "lives on virtual_account_ids and can rotate), so it must "
            "never be used to fill partner_bank_id",
        )
        self.assertEqual(notif.payment_id.journal_id, self.journal)
        self.assertEqual(notif.payment_id.ref, "TXN-SUCCESS")

    # ------------------------------------------------------------------
    # _process_notification — failure path must keep the raw payload intact
    # ------------------------------------------------------------------

    def test_process_notification_failure_keeps_payload_intact(self):
        # Simulate the incident this feature was built for: nicepay.journal_id
        # holding a value int() cannot parse.
        self.ICP.set_param("nicepay.journal_id", "account.journal()")
        raw_payload = self._make_payload(tXid="TXN-FAIL")
        notif = self._create_notification(raw_payload)

        notif._process_notification()

        self.assertEqual(notif.state, "failed")
        self.assertTrue(notif.error_message)
        self.assertFalse(notif.payment_id)
        self.assertEqual(
            json.loads(notif.payload),
            raw_payload,
            "the original payload must survive a processing failure untouched",
        )

    def test_process_notification_does_not_create_payment_on_failure(self):
        self.ICP.set_param("nicepay.journal_id", "account.journal()")
        payment_count_before = self.env["account.payment"].search_count([])
        notif = self._create_notification(self._make_payload(tXid="TXN-FAIL-2"))

        notif._process_notification()

        payment_count_after = self.env["account.payment"].search_count([])
        self.assertEqual(
            payment_count_before,
            payment_count_after,
            "a failed processing attempt must not leave a partial payment behind",
        )

    # ------------------------------------------------------------------
    # Reprocessing (the "Process Notification" button) after fixing config
    # ------------------------------------------------------------------

    def test_reprocess_after_fixing_config_succeeds(self):
        self.ICP.set_param("nicepay.journal_id", "account.journal()")
        notif = self._create_notification(self._make_payload(tXid="TXN-RETRY"))
        notif._process_notification()
        self.assertEqual(notif.state, "failed")

        self.ICP.set_param("nicepay.journal_id", str(self.journal.id))
        notif.action_process_notification()

        self.assertEqual(notif.state, "done")
        self.assertTrue(notif.payment_id)
        self.assertFalse(notif.error_message)

    def test_reprocessing_done_record_is_noop(self):
        notif = self._create_notification(self._make_payload(tXid="TXN-NODUP"))
        notif._process_notification()
        self.assertEqual(notif.state, "done")
        payment = notif.payment_id

        notif.action_process_notification()

        self.assertEqual(
            notif.payment_id,
            payment,
            "reprocessing a done record must not replace or duplicate the payment",
        )
        payments = self.env["account.payment"].search([("ref", "=", "TXN-NODUP")])
        self.assertEqual(
            len(payments), 1, "reprocessing a done record must not create a duplicate"
        )
