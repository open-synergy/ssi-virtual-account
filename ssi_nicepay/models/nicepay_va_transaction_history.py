# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import hashlib
import hmac
import json
from datetime import datetime

from odoo import api, fields, models


class NicepayVaTransactionHistory(models.Model):
    """
    Stores the raw HTTP payload of a Nicepay VA notification callback.

    The record is created as soon as the callback is received, before any
    downstream processing (partner/bank matching, payment creation) is
    attempted, so the original payload is never lost even if that
    processing fails. The "Process Notification" button lets an
    administrator retry the processing once the underlying issue (e.g. a
    misconfigured system parameter) has been fixed.
    """

    _name = "nicepay_va_transaction_history"
    _inherit = ["mixin.master_data"]
    _description = "Nicepay VA Transaction History"
    _order = "create_date desc, id desc"

    code = fields.Char(
        default="/",
    )
    state = fields.Selection(
        string="State",
        selection=[
            ("draft", "Draft"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        default="draft",
        required=True,
        readonly=True,
        copy=False,
        help=(
            "Processing status of this notification: "
            "Draft = not yet processed, "
            "Done = payment successfully created, "
            "Failed = processing raised an error, see Error Message."
        ),
    )
    payload = fields.Text(
        string="Payload",
        required=True,
        readonly=True,
        help=(
            "Raw HTTP POST parameters sent by Nicepay for this VA "
            "notification, stored as JSON exactly as received. This field "
            "is never modified after creation, regardless of whether "
            "processing succeeds or fails."
        ),
    )
    error_message = fields.Text(
        string="Error Message",
        readonly=True,
        copy=False,
        help=(
            "Exception message captured the last time processing this "
            "notification failed. Cleared once processing succeeds."
        ),
    )
    payment_id = fields.Many2one(
        string="# Payment",
        comodel_name="account.payment",
        readonly=True,
        copy=False,
        help="Payment record created from this notification once processing succeeds.",
    )
    processed_date = fields.Datetime(
        string="Processed Date",
        readonly=True,
        copy=False,
        help="Date and time this notification was last successfully processed.",
    )
    merchant_token = fields.Char(
        string="Merchant Token",
        readonly=True,
        help="Nicepay merchant token ('merchantToken') for this notification.",
    )
    reference_no = fields.Char(
        string="Reference No",
        readonly=True,
        help="Nicepay reference number ('referenceNo') for this notification.",
    )
    pay_method = fields.Char(
        string="Pay Method",
        readonly=True,
        help="Payment method code ('payMethod') used by the payer.",
    )
    amount = fields.Float(
        string="Amount",
        readonly=True,
        help="Transaction amount in IDR ('amt').",
    )
    vacct_no = fields.Char(
        string="Virtual Account No",
        readonly=True,
        help="Virtual account number ('vacctNo') that was paid.",
    )
    trans_datetime = fields.Datetime(
        string="Transaction Date",
        readonly=True,
        help=(
            "Date and time of the transaction, combined from the "
            "notification's separate 'transDt' (date) and 'transTm' "
            "(time) fields."
        ),
    )
    instmnt_type = fields.Char(
        string="Installment Type",
        readonly=True,
        help="Installment type code ('instmntType') reported by Nicepay.",
    )
    instmnt_mon = fields.Char(
        string="Installment Month",
        readonly=True,
        help="Number of installment months ('instmntMon') reported by Nicepay.",
    )
    vacct_valid_datetime = fields.Datetime(
        string="VA Valid Until",
        readonly=True,
        help=(
            "Date and time the virtual account is valid until, combined "
            "from the notification's separate 'vacctValidDt' (date) and "
            "'vacctValidTm' (time) fields."
        ),
    )
    currency = fields.Char(
        string="Currency",
        readonly=True,
        help="Currency code ('currency') of the transaction, e.g. IDR.",
    )
    goods_name = fields.Char(
        string="Goods Name",
        readonly=True,
        help="Goods/description name ('goodsNm') associated with the virtual account.",
    )
    billing_name = fields.Char(
        string="Billing Name",
        readonly=True,
        help="Name of the payer ('billingNm') as reported by the paying bank.",
    )
    bank_code = fields.Char(
        string="Bank Code",
        readonly=True,
        help="Nicepay bank code ('bankCd') of the paying bank.",
    )
    notification_status = fields.Char(
        string="Notification Status",
        readonly=True,
        help="Nicepay transaction status code ('status') for this notification.",
    )
    match_cl = fields.Char(
        string="Match Class",
        readonly=True,
        help="Match class code ('matchCl') reported by Nicepay.",
    )
    bank_id = fields.Many2one(
        string="# Bank",
        comodel_name="res.bank",
        compute="_compute_bank_id",
        store=True,
        compute_sudo=True,
        help=(
            "Bank matching the notification payload's bank code "
            "('bankCd') against res.bank.nicepay_bank_code."
        ),
    )
    partner_id = fields.Many2one(
        string="# Partner",
        comodel_name="res.partner",
        compute="_compute_partner_id",
        store=True,
        compute_sudo=True,
        help=(
            "Customer partner matching the notification payload's "
            "billing name ('billingNm')."
        ),
    )

    @api.depends("payload")
    def _compute_bank_id(self):
        Bank = self.env["res.bank"]
        for record in self:
            bank_code = record.payload and record._get_payload().get("bankCd")
            record.bank_id = (
                Bank.search([("nicepay_bank_code", "=", bank_code)], limit=1)
                if bank_code
                else False
            )

    @api.depends("payload")
    def _compute_partner_id(self):
        Partner = self.env["res.partner"]
        for record in self:
            billing_name = record.payload and record._get_payload().get("billingNm")
            record.partner_id = (
                Partner.search([("name", "=", billing_name)], limit=1)
                if billing_name
                else False
            )

    @api.model
    def _prepare_notification_data(self, payload):
        """Build ``create()`` values for a newly received notification.

        :param dict payload: Raw request parameters received from Nicepay.
        :return: Values to create a ``nicepay_va_transaction_history`` record.
        :rtype: dict
        """
        return {
            "name": payload.get("tXid") or "/",
            "code": "/",
            "payload": json.dumps(payload),
            "state": "draft",
        }

    def _get_payload(self):
        """Return this notification's stored payload as a dict.

        :rtype: dict
        """
        self.ensure_one()
        return json.loads(self.payload)

    @api.model
    def _combine_nicepay_datetime(self, date_str, time_str):
        """Combine a Nicepay ``YYYYMMDD`` date and ``HHMMSS`` time string.

        Nicepay notifications have been observed to occasionally send a
        malformed date (e.g. an extra stray digit, making it 9 characters
        instead of 8). Rather than raise and abort the whole "Generate
        Fields" action over one bad field, an unparseable date/time is
        treated as unknown so the other fields still get populated.

        :param str date_str: Date in ``YYYYMMDD`` format, or falsy.
        :param str time_str: Time in ``HHMMSS`` format, defaults to
            midnight if falsy.
        :return: Combined datetime, or ``False`` if ``date_str`` is falsy
            or unparseable.
        :rtype: datetime.datetime or bool
        """
        if not date_str:
            return False
        try:
            return datetime.strptime(date_str + (time_str or "000000"), "%Y%m%d%H%M%S")
        except ValueError:
            return False

    def _prepare_generated_fields(self, payload):
        """Build ``write()`` values mapping the payload onto structured fields.

        :param dict payload: Notification payload.
        :return: Values to write onto this record.
        :rtype: dict
        """
        return {
            "merchant_token": payload.get("merchantToken"),
            "reference_no": payload.get("referenceNo"),
            "pay_method": payload.get("payMethod"),
            "amount": payload.get("amt") or 0.0,
            "vacct_no": payload.get("vacctNo"),
            "trans_datetime": self._combine_nicepay_datetime(
                payload.get("transDt"), payload.get("transTm")
            ),
            "instmnt_type": payload.get("instmntType"),
            "instmnt_mon": payload.get("instmntMon"),
            "vacct_valid_datetime": self._combine_nicepay_datetime(
                payload.get("vacctValidDt"), payload.get("vacctValidTm")
            ),
            "currency": payload.get("currency"),
            "goods_name": payload.get("goodsNm"),
            "billing_name": payload.get("billingNm"),
            "bank_code": payload.get("bankCd"),
            "notification_status": payload.get("status"),
            "match_cl": payload.get("matchCl"),
        }

    def action_generate_fields(self):
        for record in self.sudo():
            record._generate_fields()

    def _generate_fields(self):
        """Populate the structured fields above from the stored payload."""
        self.ensure_one()
        self.write(self._prepare_generated_fields(self._get_payload()))

    def _verify_merchant_token(self, payload):
        """Verify the notification's ``merchantToken`` signature.

        Nicepay computes ``merchantToken`` as
        ``SHA256(merchant_id + tXid + amt + merchant_key)``. This endpoint
        is necessarily public (``auth="public"``) since Nicepay's server
        cannot authenticate as an Odoo user, so recomputing and comparing
        this signature is what actually distinguishes a genuine Nicepay
        notification from a forged/spoofed request.

        :param dict payload: Notification payload.
        :return: ``True`` if the signature matches, ``False`` otherwise.
        :rtype: bool
        """
        ICP = self.env["ir.config_parameter"].sudo()
        merchant_id = ICP.get_param("nicepay.merchant_id") or ""
        merchant_key = ICP.get_param("nicepay.merchant_key") or ""
        raw = "%s%s%s%s" % (
            merchant_id,
            payload.get("tXid") or "",
            payload.get("amt") or "",
            merchant_key,
        )
        expected_token = hashlib.sha256(raw.encode()).hexdigest()
        return hmac.compare_digest(expected_token, payload.get("merchantToken") or "")

    def _prepare_payment_data(self):
        """Build ``create()`` values for the inbound ``account.payment``.

        Nicepay's virtual account number (``vacctNo``) is not a
        ``res.partner.bank`` account — it lives on the partner's
        ``virtual_account_ids`` and can be reassigned/rotated over time, so
        it is intentionally not used to fill ``partner_bank_id`` here.

        :rtype: dict
        """
        self.ensure_one()
        payload = self._get_payload()
        ICP = self.env["ir.config_parameter"]
        raw_date = payload.get("transDt")
        parsed_date = datetime.strptime(raw_date, "%Y%m%d")
        odoo_date = parsed_date.strftime("%Y-%m-%d")

        vals = {
            "payment_type": "inbound",
            "partner_type": "customer",
            "ref": payload.get("tXid"),
            "amount": payload.get("amt"),
            "partner_id": self.partner_id.id,
            "date": odoo_date,
        }

        journal_id = ICP.sudo().get_param("nicepay.journal_id")
        if journal_id:
            vals["journal_id"] = int(journal_id)

        return vals

    def action_process_notification(self):
        self.ensure_one()
        self.sudo()._process_notification()

    def _find_existing_payment(self, payload):
        """Find a payment already created for this notification's tXid.

        Nicepay may resend the same notification more than once (retries,
        or replay of an already-processed tXid). Since ``account.payment``
        itself has no unique constraint on ``ref``, this must be checked
        explicitly before creating a new payment, otherwise the same
        transaction would be booked twice.

        :param dict payload: Notification payload.
        :return: Matching ``account.payment`` record, or an empty one.
        :rtype: recordset
        """
        return (
            self.env["account.payment"]
            .sudo()
            .search([("ref", "=", payload.get("tXid"))], limit=1)
        )

    def _process_notification(self):
        """Create the ``account.payment`` for this notification.

        Safe to call more than once: a notification already in the
        ``done`` state is skipped so retrying never creates a duplicate
        payment. A notification whose tXid was already paid by an
        *earlier* notification record (e.g. Nicepay resending the same
        notification) is linked to that existing payment instead of
        creating a duplicate one. On failure, only the payment creation
        attempt is rolled back (via a savepoint) so the ``failed`` state
        and error message are still persisted on this record.

        The notification's ``merchantToken`` signature is verified first;
        a mismatch (forged/spoofed request, or wrong merchant credentials
        configured) marks this record as ``failed`` without ever
        attempting to create a payment.
        """
        self.ensure_one()
        if self.state == "done":
            return

        payload = self._get_payload()
        if not self._verify_merchant_token(payload):
            self.write(
                {
                    "state": "failed",
                    "error_message": (
                        "Invalid merchantToken: notification signature does "
                        "not match. This notification was not processed."
                    ),
                }
            )
            return

        existing_payment = self._find_existing_payment(payload)
        if existing_payment:
            self.write(
                {
                    "state": "done",
                    "payment_id": existing_payment.id,
                    "error_message": False,
                    "processed_date": fields.Datetime.now(),
                }
            )
            return

        AP = self.env["account.payment"].sudo()
        try:
            with self.env.cr.savepoint():
                payment = AP.create(self._prepare_payment_data())
            self.write(
                {
                    "state": "done",
                    "payment_id": payment.id,
                    "error_message": False,
                    "processed_date": fields.Datetime.now(),
                }
            )
        except Exception as e:
            self.write(
                {
                    "state": "failed",
                    "error_message": str(e),
                }
            )
