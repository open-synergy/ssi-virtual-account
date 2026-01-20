# Copyright 2025 OpenSynergy Indonesia
# Copyright 2025 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# pylint: disable=W0104
import json
from datetime import datetime

from odoo import http
from odoo.http import request


class NicepayEndpoint(http.Controller):
    @http.route(
        "/api/nicepay/va/notification",
        type="http",
        auth="public",
        csrf=False,
        methods=["POST"],
    )
    def nicepay_va_notification(self, **kwargs):
        log = (
            request.env["ir.logging"]
            .sudo()
            .create(
                {
                    "name": "Nicepay VA Notification",
                    "type": "server",
                    "message": "",
                    "path": __name__,
                    "line": "0",
                    "func": "/api/nicepay/va/notification",
                }
            )
        )

        try:
            payload = dict(request.params)
            request.env["ir.config_parameter"]
            # iMid = ICP.sudo().get_param("nicepay.merchant_id")
            # merchantKey = ICP.sudo().get_param("nicepay.merchant_key")

            # value = iMid + merchantKey
            # received_signature = payload.get("merchantToken")
            # expected = hashlib.sha256(value.encode("utf-8")).hexdigest()

            # if expected != received_signature:
            #     log.level = "VALIDATION_ERROR"
            #     log.message = str(payload)

            #     return json.dumps({
            #         "resultCd": "001",
            #         "resultMsg": "Signature is not valid"
            #     })
            # else:
            self._process_notification(payload, log)
        except Exception as e:
            log.level = "ERROR"
            log.message = str(e)

            return json.dumps({"resultCd": "002", "resultMsg": str(e)})

        return json.dumps({"resultCd": "000", "resultMsg": "SUCCESS"})

    def _get_partner(self, payload):
        result = False
        Partner = request.env["res.partner"]
        criteria = [("name", "=", payload.get("billingNm"))]
        partner_id = Partner.sudo().search(criteria)
        if partner_id:
            result = partner_id.id
        return result

    def _get_bank(self, payload):
        result = False
        Bank = request.env["res.bank"]
        criteria = [("nicepay_bank_code", "=", payload.get("bankCd"))]
        bank_id = Bank.sudo().search(criteria)
        if bank_id:
            result = bank_id.id
        return result

    def _get_partner_bank(self, partner_id, payload):
        result = False
        bank_id = self._get_bank(payload)
        if bank_id:
            PartnerBank = request.env["res.partner.bank"]
            criteria = [
                ("partner_id", "=", partner_id),
                ("bank_id", "=", bank_id),
            ]
            partner_bank_id = PartnerBank.sudo().search(criteria)
            if partner_bank_id:
                result = partner_bank_id.id
        return result

    def _prepare_payment_data(self, payload):
        ICP = request.env["ir.config_parameter"]
        partner_id = self._get_partner(payload)
        partner_bank_id = self._get_partner_bank(partner_id, payload)
        raw_date = payload.get("transDt")
        parsed_date = datetime.strptime(raw_date, "%Y%m%d")
        odoo_date = parsed_date.strftime("%Y-%m-%d")

        vals = {
            "payment_type": "inbound",
            "partner_type": "customer",
            "ref": payload.get("tXid"),
            "amount": payload.get("amt"),
            "partner_id": partner_id,
            "partner_bank_id": partner_bank_id,
            "date": odoo_date,
        }

        journal_id = ICP.sudo().get_param("nicepay.journal_id")
        if journal_id:
            vals["journal_id"] = int(journal_id)

        return vals

    def _process_notification(self, payload, log):
        AP = request.env["account.payment"]
        try:
            AP.sudo().create(self._prepare_payment_data(payload))

            log.level = "SUCCESS"
            log.message = str(payload)
        except Exception as e:
            log.level = "ERROR"
            log.message = str(e)

            return json.dumps({"resultCd": "003", "resultMsg": str(e)})
