# Copyright 2025 OpenSynergy Indonesia
# Copyright 2025 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
from odoo import api, models


class ResBank(models.Model):
    _inherit = "res.bank"

    @api.model
    def _get_provider_bank_code_field(self, provider):
        field_name = f"{provider}_bank_code"

        if field_name not in self._fields:
            return False

        return field_name

    @api.model
    def find_by_provider_bank_code(self, provider, bank_code):
        field_name = self._get_provider_bank_code_field(provider)
        if field_name:
            return self.search(
                [(field_name, "=", bank_code)],
                limit=1,
            )
        else:
            return False
