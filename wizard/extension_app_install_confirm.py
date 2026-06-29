# -*- coding: utf-8 -*-
import os
import time
import zipfile
import tempfile
import io
import urllib.request
import urllib.parse
import urllib.error
import re
import shutil
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ExtensionAppInstallConfirm(models.TransientModel):
    _name = 'extension.app.install.confirm'
    _description = 'Confirm Third-Party App Installation'

    app_id = fields.Many2one('extension.app', string="App Reference", required=True, ondelete='cascade')
    name = fields.Char(string="App Name", required=True, readonly=True)
    tech_name = fields.Char(string="Technical Name", required=True, readonly=True)
    detail_url = fields.Char(string="App Store Path", required=True, readonly=True)
    
    git_url = fields.Char(string="GitHub Repository URL", readonly=True)
    branch = fields.Char(string="Branch/Tag to pull", readonly=True)
    has_git = fields.Boolean(string="GitHub URL Found", default=False, readonly=True)
    
    status_message = fields.Html(string="Status Summary", readonly=True)
    installation_success = fields.Boolean(string="Success State", default=False, readonly=True)
    installed_log = fields.Text(string="Installation Output Logs", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super(ExtensionAppInstallConfirm, self).default_get(fields_list)
        
        detail_url = res.get('detail_url')
        if not detail_url:
            return res
            
        # Live fetch detail page to extract source repository URL
        full_url = f"https://apps.odoo.com{detail_url}"
        _logger.info("Fetching app details from: %s", full_url)
        
        req = urllib.request.Request(
            full_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        )
        
        html_content = ""
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                html_content = response.read().decode('utf-8', errors='ignore')
        except Exception as e:
            _logger.warning("Failed to fetch detail page: %s", e)
            res['status_message'] = _("<div class='alert alert-danger'>Failed to reach Odoo App Store to extract source code metadata: %s</div>") % str(e)
            return res

        # Search for github repository link
        git_url = self._find_github_url(html_content)
        series = self.env['extension.app'].get_odoo_series()
        res['branch'] = series
        
        if git_url:
            res['git_url'] = git_url
            res['has_git'] = True
            res['status_message'] = _("""
                <div class='alert alert-success'>
                    <p><strong>Repository resolved successfully!</strong></p>
                    <ul>
                        <li><strong>GitHub URL:</strong> <code>%s</code></li>
                        <li><strong>Target Branch:</strong> <code>%s</code></li>
                    </ul>
                    <p class='mb-0'>Click <strong>Confirm Install</strong> to download, backup, and copy the module files into your addons directory.</p>
                </div>
            """) % (git_url, series)
        else:
            res['git_url'] = ""
            res['has_git'] = False
            res['status_message'] = _("""
                <div class='alert alert-warning'>
                    <p><strong>No public source repository link found!</strong></p>
                    <p>Programmatic zip downloads directly from the Odoo App Store are restricted. To install this module:</p>
                    <ol>
                        <li>Go to the App Store page: <a href="%s" target="_blank">Odoo Apps: %s</a></li>
                        <li>Download the module archive manually.</li>
                        <li>Upload it using the <strong>Install Module</strong> ZIP wizard.</li>
                    </ol>
                </div>
            """) % (full_url, res.get('name', ''))
            
        return res

    def _parse_github_repo(self, url):
        match = re.search(r'(?:github\.com/|github\.com:|git@github\.com:)([^/]+)/([^/.]+)', url)
        if match:
            owner = match.group(1)
            repo = match.group(2).replace('.git', '')
            repo = repo.split('/')[0]
            return f"https://github.com/{owner}/{repo}"
        return None

    def _parse_github_owner_repo(self, url):
        match = re.search(r'github\.com/([^/]+)/([^/]+)', url)
        if match:
            return match.group(1), match.group(2).replace('.git', '')
        return None, None

    def _is_generic_odoo_repo(self, url):
        url_lower = url.lower()
        generic_repos = [
            'https://github.com/odoo',
            'https://github.com/odoo/odoo',
            'https://github.com/odoo/enterprise',
            'https://github.com/odoo/design-themes',
            'https://github.com/odoo/runbot',
            'https://github.com/odoo/upgrade'
        ]
        return any(generic == url_lower or url_lower.startswith(generic + '/') for generic in generic_repos)

    def _find_github_url(self, html):
        # 1. Try "Website" table field
        web_match = re.search(r'<td><b>Website</b></td>\s*<td><a[^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if web_match:
            repo_url = self._parse_github_repo(web_match.group(1))
            if repo_url and not self._is_generic_odoo_repo(repo_url):
                return repo_url
                
        # 2. Try generic link scraping
        all_links = re.findall(r'href=["\'](https?://github\.com/[^"\']+)["\']', html)
        for link in all_links:
            repo_url = self._parse_github_repo(link)
            if repo_url and not self._is_generic_odoo_repo(repo_url):
                return repo_url
        return None

    def action_confirm_install(self):
        self.ensure_one()
        if not self.has_git or not self.git_url:
            raise UserError(_("This module cannot be installed automatically because no GitHub repository link was found."))

        owner, repo = self._parse_github_owner_repo(self.git_url)
        if not owner or not repo:
            raise UserError(_("Invalid GitHub repository URL: %s") % self.git_url)

        branch = self.branch or '19.0'
        
        # Download ZIP file
        download_url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{branch}"
        _logger.info("Downloading ZIP from GitHub URL: %s", download_url)
        
        req = urllib.request.Request(
            download_url,
            headers={'User-Agent': 'Mozilla/5.0 (Odoo Extension Installer)'}
        )
        zip_payload = None
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                zip_payload = response.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Try fallback download (without version branch)
                fallback_url = f"https://api.github.com/repos/{owner}/{repo}/zipball"
                _logger.info("Version branch '%s' not found. Trying default branch: %s", branch, fallback_url)
                req_fallback = urllib.request.Request(
                    fallback_url,
                    headers={'User-Agent': 'Mozilla/5.0 (Odoo Extension Installer)'}
                )
                try:
                    with urllib.request.urlopen(req_fallback, timeout=30) as response:
                        zip_payload = response.read()
                except Exception as fallback_err:
                    raise UserError(_("Failed to download repository archive. Neither version branch '%s' nor the default branch was accessible: %s") % (branch, str(fallback_err)))
            else:
                raise UserError(_("GitHub API returned error: %s") % str(e))
        except Exception as e:
            raise UserError(_("Failed to connect to GitHub: %s") % str(e))

        # Extract archive
        temp_dir = tempfile.mkdtemp(prefix="odoo_ext_inst_browser_")
        try:
            with zipfile.ZipFile(io.BytesIO(zip_payload)) as z:
                z.extractall(temp_dir)
        except Exception as e:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise UserError(_("Failed to extract downloaded ZIP archive: %s") % str(e))

        # Scan for Odoo modules inside extraction folder
        modules_found = {}
        for root, dirs, files in os.walk(temp_dir):
            manifest_file = None
            if '__manifest__.py' in files:
                manifest_file = '__manifest__.py'
            elif '__openerp__.py' in files:
                manifest_file = '__openerp__.py'
                
            if manifest_file:
                rel_path = os.path.relpath(root, temp_dir)
                path_parts = rel_path.replace('\\', '/').split('/')
                
                is_root_module = False
                if len(path_parts) == 1 and path_parts[0] != '.':
                    is_root_module = True
                elif len(path_parts) == 2 and path_parts[1] == '':
                    is_root_module = True
                elif rel_path == '.':
                    is_root_module = True
                    
                if is_root_module:
                    tech_name_detected = repo
                else:
                    tech_name_detected = os.path.basename(root)
                    
                manifest_path = os.path.join(root, manifest_file)
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        manifest_content = f.read()
                    manifest_dict = self.env['extension.install.wizard']._parse_manifest_content(manifest_content)
                except Exception:
                    manifest_dict = {}
                    
                modules_found[tech_name_detected] = {
                    'extracted_path': root,
                    'title': manifest_dict.get('name', tech_name_detected),
                    'version': manifest_dict.get('version', '1.0'),
                    'depends': manifest_dict.get('depends', []),
                }

        # Resolve target module and its local dependencies in the ZIP
        target_tech_name = self.tech_name
        modules_to_copy = set()
        
        if target_tech_name not in modules_found:
            if len(modules_found) == 1:
                target_tech_name = list(modules_found.keys())[0]
            else:
                shutil.rmtree(temp_dir)
                raise UserError(_("Could not find the target module '%s' in the downloaded archive. Available modules: %s") % (self.tech_name, ", ".join(modules_found.keys())))

        queue = [target_tech_name]
        visited = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            if current in modules_found:
                modules_to_copy.add(current)
                for dep in modules_found[current]['depends']:
                    if dep in modules_found and dep not in visited:
                        queue.append(dep)

        # Retrieve target addons folder
        target_dir = self.env['ir.config_parameter'].sudo().get_param('odoo_extension_installer.target_addons_path')
        if not target_dir or not os.path.exists(target_dir):
            options = self.env['res.config.settings']._get_addons_path_options()
            if options and options[0][0]:
                target_dir = options[0][0]
            else:
                shutil.rmtree(temp_dir)
                raise UserError(_("No target addons directory configured. Please check Extension Installer settings."))

        if not os.access(target_dir, os.W_OK):
            shutil.rmtree(temp_dir)
            raise UserError(_("The Odoo process does not have write permissions to the target addons path: %s") % target_dir)

        installed_logs = []
        history_obj = self.env['extension.installation.history']
        
        try:
            for tech in modules_to_copy:
                src_path = modules_found[tech]['extracted_path']
                dest_path = os.path.join(target_dir, tech)
                
                # Take backup of existing version if it exists
                backup_file_path = ""
                if os.path.exists(dest_path):
                    backups_dir = os.path.join(target_dir, '_backups')
                    if not os.path.exists(backups_dir):
                        os.makedirs(backups_dir)
                        
                    timestamp = time.strftime('%Y%m%d_%H%M%S')
                    backup_zip_name = f"{tech}_backup_{timestamp}"
                    backup_zip_path = os.path.join(backups_dir, backup_zip_name)
                    
                    _logger.info("Backing up existing version of %s to %s", tech, backup_zip_path)
                    shutil.make_archive(backup_zip_path, 'zip', dest_path)
                    backup_file_path = backup_zip_path + '.zip'
                    
                    shutil.rmtree(dest_path)
                    
                # Copy module folder
                _logger.info("Copying module %s from extracted ZIP to %s", tech, dest_path)
                shutil.copytree(src_path, dest_path)
                
                # History log
                history_obj.create({
                    'name': tech,
                    'display_name_module': modules_found[tech]['title'],
                    'source_type': 'github',
                    'source_url': f"{self.git_url} ({self.branch})",
                    'version': modules_found[tech]['version'],
                    'backup_path': backup_file_path,
                    'status': 'restart_pending',
                })
                installed_logs.append(_("Successfully installed: %s (version: %s)") % (modules_found[tech]['title'], modules_found[tech]['version']))
        except Exception as e:
            _logger.exception("Error extracting and copying module files.")
            raise UserError(_("Installation extraction failed: %s") % str(e))
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

        # Trigger Odoo module list update
        try:
            self.env['ir.module.module'].update_list()
        except Exception as e:
            _logger.warning("Failed to update module list: %s", e)

        self.write({
            'installation_success': True,
            'installed_log': "\n".join(installed_logs),
            'status_message': _("""
                <div class='alert alert-success'>
                    <p><strong>Installation completed successfully!</strong></p>
                    <p>The module files have been placed in your addons directory. A server restart is required to load the new code.</p>
                </div>
            """)
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_restart_server(self):
        self.ensure_one()
        dummy_history = self.env['extension.installation.history'].new()
        return dummy_history.action_restart_server()
