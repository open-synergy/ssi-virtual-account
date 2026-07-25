# Copyright 2025 OpenSynergy Indonesia
# Copyright 2025 PT. Simetri Sinergi Indonesia
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# pylint: disable=C8101
{
    "name": "Nicepay Integration",
    "version": "14.0.2.0.0",
    "website": "https://simetri-sinergi.id",
    "author": "OpenSynergy Indonesia, PT. Simetri Sinergi Indonesia",
    "license": "AGPL-3",
    "installable": True,
    "application": False,
    "depends": [
        "ssi_virtual_account",
        "ssi_l10n_id_partner_bank",
        "ssi_master_data_mixin",
    ],
    "data": [
        "security/ir_model_access/nicepay_va_transaction_history.xml",
        "security/ir_model_access/nicepay_va_settlement_history.xml",
        "data/res_bank_data.xml",
        "menu.xml",
        "views/res_bank_views.xml",
        "views/res_config_settings_views.xml",
        "views/nicepay_va_transaction_history.xml",
        "views/nicepay_va_settlement_history.xml",
    ],
}
