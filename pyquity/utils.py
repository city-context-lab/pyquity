import osmnx as ox
import geopandas as gpd

# Average speeds by mode (m/s)
SPEED = {
    'walk': 5 * 1000 / 3600,
    'bike': 20 * 1000 / 3600,
    'transfer': 5 * 1000 / 3600,
    'transit': 22 * 1000 / 3600
}

def route_length_by_mode(G, route, verbose: bool = True):
    # Convert route to GeoDataFrame and project to metric CRS
    gdf = ox.routing.route_to_gdf(G, route)
    gdf = gdf.to_crs(epsg=3857)

    # Calculate total distance by mode (km)
    distance = gdf.groupby('mode')['length'].sum() / 1000
    distance = round(distance, 2).to_dict()

    # Calculate travel time by mode (minutes)
    travel_time = {}
    for mode, dist_km in distance.items():
        if mode in SPEED:
            time_sec = (dist_km * 1000) / SPEED[mode]
            travel_time[mode] = round(time_sec / 60, 2)

    return distance, travel_time