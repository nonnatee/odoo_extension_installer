Developer and Extension Guide
=============================

This technical reference provides insight into the security constraints, architecture, and extension patterns of the Odoo Extension Installer module.

Security Architecture
---------------------
Because the installer writes files directly to the Odoo server's filesystem and executes system shell processes, strict security protocols are enforced:

1. **Access Control**:
   Both the wizard (``extension.install.wizard``) and history models (``extension.installation.history``) restrict all CRUD and execution methods to the Settings Administrator group (``base.group_system``) in ``security/ir.model.access.csv``.

2. **Safe Manifest Parsing**:
   To read module details (like dependencies, description, version) from ``__manifest__.py`` files without executing arbitrary Python code, the wizard avoids the unsafe python function ``eval()``. Instead, it uses Python's Abstract Syntax Tree (``ast``) module:

   .. code-block:: python

      import ast

      def _parse_manifest_content(self, content):
          try:
              tree = ast.parse(content)
              for node in tree.body:
                  # Ensure we only evaluate dict literal expressions
                  if isinstance(node, ast.Expr) and isinstance(node.value, ast.Dict):
                      return ast.literal_eval(node.value)
          except Exception as e:
              _logger.warning("Manifest parsing failed: %s", e)
          return {}

3. **Sandboxing and Path Sanitization**:
   The installer validates the target directory to prevent directory traversal exploits. When extracting files, they are written to a temporary sandboxed folder (``tempfile.mkdtemp``) and then copied strictly to the verified target path.

Wizard State Machine
--------------------
The install flow is managed using a three-stage state machine:

.. mermaid::

   graph TD
       init[Configure Source: init] -->|action_download_and_review| review[Review Modules: review]
       review -->|action_back| init
       review -->|action_install_confirm| done[Installation Complete: done]

- **init**: Captures source selection, URLs, or ZIP binaries.
- **review**: Shows detected modules, dependency statuses, and confirmation screens.
- **done**: Logs history, updates Odoo registries, and provides a restart button.

Tutorial: Complete GitLab Extension Module
------------------------------------------
Developers can extend the base ``odoo_extension_installer`` module to support GitLab repositories or custom private registries. Below is the complete code for a secondary Odoo module ``odoo_extension_installer_gitlab`` that adds support for downloading from GitLab.

1. **Create the Manifest file** at ``odoo_extension_installer_gitlab/__manifest__.py``:

   .. code-block:: python

      # -*- coding: utf-8 -*-
      {
          'name': 'Odoo Extension Installer - GitLab Extension',
          'version': '19.0.1.0.0',
          'category': 'Extra Tools',
          'summary': 'Adds GitLab support to the Odoo Extension Installer.',
          'depends': ['odoo_extension_installer'],
          'data': [
              'wizard/extension_install_wizard_views.xml',
          ],
          'installable': True,
          'license': 'LGPL-3',
      }

2. **Inherit the Wizard Form View** at ``odoo_extension_installer_gitlab/wizard/extension_install_wizard_views.xml`` to inject fields:

   .. code-block:: xml

      <?xml version="1.0" encoding="utf-8"?>
      <odoo>
          <record id="view_extension_install_wizard_form_inherit_gitlab" model="ir.ui.view">
              <field name="name">extension.install.wizard.form.inherit.gitlab</field>
              <field name="model">extension.install.wizard</field>
              <field name="inherit_id" ref="odoo_extension_installer.view_extension_install_wizard_form"/>
              <field name="arch" type="xml">
                  <xpath expr="//field[@name='github_url']" position="after">
                      <field name="gitlab_project_path" invisible="source_type != 'gitlab'" required="source_type == 'gitlab'" placeholder="e.g. group/project-name"/>
                      <field name="gitlab_token" password="True" invisible="source_type != 'gitlab'"/>
                  </xpath>
              </field>
          </record>
      </odoo>

