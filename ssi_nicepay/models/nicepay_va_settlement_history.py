# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import json
from datetime import datetime

from odoo import api, fields, models


class NicepayVaSettlementHistory(models.Model):
    """
    Stores one settlement record imported from Nicepay's Settlement
    History report API
    (https://docs.nicepay.co.id/nicepay-api-laporan-bisnis-settlement-history).

    Records are expected to be created by an on-site job/integration that
    calls that API directly and imports each row of its response "data"
    array here, one record per row, for bookkeeping/reconciliation
    reference. This model does not call Nicepay itself; it is only the
    storage side.
    """

    _name = "nicepay_va_settlement_history"
    _inherit = ["mixin.master_data"]
    _description = "Nicepay VA Settlement History"
    _field_name_string = "Transaction ID"

    code = fields.Char(
        default="/",
    )
    response_code = fields.Char(
        string="Response Code",
        readonly=True,
        help="Transaction response code ('code') reported by Nicepay for this settlement row.",
    )
    settlement_date = fields.Date(
        string="Settlement Date",
        readonly=True,
        help="Date this transaction was settled by Nicepay ('settlmnt_dt').",
    )
    trans_status = fields.Char(
        string="Transaction Status",
        readonly=True,
        help="Transaction status code ('trans_status') reported by Nicepay.",
    )
    pay_method = fields.Char(
        string="Payment Method",
        readonly=True,
        help="Payment method code ('pay_method') used for the original transaction.",
    )
    trans_date = fields.Date(
        string="Transaction Date",
        readonly=True,
        help="Date the original transaction ('trans_dt') was made.",
    )
    trans_amount = fields.Float(
        string="Transaction Amount",
        digits=(19, 2),
        readonly=True,
        help="Original transaction amount in IDR ('trans_amt').",
    )
    settlement_amount = fields.Float(
        string="Settlement Amount",
        digits=(19, 2),
        readonly=True,
        help="Net amount settled to the merchant in IDR ('settlmnt_amt').",
    )
    fds_fee = fields.Float(
        string="FDS Fee",
        digits=(19, 2),
        readonly=True,
        help="Fraud Detection System fee charged by Nicepay ('fds_fee').",
    )
    nicepay_fee = fields.Float(
        string="Nicepay Fee",
        digits=(19, 2),
        readonly=True,
        help="Nicepay service fee charged for this transaction ('nicepay_fee').",
    )
    bank_fee = fields.Float(
        string="Bank Fee",
        digits=(19, 2),
        readonly=True,
        help="Bank fee charged for this transaction ('bank_fee').",
    )
    vat_amount = fields.Float(
        string="VAT Amount",
        digits=(19, 2),
        readonly=True,
        help="VAT/PPN charged on the fees for this transaction ('vat').",
    )
    order_no = fields.Char(
        string="Order No",
        readonly=True,
        help="Merchant order reference number ('order_no') for the original transaction.",
    )
    bank_code = fields.Char(
        string="Bank Code",
        readonly=True,
        help="Bank code ('bank_cd') of the paying bank.",
    )
    customer_no = fields.Char(
        string="Customer No",
        readonly=True,
        help="Customer/account transaction number ('customer_no') reported by Nicepay.",
    )
    raw_payload = fields.Text(
        string="Raw Payload",
        readonly=True,
        help=(
            "Raw JSON of this settlement data row exactly as returned by "
            "Nicepay's Settlement History API, kept for audit and "
            "troubleshooting in case the structured fields above ever need "
            "to be re-derived."
        ),
    )

    @api.model
    def _parse_nicepay_date(self, value):
        """Parse a Nicepay ``YYYYMMDD`` date string into a ``date``.

        :param str value: Date string in ``YYYYMMDD`` format, or falsy.
        :return: Parsed date, or ``False`` if ``value`` is falsy.
        :rtype: datetime.date or bool
        """
        if not value:
            return False
        return datetime.strptime(value, "%Y%m%d").date()

    @api.model
    def _prepare_settlement_data(self, row):
        """Build ``create()`` values from one Nicepay settlement data row.

        :param dict row: One entry of the Settlement History API response's
            ``data`` array, using Nicepay's original field names (``txid``,
            ``settlmnt_dt``, ``trans_amt``, ...).
        :return: Values to create a ``nicepay_va_settlement_history`` record.
        :rtype: dict
        """
        return {
            "name": row.get("txid") or "/",
            "code": "/",
            "response_code": row.get("code"),
            "settlement_date": self._parse_nicepay_date(row.get("settlmnt_dt")),
            "trans_status": row.get("trans_status"),
            "pay_method": row.get("pay_method"),
            "trans_date": self._parse_nicepay_date(row.get("trans_dt")),
            "trans_amount": row.get("trans_amt") or 0.0,
            "settlement_amount": row.get("settlmnt_amt") or 0.0,
            "fds_fee": row.get("fds_fee") or 0.0,
            "nicepay_fee": row.get("nicepay_fee") or 0.0,
            "bank_fee": row.get("bank_fee") or 0.0,
            "vat_amount": row.get("vat") or 0.0,
            "order_no": row.get("order_no"),
            "bank_code": row.get("bank_cd"),
            "customer_no": row.get("customer_no"),
            "raw_payload": json.dumps(row),
        }
