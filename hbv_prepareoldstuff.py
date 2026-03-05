import netCDF4 as nc
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely.geometry
import os
def prepare_meteorological_and_landuse_data(shapefile_path, catchment_id_name, taso_id_of_interest, dinfo_path):
    """
    Processes meteorological and land-use data for a selected catchment.
    """

    # Read file paths from CSV file
    dinfo = pd.read_csv(dinfo_path)
    dinfo = dinfo.map(lambda x: str(x).strip() if isinstance(x, str) else x)

    precipitation_nc_file_path = dinfo['input_text']['precipitation_nc_file_path']
    evapotranspiration_nc_file_path = dinfo['input_text']['evapotranspiration_nc_file_path']
    temperature_nc_file_path = dinfo['input_text']['temperature_nc_file_path']
    output_csv_path = dinfo['input_text']['output_csv_path']

    print("\nReading from files:")
    print(shapefile_path)
    print(precipitation_nc_file_path)
    print(evapotranspiration_nc_file_path)
    print(temperature_nc_file_path)

    # Get year from precipitation file
    year = int(precipitation_nc_file_path.split('/')[-1].split('.')[0].split('_')[1])

    # Read shapefile
    basins_gdf = gpd.read_file(shapefile_path)
    basin_of_interest = basins_gdf[basins_gdf[catchment_id_name] == taso_id_of_interest].geometry.iloc[0]

    # Open NetCDF datasets
    precipitation_dataset = nc.Dataset(precipitation_nc_file_path)
    evapotranspiration_dataset = nc.Dataset(evapotranspiration_nc_file_path)
    temperature_dataset = nc.Dataset(temperature_nc_file_path)

    precipitation_var = precipitation_dataset.variables['RRday']
    evapotranspiration_var = evapotranspiration_dataset.variables['ET0']
    temperature_var = temperature_dataset.variables['Tday']
    latitudes = precipitation_dataset.variables['Lat'][:]
    longitudes = precipitation_dataset.variables['Lon'][:]

    # Create mask for basin
    mask = np.zeros((len(latitudes), len(longitudes)), dtype=bool)
    for i, lat in enumerate(latitudes):
        for j, lon in enumerate(longitudes):
            pt = shapely.geometry.Point(lon, lat)
            if basin_of_interest.contains(pt):
                mask[i, j] = True

    data = []
    et_time_variable = evapotranspiration_dataset.variables['Time']
    et_days_count = len(et_time_variable)
    num_days = precipitation_var.shape[0]

    for day_index in range(num_days):
        day_of_year = day_index + 1
        date = pd.Timestamp(year, 1, 1) + pd.Timedelta(days=day_of_year - 1)

        daily_precipitation = np.ma.array(precipitation_var[day_index], mask=~mask)
        mean_precipitation = np.ma.mean(daily_precipitation)

        daily_temperature = np.ma.array(temperature_var[day_index], mask=~mask)
        mean_temperature = np.ma.mean(daily_temperature)

        if 4 <= date.month <= 9:
            et_day_index = (date.month - 4) * 30 + (date.day - 1)
            mean_evapotranspiration = (
                np.ma.mean(np.ma.array(evapotranspiration_var[et_day_index], mask=~mask))
                if et_day_index < et_days_count else 0
            )
        else:
            mean_evapotranspiration = 0

        data.append([date.year, date.month, date.day, mean_precipitation, mean_temperature, mean_evapotranspiration])

    df = pd.DataFrame(data, columns=["Year", "Month", "Day", "Prec_mm/d", "Tair_oC", "Epot_mm/d"])
    df.to_csv(output_csv_path, index=False)
    print(f"\nMeteorological data exported successfully to {output_csv_path}")

    # --- LAND USE DATA PREPARATION ---
    crs = "EPSG:3067"
    urban_land_path = dinfo['input_text']['urban_land_path']
    agricultural_land_path = dinfo['input_text']['agricultural_land_path']
    csv_parameters_path = dinfo['input_text']['csv_parameters_path']

    print("\nProcessing land use data...")
    catchments = basins_gdf
    selected_catchment = catchments[catchments[catchment_id_name] == taso_id_of_interest].to_crs(crs)

    urban_land = gpd.read_file(urban_land_path).to_crs(crs)
    agricultural_land = gpd.read_file(agricultural_land_path).to_crs(crs)

    urban = gpd.clip(urban_land, selected_catchment)
    agri = gpd.clip(agricultural_land, selected_catchment)
    agri_no_urban = gpd.overlay(agri, urban, how="difference")

    urban["geometry"] = urban.buffer(0)
    agri_no_urban["geometry"] = agri_no_urban.buffer(0)

    urban_area = urban.area.sum()
    agricultural_area = agri_no_urban.area.sum()
    total_area = selected_catchment.area.sum()
    forest_area = max(total_area - (urban_area + agricultural_area), 0)

    urban_fraction = urban_area / total_area
    agricultural_fraction = agricultural_area / total_area
    forest_fraction = forest_area / total_area

    new_line = f"{agricultural_fraction:.2f},{forest_fraction:.2f},{urban_fraction:.2f},Land use fractions"
    df = pd.read_csv(csv_parameters_path, header=None)

    label_column_index = df.shape[1] - 1
    land_use_row = df[df[label_column_index] == "Land use fractions"]

    if not land_use_row.empty:
        df.loc[land_use_row.index[0]] = new_line.split(',')
    else:
        df.loc[len(df)] = new_line.split(',')

    df.to_csv(csv_parameters_path, header=False, index=False)
    abs_output_csv_path = os.path.abspath(output_csv_path)  # ✅ get full absolute path
    print(f"\nMeteorological data exported successfully to {abs_output_csv_path}")
    print(f"Updated or appended land use fractions in {csv_parameters_path}")
    return abs_output_csv_path