# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import hashlib
import hmac
import html
import json
import logging
from datetime import datetime

import pytz

from odoo import _, api, fields, models

NICEPAY_TIMEZONE = pytz.timezone("Asia/Jakarta")

_logger = logging.getLogger(__name__)


def _unescape_billing_name(value):
    """Decode HTML entities (e.g. ``&amp;``) in a Nicepay billing name.

    Some banks/Nicepay HTML-entity-encode ``billingNm`` before sending it
    (observed with ``&`` becoming ``&amp;``), while partner names in Odoo
    use the plain character. Decoding here is only meant to make the
    partner *search* below entity-insensitive -- it must never be used to
    alter any value that is actually stored (``billing_name``, ``payload``).

    :param str value: Raw ``billingNm`` value, or falsy.
    :return: ``value`` with HTML entities decoded, unchanged if falsy.
    :rtype: str or None
    """
    return html.unescape(value) if value else value


class NicepayVaTransactionHistory(models.Model):
    """
    Stores the raw HTTP payload of a Nicepay VA notification callback.

    The record is created as soon as the callback is received, before any
    downstream processing (partner/bank matching, payment creation) is
    attempted, so the original payload is never lost even if that
    processing fails. The "Process Notification" button lets an
    administrator retry the processing once the underlying issue (e.g. a
    misconfigured system parameter) has been fixed.

    At most one record is kept per tXid *when received through the
    webhook* (see ``_create_or_reuse_notification()``): a resent/duplicate
    notification reuses the existing record for that tXid instead of
    creating another row, so this table stays safe to build SQL views on
    without needing to de-duplicate it downstream. This reuse rule is
    deliberately not part of ``create()`` itself, which behaves like any
    other Odoo model (always inserts a new row) for any other caller --
    manual creation via the UI, "Duplicate", imports, etc.
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
    bypass_merchant_token_check = fields.Boolean(
        string="Bypass Merchant Token Check",
        default=False,
        copy=False,
        help=(
            'When enabled, "Process Notification" proceeds even if this '
            "notification's merchantToken signature does not match, "
            "instead of being marked Failed. Only enable this after you "
            "have manually confirmed the notification is genuinely from "
            "Nicepay (e.g. it fails re-verification only because "
            "nicepay.merchant_key was rotated after this notification was "
            "originally received) -- bypassing this check accepts an "
            "unauthenticated payload as-is, so use with caution."
        ),
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
        """Match the payload's billing name against an existing partner.

        The billing name is passed through
        ``_unescape_billing_name()`` before the search so an
        HTML-entity-encoded value (e.g. ``&amp;``) from the payload
        still matches a partner name using the plain character.
        """
        Partner = self.env["res.partner"]
        for record in self:
            billing_name = record.payload and record._get_payload().get("billingNm")
            search_name = _unescape_billing_name(billing_name)
            record.partner_id = (
                Partner.search([("name", "=", search_name)], limit=1)
                if search_name
                else False
            )

    @api.model_create_multi
    def create(self, vals_list):
        """Populate the structured fields from ``payload`` right away.

        Structured fields are generated automatically as soon as a record
        is created, instead of requiring an admin to click "Generate
        Fields" manually. The button remains available to re-derive the
        fields later (e.g. after a malformed value in the original
        payload has been understood/fixed).

        This is standard Odoo ``create()`` behavior otherwise -- it always
        inserts a new row. The tXid de-duplication used by the webhook
        (see ``_create_or_reuse_notification()``) is intentionally kept
        out of here: overriding the generic ``create()`` to sometimes
        return an existing record instead of a new one would surprise any
        other caller (manual creation via the UI, "Duplicate", imports,
        ...), which all expect ``create()`` to always insert.
        """
        records = super().create(vals_list)
        for record in records.sudo():
            record._generate_fields_on_create()
        return records

    @api.model
    def _create_or_reuse_notification(self, payload):
        """Find or create the single record for this notification's tXid.

        This is the webhook's entry point (used instead of calling
        ``create()`` directly): at most one record is kept per tXid so
        downstream consumers (e.g. SQL views built for reporting) never
        need to de-duplicate this table themselves. A tXid already
        ``done`` is reused untouched (already successfully processed,
        nothing left to redo); a tXid still ``draft``/``failed`` absorbs
        the freshly received payload into that same record instead of
        creating a duplicate row, so it can be (re)processed.

        :param dict payload: Raw request parameters received from Nicepay.
        :return: The single record for this tXid.
        :rtype: recordset
        """
        vals = self._prepare_notification_data(payload)
        existing = self._find_existing_by_txid(vals.get("name"))
        if existing:
            return existing._reuse_for_resend(vals)
        return self.create(vals)

    def _find_existing_by_txid(self, name):
        """Find the existing record for a tXid ('name'), if any.

        :param str name: tXid to look up. The "/" placeholder used when a
            payload lacks a tXid is deliberately never matched, so several
            such records can coexist without being merged into one.
        :return: The existing record for this tXid, or an empty recordset.
        :rtype: recordset
        """
        return (
            self.search([("name", "=", name)], limit=1)
            if name and name != "/"
            else self.browse()
        )

    def _reuse_for_resend(self, vals):
        """Absorb a freshly received ``vals`` into this existing record.

        A record already ``done`` is left untouched (already successfully
        processed, nothing left to redo); any other record absorbs the new
        payload so it can be (re)processed.

        :param dict vals: Freshly received ``create()`` values for this
            tXid, as built by ``_prepare_notification_data``.
        :return: This record.
        :rtype: recordset
        """
        self.ensure_one()
        if self.state != "done":
            self.write(dict(vals, error_message=False))
            self.sudo()._generate_fields_on_create()
        return self

    def _generate_fields_on_create(self):
        """Best-effort ``_generate_fields()`` call, tolerant of failure.

        This whole model exists to guarantee the raw payload is never
        lost, even when downstream processing fails -- so a bug in field
        generation (e.g. an unexpected payload shape) must not be allowed
        to abort ``create()`` and take the just-received payload down with
        it. Only the field-generation attempt is rolled back (via a
        savepoint) on failure; the record itself, with its raw payload
        intact, is left for "Generate Fields" to be retried manually later.
        """
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self._generate_fields()
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "nicepay_va_transaction_history #%s: automatic field "
                "generation on create failed, raw payload is preserved",
                self.id,
            )
            self.message_post(
                body=_('Automatic "Generate Fields" failed on creation: %s') % exc
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

        Nicepay reports this date/time in Indonesian local time (WIB,
        ``Asia/Jakarta``, UTC+7), while Odoo ``Datetime`` fields are
        always stored as UTC and converted to each user's timezone only
        when displayed. Storing the naive local value as-is would make it
        display 7 hours ahead of what Nicepay actually sent, so it is
        converted to UTC here before being returned.

        :param str date_str: Date in ``YYYYMMDD`` format, or falsy.
        :param str time_str: Time in ``HHMMSS`` format, defaults to
            midnight if falsy.
        :return: Combined datetime converted to UTC, or ``False`` if
            ``date_str`` is falsy or unparseable.
        :rtype: datetime.datetime or bool
        """
        if not date_str:
            return False
        try:
            naive_local = datetime.strptime(
                date_str + (time_str or "000000"), "%Y%m%d%H%M%S"
            )
        except ValueError:
            return False
        return (
            NICEPAY_TIMEZONE.localize(naive_local)
            .astimezone(pytz.utc)
            .replace(tzinfo=None)
        )

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
        """Populate the structured fields above from the stored payload.

        ``bank_id``/``partner_id`` are stored compute fields depending
        only on ``payload`` (``@api.depends("payload")``), and the
        ``write()`` below never touches ``payload`` itself, so Odoo
        never schedules them for recompute as a side effect of this
        write. Left alone, a record whose match originally failed
        (e.g. an un-decoded HTML entity in ``billingNm`` before this
        fix existed) would stay empty forever, even after "Generate
        Fields" is used to fix it -- defeating the whole point of that
        button. Calling both compute methods directly forces them to
        re-run and persist their new value. ``invalidate_cache()`` is
        deliberately NOT used here instead: for a ``store=True`` field
        it only discards the cached value, so the record would simply
        reread the same stale value back from the database rather than
        recomputing it.
        """
        self.ensure_one()
        self.write(self._prepare_generated_fields(self._get_payload()))
        self._compute_bank_id()
        self._compute_partner_id()

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
        attempting to create a payment, unless an administrator has
        explicitly enabled ``bypass_merchant_token_check`` on this record.
        """
        self.ensure_one()
        if self.state == "done":
            return

        payload = self._get_payload()
        if not self._verify_merchant_token(payload):
            if not self.bypass_merchant_token_check:
                self.write(
                    {
                        "state": "failed",
                        "error_message": (
                            "Invalid merchantToken: notification signature "
                            "does not match. This notification was not "
                            "processed."
                        ),
                    }
                )
                return
            self.message_post(
                body=_(
                    "Processed with merchant token verification bypassed: "
                    "this notification's signature did not match, but was "
                    'processed anyway because "Bypass Merchant Token '
                    'Check" is enabled.'
                )
            )

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
