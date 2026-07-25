# Copyright 2026 OpenSynergy Indonesia
# Copyright 2026 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import ast
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

_LOG_DOMAIN = [
    ("name", "=", "Nicepay VA Notification"),
    ("type", "=", "server"),
    ("func", "=", "/api/nicepay/va/notification"),
    ("level", "=", "SUCCESS"),
]


def migrate(cr, version):
    """Copy successful Nicepay VA notifications from ``ir.logging`` into
    ``nicepay_va_transaction_history``.

    Only ``level == "SUCCESS"`` logs are migrated: the old controller only
    ever stored the raw payload in ``ir.logging.message`` on success
    (``level == "ERROR"`` logs only ever held the exception text, never
    the payload, so there is nothing recoverable to migrate for those).
    """
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    Notification = env["nicepay_va_transaction_history"]
    Payment = env["account.payment"]
    logs = env["ir.logging"].search(_LOG_DOMAIN)

    _logger.info("Found %s Nicepay VA notification log(s) to migrate", len(logs))

    migrated = 0
    skipped_existing = 0
    skipped_unparseable = 0

    for log in logs:
        try:
            payload = ast.literal_eval(log.message)
        except (ValueError, SyntaxError):
            skipped_unparseable += 1
            _logger.warning(
                "Skipping ir.logging id %s: message is not a parseable payload",
                log.id,
            )
            continue

        vals = Notification._prepare_notification_data(payload)
        # A tXid must only ever have one migrated notification record: if
        # an earlier log with the same tXid was already migrated in this
        # loop (or a previous run of this script), skip this one.
        if Notification.search_count([("name", "=", vals["name"])]):
            skipped_existing += 1
            continue

        vals["state"] = "done"
        vals["processed_date"] = log.create_date

        # If the same tXid somehow has more than one account.payment
        # (should not happen going forward, see
        # nicepay_va_transaction_history._find_existing_payment), link to
        # the oldest one deterministically rather than an arbitrary match.
        payment = Payment.search(
            [("ref", "=", payload.get("tXid"))],
            order="id asc",
            limit=1,
        )
        if payment:
            vals["payment_id"] = payment.id

        Notification.create(vals)
        migrated += 1

    _logger.info(
        "Nicepay VA notification migration done: %s migrated, "
        "%s already present, %s unparseable",
        migrated,
        skipped_existing,
        skipped_unparseable,
    )
