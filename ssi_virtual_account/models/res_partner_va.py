# Copyright 2025 OpenSynergy Indonesia
# Copyright 2025 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl-3.0-standalone.html).

from odoo import fields, models


class ResPartnerVA(models.Model):
    _name = "res.partner.va"
    _description = "Partner Virtual Account"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        required=True,
        ondelete="cascade",
    )
    bank_code = fields.Char()
    va_number = fields.Char(
        required=True,
    )
    provider = fields.Char(
        required=True,
    )
    status = fields.Selection(
        selection=[
            ("active", "Active"),
            ("inactive", "Inactive"),
            ("expired", "Expired"),
        ],
        default="active",
    )

    _sql_constraints = [
        (
            "uniq_partner_provider_va",
            "unique(partner_id, provider, va_number)",
            "Virtual Account must be unique per provider",
        )
    ]
