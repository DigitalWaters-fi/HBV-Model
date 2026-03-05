import os
import requests
import zipfile
import tempfile
import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Point
from hbv_prepare import prepare_meteorological_and_landuse_data
from hbv_S2S import run_hbv_model  # import HBV function
import pandas as pd


def download_and_extract_shapefile():
    url = input("Paste the shapefile link (.zip or .shp): ").strip()
    temp_dir = tempfile.gettempdir()

    # If it's a ZIP file → download and extract
    if url.endswith(".zip"):
        zip_path = os.path.join(temp_dir, os.path.basename(url))
        print("Downloading shapefile ZIP...")
        response = requests.get(url)
        with open(zip_path, "wb") as f:
            f.write(response.content)
        print("Extracting ZIP...")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)
        print(f"Extracted to: {temp_dir}")

    elif url.endswith(".shp"):
        print("Using direct shapefile link...")
    else:
        raise ValueError("Please provide a valid .zip or .shp link.")

    # Find .shp files
    shapefiles = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.endswith(".shp")]
    if not shapefiles:
        raise FileNotFoundError("No shapefiles found in the extracted contents.")

    print("\nAvailable shapefiles:")
    for i, shp in enumerate(shapefiles, start=1):
        print(f"{i}: {os.path.basename(shp)}")

    selected_idx = int(input("\nEnter the number of the shapefile to use: ")) - 1
    selected_shapefile = shapefiles[selected_idx]
    print(f"Selected shapefile: {selected_shapefile}")

    return selected_shapefile


def plot_and_select_catchment(shapefile_path):
    gdf = gpd.read_file(shapefile_path)
    id_col = next((col for col in gdf.columns if col.lower().endswith("_id")), None)
    if id_col is None:
        raise ValueError("No column ending with '_id' found in shapefile.")

    print(f"Using '{id_col}' as the ID column for catchments.")
    fig, ax = plt.subplots(figsize=(8, 8))
    gdf.plot(ax=ax, color="lightblue", edgecolor="black")
    plt.title("Click a catchment to select it")

    selected_id = {"value": None}

    def onclick(event):
        if event.button != 1 or event.dblclick:
            return
        if event.xdata is None or event.ydata is None:
            return

        click_point = Point(event.xdata, event.ydata)
        selected = gdf[gdf.geometry.contains(click_point)]

        if selected.empty:
            distances = gdf.geometry.distance(click_point)
            min_idx = distances.idxmin()
            selected = gdf.loc[[min_idx]]

        catchment_id = selected[id_col].values[0]
        selected_id["value"] = catchment_id
        print(f"Clicked catchment ID: {catchment_id}")

    fig.canvas.mpl_connect('button_press_event', onclick)
    plt.show()

    return id_col, selected_id["value"]


def main():
    shapefile_path = download_and_extract_shapefile()
    id_col, selected_catchment_id = plot_and_select_catchment(shapefile_path)

    if selected_catchment_id is None:
        print("No catchment selected.")
        return

    print(f"\nRunning HBV preparation for catchment ID: {selected_catchment_id}")
    dinfo_path = input("Enter path to 'predata.csv' file: ").strip()

    output_csv_path = prepare_meteorological_and_landuse_data(
        shapefile_path=shapefile_path,
        catchment_id_name=id_col,
        taso_id_of_interest=selected_catchment_id,
        dinfo_path=dinfo_path
    )
    print(f"\nMeteorological data file created at: {output_csv_path}")
    print("\nRunning HBV model using generated meteorological data...")
    output_files = run_hbv_model(output_csv_path)
    print("\nHBV model outputs:")
    for idx, (key, path) in enumerate(output_files.items(), start=1):
        print(f"{idx}: {key} → {path}")

    # Let user choose a file
    choice = int(input("\nEnter the number of the file you want to preview: "))
    keys_list = list(output_files.keys())
    selected_key = keys_list[choice - 1]
    selected_path = output_files[selected_key]
    print(f"\nYou selected '{selected_key}' at path: {selected_path}")

    # Read CSV dynamically
    df = pd.read_csv(selected_path)
    print("\nFirst 10 lines of the file:")
    print(df.head(10))
# Aggregate total runoff (sum over time)
    if 'totalrunoff mm' not in df.columns:
        raise ValueError("CSV file does not contain 'totalrunoff mm' column.")
    total_runoff = df['totalrunoff mm'].sum()
    print(f"\nTotal runoff for selected catchment: {total_runoff} mm")

    # Load shapefile
    gdf = gpd.read_file(shapefile_path)

    # Add total runoff column to all catchments (0 for others)
    gdf['total_runoff'] = 0.0
    gdf.loc[gdf[id_col] == selected_catchment_id, 'total_runoff'] = total_runoff

    # Plot choropleth using a single call (cleaner and scalable)
    fig, ax = plt.subplots(1, 1, figsize=(8, 8))
    gdf.plot(
        ax=ax,
        column='total_runoff',
        cmap='Blues',
        legend=True,
        edgecolor='black',
        missing_kwds={"color": "lightgrey"}  # catchments with 0 stay light grey
    )
    plt.title(f"Total Runoff for Catchment ID {selected_catchment_id}")
    plt.show()


if __name__ == "__main__":
    main()