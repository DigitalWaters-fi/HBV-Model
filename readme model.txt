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