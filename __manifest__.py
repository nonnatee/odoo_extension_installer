# -*- coding: utf-8 -*-
{
    'name': 'Odoo Extension Installer',
    'version': '19.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Install third-party open-source Odoo modules from GitHub URLs or ZIP file uploads.',
    'description': """
Odoo Extension Installer
========================
This module allows Odoo administrators to:
- Download and install modules directly from public GitHub repositories.
- Upload Odoo module ZIP archives directly through the UI.
- Maintain a backup copy of existing modules before overwriting.
- Check and validate module dependencies.
- View a history log of installations.
- Configure and execute a custom shell command to restart the Odoo server.
    """,
    'author': 'Nonnatee Kanjana',
    'website': 'https://github.com/nonnatee/odoo_extension_installer',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/extension_history_views.xml',
        'wizard/extension_install_wizard_views.xml',
        'views/extension_app_views.xml',
        'wizard/extension_app_install_confirm_views.xml',
        'views/menus.xml',

    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
