import osmnx as ox
import numpy as np
import pandas as pd
import networkx as nx
import geopandas as gpd
import partridge as ptg
from shapely import ops as sops
from scipy.spatial import cKDTree
from geopy.distance import distance
from shapely.geometry import Point, Polygon, LineString

SPEED = {
    'walk': 5 * 1000 / 3600,
    'bike': 20 * 1000 / 3600,
    'transfer': 5 * 1000 / 3600,
    'transit': 22 * 1000 / 3600
}

def multimodal_graph(G_osm: nx.MultiDiGraph, G_gtfs: nx.MultiDiGraph, k: int=1):
    # Relabel GTFS nodes with unique integers to avoid ID collisions with OSM graph
    G_gtfs = nx.relabel_nodes(G_gtfs, {node: i for i, node in enumerate(G_gtfs.nodes())}, copy=True)

    # Get OSM node coordinates
    osm_nodes, _ = ox.graph_to_gdfs(G_osm)
    osm_coords = np.array(list(zip(osm_nodes["y"], osm_nodes["x"])))

    # Get GTFS stop coordinates
    gtfs_nodes = [(n, data["x"], data["y"]) for n, data in G_gtfs.nodes(data=True)]
    gtfs_coords = np.array([(y, x) for _, x, y in gtfs_nodes])

    # Build KD-tree for nearest-neighbor search
    tree = cKDTree(osm_coords)

     # Combine OSM and GTFS graphs
    G = nx.compose(G_osm, G_gtfs)

    # Connect each GTFS stop to its nearest OSM node(s)
    for (stop_id, x, y), (dist, idx) in zip(gtfs_nodes, zip(*tree.query(gtfs_coords, k=k))):
        osm_node = osm_nodes.iloc[idx].name
        point_u = (y, x)
        point_v = (osm_nodes.iloc[idx].y, osm_nodes.iloc[idx].x)

        length = distance(point_u, point_v).m
        travel_time = length / SPEED['transfer'] / 60
        G.add_edge(stop_id, osm_node, mode="transfer", length=length, travel_time=travel_time)
        G.add_edge(osm_node, stop_id, mode="transfer", length=length, travel_time=travel_time)

    # Set the graph's CRS to WGS84 (EPSG:4326)
    if G.graph.get('crs') is not None:
        G.graph["crs"] = "EPSG:4326"

    # Return the graph
    return G

def graph_from_gtfs(gtfs: str) -> nx.MultiDiGraph:
    # Read available service dates
    date = ptg.read_service_ids_by_date(gtfs)
    if not date:
        raise ValueError("No valid service date found in GTFS.")

    # Select the first available service date
    target_date = sorted(date.keys())[0]
    feed = ptg.load_geo_feed(gtfs, view={'trips.txt': {'service_id': date[target_date]}, 'shapes.txt': {}})

    # Extract GTFS tables
    stop_times = feed.stop_times
    trips = feed.trips
    stops = feed.stops
    shapes = feed.shapes

    # Initialize a multidirected graph
    G = nx.MultiDiGraph()

    # Add each transit stop as a node in the graph
    for _, row in stops.iterrows():
        G.add_node(row['stop_id'], name=row['stop_name'], x=row['geometry'].x, y=row['geometry'].y)

    # Ensure all shape geometries are LineString
    shapes['geometry'] = shapes['geometry'].apply( lambda geoms: geoms if isinstance(geoms, LineString) else LineString(geoms))
    shapes = shapes.set_index('shape_id').geometry

    # Create edges from trips, grouped by shape_id
    for shape_id, group in trips.groupby('shape_id'):
        if shape_id not in shapes.index or shapes[shape_id] is None:
            continue
        geoms = shapes[shape_id]

        # Take the first trip in the group as representative
        trip_id = group.iloc[0]['trip_id']

        # Get the stop sequence for the trip
        stop_sequence = stop_times[stop_times.trip_id == trip_id].sort_values('stop_sequence')
        stop_id = stop_sequence['stop_id'].tolist()

        # Add edges between consecutive stops
        for i in range(len(stop_id) - 1):
            u, v = stop_id[i], stop_id[i + 1]

            # Retrieve the coordinates of the two stops
            point_u = stops.loc[stops.stop_id == u, 'geometry'].values[0]
            point_v = stops.loc[stops.stop_id == v, 'geometry'].values[0]
            length = distance((point_u.y, point_u.x), (point_v.y, point_v.x)).m
            travel_time = length / SPEED['transit'] / 60

            # Get geometry for the edge
            try:
                orig = geoms.project(point_u)
                dest = geoms.project(point_v)
                low, high = sorted([orig, dest])
                segment = sops.substring(geoms, low, high, normalized=False)
                if segment.is_empty or segment.length == 0:
                    segment = LineString([point_u, point_v])
            except:
                segment = LineString([point_u, point_v])

            # Add edge only if it does not already exist, and add geometry
            if not G.has_edge(u, v, key=trip_id):
                G.add_edge(
                    u, v,
                    trip_id=trip_id,
                    geometry=segment,
                    length=length,
                    mode='transit',
                    travel_time=travel_time
                )

    # Set the graph's CRS based on the stops' coordinates
    if stops.estimate_utm_crs() is not None:
        G.graph['crs'] = stops.estimate_utm_crs()
    else:
        G.graph['crs'] = "EPSG:4326"

    # Return the graph
    return G

