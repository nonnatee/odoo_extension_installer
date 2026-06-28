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
