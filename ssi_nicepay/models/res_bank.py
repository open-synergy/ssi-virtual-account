# Copyright 2025 OpenSynergy Indonesia
# Copyright 2025 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
from odoo import fields, models


class ResBank(models.Model):
    _inherit = "res.bank"

    nicepay_bank_code = fields.Char(
        string="Nicepay Code",
        copy=False,
    )
