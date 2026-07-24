# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
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

    def _get_partner(self, payload):
        """Find the customer partner matching the notification's billing name.

        :param dict payload: Notification payload.
        :return: Partner id, or ``False`` if not found.
        :rtype: int or bool
        """
        result = False
        Partner = self.env["res.partner"]
        criteria = [("name", "=", payload.get("billingNm"))]
        partner_id = Partner.sudo().search(criteria, limit=1)
        if partner_id:
            result = partner_id.id
        return result

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
        partner_id = self._get_partner(payload)
        raw_date = payload.get("transDt")
        parsed_date = datetime.strptime(raw_date, "%Y%m%d")
        odoo_date = parsed_date.strftime("%Y-%m-%d")

        vals = {
            "payment_type": "inbound",
            "partner_type": "customer",
            "ref": payload.get("tXid"),
            "amount": payload.get("amt"),
            "partner_id": partner_id,
            "date": odoo_date,
        }

        journal_id = ICP.sudo().get_param("nicepay.journal_id")
        if journal_id:
            vals["journal_id"] = int(journal_id)

        return vals

    def action_process_notification(self):
        for record in self.sudo():
            record._process_notification()

    def _process_notification(self):
        """Create the ``account.payment`` for this notification.

        Safe to call more than once: a notification already in the
        ``done`` state is skipped so retrying never creates a duplicate
        payment. On failure, only the payment creation attempt is rolled
        back (via a savepoint) so the ``failed`` state and error message
        are still persisted on this record.
        """
        self.ensure_one()
        if self.state == "done":
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
