# Odoo Extension Installer

[![Odoo Version](https://img.shields.io/badge/odoo-19.0-blue.svg)](https://github.com/odoo/odoo)
[![License](https://img.shields.io/badge/license-LGPL--3-green.svg)](https://www.gnu.org/licenses/lgpl-3.0.en.html)

**Odoo Extension Installer** is a secure, user-friendly tool that allows Odoo administrators (Settings group) to download and install open-source, third-party Odoo modules directly from the web client interface. It supports downloading from public **GitHub repositories** (supporting custom branches/tags/commits) as well as direct **ZIP file uploads**.

---

## Key Features

- 📥 **Dual Sourcing**: Install modules using GitHub repository URLs or local ZIP archives.
- 🔍 **Dependency Validation**: Scans manifest files (`__manifest__.py`) to identify missing dependencies before installation.
- 📦 **Multi-Module Support**: Automatically detects if an archive contains a single module or multiple modules in subdirectories and extracts them cleanly.
- 🗄️ **Automated Backups**: Compresses and archives the existing version of a module in `_backups/*.zip` before overwriting.
- 🔄 **Restart Integration**: Execute a custom shell command (e.g. via systemd or Docker) to restart Odoo directly from the web UI to load new Python code.
- 🛡️ **Advanced Security**: Restricts actions to Odoo's standard Settings administrators (`base.group_system`) and uses Python's `ast` module to safely parse manifest dictionaries without code evaluation risk.

---

## Quick Start

1. **Deploy Module**: Clone or copy this repository into your Odoo custom addons directory.
2. **Update Apps**: Activate Developer Mode in Odoo, navigate to **Apps** -> click **Update Apps List**.
3. **Install**: Search for `Odoo Extension Installer` and click **Install**.
4. **Configure Settings**: Go to **Settings** -> **Extension Installer** and specify:
   - **Target Addons Directory**: Which directory to extract new modules into.
   - **Restart Command**: The CLI command to restart Odoo (e.g., `sudo systemctl restart odoo`).

---

## Documentation Index

Detailed documentation is available in the `doc/` directory:

- **[Installation and Configuration Guide](doc/installation_and_configuration.rst)**: Details on file permissions, systemd setup, Python virtual environments, and Nginx reverse proxy optimizations.
- **[User Guide & Use Case Tutorial](doc/user_guide.rst)**: Step-by-step walkthroughs for downloading from GitHub and uploading local ZIPs.
- **[Developer & Extension Guide](doc/developer_guide.rst)**: Explanations of security guards, the wizard state machine, unit tests, and how to extend the module to support GitLab or private git hosts.
