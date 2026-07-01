# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
import os
import shutil
import tempfile
import zipfile

class TestExtensionInstaller(TransactionCase):

    def setUp(self):
        super(TestExtensionInstaller, self).setUp()
        self.wizard = self.env['extension.install.wizard'].create({
            'source_type': 'github',
            'github_url': 'https://github.com/google-deepmind/odoo_extension_installer',
            'target_path': '/tmp',  # Dummy path for wizard creation
        })

    def test_parse_github_url(self):
        """Test extraction of owner and repo name from various GitHub URLs."""
        urls = [
            ('https://github.com/google-deepmind/odoo_extension_installer', 'google-deepmind', 'odoo_extension_installer'),
            ('https://github.com/google-deepmind/odoo_extension_installer.git', 'google-deepmind', 'odoo_extension_installer'),
            ('git@github.com:google-deepmind/odoo_extension_installer.git', 'google-deepmind', 'odoo_extension_installer'),
            ('github.com/google-deepmind/odoo_extension_installer', 'google-deepmind', 'odoo_extension_installer'),
        ]
        for url, expected_owner, expected_repo in urls:
            owner, repo = self.wizard._parse_github_url(url)
            self.assertEqual(owner, expected_owner, "Failed parsing owner for %s" % url)
            self.assertEqual(repo, expected_repo, "Failed parsing repo for %s" % url)

        # Invalid URL
        owner, repo = self.wizard._parse_github_url("https://google.com")
        self.assertFalse(owner)
        self.assertFalse(repo)

    def test_parse_manifest_content(self):
        """Test safe parsing of python dictionaries inside Odoo manifest files."""
        manifest_content = """# -*- coding: utf-8 -*-
{
    'name': 'Test Module',
    'version': '1.0.0',
    'depends': ['base', 'sale'],
    'author': 'Antigravity',
}
"""
        parsed = self.wizard._parse_manifest_content(manifest_content)
        self.assertEqual(parsed.get('name'), 'Test Module')
        self.assertEqual(parsed.get('version'), '1.0.0')
        self.assertEqual(parsed.get('depends'), ['base', 'sale'])
        self.assertEqual(parsed.get('author'), 'Antigravity')

        # Invalid manifest should return empty dict
        invalid_content = "invalid python code {{{"
        parsed_invalid = self.wizard._parse_manifest_content(invalid_content)
        self.assertEqual(parsed_invalid, {})

    def test_backup_mechanism(self):
        """Test that directories are correctly backed up to a zip archive."""
        # Create a temporary directory structure for tests
        temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp_dir)

        # Create dummy module directory to backup
        module_dir = os.path.join(temp_dir, 'dummy_module')
        os.makedirs(module_dir)
        with open(os.path.join(module_dir, 'dummy_file.txt'), 'w') as f:
            f.write("hello world")

        # Create backup directory
        backups_dir = os.path.join(temp_dir, '_backups')
        os.makedirs(backups_dir)

        # Execute backup zipping logic
        backup_zip_path = os.path.join(backups_dir, 'dummy_module_backup')
        shutil.make_archive(backup_zip_path, 'zip', module_dir)
        full_backup_path = backup_zip_path + '.zip'

        self.assertTrue(os.path.exists(full_backup_path), "Backup zip file was not created.")
        
        # Verify ZIP contains the file
        with zipfile.ZipFile(full_backup_path, 'r') as z:
            namelist = z.namelist()
            self.assertIn('dummy_file.txt', namelist, "Backup ZIP does not contain target files.")

    def test_get_addons_path_options(self):
        """Test _get_addons_path_options handling string, list, and invalid config types."""
        from unittest.mock import patch
        from odoo.tools import config
        
        settings = self.env['res.config.settings'].create({})
        
        # Scenario 1: config returns a string
        with patch.object(config, 'get', return_value='/opt/odoo/addons,/var/lib/odoo/custom'):
            options = settings._get_addons_path_options()
            self.assertEqual(len(options), 2)
            self.assertEqual(options[0][0], os.path.normpath('/opt/odoo/addons'))
            self.assertEqual(options[1][0], os.path.normpath('/var/lib/odoo/custom'))
            
        # Scenario 2: config returns a list (including non-string safety check)
        with patch.object(config, 'get', return_value=['/opt/odoo/addons', None, 123, '/var/lib/odoo/custom']):
            options = settings._get_addons_path_options()
            self.assertEqual(len(options), 2)
            self.assertEqual(options[0][0], os.path.normpath('/opt/odoo/addons'))
            self.assertEqual(options[1][0], os.path.normpath('/var/lib/odoo/custom'))

        # Scenario 3: config returns an empty/invalid type
        with patch.object(config, 'get', return_value=None):
            options = settings._get_addons_path_options()
            self.assertEqual(options, [('', 'No addons path detected')])

    def test_get_odoo_series(self):
        """Test that get_odoo_series parses various Odoo release version string formats correctly."""
        from unittest.mock import patch
        import sys
        
        # We patch odoo.release inside sys.modules or mock the attribute
        import odoo
        app_model = self.env['extension.app']
        
        # Test standard major version
        with patch('odoo.release.version', '18.0'):
            self.assertEqual(app_model.get_odoo_series(), '18.0')
            
        # Test SaaS version format
        with patch('odoo.release.version', 'saas~18.3'):
            self.assertEqual(app_model.get_odoo_series(), '18.0')
            
        # Test older SaaS version format
        with patch('odoo.release.version', '7.saas~3.1.0'):
            self.assertEqual(app_model.get_odoo_series(), '7.0')

        # Test development/alpha version
        with patch('odoo.release.version', '19.0a1'):
            self.assertEqual(app_model.get_odoo_series(), '19.0')

    def test_selective_installation(self):
        """Test that only selected modules in the wizard are extracted and installed."""
        import tempfile
        import zipfile
        import io
        import base64
        import shutil
        
        # 1. Create a dummy target directory
        target_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, target_dir)
        
        # 2. Create a mock ZIP file in memory containing two dummy Odoo modules
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            # Module A
            zf.writestr('module_a/__manifest__.py', "{'name': 'Module A', 'depends': ['base']}")
            zf.writestr('module_a/main.py', "# Code for A")
            # Module B
            zf.writestr('module_b/__manifest__.py', "{'name': 'Module B', 'depends': ['base']}")
            zf.writestr('module_b/main.py', "# Code for B")
            
        zip_data = base64.b64encode(zip_buffer.getvalue())
        
        # 3. Create install wizard
        wizard = self.env['extension.install.wizard'].create({
            'source_type': 'zip',
            'zip_file': zip_data,
            'zip_filename': 'test_modules.zip',
            'target_path': target_dir,
        })
        
        # 4. Step 1: Review & Verify
        wizard.action_download_and_review()
        self.assertEqual(wizard.state, 'review')
        self.assertEqual(len(wizard.module_ids), 2)
        
        # 5. Deselect Module B (only install Module A)
        module_a = wizard.module_ids.filtered(lambda m: m.tech_name == 'module_a')
        module_b = wizard.module_ids.filtered(lambda m: m.tech_name == 'module_b')
        self.assertTrue(module_a)
        self.assertTrue(module_b)
        
        module_a.write({'install': True})
        module_b.write({'install': False})
        
        # 6. Step 2: Extract & Install
        wizard.action_install_confirm()
        self.assertEqual(wizard.state, 'done')
        
        # 7. Assertions
        # Module A must exist in target_dir
        dest_a = os.path.join(target_dir, 'module_a')
        self.assertTrue(os.path.exists(dest_a))
        self.assertTrue(os.path.exists(os.path.join(dest_a, '__manifest__.py')))
        
        # Module B must NOT exist in target_dir
        dest_b = os.path.join(target_dir, 'module_b')
        self.assertFalse(os.path.exists(dest_b))

    def test_dependency_auto_resolution(self):
        """Test that missing third-party dependencies are searched and auto-installed."""
        from unittest.mock import patch
        import tempfile
        import zipfile
        import io
        import base64
        import shutil
        
        target_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, target_dir)
        
        # Create ZIP payload with a module that depends on 'missing_dep'
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            zf.writestr('my_module/__manifest__.py', "{'name': 'My Module', 'depends': ['missing_dep']}")
            
        zip_data = base64.b64encode(zip_buffer.getvalue())
        
        # Mock Odoo Apps search and urllib request to mock App Store dependency resolution
        mock_app_data = [{
            'tech_name': 'missing_dep',
            'name': 'Missing Dependency',
            'detail_url': '/apps/modules/18.0/missing_dep',
        }]
        
        # Mock details page HTML containing a fake GitHub URL
        mock_html = """
        <html>
            <body>
                <td><b>Website</b></td>
                <td><a href="https://github.com/test_owner/missing_dep">Repo Link</a></td>
            </body>
        </html>
        """
        
        # Mock zip payload of the dependency
        dep_zip_buffer = io.BytesIO()
        with zipfile.ZipFile(dep_zip_buffer, 'w') as zf:
            zf.writestr('test_owner-missing_dep-hash/missing_dep/__manifest__.py', "{'name': 'Missing Dep', 'depends': ['base']}")
            zf.writestr('test_owner-missing_dep-hash/missing_dep/utils.py', "# Utility code")
            
        dep_zip_payload = dep_zip_buffer.getvalue()
        
        wizard = self.env['extension.install.wizard'].create({
            'source_type': 'zip',
            'zip_file': zip_data,
            'zip_filename': 'my_module.zip',
            'target_path': target_dir,
        })
        
        # Review
        wizard.action_download_and_review()
        self.assertEqual(wizard.module_ids[0].status, 'missing')
        
        # Install and resolve
        with patch.object(self.env['extension.app'], '_scrape_apps', return_value=mock_app_data), \
             patch('urllib.request.urlopen') as mock_urlopen:
             
             # First call returns detail page, second returns dependency zipball
             mock_urlopen.return_value.__enter__.return_value.read.side_effect = [
                 mock_html.encode('utf-8'),
                 dep_zip_payload
             ]
             
             wizard.action_install_confirm()
             
        # Assertions: both my_module and missing_dep should be in target_dir
        self.assertTrue(os.path.exists(os.path.join(target_dir, 'my_module')))
        self.assertTrue(os.path.exists(os.path.join(target_dir, 'missing_dep')))
        self.assertTrue(os.path.exists(os.path.join(target_dir, 'missing_dep', 'utils.py')))




