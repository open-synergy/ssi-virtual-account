# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import json
from datetime import date
from unittest import mock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

_MODEL = "nicepay_va_settlement_history"

# Example data-array row taken verbatim from Nicepay's own Settlement
# History API documentation:
# https://docs.nicepay.co.id/nicepay-api-laporan-bisnis-settlement-history
_SAMPLE_ROW = {
    "code": "10",
    "txid": "ionpaytest02202001100933358310",
    "settlmnt_dt": "20200113",
    "trans_status": 0,
    "pay_method": "02",
    "trans_dt": "20200110",
    "trans_amt": 1000,
    "settlmnt_amt": 400,
    "fds_fee": 0,
    "nicepay_fee": 545,
    "bank_fee": 0,
    "vat": 55,
    "order_no": "ordno20200933270",
    "bank_cd": "bmri",
    "customer_no": "79150000090933358310",
}


@tagged("post_install", "-at_install")
class TestNicepayVaSettlementHistoryMapping(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Settlement = self.env[_MODEL]

    def test_parse_nicepay_date_parses_yyyymmdd(self):
        parsed = self.Settlement._parse_nicepay_date("20200113")
        self.assertEqual(parsed, date(2020, 1, 13))

    def test_parse_nicepay_date_returns_false_for_falsy(self):
        self.assertFalse(self.Settlement._parse_nicepay_date(False))
        self.assertFalse(self.Settlement._parse_nicepay_date(None))
        self.assertFalse(self.Settlement._parse_nicepay_date(""))

    def test_prepare_settlement_data_maps_all_fields(self):
        vals = self.Settlement._prepare_settlement_data(_SAMPLE_ROW)
        self.assertEqual(vals["name"], "ionpaytest02202001100933358310")
        self.assertEqual(vals["code"], "/")
        self.assertEqual(vals["response_code"], "10")
        self.assertEqual(vals["settlement_date"], date(2020, 1, 13))
        self.assertEqual(vals["trans_status"], 0)
        self.assertEqual(vals["pay_method"], "02")
        self.assertEqual(vals["trans_date"], date(2020, 1, 10))
        self.assertEqual(vals["trans_amount"], 1000)
        self.assertEqual(vals["settlement_amount"], 400)
        self.assertEqual(vals["fds_fee"], 0)
        self.assertEqual(vals["nicepay_fee"], 545)
        self.assertEqual(vals["bank_fee"], 0)
        self.assertEqual(vals["vat_amount"], 55)
        self.assertEqual(vals["order_no"], "ordno20200933270")
        self.assertEqual(vals["bank_code"], "bmri")
        self.assertEqual(vals["customer_no"], "79150000090933358310")
        self.assertEqual(json.loads(vals["raw_payload"]), _SAMPLE_ROW)

    def test_prepare_settlement_data_falls_back_when_no_txid(self):
        row = dict(_SAMPLE_ROW)
        del row["txid"]
        vals = self.Settlement._prepare_settlement_data(row)
        self.assertEqual(vals["name"], "/")

    def test_create_settlement_record_from_sample_row(self):
        vals = self.Settlement._prepare_settlement_data(_SAMPLE_ROW)
        settlement = self.Settlement.create(vals)
        self.assertEqual(settlement.name, "ionpaytest02202001100933358310")
        self.assertEqual(settlement.settlement_date, date(2020, 1, 13))
        self.assertEqual(settlement.settlement_amount, 400)
        self.assertEqual(settlement.bank_code, "bmri")

    def test_bank_id_computed_from_bank_code(self):
        bank = self.env["res.bank"].create(
            {
                "name": "Bank Mandiri Test",
                "nicepay_bank_code": "bmri",
            }
        )
        settlement = self.Settlement.create(
            self.Settlement._prepare_settlement_data(_SAMPLE_ROW)
        )
        self.assertEqual(settlement.bank_id, bank)

    def test_partner_id_computed_from_customer_no_via_virtual_account(self):
        partner = self.env["res.partner"].create({"name": "Test Settlement Partner"})
        self.env["res.partner.va"].create(
            {
                "partner_id": partner.id,
                "va_number": "79150000090933358310",
                "bank_code": "bmri",
                "provider": "nicepay",
                "status": "active",
            }
        )
        settlement = self.Settlement.create(
            self.Settlement._prepare_settlement_data(_SAMPLE_ROW)
        )
        self.assertEqual(settlement.partner_id, partner)

    def test_partner_id_empty_when_no_matching_virtual_account(self):
        settlement = self.Settlement.create(
            self.Settlement._prepare_settlement_data(_SAMPLE_ROW)
        )
        self.assertFalse(settlement.partner_id)

    def test_action_generate_fields_handles_multiple_records(self):
        row_1 = dict(_SAMPLE_ROW, txid="TXID-MULTI-1")
        row_2 = dict(_SAMPLE_ROW, txid="TXID-MULTI-2")
        first = self.Settlement.create(
            {"name": row_1["txid"], "code": "/", "raw_payload": json.dumps(row_1)}
        )
        second = self.Settlement.create(
            {"name": row_2["txid"], "code": "/", "raw_payload": json.dumps(row_2)}
        )

        (first + second).action_generate_fields()

        self.assertEqual(first.bank_code, "bmri")
        self.assertEqual(second.bank_code, "bmri")

    def test_records_are_ordered_by_create_date_desc(self):
        first = self.Settlement.create(
            self.Settlement._prepare_settlement_data(
                dict(_SAMPLE_ROW, txid="TXID-ORDER-1")
            )
        )
        second = self.Settlement.create(
            self.Settlement._prepare_settlement_data(
                dict(_SAMPLE_ROW, txid="TXID-ORDER-2")
            )
        )

        found = self.Settlement.search([("id", "in", [first.id, second.id])])
        self.assertEqual(
            found.ids,
            [second.id, first.id],
            "default order must be newest create_date first",
        )

    def test_fields_are_generated_automatically_from_raw_payload_on_create(self):
        # Create with only the raw payload (as if imported bare, without
        # going through _prepare_settlement_data): fields must already be
        # generated, with no need to click "Generate Fields" manually.
        settlement = self.Settlement.create(
            {
                "name": "ionpaytest02202001100933358310",
                "code": "/",
                "raw_payload": json.dumps(_SAMPLE_ROW),
            }
        )

        self.assertEqual(settlement.settlement_date, date(2020, 1, 13))
        self.assertEqual(settlement.settlement_amount, 400)
        self.assertEqual(settlement.bank_code, "bmri")
        self.assertEqual(settlement.customer_no, "79150000090933358310")

        # calling it again manually must remain safe/idempotent
        settlement.action_generate_fields()

        self.assertEqual(settlement.settlement_date, date(2020, 1, 13))
        self.assertEqual(settlement.settlement_amount, 400)
        self.assertEqual(settlement.bank_code, "bmri")
        self.assertEqual(settlement.customer_no, "79150000090933358310")

    def test_no_fields_generated_on_create_without_raw_payload(self):
        settlement = self.Settlement.create({"name": "/", "code": "/"})
        self.assertFalse(settlement.bank_code)
        self.assertFalse(settlement.settlement_date)

    def test_create_survives_generate_fields_failure(self):
        # raw_payload is kept specifically for audit/troubleshooting; a bug
        # in automatic field generation on create must not be allowed to
        # abort create() and take the just-imported row down with it.
        row = dict(_SAMPLE_ROW, txid="TXID-GENFIELD-CRASH")
        with mock.patch.object(
            type(self.Settlement), "_generate_fields", side_effect=Exception("boom")
        ):
            settlement = self.Settlement.create(
                {"name": row["txid"], "code": "/", "raw_payload": json.dumps(row)}
            )

        self.assertTrue(settlement.id)
        self.assertEqual(json.loads(settlement.raw_payload), row)
        self.assertFalse(settlement.bank_code)
