# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.addons.odoo_extension_installer.models.extension_app import OdooAppParser

MOCK_SEARCH_HTML = """
<!DOCTYPE html>
<html>
<body>
    <div class="loempia_app_entry loempia_app_card col-md-6 col-lg-3 " data-publish="on">
        <a href="/apps/modules/18.0/crm_dashboard_test">
            <div class="loempia_app_entry_top loempia_cover">
                <p class="loempia_panel_summary">Get a visual report of CRM through a Dashboard in CRM </p>
                <div class="img img-fluid" style="background-image: url(//apps.odoocdn.com/apps/module_image?image_id=31274099);"></div>
            </div>
            <div class="loempia_app_entry_bottom">
                <div><h5 title="CRM Dashboard"><b>CRM Dashboard Test</b></h5></div>
                <div class="row">
                    <div class="col-8 loempia_panel_author">
                        <b>Cybrosys Techno Solutions</b>
                    </div>
                    <div class="col-4 loempia_panel_price text-end">
                        <b>FREE</b>
                    </div>
                </div>
                <div>
                    <span class="loempia_tags float-end">
                        <span title="Total Downloads: 7792, Last month: 74">
                            <i class="fa fa-download"></i>
                            7792
                        </span>
                    </span>
                </div>
            </div>
        </a>
    </div>
</body>
</html>
"""

MOCK_DETAIL_HTML_WITH_GIT = """
<!DOCTYPE html>
<html>
<body>
    <table class="loempia_app_table">
        <tbody>
            <tr>
                <td><b>Technical Name</b></td>
                <td><code>partner_firstname</code></td>
            </tr>
            <tr>
                <td><b>License</b></td>
                <td>AGPL-3</td>
            </tr>
            <tr>
                <td><b>Website</b></td>
                <td><a rel="nofollow" href="https://github.com/OCA/partner-contact/tree/18.0">https://github.com/OCA/partner-contact</a></td>
            </tr>
        </tbody>
    </table>
    <div class="footer">
        <a href="https://github.com/odoo/odoo">Generic Odoo Link</a>
    </div>
</body>
</html>
"""

class TestAppStoreBrowser(TransactionCase):

    def setUp(self):
        super(TestAppStoreBrowser, self).setUp()
        self.browser_model = self.env['extension.app']
        self.confirm_wizard = self.env['extension.app.install.confirm']

    def test_parser_parsing_logic(self):
        """Test that OdooAppParser correctly parses the modules list grid."""
        parser = OdooAppParser()
        parser.feed(MOCK_SEARCH_HTML)
        
        apps = parser.apps
        self.assertEqual(len(apps), 1, "Should have parsed exactly 1 app card.")
        
        app = apps[0]
        self.assertEqual(app['name'], "CRM Dashboard Test")
        self.assertEqual(app['tech_name'], "crm_dashboard_test")
        self.assertEqual(app['summary'], "Get a visual report of CRM through a Dashboard in CRM")
        self.assertEqual(app['author'], "Cybrosys Techno Solutions")
        self.assertEqual(app['icon_url'], "https://apps.odoocdn.com/apps/module_image?image_id=31274099")
        self.assertEqual(app['downloads_str'], "7792")

    def test_github_link_resolving(self):
        """Test finding and cleaning module source repository links from page markup."""
        # Clean URL resolver
        clean_url_1 = self.confirm_wizard._parse_github_repo("https://github.com/OCA/partner-contact/issues")
        self.assertEqual(clean_url_1, "https://github.com/OCA/partner-contact")
        
        clean_url_2 = self.confirm_wizard._parse_github_repo("https://github.com/OCA/partner-contact/tree/18.0")
        self.assertEqual(clean_url_2, "https://github.com/OCA/partner-contact")

        # Exclude generic Odoo URLs
        self.assertTrue(self.confirm_wizard._is_generic_odoo_repo("https://github.com/odoo/odoo"))
        self.assertTrue(self.confirm_wizard._is_generic_odoo_repo("https://github.com/odoo/enterprise/issues"))
        self.assertFalse(self.confirm_wizard._is_generic_odoo_repo("https://github.com/OCA/partner-contact"))

        # Find GitHub link in HTML
        git_url = self.confirm_wizard._find_github_url(MOCK_DETAIL_HTML_WITH_GIT)
        self.assertEqual(git_url, "https://github.com/OCA/partner-contact")
