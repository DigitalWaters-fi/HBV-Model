#!/bin/bash
# Runs before Jupyter starts. Copies dashboard files from /opt/hbv into
# the user's home dir so they survive the JupyterHub PVC home-dir mount.
set -e

cp -f  /opt/hbv/hbv_dashboard_app.ipynb "${HOME}/hbv_dashboard_app.ipynb"
cp -rf /opt/hbv/dashboard_utils          "${HOME}/dashboard_utils"

mkdir -p "${HOME}/.jupyter"
printf 'c.ServerApp.default_url = "/voila/render/hbv_dashboard_app.ipynb"\n' \
    > "${HOME}/.jupyter/jupyter_server_config.py"

echo "[hbv-start] Dashboard files copied to ${HOME}"
