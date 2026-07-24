# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import json
from datetime import date

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
