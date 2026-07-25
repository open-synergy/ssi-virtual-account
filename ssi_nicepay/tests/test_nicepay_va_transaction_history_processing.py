# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import hashlib
import json
from datetime import datetime
from unittest import mock

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
        self.bank = self.env["res.bank"].create(
            {
                "name": "Test Nicepay Bank",
                "nicepay_bank_code": "014",
            }
        )
        self.journal = self.env["account.journal"].search(
            [("type", "=", "bank")], limit=1
        )
        if not self.journal:
            self.skipTest("No bank journal found in test environment")
        self.ICP.set_param("nicepay.journal_id", str(self.journal.id))
        self.ICP.set_param("nicepay.merchant_id", "TESTMID01")
        self.ICP.set_param("nicepay.merchant_key", "test-secret-merchant-key")

    def _sign_payload(self, payload):
        merchant_id = self.ICP.get_param("nicepay.merchant_id") or ""
        merchant_key = self.ICP.get_param("nicepay.merchant_key") or ""
        raw = "%s%s%s%s" % (
            merchant_id,
            payload.get("tXid") or "",
            payload.get("amt") or "",
            merchant_key,
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def _make_payload(self, **overrides):
        payload = {
            "tXid": "TXN-TEST-1",
            "billingNm": self.partner.name,
            "amt": "150000",
            "transDt": "20260724",
            "transTm": "113628",
            "bankCd": "014",
            "vacctNo": "1234567890",
            "referenceNo": "REF-1",
            "payMethod": "02",
            "instmntType": "0",
            "instmntMon": "1",
            "vacctValidDt": "20260731",
            "vacctValidTm": "235959",
            "currency": "IDR",
            "goodsNm": "TEST-GOODS",
            "status": "0",
            "matchCl": "1",
        }
        payload.update(overrides)
        if "merchantToken" not in overrides:
            payload["merchantToken"] = self._sign_payload(payload)
        return payload

    def _create_notification(self, payload):
        # Mirrors what the webhook controller does on receipt: this goes
        # through _create_or_reuse_notification(), not create() directly.
        return self.Notification._create_or_reuse_notification(payload)

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
    # bank_id / partner_id — computed+stored directly from the payload,
    # no button needed
    # ------------------------------------------------------------------

    def test_bank_id_and_partner_id_computed_on_create(self):
        notif = self._create_notification(
            self._make_payload(tXid="TXN-COMPUTE", billingNm=self.partner.name)
        )
        self.assertEqual(notif.bank_id, self.bank)
        self.assertEqual(notif.partner_id, self.partner)

    def test_bank_id_and_partner_id_empty_when_no_match(self):
        notif = self._create_notification(
            self._make_payload(
                tXid="TXN-COMPUTE-NOMATCH",
                bankCd="NOSUCHBANK",
                billingNm="No Such Partner At All",
            )
        )
        self.assertFalse(notif.bank_id)
        self.assertFalse(notif.partner_id)

    # ------------------------------------------------------------------
    # Generate Fields — derive structured fields from the stored payload
    # ------------------------------------------------------------------

    def test_combine_nicepay_datetime_merges_date_and_time(self):
        # Nicepay reports WIB (Asia/Jakarta, UTC+7); the result must be
        # converted to UTC for storage in a Datetime field.
        combined = self.Notification._combine_nicepay_datetime("20260724", "113628")
        self.assertEqual(combined, datetime(2026, 7, 24, 4, 36, 28))

    def test_combine_nicepay_datetime_returns_false_when_no_date(self):
        self.assertFalse(self.Notification._combine_nicepay_datetime(False, "113628"))

    def test_combine_nicepay_datetime_returns_false_for_malformed_date(self):
        # Real-world Nicepay data has been observed with a stray extra
        # digit (9 chars instead of 8, e.g. "202601224"), which must not
        # raise -- just be treated as unknown.
        self.assertFalse(
            self.Notification._combine_nicepay_datetime("202601224", "235959")
        )

    def test_generate_fields_does_not_crash_on_malformed_date(self):
        payload = self._make_payload(tXid="TXN-BAD-DATE", vacctValidDt="202601224")
        notif = self._create_notification(payload)

        notif.action_generate_fields()

        self.assertFalse(notif.vacct_valid_datetime)
        # the rest of the fields must still be populated normally
        self.assertEqual(notif.bank_code, "014")
        self.assertEqual(notif.reference_no, "REF-1")

    def test_create_survives_generate_fields_failure(self):
        # This model exists to guarantee the raw payload is never lost;
        # a bug in automatic field generation on create must not be
        # allowed to abort create() and take the payload down with it.
        payload = self._make_payload(tXid="TXN-GENFIELD-CRASH")
        with mock.patch.object(
            type(self.Notification), "_generate_fields", side_effect=Exception("boom")
        ):
            notif = self._create_notification(payload)

        self.assertTrue(notif.id)
        self.assertEqual(json.loads(notif.payload), payload)
        self.assertFalse(notif.merchant_token)
        self.assertEqual(notif.state, "draft")

    def test_generate_fields_populates_structured_fields(self):
        payload = self._make_payload(tXid="TXN-GENERATE", amt="250000")
        notif = self._create_notification(payload)
        notif.action_generate_fields()

        self.assertEqual(notif.merchant_token, payload["merchantToken"])
        self.assertEqual(notif.reference_no, "REF-1")
        self.assertEqual(notif.pay_method, "02")
        self.assertEqual(notif.amount, 250000.0)
        self.assertEqual(notif.vacct_no, "1234567890")
        # Payload times are WIB (UTC+7); stored value must be UTC.
        self.assertEqual(notif.trans_datetime, datetime(2026, 7, 24, 4, 36, 28))
        self.assertEqual(notif.vacct_valid_datetime, datetime(2026, 7, 31, 16, 59, 59))
        self.assertEqual(notif.instmnt_type, "0")
        self.assertEqual(notif.instmnt_mon, "1")
        self.assertEqual(notif.currency, "IDR")
        self.assertEqual(notif.goods_name, "TEST-GOODS")
        self.assertEqual(notif.billing_name, self.partner.name)
        self.assertEqual(notif.bank_code, "014")
        self.assertEqual(notif.notification_status, "0")
        self.assertEqual(notif.match_cl, "1")

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
    # _verify_merchant_token — reject forged/spoofed notifications
    # ------------------------------------------------------------------

    def test_verify_merchant_token_accepts_correctly_signed_payload(self):
        payload = self._make_payload(tXid="TXN-SIGNED")
        self.assertTrue(self.Notification._verify_merchant_token(payload))

    def test_verify_merchant_token_rejects_wrong_signature(self):
        payload = self._make_payload(
            tXid="TXN-FORGED", merchantToken="not-the-real-token"
        )
        self.assertFalse(self.Notification._verify_merchant_token(payload))

    def test_process_notification_rejects_invalid_merchant_token(self):
        raw_payload = self._make_payload(
            tXid="TXN-FORGED-2", merchantToken="not-the-real-token"
        )
        notif = self._create_notification(raw_payload)

        notif._process_notification()

        self.assertEqual(notif.state, "failed")
        self.assertIn("merchantToken", notif.error_message)
        self.assertFalse(
            notif.payment_id,
            "a notification with an invalid signature must never create a payment",
        )
        self.assertEqual(
            json.loads(notif.payload),
            raw_payload,
            "the original (forged) payload must still be kept for audit purposes",
        )

    def test_process_notification_bypasses_invalid_merchant_token_when_enabled(self):
        raw_payload = self._make_payload(
            tXid="TXN-BYPASS", merchantToken="not-the-real-token"
        )
        notif = self._create_notification(raw_payload)
        notif.bypass_merchant_token_check = True

        notif._process_notification()

        self.assertEqual(notif.state, "done")
        self.assertTrue(notif.payment_id)
        self.assertFalse(notif.error_message)

    def test_process_notification_still_fails_when_bypass_disabled(self):
        raw_payload = self._make_payload(
            tXid="TXN-NOBYPASS", merchantToken="not-the-real-token"
        )
        notif = self._create_notification(raw_payload)
        self.assertFalse(notif.bypass_merchant_token_check)

        notif._process_notification()

        self.assertEqual(notif.state, "failed")
        self.assertFalse(notif.payment_id)

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

    def test_create_does_not_dedupe_unlike_the_webhook_entry_point(self):
        # Unlike _create_or_reuse_notification() (used by the webhook),
        # calling create() directly -- as manual creation via the UI,
        # "Duplicate", or an import would -- must behave like standard
        # Odoo create(): always insert a new row, even if the name
        # happens to collide with an existing record.
        vals = self.Notification._prepare_notification_data(
            self._make_payload(tXid="TXN-MANUAL-DUP")
        )
        first = self.Notification.create(vals)
        second = self.Notification.create(vals)

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(
            self.Notification.search_count([("name", "=", "TXN-MANUAL-DUP")]),
            2,
        )

    def test_resending_same_txid_reuses_the_done_record_unchanged(self):
        # Simulate Nicepay resending the exact same notification for a
        # tXid that has already been successfully processed: at most one
        # row per tXid must ever exist in this table (so it stays safe to
        # build SQL views on), so the second "arrival" must reuse the
        # existing done record rather than creating another row.
        first = self._create_notification(self._make_payload(tXid="TXN-REPLAY"))
        first._process_notification()
        self.assertEqual(first.state, "done")
        payment = first.payment_id

        second = self._create_notification(self._make_payload(tXid="TXN-REPLAY"))

        self.assertEqual(
            second.id,
            first.id,
            "a resent notification for an already-'done' tXid must reuse "
            "the existing record, never create a duplicate row",
        )
        self.assertEqual(second.payment_id, payment)
        self.assertEqual(
            self.Notification.search_count([("name", "=", "TXN-REPLAY")]),
            1,
            "at most one record must ever exist per tXid",
        )

    def test_resending_same_txid_reuses_and_updates_a_not_done_record(self):
        # A tXid that hasn't been successfully processed yet (still draft
        # or failed) must still only ever have one row -- a resend absorbs
        # the freshly received payload into the same record instead of
        # creating a duplicate.
        first_payload = self._make_payload(
            tXid="TXN-RETRY", merchantToken="not-the-real-token"
        )
        first = self._create_notification(first_payload)
        first._process_notification()
        self.assertEqual(first.state, "failed")

        second_payload = self._make_payload(tXid="TXN-RETRY")
        second = self._create_notification(second_payload)

        self.assertEqual(
            second.id,
            first.id,
            "a resent notification for a not-yet-done tXid must reuse the "
            "existing record, never create a duplicate row",
        )
        self.assertEqual(json.loads(second.payload), second_payload)
        self.assertEqual(second.state, "draft")
        self.assertFalse(second.error_message)
        self.assertEqual(
            self.Notification.search_count([("name", "=", "TXN-RETRY")]),
            1,
            "at most one record must ever exist per tXid",
        )

        second._process_notification()
        self.assertEqual(second.state, "done")

    def test_action_process_notification_rejects_multiple_records(self):
        first = self._create_notification(self._make_payload(tXid="TXN-MULTI-1"))
        second = self._create_notification(self._make_payload(tXid="TXN-MULTI-2"))

        with self.assertRaises(ValueError):
            (first + second).action_process_notification()

    def test_action_generate_fields_handles_multiple_records(self):
        first = self._create_notification(self._make_payload(tXid="TXN-MULTI-GEN-1"))
        second = self._create_notification(self._make_payload(tXid="TXN-MULTI-GEN-2"))

        (first + second).action_generate_fields()

        self.assertEqual(first.reference_no, "REF-1")
        self.assertEqual(second.reference_no, "REF-1")

    # ------------------------------------------------------------------
    # Sort order
    # ------------------------------------------------------------------

    def test_records_are_ordered_by_create_date_desc(self):
        first = self._create_notification(self._make_payload(tXid="TXN-ORDER-1"))
        second = self._create_notification(self._make_payload(tXid="TXN-ORDER-2"))

        found = self.Notification.search([("id", "in", [first.id, second.id])])
        self.assertEqual(
            found.ids,
            [second.id, first.id],
            "default order must be newest create_date first",
        )
