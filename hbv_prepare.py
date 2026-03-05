import netCDF4 as nc
import numpy as np
import pandas as pd
import geopandas as gpd
import shapely.geometry
import os


def prepare_meteorological_and_landuse_data(shapefile_path, catchment_id_name, taso_id_of_interest, dinfo_path):
    """
    Original function — reads paths from predata.csv.
    Kept for backward compatibility.
    """
    rows = []
    with open(dinfo_path) as f:
        for line in f:
            line = line.strip()
            if not line or line == 'input_text':
                continue
            parts = line.split(',', 1)
            if len(parts) == 2:
                rows.append((parts[0].strip(), parts[1].strip()))
    cfg = dict(rows)

    return prepare_meteorological_and_landuse_data_direct(
        shapefile_path=shapefile_path,
        catchment_id_name=catchment_id_name,
        taso_id_of_interest=taso_id_of_interest,
        precipitation_nc=cfg['precipitation_nc_file_path'],
        evapotranspiration_nc=cfg['evapotranspiration_nc_file_path'],
        temperature_nc=cfg['temperature_nc_file_path'],
        output_csv_path=cfg['output_csv_path'],
        urban_land_path=cfg['urban_land_path'],
        agricultural_land_path=cfg['agricultural_land_path'],
        csv_parameters_path=cfg['csv_parameters_path'],
    )


def prepare_meteorological_and_landuse_data_direct(
    shapefile_path,
    catchment_id_name,
    taso_id_of_interest,
    precipitation_nc,
    evapotranspiration_nc,
    temperature_nc,
    output_csv_path,
    urban_land_path,
    agricultural_land_path,
    csv_parameters_path,
):
    """
    Direct version — all paths passed as arguments, no predata.csv needed.
    """
    print("\nReading from files:")
    print(f"  Shapefile:          {shapefile_path}")
    print(f"  Precipitation NC:   {precipitation_nc}")
    print(f"  Evapotranspiration: {evapotranspiration_nc}")
    print(f"  Temperature NC:     {temperature_nc}")

    # Get year from precipitation filename
    year = int(precipitation_nc.split('/')[-1].split('.')[0].split('_')[1])
    print(f"  Year detected:      {year}")

    # Read shapefile
    basins_gdf = gpd.read_file(shapefile_path)
    match = basins_gdf[basins_gdf[catchment_id_name] == taso_id_of_interest]
    if match.empty:
        raise ValueError(f"Catchment ID {taso_id_of_interest} not found in column '{catchment_id_name}'")
    basin_of_interest = match.geometry.iloc[0]

    # Open NetCDF datasets
    precipitation_dataset     = nc.Dataset(precipitation_nc)
    evapotranspiration_dataset = nc.Dataset(evapotranspiration_nc)
    temperature_dataset       = nc.Dataset(temperature_nc)

    precipitation_var     = precipitation_dataset.variables['RRday']
    evapotranspiration_var = evapotranspiration_dataset.variables['ET0']
    temperature_var       = temperature_dataset.variables['Tday']
    latitudes  = precipitation_dataset.variables['Lat'][:]
    longitudes = precipitation_dataset.variables['Lon'][:]

    # Build spatial mask
    mask = np.zeros((len(latitudes), len(longitudes)), dtype=bool)
    for i, lat in enumerate(latitudes):
        for j, lon in enumerate(longitudes):
            pt = shapely.geometry.Point(lon, lat)
            if basin_of_interest.contains(pt):
                mask[i, j] = True

    et_days_count = len(evapotranspiration_dataset.variables['Time'])
    num_days = precipitation_var.shape[0]
    print(f"\n  Processing {num_days} days...")

    data = []
    for day_index in range(num_days):
        date = pd.Timestamp(year, 1, 1) + pd.Timedelta(days=day_index)

        daily_precip = np.ma.array(precipitation_var[day_index], mask=~mask)
        mean_precip  = float(np.ma.mean(daily_precip))

        daily_temp  = np.ma.array(temperature_var[day_index], mask=~mask)
        mean_temp   = float(np.ma.mean(daily_temp))

        if 4 <= date.month <= 9:
            et_idx = (date.month - 4) * 30 + (date.day - 1)
            mean_et = float(np.ma.mean(np.ma.array(evapotranspiration_var[et_idx], mask=~mask))) \
                      if et_idx < et_days_count else 0.0
        else:
            mean_et = 0.0

        data.append([date.year, date.month, date.day, mean_precip, mean_temp, mean_et])

    df = pd.DataFrame(data, columns=["Year", "Month", "Day", "Prec_mm/d", "Tair_oC", "Epot_mm/d"])
    df.to_csv(output_csv_path, index=False)
    print(f"  Meteorological data exported to: {output_csv_path}")

    # ── Land use ──────────────────────────────────────────────────────────
    crs = "EPSG:3067"
    print("\nProcessing land use data...")

    selected_catchment = basins_gdf[
        basins_gdf[catchment_id_name] == taso_id_of_interest
    ].to_crs(crs)

    urban_land       = gpd.read_file(urban_land_path).to_crs(crs)
    agricultural_land = gpd.read_file(agricultural_land_path).to_crs(crs)

    urban = gpd.clip(urban_land, selected_catchment)
    agri  = gpd.clip(agricultural_land, selected_catchment)

    if urban.empty:
        print("  ⚠️  No urban land found in catchment — fraction set to 0")
    else:
        urban["geometry"] = urban.buffer(0)

    if agri.empty:
        print("  ⚠️  No agricultural land found in catchment — fraction set to 0")
        agri_no_urban = gpd.GeoDataFrame(geometry=[], crs=crs)
    else:
        if urban.empty:
            agri_no_urban = agri.copy()
        else:
            agri_no_urban = gpd.overlay(agri, urban, how="difference")
            if agri_no_urban.empty:
                print("  ⚠️  Agricultural area fully covered by urban — fraction set to 0")
        if not agri_no_urban.empty:
            agri_no_urban["geometry"] = agri_no_urban.buffer(0)

    total_area       = float(selected_catchment.area.sum())
    urban_area       = float(urban.area.sum())       if not urban.empty       else 0.0
    agricultural_area = float(agri_no_urban.area.sum()) if not agri_no_urban.empty else 0.0
    forest_area      = max(total_area - (urban_area + agricultural_area), 0.0)

    urban_fraction        = urban_area / total_area        if total_area > 0 else 0.0
    agricultural_fraction = agricultural_area / total_area if total_area > 0 else 0.0
    forest_fraction       = forest_area / total_area       if total_area > 0 else 0.0

    print(f"  Urban fraction:        {urban_fraction:.3f}")
    print(f"  Agricultural fraction: {agricultural_fraction:.3f}")
    print(f"  Forest fraction:       {forest_fraction:.3f}")

    # Write land use fractions to hbv_para.csv
    new_line = f"{agricultural_fraction:.2f},{forest_fraction:.2f},{urban_fraction:.2f},Land use fractions"
    df_para  = pd.read_csv(csv_parameters_path, header=None)
    label_col = df_para.shape[1] - 1
    land_use_row = df_para[df_para[label_col] == "Land use fractions"]

    if not land_use_row.empty:
        df_para.loc[land_use_row.index[0]] = new_line.split(',')
    else:
        df_para.loc[len(df_para)] = new_line.split(',')

    df_para.to_csv(csv_parameters_path, header=False, index=False)
    print(f"  Land use written to: {csv_parameters_path}")

    abs_path = os.path.abspath(output_csv_path)
    print(f"\n✅ hbv_prepare complete. Met CSV: {abs_path}")
    return abs_path
