# Copyright 2025 OpenSynergy Indonesia
# Copyright 2025 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
from odoo import _, api, models


class ResPartnerBank(models.Model):
    _inherit = "res.partner.bank"

    @api.model
    def _get_supported_account_types(self):
        _super = super(ResPartnerBank, self)
        res = _super._get_supported_account_types()
        res += [("virtual_account", _("Virtual Account"))]
        return res

    @api.model
    def retrieve_acc_type(self, acc_number):
        if acc_number in self.partner_id.virtual_account_ids.mapped("va_number"):
            return "virtual_account"
        else:
            return super(ResPartnerBank, self).retrieve_acc_type(acc_number)
