# ─── Base image ───────────────────────────────────────────────────────────────
# jupyter/scipy-notebook gives us Python 3.11, JupyterLab, conda, and common
# scientific libs already installed. We build on top of it.
FROM quay.io/jupyter/scipy-notebook:python-3.11

# Switch to root to install system dependencies
USER root

# GDAL and geospatial system libs needed by geopandas / fiona
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    gdal-bin \
    libproj-dev \
    libgeos-dev \
    libnetcdf-dev \
    libhdf5-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Switch back to the default notebook user
USER ${NB_UID}

# ─── Python dependencies ──────────────────────────────────────────────────────
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ─── Copy HBV model files ─────────────────────────────────────────────────────
# All model files go into the jovyan home so they're on sys.path by default
USER root
COPY hbv_prepare.py      /home/jovyan/hbv_prepare.py
COPY hbv_S2S.py          /home/jovyan/hbv_S2S.py
COPY hbv_dashboard.ipynb /home/jovyan/hbv_dashboard.ipynb

# Fix ownership so jovyan can read/execute, and set permissions as root
RUN chown ${NB_UID}:${NB_GID} \
        /home/jovyan/hbv_prepare.py \
        /home/jovyan/hbv_S2S.py \
        /home/jovyan/hbv_dashboard.ipynb \
    && chmod 644 \
        /home/jovyan/hbv_prepare.py \
        /home/jovyan/hbv_S2S.py \
        /home/jovyan/hbv_dashboard.ipynb

# ─── Voilà config ─────────────────────────────────────────────────────────────
RUN mkdir -p /home/jovyan/.jupyter
COPY voila_config.py /home/jovyan/.jupyter/jupyter_config.py
RUN chown ${NB_UID}:${NB_GID} /home/jovyan/.jupyter/jupyter_config.py

# Switch back to notebook user for runtime
USER ${NB_UID}

# ─── Set working directory ────────────────────────────────────────────────────
WORKDIR /home/jovyan

CMD ["voila", "--no-browser", "--port=8888", "--Voila.ip=0.0.0.0", "--base_url=/", "hbv_dashboard.ipynb"]