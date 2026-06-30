# -*- coding: utf-8 -*-
import odoo
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import urllib.request
import urllib.parse
import urllib.error
from html.parser import HTMLParser
import re
import logging

_logger = logging.getLogger(__name__)

class OdooAppParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.apps = []
        self.current_app = None
        self.in_summary = False
        self.in_title = False
        self.in_author = False
        self.in_downloads = False
        self.tag_stack = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self.tag_stack.append((tag, attrs_dict))
        
        # Check for card container
        cls = attrs_dict.get('class', '')
        if tag == 'div' and 'loempia_app_card' in cls:
            self.current_app = {
                'name': '',
                'tech_name': '',
                'summary': '',
                'author': '',
                'icon_url': '',
                'detail_url': '',
                'downloads_str': '',
                'price': 'FREE'
            }
            return
            
        if not self.current_app:
            return
            
        # Extract detail_url and tech_name from standard wrapper link
        if tag == 'a' and not self.current_app['detail_url']:
            href = attrs_dict.get('href', '')
            if href.startswith('/apps/modules/'):
                self.current_app['detail_url'] = href
                parts = href.strip('/').split('/')
                if parts:
                    self.current_app['tech_name'] = parts[-1]
                    
        # Extract summary
        if tag == 'p' and 'loempia_panel_summary' in cls:
            self.in_summary = True
            
        # Extract icon URL from background-image url()
        if tag == 'div' and 'img' in cls:
            style = attrs_dict.get('style', '')
            img_match = re.search(r'url\([\'"]?(.*?)[\'"]?\)', style)
            if img_match:
                img_url = img_match.group(1)
                if img_url.startswith('//'):
                    img_url = 'https:' + img_url
                self.current_app['icon_url'] = img_url
                
        # Also check for <img> tag icon fallback
        if tag == 'img' and ('loempia_app_entry_icon' in cls or 'loempia_app_icon' in cls):
            src = attrs_dict.get('src', '')
            if src.startswith('//'):
                src = 'https:' + src
            self.current_app['icon_url'] = src
            
        # Extract title
        if tag == 'h5' or (tag == 'b' and self.tag_stack and self.tag_stack[-2][0] == 'h5'):
            self.in_title = True
            
        # Extract author
        if 'loempia_panel_author' in cls:
            self.in_author = True
            
        # Extract downloads
        if tag == 'span' and 'Total Downloads' in attrs_dict.get('title', ''):
            self.in_downloads = True

    def handle_endtag(self, tag):
        if self.tag_stack:
            self.tag_stack.pop()
            
        if not self.current_app:
            return
            
        if tag == 'p':
            self.in_summary = False
        elif tag in ('h5', 'b', 'strong'):
            self.in_title = False
        elif tag == 'div':
            self.in_author = False
        elif tag == 'span':
            self.in_downloads = False
            
        # Save app when card container ends
        if tag == 'div' and self.current_app and not any('loempia_app_card' in d[1].get('class', '') for d in self.tag_stack):
            self.current_app['name'] = self.current_app['name'].strip()
            self.current_app['summary'] = self.current_app['summary'].strip()
            self.current_app['author'] = self.current_app['author'].strip()
            self.current_app['downloads_str'] = self.current_app['downloads_str'].strip()
            
            # Clean up comma prefix in author if present
            if self.current_app['author'].startswith(','):
                self.current_app['author'] = self.current_app['author'].lstrip(', ').strip()
                
            if self.current_app['tech_name']:
                self.apps.append(self.current_app)
            self.current_app = None

    def handle_data(self, data):
        if not self.current_app:
            return
            
        if self.in_summary:
            self.current_app['summary'] += data
        elif self.in_title:
            self.current_app['name'] += data
        elif self.in_author:
            self.current_app['author'] += data
        elif self.in_downloads:
            self.current_app['downloads_str'] += data


class ExtensionApp(models.TransientModel):
    _name = 'extension.app'
    _description = 'Third-Party App Browser'

    name = fields.Char(string="Title", readonly=True)
    tech_name = fields.Char(string="Technical Name", readonly=True)
    summary = fields.Char(string="Summary", readonly=True)
    author = fields.Char(string="Author", readonly=True)
    icon_url = fields.Char(string="Icon URL", readonly=True)
    detail_url = fields.Char(string="Detail URL", readonly=True)
    downloads_str = fields.Char(string="Downloads", readonly=True)
    price = fields.Char(string="Price", default="FREE", readonly=True)

    @api.model
    def get_odoo_series(self):
        try:
            import odoo.release
            version = odoo.release.version
        except ImportError:
            version = '19.0'
        # Extract the first sequence of digits (e.g. '18' from 'saas~18.3' or '18.0') and append '.0'
        match = re.search(r'(\d+)', str(version))
        return f"{match.group(1)}.0" if match else '19.0'

    @api.model
    def _scrape_apps(self, query=""):
        series = self.get_odoo_series()
        query_enc = urllib.parse.quote_plus(query.strip())
        url = f"https://apps.odoo.com/apps/modules?series={series}&price=Free"
        if query_enc:
            url += f"&search={query_enc}"
            
        _logger.info("Scraping Odoo Apps Store: %s", url)
        
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        )
        
        import ssl
        try:
            # First try with default secure SSL context
            context = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=15, context=context) as response:
                html_content = response.read().decode('utf-8', errors='ignore')
        except Exception as ssl_e:
            _logger.warning("Failed to fetch Odoo App Store listings with secure SSL: %s. Retrying with unverified context...", ssl_e)
            try:
                # Fallback to unverified SSL context if standard SSL verification fails
                unverified_context = ssl._create_unverified_context()
                with urllib.request.urlopen(req, timeout=15, context=unverified_context) as response:
                    html_content = response.read().decode('utf-8', errors='ignore')
            except Exception as e:
                _logger.error("Failed to fetch Odoo App Store listings: %s", e)
                return []
            
        parser = OdooAppParser()
        try:
            parser.feed(html_content)
        except Exception as e:
            _logger.warning("Failed to parse Odoo App Store HTML: %s", e)
            return []
            
        return parser.apps

    @api.model
    def search(self, domain, offset=0, limit=None, order=None, count=False):
        # Extract search query from search criteria domain
        search_query = ""
        if domain:
            for arg in domain:
                if isinstance(arg, (list, tuple)) and len(arg) == 3 and arg[0] in ('name', 'tech_name', 'summary'):
                    search_query = arg[2]
                    break
                    
        self._sync_apps(search_query)
        return super(ExtensionApp, self).search([], offset=offset, limit=limit, order=order, count=count)

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None, **kwargs):
        # Extract search query
        search_query = ""
        if domain:
            for arg in domain:
                if isinstance(arg, (list, tuple)) and len(arg) == 3 and arg[0] in ('name', 'tech_name', 'summary'):
                    search_query = arg[2]
                    break
                    
        self._sync_apps(search_query)
        return super(ExtensionApp, self).search_read([], fields=fields, offset=offset, limit=limit, order=order, **kwargs)

    @api.model
    def _sync_apps(self, query):
        # Unlink all existing transient browser records
        self.search([]).unlink()
        
        apps_data = self._scrape_apps(query)
        for data in apps_data:
            self.create(data)

    def action_install_app(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'extension.app.install.confirm',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_app_id': self.id,
                'default_name': self.name,
                'default_tech_name': self.tech_name,
                'default_detail_url': self.detail_url,
            }
        }
