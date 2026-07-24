# Copyright 2025 OpenSynergy Indonesia
# Copyright 2025 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import json

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
        Notification = request.env["nicepay_va_transaction_history"].sudo()
        payload = dict(request.params)

        notification = Notification.create(
            Notification._prepare_notification_data(payload)
        )
        # Commit immediately: the raw payload must survive even if
        # processing below crashes unexpectedly.
        request.env.cr.commit()

        notification._process_notification()
        # Commit the outcome (done/failed + error_message) regardless of
        # what happens after this point.
        request.env.cr.commit()

        if notification.state == "failed":
            return json.dumps(
                {"resultCd": "002", "resultMsg": notification.error_message}
            )
        return json.dumps({"resultCd": "000", "resultMsg": "SUCCESS"})
