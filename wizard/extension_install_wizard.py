# -*- coding: utf-8 -*-
import os
import re
import shutil
import time
import zipfile
import tempfile
import io
import urllib.request
import urllib.error
import json
import ast
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ExtensionInstallWizard(models.TransientModel):
    _name = 'extension.install.wizard'
    _description = 'Install Third-Party Extension'

    state = fields.Selection([
        ('init', 'Configure Source'),
        ('review', 'Review Modules'),
        ('done', 'Installation Complete')
    ], string="State", default='init', readonly=True)

    source_type = fields.Selection([
        ('github', 'GitHub Repository'),
        ('zip', 'ZIP File Upload')
    ], string="Source Type", default='github', required=True)

    github_url = fields.Char(
        string="GitHub Repository URL",
        placeholder="e.g. https://github.com/odoo/odoo"
    )
    github_branch = fields.Char(
        string="Branch / Tag / Commit",
        placeholder="e.g. 19.0 (defaults to default branch if empty)"
    )

    zip_file = fields.Binary(string="ZIP File Payload")
    zip_filename = fields.Char(string="ZIP Filename")

    target_path = fields.Selection(
        selection='_get_addons_path_options',
        string="Target Directory",
        required=True,
        help="The directory in addons_path where the module will be installed."
    )

    modules_data = fields.Text(string="Modules Serialized Data", readonly=True)
    review_message = fields.Html(string="Review Modules Summary", readonly=True)
    temp_dir_path = fields.Char(string="Temp Directory Path", readonly=True)
    
    # Track which modules are actually installed/selected by user
    installed_modules_log = fields.Text(string="Installed Modules Log", readonly=True)
    restart_pending = fields.Boolean(string="Restart Pending", default=False, readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super(ExtensionInstallWizard, self).default_get(fields_list)
        # Fetch target addons path from general settings
        default_path = self.env['ir.config_parameter'].sudo().get_param('odoo_extension_installer.target_addons_path')
        if default_path:
            res['target_path'] = default_path
        else:
            # Fallback to the first available option
            options = self._get_addons_path_options()
            if options and options[0][0]:
                res['target_path'] = options[0][0]
        return res

    def _get_addons_path_options(self):
        return self.env['res.config.settings']._get_addons_path_options()

    def _parse_github_url(self, url):
        if not url:
            return None, None
        # Support formats:
        # https://github.com/owner/repo
        # git@github.com:owner/repo.git
        # github.com/owner/repo
        match = re.search(r'(?:github\.com/|github\.com:|git@github\.com:)([^/]+)/([^/.]+)', url)
        if match:
            return match.group(1), match.group(2).replace('.git', '')
        return None, None

    def _parse_manifest_content(self, content):
        try:
            tree = ast.parse(content)
            for node in tree.body:
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Dict):
                    return ast.literal_eval(node.value)
        except Exception as e:
            _logger.warning("Failed to parse manifest content safely: %s", e)
        return {}

    def action_download_and_review(self):
        """Step 1: Fetch ZIP (GitHub or local), inspect structure, check dependencies, prepare review."""
        self.ensure_one()
        
        # Validate inputs
        if self.source_type == 'github':
            if not self.github_url:
                raise UserError(_("Please provide a GitHub Repository URL."))
            owner, repo = self._parse_github_url(self.github_url)
            if not owner or not repo:
                raise UserError(_("Could not parse GitHub URL. Ensure it matches 'https://github.com/owner/repo'."))
        else:
            if not self.zip_file:
                raise UserError(_("Please upload a ZIP file."))
            if not self.zip_filename or not self.zip_filename.lower().endswith('.zip'):
                raise UserError(_("Uploaded file must be a ZIP archive."))

        # Create temporary extraction directory
        temp_dir = tempfile.mkdtemp(prefix="odoo_ext_inst_")
        
        try:
            zip_payload = None
            if self.source_type == 'github':
                owner, repo = self._parse_github_url(self.github_url)
                ref = self.github_branch.strip() if self.github_branch else ""
                
                # Build zipball redirect URL
                if ref:
                    download_url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{ref}"
                else:
                    download_url = f"https://api.github.com/repos/{owner}/{repo}/zipball"
                
                _logger.info("Downloading ZIP from GitHub: %s", download_url)
                try:
                    req = urllib.request.Request(
                        download_url,
                        headers={'User-Agent': 'Mozilla/5.0 (Odoo Extension Installer)'}
                    )
                    with urllib.request.urlopen(req, timeout=30) as response:
                        zip_payload = response.read()
                except urllib.error.URLError as e:
                    _logger.exception("GitHub download failed.")
                    raise UserError(_("Failed to download from GitHub: %s. Check the URL/branch or internet connectivity.") % str(e))
            else:
                # Local uploaded ZIP file
                # In Odoo, self.zip_file is binary encoded, but we can read it directly into BytesIO
                # Wait, binary fields in Odoo are base64 encoded strings (bytes or str depending on Odoo version).
                # We need to decode it first!
                import base64
                try:
                    zip_payload = base64.b64decode(self.zip_file)
                except Exception as e:
                    raise UserError(_("Failed to decode ZIP file: %s") % str(e))

            # Extract ZIP payload to temp directory
            with zipfile.ZipFile(io.BytesIO(zip_payload)) as z:
                z.extractall(temp_dir)

        except Exception as e:
            # Clean up temp dir if something failed here
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise UserError(_("Error processing archive: %s") % str(e))

        # Scan the extracted directories for Odoo modules
        modules_found = []
        for root, dirs, files in os.walk(temp_dir):
            # Check for Odoo manifests
            manifest_file = None
            if '__manifest__.py' in files:
                manifest_file = '__manifest__.py'
            elif '__openerp__.py' in files:
                manifest_file = '__openerp__.py'

            if manifest_file:
                manifest_path = os.path.join(root, manifest_file)
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        manifest_content = f.read()
                    manifest_dict = self._parse_manifest_content(manifest_content)
                except Exception as e:
                    _logger.warning("Could not read manifest at %s: %s", manifest_path, e)
                    manifest_dict = {}

                # Determine technical name
                # If manifest is at the root of the ZIP's unique top-level dir (GitHub zipballs put everything in owner-repo-hash folder)
                rel_path = os.path.relpath(root, temp_dir)
                path_parts = rel_path.replace('\\', '/').split('/')
                
                # If there's a wrapper directory (e.g. ['owner-repo-commit']) and the manifest is inside it, e.g. ['owner-repo-commit']
                # then this is a single module repository.
                # Its technical name should default to the repository name.
                is_root_module = False
                if len(path_parts) == 1 and path_parts[0] != '.':
                    is_root_module = True
                elif len(path_parts) == 2 and path_parts[1] == '':
                    is_root_module = True
                elif rel_path == '.':
                    # ZIP has manifest directly at the root
                    is_root_module = True

                if is_root_module:
                    if self.source_type == 'github':
                        owner, repo = self._parse_github_url(self.github_url)
                        tech_name = repo
                    else:
                        # For ZIP upload, use the filename without extension
                        tech_name = os.path.splitext(self.zip_filename)[0]
                        # clean technical name (must be alphanumeric + underscores)
                        tech_name = re.sub(r'[^a-zA-Z0-9_]', '_', tech_name)
                else:
                    # Multi-module structure or nested module. The folder name itself is the technical name.
                    tech_name = os.path.basename(root)

                modules_found.append({
                    'tech_name': tech_name,
                    'title': manifest_dict.get('name', tech_name),
                    'version': manifest_dict.get('version', '1.0'),
                    'depends': manifest_dict.get('depends', []),
                    'extracted_path': root,
                })

        if not modules_found:
            shutil.rmtree(temp_dir)
            raise UserError(_("No Odoo modules (containing __manifest__.py) were found in the uploaded/downloaded archive."))

        # Build Review Summary HTML
        review_html = []
        review_html.append("<div class='o_extension_installer_review'>")
        review_html.append("<p><strong>Modules detected in the archive:</strong></p>")
        review_html.append("<table class='table table-sm table-striped'>")
        review_html.append("<thead><tr><th>Technical Name</th><th>Title</th><th>Version</th><th>Dependencies</th></tr></thead>")
        review_html.append("<tbody>")

        all_detected_names = [m['tech_name'] for m in modules_found]
        ir_module_obj = self.env['ir.module.module']

        for module in modules_found:
            dep_status = []
            for dep in module['depends']:
                if dep == 'base':
                    continue
                # Check database status
                db_mod = ir_module_obj.search([('name', '=', dep)], limit=1)
                if db_mod:
                    if db_mod.state == 'installed':
                        dep_status.append(f"<span class='text-success'>{dep}</span>")
                    else:
                        dep_status.append(f"<span class='text-warning'>{dep} (not installed)</span>")
                elif dep in all_detected_names:
                    # Dependency is part of the same zip archive
                    dep_status.append(f"<span class='text-info'>{dep} (included)</span>")
                else:
                    # Dependency completely missing
                    dep_status.append(f"<span class='text-danger'><strong>{dep} (missing!)</strong></span>")

            dep_str = ", ".join(dep_status) if dep_status else "<span class='text-muted'>None</span>"
            review_html.append(f"<tr>")
            review_html.append(f"<td><code>{module['tech_name']}</code></td>")
            review_html.append(f"<td>{module['title']}</td>")
            review_html.append(f"<td>{module['version']}</td>")
            review_html.append(f"<td>{dep_str}</td>")
            review_html.append(f"</tr>")

        review_html.append("</tbody>")
        review_html.append("</table>")
        review_html.append("</div>")

        self.write({
            'state': 'review',
            'temp_dir_path': temp_dir,
            'modules_data': json.dumps(modules_found),
            'review_message': "".join(review_html)
        })

        # Return the wizard to keep it open in the review state
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_install_confirm(self):
        """Step 2: Extract modules to target_path, handle backups, update Odoo module list, write history logs."""
        self.ensure_one()
        if self.state != 'review' or not self.temp_dir_path or not self.modules_data:
            raise UserError(_("Invalid state or missing module data."))

        target_dir = self.target_path
        if not target_dir or not os.path.exists(target_dir):
            raise UserError(_("Target addons directory does not exist: %s") % target_dir)

        if not os.access(target_dir, os.W_OK):
            raise UserError(_("The Odoo server process does not have write permissions to the target directory: %s") % target_dir)

        modules = json.loads(self.modules_data)
        installed_logs = []
        history_obj = self.env['extension.installation.history']

        try:
            for module in modules:
                tech_name = module['tech_name']
                src_path = module['extracted_path']
                dest_path = os.path.join(target_dir, tech_name)
                
                # 1. Backup old directory if it exists
                backup_file_path = ""
                if os.path.exists(dest_path):
                    backups_dir = os.path.join(target_dir, '_backups')
                    if not os.path.exists(backups_dir):
                        os.makedirs(backups_dir)
                    
                    timestamp = time.strftime('%Y%m%d_%H%M%S')
                    backup_zip_name = f"{tech_name}_backup_{timestamp}"
                    backup_zip_path = os.path.join(backups_dir, backup_zip_name)
                    
                    # Create ZIP archive of the old directory
                    _logger.info("Backing up existing module %s to %s", tech_name, backup_zip_path)
                    shutil.make_archive(backup_zip_path, 'zip', dest_path)
                    backup_file_path = backup_zip_path + '.zip'
                    
                    # Delete old directory
                    shutil.rmtree(dest_path)

                # 2. Extract/copy new module to dest_path
                _logger.info("Copying module %s from temp %s to target %s", tech_name, src_path, dest_path)
                shutil.copytree(src_path, dest_path)

                # 3. Create Installation History Record
                source_detail = self.github_url if self.source_type == 'github' else self.zip_filename
                if self.source_type == 'github' and self.github_branch:
                    source_detail += f" ({self.github_branch})"

                history_obj.create({
                    'name': tech_name,
                    'display_name_module': module['title'],
                    'source_type': self.source_type,
                    'source_url': source_detail,
                    'version': module['version'],
                    'backup_path': backup_file_path,
                    'status': 'restart_pending',
                })

                installed_logs.append(_("Installed %s (version %s)") % (module['title'], module['version']))

        except Exception as e:
            _logger.exception("Error extracting module files.")
            raise UserError(_("Extraction failed: %s") % str(e))
        
        finally:
            # Always clean up temp directory
            if os.path.exists(self.temp_dir_path):
                shutil.rmtree(self.temp_dir_path)

        # 4. Trigger Odoo Apps Update List
        try:
            self.env['ir.module.module'].update_list()
        except Exception as e:
            _logger.warning("Failed to automatically update Odoo apps list: %s", e)

        # Write result status
        self.write({
            'state': 'done',
            'installed_modules_log': "\n".join(installed_logs),
            'restart_pending': True
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_back(self):
        """Go back to the configuration page of the wizard."""
        self.ensure_one()
        self.write({'state': 'init'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_restart_server(self):
        """Invoke server restart from wizard."""
        self.ensure_one()
        # Find any dummy log history or reuse logic from history
        dummy_history = self.env['extension.installation.history'].new()
        return dummy_history.action_restart_server()
