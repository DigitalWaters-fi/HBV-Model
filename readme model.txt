HBV model:

File 
hbv_S2S.py 
- contains the degree day snow model and hb- runoff models

Model parameters for three land use types are in text-file: 
hbv_para.csv
- the land use types are agricultural, forest and built (urban) areas
- contains snow model parameter values and runoff model parameter values
- last line contains shares of agricultureal, forest and urban areas

Model meteorological text-input 
met_input.csv
- contains daily time series of precipitation, air temperature, and potential evapotranspiration

Model produces 4 output text-files:
hbv_output_agric.csv
-  contains daily timeseries of water storages and simulated water fluxes in agricultural area
hbv_output_forest.csv
-  contains daily timeseries of water storages and simulated water fluxes in forested area
hbv_output_urban.csv
-  contains daily timeseries of water storages and simulated water fluxes in urban area
hbv_output_totalrunoff.csv
- total runoff file contains daoly timeseries of catchment outflow and outflow components from three different land use areas




https://wwwd3.ymparisto.fi/d3/gis_data/spesific/valumaalueet.zip

https://wwwd3.ymparisto.fi/d3/gis_data/spesific/valumaalueet.zip


https://copernicus-dem-90m.s3.amazonaws.com/Copernicus_DSM_COG_30_N65_00_E026_00_DEM/Copernicus_DSM_COG_30_N65_00_E026_00_DEM.tif
https://copernicus-dem-90m.s3.amazonaws.com/Copernicus_DSM_COG_30_N65_00_E025_00_DEM/Copernicus_DSM_COG_30_N65_00_E025_00_DEM.tif


https://wwwd3.ymparisto.fi/d3/gis_data/spesific/maatalousmaa2021.zip








# ── Startup log ───────────────────────────────────────────────────────────
log(f'HBV Dashboard ready | Python {sys.version.split()[0]} | '
    f'CPUs detected: {_max_cpu} | '
    f'mpirun: {_MPIRUN or "NOT FOUND — install OpenMPI in Docker"}', 'ok')
------------------


---------------------------------------------------------------------------
NameError                                 Traceback (most recent call last)
Cell In[1], line 1786
   1731 # ── Left panel ────────────────────────────────────────────────────────────
   1732 input_tab = widgets.VBox([
   1733 
   1734     widgets.HTML('<h3>Step 1 — Location &amp; Catchment</h3>'),
   (...)   1783 
   1784 ], layout=widgets.Layout(padding='16px'))
-> 1786 left_tabs = widgets.Tab(children=[input_tab, custom_catchment_tab])
   1787 left_tabs.set_title(0, 'Input')
   1788 left_tabs.set_title(0, 'Custom Catchment')

NameError: name 'custom_catchment_tab' is not defined

[Voila] Adapting from protocol version 5.3 (kernel f7cccc34-94ff-4dc4-ba33-9dd8e5016cbd) to 5.4 (client).
[Voila] Connecting to kernel f7cccc34-94ff-4dc4-ba33-9dd8e5016cbd.
The websocket_ping_timeout (90000) cannot be longer than the websocket_ping_interval (30000).
Setting websocket_ping_timeout=30000
404 GET /api/kernels/4cd8ae73-7236-45a9-9c54-aaf7986e8b75?1780911705455 (::1): Kernel does not exist: 4cd8ae73-7236-45a9-9c54-aaf7986e8b75
[Voila] WARNING | wrote error: 'Kernel does not exist: 4cd8ae73-7236-45a9-9c54-aaf7986e8b75'
Traceback (most recent call last):
  File "/Users/mujaved21/Desktop/WE3Unit/HBV-MODEL/venv/lib/python3.14/site-packages/tornado/web.py", line 1859, in _execute
    result = await result
             ^^^^^^^^^^^^
  File "/Users/mujaved21/Desktop/WE3Unit/HBV-MODEL/venv/lib/python3.14/site-packages/j