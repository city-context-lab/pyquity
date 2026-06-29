import pyquity
import osmnx as ox
import numpy as np
import networkx as nx

class Equity:
    def __init__(self, G_walk, G_micromobility, grid, amenity):
        self.G_walk = G_walk
        self.G_micromobility = G_micromobility
        self.grid = grid
        self.amenity = amenity

        # Ensure amenities are point geometries
        if not all(self.amenity.geometry.geom_type == "Point"):
            self.amenity["geometry"] = self.amenity.geometry.centroid

    def sufficientarianism(self, served_time: int = 15, weight: str = 'length'):
        # Map amenities to nearest nodes and map grid centroids to nearest nodes with micromobility
        self.micromobility_amenity_nodes = ox.distance.nearest_nodes(self.G_micromobility, self.amenity.geometry.centroid.x.values, self.amenity.geometry.centroid.y.values)
        self.micromobility_grid_nodes = ox.distance.nearest_nodes(self.G_micromobility, self.grid.geometry.centroid.x.values, self.grid.geometry.centroid.y.values)

        # Map amenities to nearest nodes and map grid centroids to nearest nodes with walk
        self.walk_amenity_nodes = ox.distance.nearest_nodes(self.G_walk, self.amenity.geometry.centroid.x.values, self.amenity.geometry.centroid.y.values)
        self.walk_grid_nodes = ox.distance.nearest_nodes(self.G_walk, self.grid.geometry.centroid.x.values, self.grid.geometry.centroid.y.values)

        # Assign the nearest network node ID to each grid cell based on micromobility count
        self.grid["grid_id"] = np.where(self.grid['micromobility_count'] > 0, self.micromobility_grid_nodes, self.walk_grid_nodes)
        self.grid["served"] = 0

        # Iterate over each grid row to calculate serviceability
        for idx, grid_row in self.grid.iterrows():
            grid_node = grid_row['grid_id']

            # Check if the grid has micromobility services or not and select the appropriate graph and nodes
            if grid_row['micromobility_count'] > 0:
                G_current = self.G_micromobility
                amenity_nodes = self.micromobility_amenity_nodes
            else:
                G_current = self.G_walk
                amenity_nodes = self.walk_amenity_nodes

            # Compute shortest paths from the selected grid node to all other nodes
            if weight in ('travel_time', 'total_time'):
                costs, paths = nx.single_source_dijkstra(G_current, source=grid_node, weight=weight, cutoff=served_time)
            else:
                costs, paths = nx.single_source_dijkstra(G_current, source=grid_node, weight=weight, cutoff=served_time * (22 * 1000 / 3600) * 60)

            # Iterate over each amenity node to check if it's reachable within the time limit
            for amenity_node in amenity_nodes:
                # If this grid node is already served, no need to check further amenities
                if self.grid.loc[self.grid["grid_id"] == grid_node, "served"].values[0] == 1:
                    break

                # Check if the amenity is reachable in the computed paths
                if amenity_node in paths:
                    if weight in ('travel_time', 'total_time'):
                        # Dijkstra cost is already in minutes (includes waiting for total_time)
                        if costs[amenity_node] <= served_time:
                            self.grid.loc[self.grid["grid_id"] == grid_node, "served"] = 1
                            break
                    else:
                        try:
                            route = [int(node) for node in paths[int(amenity_node)]]
                            distance, travel_time = pyquity.route_length_by_mode(G_current, route)
                            total_time = sum(travel_time.values())
                            if total_time <= served_time:
                                self.grid.loc[self.grid["grid_id"] == grid_node, "served"] = 1
                                break
                        except:
                            continue

        # Return GeoDataFrame of grid
        return self.grid

    def egalitarianism(self, grid):
        # Extract binary accessibility outcome (served=1, unserved=0) and sort ascending
        data = np.sort(grid["served"].to_numpy(dtype=float))

        # If nobody is served, define gini = 0 and Lorenz = all zeros
        if data.sum() == 0:
            return 0.0, np.zeros(len(data) + 1)

        # Lorenz curve: cumulative share of "served" outcomes across grid cells
        lorenz = np.insert(np.cumsum(data) / data.sum(), 0, 0.0)

        # Compute area under the Lorenz curve using trapezoidal integration
        B = np.trapz(lorenz, np.linspace(0.0, 1.0, len(data) + 1))

        # Gini coefficient derived from Lorenz curve area: G = 1 - 2B
        gini = 1.0 - 2.0 * B

        # Return Gini coefficient and Lorenz curve values
        return float(gini), lorenz
    
    def utilitarianism(self, served_time: int = 15, weight: str = 'length'):
        # Initialize a column to track how many amenities serve each grid cell
        self.grid["count_served"] = 0

        # Iterate over each grid cell and choose network based on micromobility presence
        for pos, (idx, grid_row) in enumerate(self.grid.iterrows()):
            # Choose network and amenity nodes per-grid based on micromobility_count
            if grid_row.get('micromobility_count', 0) > 0:
                G_current = self.G_micromobility
                amenity_nodes = getattr(self, 'micromobility_amenity_nodes', [])
                # Prefer precomputed micromobility grid node mapping when available
                if hasattr(self, 'micromobility_grid_nodes'):
                    grid_node = int(self.micromobility_grid_nodes[pos])
                else:
                    grid_node = int(grid_row.get('grid_id'))
            else:
                G_current = self.G_walk
                amenity_nodes = getattr(self, 'walk_amenity_nodes', [])
                if hasattr(self, 'walk_grid_nodes'):
                    grid_node = int(self.walk_grid_nodes[pos])
                else:
                    grid_node = int(grid_row.get('grid_id'))

            # Compute shortest paths (Dijkstra) from the grid node to all reachable nodes
            if weight in ('travel_time', 'total_time'):
                costs, paths = nx.single_source_dijkstra(G_current, source=grid_node, weight=weight, cutoff=served_time)
            else:
                costs, paths = nx.single_source_dijkstra(G_current, source=grid_node, weight=weight, cutoff=served_time * (22 * 1000 / 3600) * 60)

            # Check each amenity node to see if it is reachable and increment count
            for amenity_node in amenity_nodes:
                if amenity_node in paths:
                    if weight in ('travel_time', 'total_time'):
                        # Dijkstra cost is already in minutes (includes waiting for total_time)
                        if costs[amenity_node] <= served_time:
                            self.grid.at[idx, "count_served"] += 1
                    else:
                        try:
                            route = [int(node) for node in paths[int(amenity_node)]]
                            distance, travel_time = pyquity.route_length_by_mode(G_current, route)
                            total_time = sum(travel_time.values())
                            if total_time <= served_time:
                                self.grid.at[idx, "count_served"] += 1
                        except:
                            continue

        return self.grid