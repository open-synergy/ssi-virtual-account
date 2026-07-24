# Copyright 2025 OpenSynergy Indonesia
# Copyright 2025 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    nicepay_merchant_id = fields.Char(
        string="Merchant ID",
        config_parameter="nicepay.merchant_id",
        inverse="_inverse_nicepay_merchant_id",
    )
    nicepay_merchant_key = fields.Char(
        string="Merchant Key",
        config_parameter="nicepay.merchant_key",
        inverse="_inverse_nicepay_merchant_key",
    )
    nicepay_journal_id = fields.Many2one(
        string="# Journal",
        comodel_name="account.journal",
        config_parameter="nicepay.journal_id",
    )

    def _inverse_nicepay_merchant_id(self):
        for record in self:
            ICP = self.env["ir.config_parameter"]
            ICP.sudo().set_param(
                "nicepay.merchant_id",
                record.nicepay_merchant_id,
            )

    def _inverse_nicepay_merchant_key(self):
        for record in self:
            ICP = self.env["ir.config_parameter"]
            ICP.sudo().set_param(
                "nicepay.merchant_key",
                record.nicepay_merchant_key,
            )