def graph_from_place(place_name: str, network_type: str):
    # Return a graph from OSMnx
    G = ox.graph_from_place(place_name, network_type=network_type)

    # Add mode to each edge in the graph
    for u, v, k, data in G.edges(keys=True, data=True):
        data['mode'] = network_type
        data['travel_time'] = data['length'] / SPEED[network_type] / 60
    
    # Set the graph's CRS to WGS84 (EPSG:4326)
    if G.graph.get('crs') is not None:
        G.graph['crs'] = "EPSG:4326"

    return G

def grid_from_place(place_name: str, grid_size: float) -> gpd.GeoDataFrame:
    # Read boundary from OpenStreetMap(OSM)
    boundary = ox.geocode_to_gdf(place_name)

    # Project the boundary to a metric CRS (UTM) for accurate grid creation
    utm = boundary.estimate_utm_crs()
    boundary = boundary.to_crs(utm)
    
    minx, miny, maxx, maxy = boundary.total_bounds

    # Initialize a grid and Add into GeoDataFrame 
    polygons = [Polygon([(x, y), (x + grid_size, y), (x + grid_size, y + grid_size), (x, y + grid_size)]) for x in np.arange(minx, maxx, grid_size) for y in np.arange(miny, maxy, grid_size)]
    gdf = gpd.GeoDataFrame(geometry=polygons, crs=boundary.crs)
    grid = gpd.overlay(gdf, boundary, how='intersection')

    # Reproject the grid back to WGS84 (EPSG:4326) and return it
    return grid.to_crs(epsg=4326)

def amenity_from_place(place_name: str, amenity_type: list) -> gpd.GeoDataFrame:
    if isinstance(amenity_type, str):
        amenity_type = [amenity_type]

    # Define categories of amenities with their corresponding OSM tags
    amenities = {
        'education': ['college', 'dancing_school', 'driving_school', 'first_aid_school', 'kindergarten', 'language_school', 'library', 'surf_school', 'toy_library', 'research_institute', 'training', 'music_school', 'school', 'traffic_park', 'university'],
        'financial': ['atm', 'bank', 'bureau_de_change'],
        'healthcare': ['baby_hatch', 'clinic', 'dentist', 'doctors', 'hospital', 'nursing_home', 'pharmacy', 'social_facility', 'veterinary' ],
        'all': ['college', 'dancing_school', 'driving_school', 'first_aid_school', 'kindergarten', 'language_school', 'library', 'surf_school', 'toy_library', 'research_institute', 'training', 'music_school', 'school', 'traffic_park', 'university', 'atm', 'bank', 'bureau_de_change', 'baby_hatch', 'clinic', 'dentist', 'doctors', 'hospital', 'nursing_home', 'pharmacy', 'social_facility', 'veterinary'] 
        }
    
    # Get the list of amenity tags for the selected amenity type
    amenity = []
    
    for item in amenity_type:
        amenity.extend(amenities[item.lower()])


    # Query OpenStreetMap for features matching the selected amenity tags within the specified place
    gdf = ox.features.features_from_place(place_name, tags={'amenity': amenity})

    if gdf.crs is None:
        gdf = gdf.to_crs(epsg=4326)
    # Return the resulting GeoDataFrame
    return gdf

def amenity_in_grid(grid: gpd.GeoDataFrame, amenity: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    # Reproject amenities to UTM and convert geometry to centroids (points)
    amenity = amenity.to_crs(amenity.estimate_utm_crs())
    amenity['geometry'] = amenity.geometry.centroid

    # Reproject grid to UTM
    grid = grid.to_crs(grid.estimate_utm_crs())

    # Ensure both layers have the same CRS before spatial operations
    if grid.crs == amenity.crs:
        grid['amenity_count'] = 0 # Initialize 'amenity_count' column in the grid

        # Count amenities within each grid cell
        for index, x in grid.iterrows():
            for _, y in amenity.iterrows():
                if x.geometry.contains(y.geometry): 
                    grid.at[index, 'amenity_count'] += 1
    
    # Reproject the grid back to WGS84 (EPSG:4326) and return it
    if grid.crs is not None:
        grid = grid.to_crs(epsg=4326)

    return grid

def micromobility_in_grid(grid: gpd.GeoDataFrame, micromobility_size: int, alpha: float = 1.0) -> gpd.GeoDataFrame:
    # If amenity counts are not present, initialize micromobility counts and return zeros
    if 'amenity_count' not in grid.columns:
        grid['micromobility_count'] = 0
        return grid

    # Prepare counts and ensure numeric
    counts = grid['amenity_count'].fillna(0).astype(float)

    # Compute weights: raise counts to the power of alpha to control emphasis
    weights = counts ** alpha

    total_weight = weights.sum()
    # If there are no amenities at all, assign zero everywhere
    if total_weight == 0 or micromobility_size <= 0:
        grid['micromobility_count'] = 0
        return grid

    # Normalize weights to form a probability distribution
    probs = weights / total_weight

    # Expected (real-valued) allocation per cell
    expected = probs * micromobility_size

    # Assign integer allocations by flooring expected values
    grid['micromobility_count'] = np.floor(expected).astype(int)

    # Distribute the remaining units by largest fractional parts (prioritizes high-amenity cells)
    remainder = int(micromobility_size - grid['micromobility_count'].sum())
    if remainder > 0:
        fractional = expected - np.floor(expected)
        indices = fractional.sort_values(ascending=False).index[:remainder]
        for idx in indices:
            grid.at[idx, 'micromobility_count'] += 1

    return grid