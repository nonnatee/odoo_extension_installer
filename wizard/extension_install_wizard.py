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
    
    module_ids = fields.One2many(
        'extension.install.wizard.module', 
        'wizard_id', 
        string="Detected Modules"
    )


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
                    import ssl
                    ssl_ctx = ssl._create_unverified_context()
                    with urllib.request.urlopen(req, timeout=30, context=ssl_ctx) as response:
                        zip_payload = response.read()
                except urllib.error.URLError as e:
                    _logger.exception("GitHub download failed.")
                    raise UserError(_("Failed to download from GitHub: %s. Check the URL/branch or internet connectivity.") % str(e))
            else:
                # Local uploaded ZIP file
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
                    if self.source_type == 'github':
                        owner, repo = self._parse_github_url(self.github_url)
                        tech_name = repo
                    else:
                        tech_name = os.path.splitext(self.zip_filename)[0]
                        tech_name = re.sub(r'[^a-zA-Z0-9_]', '_', tech_name)
                else:
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

        # Populate module_ids O2M field
        self.module_ids.unlink()
        all_detected_names = [m['tech_name'] for m in modules_found]
        ir_module_obj = self.env['ir.module.module']
        
        wizard_modules = []
        for m in modules_found:
            # Check dependency statuses
            has_missing = False
            for dep in m['depends']:
                if dep == 'base':
                    continue
                db_mod = ir_module_obj.search([('name', '=', dep)], limit=1)
                if db_mod and db_mod.state == 'installed':
                    continue
                if dep in all_detected_names:
                    continue
                has_missing = True
                break
                
            status = 'missing' if has_missing else 'ok'
            
            wizard_modules.append((0, 0, {
                'tech_name': m['tech_name'],
                'title': m['title'],
                'version': m['version'],
                'depends_str': ", ".join(m['depends']) if m['depends'] else "None",
                'depends_raw': json.dumps(m['depends']),
                'extracted_path': m['extracted_path'],
                'status': status,
            }))

        self.write({
            'state': 'review',
            'temp_dir_path': temp_dir,
            'modules_data': json.dumps(modules_found),
            'module_ids': wizard_modules
        })

        # Return the wizard to keep it open in the review state
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

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
        web_match = re.search(r'<td><b>Website</b></td>\s*<td><a[^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if web_match:
            repo_url = self._parse_github_repo(web_match.group(1))
            if repo_url and not self._is_generic_odoo_repo(repo_url):
                return repo_url
                
        all_links = re.findall(r'href=["\'](https?://github\.com/[^"\']+)["\']', html)
        for link in all_links:
            repo_url = self._parse_github_repo(link)
            if repo_url and not self._is_generic_odoo_repo(repo_url):
                return repo_url
        return None

    def _resolve_missing_dependencies(self, missing_deps, target_dir, installed_logs, history_obj, resolved_set=None):
        if resolved_set is None:
            resolved_set = set()
            
        series = self.env['extension.app'].get_odoo_series()
        ir_module_obj = self.env['ir.module.module']
        
        for dep in missing_deps:
            if dep in resolved_set:
                continue
            resolved_set.add(dep)
            
            if os.path.exists(os.path.join(target_dir, dep)):
                continue
                
            _logger.info("Attempting to auto-resolve dependency: %s", dep)
            apps = self.env['extension.app']._scrape_apps(query=dep)
            target_app = None
            for app in apps:
                if app.get('tech_name') == dep:
                    target_app = app
                    break
            if not target_app and apps and apps[0].get('tech_name') == dep:
                target_app = apps[0]
                
            if not target_app:
                _logger.warning("Dependency %s not found on Odoo App Store.", dep)
                installed_logs.append(_("Warning: Could not resolve dependency '%s' (not found on App Store).") % dep)
                continue
                
            detail_url = target_app.get('detail_url')
            if not detail_url:
                _logger.warning("No detail URL for dependency %s", dep)
                continue
                
            full_url = f"https://apps.odoo.com{detail_url}"
            req = urllib.request.Request(
                full_url,
                headers={'User-Agent': 'Mozilla/5.0 (Odoo Extension Installer)'}
            )
            try:
                import ssl
                ssl_ctx = ssl._create_unverified_context()
                with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as response:
                    html_content = response.read().decode('utf-8', errors='ignore')
            except Exception as e:
                _logger.warning("Failed to fetch detail page for %s: %s", dep, e)
                installed_logs.append(_("Warning: Failed to fetch App Store detail page for '%s'.") % dep)
                continue
                
            git_url = self._find_github_url(html_content)
            if not git_url:
                _logger.warning("No GitHub repository link found for dependency %s", dep)
                installed_logs.append(_("Warning: Could not auto-download dependency '%s' (no public GitHub repository found on App Store page).") % dep)
                continue
                
            owner, repo = self._parse_github_owner_repo(git_url)
            if not owner or not repo:
                continue
                
            download_url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{series}"
            _logger.info("Downloading dependency %s from GitHub: %s", dep, download_url)
            
            dep_temp_dir = tempfile.mkdtemp(prefix=f"odoo_ext_dep_{dep}_")
            try:
                req_download = urllib.request.Request(
                    download_url,
                    headers={'User-Agent': 'Mozilla/5.0 (Odoo Extension Installer)'}
                )
                with urllib.request.urlopen(req_download, timeout=30, context=ssl_ctx) as response:
                    zip_payload = response.read()
                    
                with zipfile.ZipFile(io.BytesIO(zip_payload)) as z:
                    z.extractall(dep_temp_dir)
                    
                found_dep_path = None
                found_manifest = {}
                for root, dirs, files in os.walk(dep_temp_dir):
                    manifest_file = None
                    if '__manifest__.py' in files:
                        manifest_file = '__manifest__.py'
                    elif '__openerp__.py' in files:
                        manifest_file = '__openerp__.py'
                        
                    if manifest_file:
                        if os.path.basename(root) == dep:
                            found_dep_path = root
                            try:
                                with open(os.path.join(root, manifest_file), 'r', encoding='utf-8') as f:
                                    found_manifest = self._parse_manifest_content(f.read())
                            except Exception:
                                pass
                            break
                            
                if not found_dep_path:
                    for root, dirs, files in os.walk(dep_temp_dir):
                        manifest_file = None
                        if '__manifest__.py' in files:
                            manifest_file = '__manifest__.py'
                        elif '__openerp__.py' in files:
                            manifest_file = '__openerp__.py'
                        if manifest_file:
                            rel_path = os.path.relpath(root, dep_temp_dir)
                            path_parts = rel_path.replace('\\', '/').split('/')
                            if len(path_parts) <= 2:
                                found_dep_path = root
                                try:
                                    with open(os.path.join(root, manifest_file), 'r', encoding='utf-8') as f:
                                        found_manifest = self._parse_manifest_content(f.read())
                                except Exception:
                                    pass
                                break
                                
                if not found_dep_path:
                    _logger.warning("Could not find Odoo module directory for dependency '%s' in the downloaded archive.", dep)
                    installed_logs.append(_("Warning: Downloaded archive for '%s' did not contain a matching module folder.") % dep)
                    continue
                    
                dest_path = os.path.join(target_dir, dep)
                if os.path.exists(dest_path):
                    shutil.rmtree(dest_path)
                shutil.copytree(found_dep_path, dest_path)
                
                history_obj.create({
                    'name': dep,
                    'display_name_module': found_manifest.get('name', dep),
                    'source_type': 'github',
                    'source_url': f"{git_url} (dependency of {dep})",
                    'version': found_manifest.get('version', '1.0'),
                    'status': 'restart_pending',
                })
                
                installed_logs.append(_("Auto-resolved and installed dependency: %s (version %s)") % (found_manifest.get('name', dep), found_manifest.get('version', '1.0')))
                
                dep_manifest_deps = found_manifest.get('depends', [])
                nested_missing = []
                for nested_dep in dep_manifest_deps:
                    if nested_dep == 'base':
                        continue
                    db_mod = ir_module_obj.search([('name', '=', nested_dep)], limit=1)
                    if not db_mod or db_mod.state != 'installed':
                        if not os.path.exists(os.path.join(target_dir, nested_dep)):
                            nested_missing.append(nested_dep)
                            
                if nested_missing:
                    self._resolve_missing_dependencies(nested_missing, target_dir, installed_logs, history_obj, resolved_set)
                    
            except Exception as e:
                _logger.exception("Error processing dependency %s", dep)
                installed_logs.append(_("Warning: Failed to install dependency '%s': %s") % (dep, str(e)))
            finally:
                if os.path.exists(dep_temp_dir):
                    shutil.rmtree(dep_temp_dir)

    def action_install_confirm(self):
        """Step 2: Extract modules to target_path, handle backups, update Odoo module list, write history logs."""
        self.ensure_one()
        if self.state != 'review' or not self.temp_dir_path:
            raise UserError(_("Invalid state or missing module data."))

        target_dir = self.target_path
        if not target_dir or not os.path.exists(target_dir):
            raise UserError(_("Target addons directory does not exist: %s") % target_dir)

        if not os.access(target_dir, os.W_OK):
            raise UserError(_("The Odoo server process does not have write permissions to the target directory: %s") % target_dir)

        selected_modules = self.module_ids.filtered(lambda m: m.install)
        if not selected_modules:
            raise UserError(_("Please select at least one module to install."))

        installed_logs = []
        history_obj = self.env['extension.installation.history']
        ir_module_obj = self.env['ir.module.module']

        # Scan for missing dependencies of selected modules
        missing_deps = []
        for m in selected_modules:
            deps = json.loads(m.depends_raw or '[]')
            for dep in deps:
                if dep == 'base':
                    continue
                db_mod = ir_module_obj.search([('name', '=', dep)], limit=1)
                if db_mod and db_mod.state == 'installed':
                    continue
                if dep in [sm.tech_name for sm in selected_modules]:
                    continue
                if dep not in missing_deps:
                    missing_deps.append(dep)

        try:
            # 1. Install selected modules
            for module in selected_modules:
                tech_name = module.tech_name
                src_path = module.extracted_path
                dest_path = os.path.join(target_dir, tech_name)
                
                # Backup old directory if it exists
                backup_file_path = ""
                if os.path.exists(dest_path):
                    backups_dir = os.path.join(target_dir, '_backups')
                    if not os.path.exists(backups_dir):
                        os.makedirs(backups_dir)
                    
                    timestamp = time.strftime('%Y%m%d_%H%M%S')
                    backup_zip_name = f"{tech_name}_backup_{timestamp}"
                    backup_zip_path = os.path.join(backups_dir, backup_zip_name)
                    
                    _logger.info("Backing up existing module %s to %s", tech_name, backup_zip_path)
                    shutil.make_archive(backup_zip_path, 'zip', dest_path)
                    backup_file_path = backup_zip_path + '.zip'
                    
                    shutil.rmtree(dest_path)

                # Copy new module to dest_path
                _logger.info("Copying module %s from temp %s to target %s", tech_name, src_path, dest_path)
                shutil.copytree(src_path, dest_path)

                # Create Installation History Record
                source_detail = self.github_url if self.source_type == 'github' else self.zip_filename
                if self.source_type == 'github' and self.github_branch:
                    source_detail += f" ({self.github_branch})"

                history_obj.create({
                    'name': tech_name,
                    'display_name_module': module.title,
                    'source_type': self.source_type,
                    'source_url': source_detail,
                    'version': module.version,
                    'backup_path': backup_file_path,
                    'status': 'restart_pending',
                })

                installed_logs.append(_("Installed %s (version %s)") % (module.title, module.version))

            # 2. Automatically resolve and install missing dependencies
            if missing_deps:
                self._resolve_missing_dependencies(missing_deps, target_dir, installed_logs, history_obj)

        except Exception as e:
            _logger.exception("Error extracting module files.")
            raise UserError(_("Extraction failed: %s") % str(e))
        
        finally:
            if os.path.exists(self.temp_dir_path):
                shutil.rmtree(self.temp_dir_path)

        # Trigger Odoo Apps Update List
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
        dummy_history = self.env['extension.installation.history'].new()
        return dummy_history.action_restart_server()


class ExtensionInstallWizardModule(models.TransientModel):
    _name = 'extension.install.wizard.module'
    _description = 'Odoo Module in Installation Archive'

    wizard_id = fields.Many2one('extension.install.wizard', string="Wizard", ondelete='cascade')
    install = fields.Boolean(string="Install", default=True)
    tech_name = fields.Char(string="Technical Name", readonly=True)
    title = fields.Char(string="Title", readonly=True)
    version = fields.Char(string="Version", readonly=True)
    depends_str = fields.Char(string="Dependencies", readonly=True)
    depends_raw = fields.Text(string="Raw Dependencies", readonly=True)
    extracted_path = fields.Char(string="Extracted Path", readonly=True)
    status = fields.Selection([
        ('ok', 'Ready'),
        ('missing', 'Missing (will auto-resolve)')
    ], string="Status", default='ok', readonly=True)
