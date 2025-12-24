# Copyright 2025 OpenSynergy Indonesia
# Copyright 2025 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
# pylint: disable=W0104
from odoo import _, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = "res.partner"

    va_customer_id = fields.Char(
        string="Customer ID",
        copy=False,
    )
    virtual_account_ids = fields.One2many(
        comodel_name="res.partner.va",
        inverse_name="partner_id",
    )

    def action_sync_virtual_account(self):
        for record in self:
            record.sync_virtual_account()

    def sync_virtual_account(self):
        self.ensure_one()

        PartnerBank = self.env["res.partner.bank"]
        Bank = self.env["res.bank"]

        va_accounts = self.virtual_account_ids.filtered(lambda v: v.status == "active")

        existing_banks = self.bank_ids.filtered(
            lambda b: b.acc_type == "virtual_account"
        )

        bank_by_acc = {b.acc_number: b for b in existing_banks}

        for va in va_accounts:
            if va.va_number in bank_by_acc:
                bank_by_acc[va.va_number].write(
                    {
                        "acc_holder_name": self.name,
                    }
                )
            else:
                PartnerBank.create(
                    {
                        "partner_id": self.id,
                        "acc_holder_name": self.name,
                        "acc_number": va.va_number,
                        "bank_id": Bank.find_by_provider_bank_code(
                            va.provider, va.bank_code
                        ).id,
                    }
                )

        existing_banks.filtered(
            lambda b: b.acc_number not in va_accounts.mapped("va_number")
        ).unlink()

    def _prepare_va_data(self, bank_code, va_number, provider):
        self.ensure_one()
        self.env.company
        return {
            "partner_id": self.id,
            "bank_code": bank_code,
            "va_number": va_number,
            "provider": provider,
        }

    def _create_va(self, bank_code, va_number, provider):
        self.ensure_one()
        PartnerVA = self.env["res.partner.va"]
        try:
            PartnerVA.create(self._prepare_va_data(bank_code, va_number, provider))
        except Exception as e:
            msg_err = _(str(e))
            raise ValidationError(msg_err)