3. **Extend the Wizard Model** at ``odoo_extension_installer_gitlab/wizard/extension_install_wizard.py``:

   .. code-block:: python

      # -*- coding: utf-8 -*-
      import urllib.request
      import urllib.parse
      import urllib.error
      import io
      import base64
      import zipfile
      import shutil
      import tempfile
      import logging
      from odoo import models, fields, api, _
      from odoo.exceptions import UserError

      _logger = logging.getLogger(__name__)

      class ExtensionInstallWizard(models.TransientModel):
          _inherit = 'extension.install.wizard'

          # Extend selection field to add GitLab support
          source_type = fields.Selection(selection_add=[
              ('gitlab', 'GitLab Repository')
          ], ondelete={'gitlab': 'cascade'})

          gitlab_project_path = fields.Char(string="GitLab Project Path (namespace/project)")
          gitlab_token = fields.Char(string="GitLab Private Access Token")

          def action_download_and_review(self):
              self.ensure_one()
              if self.source_type != 'gitlab':
                  return super(ExtensionInstallWizard, self).action_download_and_review()

              # 1. Input validation
              if not self.gitlab_project_path:
                  raise UserError(_("Please provide a GitLab Project Path."))

              temp_dir = tempfile.mkdtemp(prefix="odoo_ext_inst_gitlab_")
              try:
                  # URL encode project namespace/name
                  project_id = urllib.parse.quote_plus(self.gitlab_project_path.strip())
                  ref = self.github_branch.strip() if self.github_branch else "main"
                  
                  # Construct GitLab API archive URL
                  download_url = f"https://gitlab.com/api/v4/projects/{project_id}/repository/archive.zip?sha={ref}"
                  
                  _logger.info("Downloading ZIP from GitLab: %s", download_url)
                  req = urllib.request.Request(download_url)
                  req.add_header('User-Agent', 'Mozilla/5.0 (Odoo Extension Installer)')
                  
                  # Add private token if configured
                  if self.gitlab_token:
                      req.add_header('PRIVATE-TOKEN', self.gitlab_token.strip())

                  with urllib.request.urlopen(req, timeout=30) as response:
                      zip_payload = response.read()

                  # Extract archive
                  with zipfile.ZipFile(io.BytesIO(zip_payload)) as z:
                      z.extractall(temp_dir)

              except urllib.error.URLError as e:
                  if os.path.exists(temp_dir):
                      shutil.rmtree(temp_dir)
                  _logger.exception("GitLab download failed.")
                  raise UserError(_("Failed to download from GitLab: %s. Verify project path or API tokens.") % str(e))
              except Exception as e:
                  if os.path.exists(temp_dir):
                      shutil.rmtree(temp_dir)
                  raise UserError(_("Error processing GitLab archive: %s") % str(e))

              # Run the common manifest parsing and evaluation logic
              # We pass the temporary folder path to review parent logic
              # Note: In the base model, we override and process the directory contents
              return self._process_extracted_directory_and_review(temp_dir)

Automated Test Suite Overview
-----------------------------
Automated unit tests reside inside the ``tests/test_installer.py`` file and inherit from Odoo's ``TransactionCase``.

- **Test Parsing GitHub URL**:
  Ensures URL formats (SSH, HTTPS, and variants) are correctly mapped to owner and repository names.
  
  .. code-block:: python

     owner, repo = self.wizard._parse_github_url('git@github.com:owner/repo.git')
     self.assertEqual(owner, 'owner')
     self.assertEqual(repo, 'repo')

- **Test Safe Manifest Parser**:
  Passes string representations of python dictionary configurations to verify the AST parser successfully returns a native dict without calling ``eval()``:

  .. code-block:: python

     manifest_content = "{'name': 'Test App', 'depends': ['base']}"
     parsed = self.wizard._parse_manifest_content(manifest_content)
     self.assertEqual(parsed.get('name'), 'Test App')

- **Test Backup Mechanism**:
  Creates mock folder directories inside temporary paths, compresses them to a ZIP archive, and deletes the original folder, verifying the backup exists and contains all files:

  .. code-block:: python

     shutil.make_archive(backup_zip_path, 'zip', module_dir)
     self.assertTrue(os.path.exists(backup_zip_path + '.zip'))
