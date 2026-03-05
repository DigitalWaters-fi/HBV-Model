import os
import base64
import zipfile
import tempfile
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from hbv_prepare import prepare_meteorological_and_landuse_data
from hbv_S2S import run_hbv_model

import dash
from dash import dcc, html, Input, Output, State
import dash_leaflet as dl
import dash_leaflet.express as dlx
import plotly.express as px

# --- Initialize Dash app ---
app = dash.Dash(__name__)

app.layout = html.Div([
    html.H2("HBV Catchment Visualization and Model"),
    
    html.H4("1. Paste Shapefile Link (.zip or .shp)"),
    dcc.Input(id='shapefile-url', type='text', placeholder='Paste shapefile link here', style={'width':'60%'}),
    html.Button("Download & Load", id='download-button'),
    
    html.H4("2. Select Catchment on Map"),
    dl.Map(id='catchment-map', style={'width': '100%', 'height': '500px'}, center=[0,0], zoom=2, children=[dl.TileLayer()]),
    html.Div(id='selected-catchment', style={'marginTop':'10px'}),
    
    html.H4("3. Upload predata.csv for HBV preparation"),
    dcc.Upload(id='upload-predata', children=html.Button('Upload CSV')),
    
    html.H4("4. Select HBV Output File"),
    dcc.Dropdown(id='output-dropdown', placeholder="Select HBV output"),
    
    html.H4("5. Select Column to Aggregate"),
    dcc.Dropdown(id='column-dropdown', placeholder="Select numeric column"),
    
    html.H4("6. Aggregation Choice"),
    dcc.RadioItems(id='agg-choice', options=[{'label':'Sum','value':'sum'}, {'label':'Mean','value':'mean'}], value='sum'),
    
    html.H4("7. Aggregated Interactive Map"),
    dcc.Graph(id='aggregated-map')
])

# --- Global variables ---
gdf_global = None
selected_catchment_id = None
id_col = None
hbv_outputs = {}
selected_column_df = None

# --- Download and load shapefile from URL ---
@app.callback(
    Output('catchment-map', 'children'),
    Input('download-button', 'n_clicks'),
    State('shapefile-url', 'value')
)
def download_and_load_shapefile(n_clicks, url):
    global gdf_global, id_col
    if n_clicks is None or not url:
        return [dl.TileLayer()]
    
    temp_dir = tempfile.gettempdir()
    filename = os.path.basename(url)
    file_path = os.path.join(temp_dir, filename)
    
    # Download file
    response = requests.get(url)
    with open(file_path, 'wb') as f:
        f.write(response.content)
    
    # If ZIP → extract
    if filename.endswith('.zip'):
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        shp_files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.endswith('.shp')]
        shapefile_path = shp_files[0]
    elif filename.endswith('.shp'):
        shapefile_path = file_path
    else:
        return [dl.TileLayer()]
    
    # Load shapefile
    gdf_global = gpd.read_file(shapefile_path).to_crs(epsg=4326)
    
    # Detect id column
    id_col = next((c for c in gdf_global.columns if c.lower().endswith('_id')), gdf_global.columns[0])
    
    # Create geojson
    geojson = dlx.geojson_to_geobuf(dlx.dicts_to_geojson([{
        "geometry": g.geometry.__geo_interface__,
        "properties": {id_col: g[id_col]}
    } for _, g in gdf_global.iterrows()]))
    
    geojson_layer = dl.GeoJSON(data=geojson, id='geojson', zoomToBounds=True,
                               options=dict(style=dict(weight=2, color='blue', fillOpacity=0.4)))
    
    return [dl.TileLayer(), geojson_layer]

# --- Catchment click selection ---
@app.callback(
    Output('selected-catchment', 'children'),
    Input('geojson', 'click_feature')
)
def select_catchment(feature):
    global selected_catchment_id
    if feature is None:
        return "No catchment selected"
    selected_catchment_id = feature['properties'][id_col]
    return f"Selected Catchment ID: {selected_catchment_id}"

# --- HBV output dropdown population ---
@app.callback(
    Output('output-dropdown', 'options'),
    Input('upload-predata', 'contents'),
    State('upload-predata', 'filename')
)
def prepare_hbv(contents, filename):
    global hbv_outputs, selected_catchment_id, id_col
    if contents is None or selected_catchment_id is None:
        return []
    
    # Save predata.csv
    temp_dir = tempfile.gettempdir()
    predata_path = os.path.join(temp_dir, filename)
    content_type, content_string = contents.split(',')
    with open(predata_path, "wb") as f:
        f.write(base64.b64decode(content_string))
    
    # Prepare meteorological data
    output_csv_path = prepare_meteorological_and_landuse_data(
        shapefile_path=None,  # Using global gdf
        catchment_id_name=id_col,
        taso_id_of_interest=selected_catchment_id,
        dinfo_path=predata_path
    )
    
    # Run HBV model
    hbv_outputs = run_hbv_model(output_csv_path)
    
    options = [{'label': k, 'value': k} for k in hbv_outputs.keys()]
    return options

# --- Populate column dropdown based on selected output ---
@app.callback(
    Output('column-dropdown', 'options'),
    Input('output-dropdown', 'value')
)
def populate_columns(selected_key):
    global hbv_outputs
    if selected_key is None:
        return []
    df = pd.read_csv(hbv_outputs[selected_key])
    numeric_cols = df.select_dtypes(include='number').columns
    return [{'label': c, 'value': c} for c in numeric_cols]

# --- Aggregation and interactive map ---
@app.callback(
    Output('aggregated-map', 'figure'),
    Input('agg-choice', 'value'),
    Input('column-dropdown', 'value'),
    Input('output-dropdown', 'value')
)
def plot_aggregated_map(agg_choice, selected_col, selected_output):
    global gdf_global, selected_catchment_id, hbv_outputs, id_col
    if gdf_global is None or selected_catchment_id is None or selected_col is None or selected_output is None:
        return px.choropleth_mapbox()
    
    df = pd.read_csv(hbv_outputs[selected_output])
    total_value = df[selected_col].sum() if agg_choice == 'sum' else df[selected_col].mean()
    
    gdf_global['selected_value'] = 0
    gdf_global.loc[gdf_global[id_col] == selected_catchment_id, 'selected_value'] = total_value
    
    fig = px.choropleth_mapbox(
        gdf_global,
        geojson=gdf_global.geometry,
        locations=gdf_global.index,
        color='selected_value',
        hover_name=id_col,
        color_continuous_scale="Blues",
        mapbox_style="carto-positron",
        zoom=9,
        center={"lat": gdf_global.geometry.centroid.y.mean(),
                "lon": gdf_global.geometry.centroid.x.mean()},
        opacity=0.6
    )
    fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
    return fig

# --- Run Dash app ---
if __name__ == '__main__':
    app.run(debug=True)
