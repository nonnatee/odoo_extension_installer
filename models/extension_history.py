# -*- coding: utf-8 -*-
import subprocess
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ExtensionInstallationHistory(models.Model):
    _name = 'extension.installation.history'
    _description = 'Extension Installation History'
    _order = 'install_date desc'

    name = fields.Char(string="Module Name", required=True, readonly=True)
    display_name_module = fields.Char(string="Module Title", readonly=True)
    source_type = fields.Selection([
        ('github', 'GitHub Repository'),
        ('zip', 'ZIP File Upload')
    ], string="Source Type", required=True, readonly=True)
    source_url = fields.Char(string="Source Detail", readonly=True)
    version = fields.Char(string="Version", readonly=True)
    backup_path = fields.Char(string="Backup File Path", readonly=True)
    status = fields.Selection([
        ('success', 'Installed'),
        ('restart_pending', 'Restart Pending'),
        ('failed', 'Failed')
    ], string="Status", default='restart_pending', required=True, readonly=True)
    failure_reason = fields.Text(string="Failure Reason", readonly=True)
    install_date = fields.Datetime(string="Installation Date", default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one('res.users', string="Installer", default=lambda self: self.env.user, readonly=True)

    def action_restart_server(self):
        # Check permissions
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only administrators can restart the server."))
        
        # Get configured restart command
        restart_cmd = self.env['ir.config_parameter'].sudo().get_param('odoo_extension_installer.restart_command')
        if not restart_cmd:
            raise UserError(_("No restart command configured. Please go to Settings to configure the command, or restart the server manually."))
        
        _logger.info("Executing Odoo restart command: %s", restart_cmd)
        try:
            # Execute command asynchronously
            subprocess.Popen(restart_cmd, shell=True)
        except Exception as e:
            _logger.exception("Failed to execute restart command.")
            raise UserError(_("Error executing restart command: %s") % str(e))
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Restart Executed'),
                'message': _('The restart command has been sent to the server. Odoo will reload shortly.'),
                'type': 'success',
                'sticky': False,
            }
        }
