# Makes JupyterHub open Voila dashboard directly on server start
# No JupyterLab, no file browser — just the HBV dashboard

c.ServerApp.default_url = '/voila/render/hbv_dashboard.ipynb'
c.ServerApp.open_browser = False
c.ServerApp.token = ''
c.ServerApp.password = ''