User Guide & Use Case Tutorial
==============================

This user guide describes how to operate the Odoo Extension Installer module to download, configure, and manage third-party modules.

How to Pack an Odoo Module for ZIP Upload
-----------------------------------------
When uploading a local Odoo module via ZIP file, the archive must be structured properly so that the installer can recognize and unpack it cleanly.

Using the command line, navigate to the parent folder of your module and run the following command. This creates a clean ZIP, excluding development files, repository meta-folders, and compiled caches:

.. code-block:: bash

   # Syntax: zip -r <archive_name>.zip <module_folder>/ -x <exclusions>
   zip -r sale_approval.zip sale_approval/ -x "*.pyc" -x "__pycache__/*" -x "*/.git/*" -x "*/.gitignore"

**Why Exclusions Matter**:
   - Excluding ``__pycache__`` and ``.pyc`` files ensures Odoo doesn't run stale compiled byte code.
   - Excluding the ``.git`` folder keeps the archive size small and prevents copying git tracking files.

Sourcing from GitHub
--------------------
Use Case: You want to install a module hosted in a public GitHub repository (e.g., a community app or OCA module).

1. **Get GitHub Repository URL**:
   Navigate to the target repository on GitHub and copy the HTTPS URL, for example:
   ``https://github.com/OCA/social-media``

2. **Open the Installation Wizard**:
   In Odoo, navigate to **Settings** -> **Extension Installer** -> **Install Module**.

3. **Configure the Input**:
   - **Source Type**: Select *GitHub Repository*.
   - **GitHub Repository URL**: Paste the copied URL.
   - **Branch / Tag / Commit**: Input the specific branch matching your Odoo version (e.g., ``19.0`` or ``master``). If left blank, Odoo will download the default branch of the repository.
   - **Target Directory**: Choose the target addons path folder.

4. **Verify Dependencies**:
   Click **Review & Verify**. Odoo will download the zipball in a temporary folder and display the review layout:
   
   - A list of all modules found in the ZIP.
   - A column showing **Dependencies**. If any required module is missing in Odoo, it will display a red **(missing!)** label. If it is included in the same GitHub repository, it will show a blue **(included)** badge.

5. **Complete Extraction**:
   If the dependencies are correct, click **Extract & Install**. The wizard will copy the folder, back up any pre-existing version, register the new apps, and transition to the success screen.

6. **Reload the Server**:
   Click **Restart Odoo Server Now** to execute the reload command and load the python files into memory.

Sourcing from ZIP File Upload
-----------------------------
Use Case: You downloaded an open-source module ZIP file from an app store or have a custom ZIP file on your computer.

1. **Verify ZIP Archive Structure**:
   Ensure that the ZIP file contains either:
   
   - A folder named after the module (e.g. ``my_module/``) containing the ``__manifest__.py`` file directly inside it.
   - The ``__manifest__.py`` file directly at the root of the ZIP file structure.

2. **Launch the Wizard**:
   Go to **Settings** -> **Extension Installer** -> **Install Module**.

3. **Configure the Input**:
   - **Source Type**: Select *ZIP File Upload*.
   - **ZIP File Payload**: Click upload and select your ZIP file.
   - **Target Directory**: Select the destination path.

4. **Verify & Install**:
   Click **Review & Verify** to review modules. Click **Extract & Install** to finish.

Managing Backups and History Logs
----------------------------------
To audit and review installed modules or restore old versions:

1. **Access Logs**:
   Navigate to **Settings** -> **Extension Installer** -> **Installation History**.
   Here, you can view the list of all installed modules, the source URL/ZIP filename, the installer user, the execution date, and the status.

2. **Locate Backups**:
   If you overwrite an existing module, Odoo Extension Installer automatically compresses the old directory and saves it as:
   ``<target_addons_path>/_backups/<module_name>_backup_<timestamp>.zip``

CommandLine Restore & Rollback Tutorial
---------------------------------------
If a newly installed module causes Odoo to crash on startup (e.g. because of an incompatible Python import or syntax error in the third-party app), follow these command-line steps to safely restore the backup and bring Odoo back online:

1. **Open terminal** on your Odoo server.
2. **Navigate** to your custom addons directory:

   .. code-block:: bash

      cd /opt/odoo/custom_addons

3. **List the backups** to find the timestamped ZIP of your old module version:

   .. code-block:: bash

      ls -lh _backups/
      # Example output: sale_approval_backup_20260627_120000.zip

4. **Delete the broken module** directory:

   .. code-block:: bash

      rm -rf sale_approval

5. **Re-create and extract the backup** into the module folder:

   .. code-block:: bash

      # Create directory structure
      mkdir sale_approval
      # Extract files
      unzip _backups/sale_approval_backup_20260627_120000.zip -d sale_approval

6. **Reset file ownership and permissions** to ensure Odoo can access the restored files:

   .. code-block:: bash

      sudo chown -R odoo:odoo sale_approval
      sudo chmod -R 775 sale_approval

7. **Restart Odoo** to apply the rollback:

   .. code-block:: bash

      sudo systemctl restart odoo
