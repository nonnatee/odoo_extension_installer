Installation and Configuration Guide
=====================================

This document outlines the detailed system configurations required to deploy and run the Odoo Extension Installer module under various Linux service setups, virtual environments (venv), and behind reverse proxies (Nginx).

Filesystem Permissions
----------------------
Before configuring the installer, ensure that the Odoo server process (typically running under user ``odoo``) has read and write permissions on the target custom addons directory.

To grant write access, execute the following commands in your server terminal:

.. code-block:: bash

   # Change owner of target custom addons to odoo
   sudo chown -R odoo:odoo /opt/odoo/custom_addons
   
   # Set write permissions (owner read/write/execute, group read/write/execute, others read/execute)
   sudo chmod -R 775 /opt/odoo/custom_addons

Linux Systemd Service Setup
----------------------------
In standard Linux deployments, Odoo runs as a background service managed by ``systemd``. To enable the Odoo server to trigger its own restart programmatically, the system user running Odoo (``odoo``) must have permissions to run the systemctl restart command.

Because ``odoo`` is not a root user, you must grant sudo privilege *specifically* for the systemctl restart command in the sudoers file.

1. **Systemd Service File Template**:
   Ensure you have a systemd service file configured at ``/etc/systemd/system/odoo.service``. Here is a complete production template:

   .. code-block:: ini

      [Unit]
      Description=Odoo Open Source ERP
      Requires=postgresql.service
      After=network.target postgresql.service

      [Service]
      Type=simple
      PermissionsStartOnly=true
      User=odoo
      Group=odoo
      SyslogIdentifier=odoo
      ExecStart=/opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin -c /etc/odoo/odoo.conf
      StandardOutput=journal+console
      StandardError=journal+console
      Restart=always
      RestartSec=5s

      [Install]
      WantedBy=multi-user.target

2. **Configure Sudoers**:
   Open the sudoers configuration:

   .. code-block:: bash

      sudo visudo -f /etc/sudoers.d/odoo

   Add the following line to allow the ``odoo`` user to run the restart command without a password prompt:

   .. code-block:: text

      odoo ALL=INDEPENDENT_RESTART NOPASSWD: /bin/systemctl restart odoo
      # Note: If your system uses /usr/bin/systemctl instead of /bin/systemctl, adjust the path:
      # odoo ALL=NOPASSWD: /usr/bin/systemctl restart odoo

3. **Verify Sudoers Permissions (Bash Script)**:
   Create a verification script at ``/opt/odoo/bin/verify_restart.sh`` to test if the ``odoo`` user can restart the service without being prompted for a password:

   .. code-block:: bash

      #!/bin/bash
      # /opt/odoo/bin/verify_restart.sh
      
      echo "=== Testing sudoers configuration for Odoo restart ==="
      echo "Current user: $(whoami)"
      
      # Run systemctl command using sudo non-interactively (-n flag)
      sudo -n /bin/systemctl restart odoo > /dev/null 2>&1
      
      if [ $? -eq 0 ]; then
          echo "SUCCESS: The 'odoo' user can successfully restart Odoo without a password!"
      else
          echo "ERROR: The 'odoo' user cannot restart the service. Please verify: "
          echo "1. The path to systemctl (/bin/systemctl vs /usr/bin/systemctl)"
          echo "2. Sudoers file permissions and rules in /etc/sudoers.d/odoo"
          exit 1
      fi

   To run this verification script:

   .. code-block:: bash

      sudo chmod +x /opt/odoo/bin/verify_restart.sh
      sudo -u odoo -H /opt/odoo/bin/verify_restart.sh

4. **Web Configuration**:
   Open the Odoo web client, navigate to **Settings** -> **Extension Installer** and set the **Restart Command** to:

   .. code-block:: text

      sudo /bin/systemctl restart odoo

Python Virtual Environment (venv) Setup
---------------------------------------
If you are developing locally or running Odoo inside a Python virtual environment (venv) without systemd, you should run Odoo under a process manager like **Supervisord**.

1. **Supervisord Configuration File**:
   Create a Supervisord configuration file at ``/etc/supervisor/conf.d/odoo.conf``:

   .. code-block:: ini

      [program:odoo]
      command=/opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin -c /opt/odoo/odoo.conf
      directory=/opt/odoo
      user=odoo
      autostart=true
      autorestart=true
      startsecs=5
      stopwaitsecs=10
      stdout_logfile=/var/log/supervisor/odoo.log
      stderr_logfile=/var/log/supervisor/odoo.err.log

2. **Triggering Restart**:
   If Supervisord is configured with ``autorestart=true``, Odoo can restart simply by terminating its own PID. You can use the restart command configuration in Settings:

   .. code-block:: text

      kill -9 $PPID

   Or, you can allow the ``odoo`` user to run supervisorctl commands:

   .. code-block:: text

      supervisorctl restart odoo

Reverse Proxy (Nginx) Optimization
-----------------------------------
When Odoo restarts, the web socket and HTTP listeners will drop immediately. Any request made during the shutdown/startup sequence will result in Nginx serving a ``502 Bad Gateway`` error.

To ensure a smooth transition and rapid reconnection:

1. **Complete Nginx Site Configuration**:
   Open your Nginx configuration (e.g. ``/etc/nginx/sites-available/odoo``) and apply the following template:

   .. code-block:: nginx

      # Odoo upstream backend servers
      upstream odoobackend {
          server 127.0.0.1:8069;
      }
      upstream odoochat {
          server 127.0.0.1:8072;
      }

      server {
          listen 80;
          server_name odoo.example.com;

          # Log files
          access_log /var/log/nginx/odoo.access.log;
          error_log /var/log/nginx/odoo.error.log;

          # Increase max upload size for ZIP files
          client_max_body_size 100M;

          # WebSocket connection settings (Odoo longpolling)
          location /websocket {
              proxy_pass http://odoochat;
              proxy_set_header Upgrade $http_upgrade;
              proxy_set_header Connection "upgrade";
              proxy_set_header X-Forwarded-Host $host;
              proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
              proxy_set_header X-Forwarded-Proto $scheme;
              proxy_set_header X-Real-IP $remote_addr;
          }

          # Standard HTTP settings
          location / {
              proxy_pass http://odoobackend;
              proxy_redirect off;

              # Increase connection and read timeouts to prevent 504 Gateway Timeout during restarts
              proxy_connect_timeout 600s;
              proxy_read_timeout 600s;
              proxy_send_timeout 600s;
              
              # Buffer settings to handle large assets/JSON payloads
              proxy_buffers 16 64k;
              proxy_buffer_size 128k;
              proxy_busy_buffers_size 128k;
              
              # Forward headers
              proxy_set_header Host $host;
              proxy_set_header X-Real-IP $remote_addr;
              proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
              proxy_set_header X-Forwarded-Proto $scheme;
              proxy_set_header X-Forwarded-Host $host;
          }

          # Enable gzip compression to speed up load times
          gzip on;
          gzip_types text/css text/scss text/plain text/xml application/xml application/json application/javascript;
          gzip_min_length 1000;
      }

2. **Directives Explanation**:
   - ``client_max_body_size 100M``: Allows uploading third-party ZIP modules up to 100 MB.
   - ``proxy_read_timeout 600s``: Prevents Nginx from killing the connection early if Odoo takes some time to build database registry registries during module installation.
   - ``proxy_buffers``: Handles larger JSON responses returned by Odoo actions.
