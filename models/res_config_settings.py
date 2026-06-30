# -*- coding: utf-8 -*-
import os
from odoo import models, fields, api
from odoo.tools import config

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    extension_target_addons_path = fields.Selection(
        selection='_get_addons_path_options',
        string="Target Addons Path",
        help="Directory where third-party modules will be extracted. Ensure Odoo has write permissions here.",
        config_parameter='odoo_extension_installer.target_addons_path'
    )
    extension_restart_command = fields.Char(
        string="Restart Shell Command",
        help="Shell command executed when restarting the Odoo server (e.g. 'docker restart odoo-container').",
        config_parameter='odoo_extension_installer.restart_command'
    )

    @api.model
    def _get_addons_path_options(self):
        paths_raw = config.get('addons_path', '')
        if isinstance(paths_raw, (list, tuple)):
            addons_paths = paths_raw
        elif isinstance(paths_raw, str):
            # In Windows, config.get('addons_path') might use comma separator
            # e.g., 'c:\odoo\odoo\addons,c:\odoo\addons'
            addons_paths = paths_raw.split(',')
        else:
            addons_paths = []
        options = []
        for path in addons_paths:
            if not isinstance(path, str):
                continue
            path = path.strip()
            if not path:
                continue
            path_norm = os.path.normpath(path)
            # Label as core if path matches common Odoo core structure
            is_core = False
            parts = path_norm.lower().replace('\\', '/').split('/')
            if 'odoo' in parts and ('addons' in parts or 'core' in parts):
                # But it could be custom addons inside odoo directory too, let's keep label informative
                if any(x in parts for x in ['addons/base', 'odoo/addons']):
                    is_core = True
            
            label = f"{path_norm} (Odoo Core Addons)" if is_core else path_norm
            options.append((path_norm, label))
        
        if not options:
            options.append(('', 'No addons path detected'))
        return options
