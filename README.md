## PyQuity
PyQuity is a compact Python toolkit for building and analyzing multimodal street and transit networks with a focus on accessibility and distributive equity. Quickly generate graphs and grids, attach POIs/GTFS, compute route-based accessibility, and evaluate equity (sufficientarianism, egalitarianism, utilitarianism) with seamless GeoPandas/NetworkX/OSMnx integration.

## Installation
PyQuity can be installed via PyPI:
```bash
pip install pyquity
```

## Usage
Graph Construction
```python
import pyquity

# Street networks from OpenStreetMap
G_walk = pyquity.graph_from_place('Barrie, Canada', network_type='walk')
G_bike = pyquity.graph_from_place('Barrie, Canada', network_type='bike')

# Transit network from GTFS
G_gtfs = pyquity.graph_from_gtfs('gtfs.zip')

# Combine into multimodal graph
MG_walk = pyquity.multimodal_graph(G_walk, G_gtfs)
MG_bike = pyquity.multimodal_graph(G_bike, G_gtfs)
```

Grid Construction
```python
# Create amenity GeoDataFrame
amenity = pyquity.amenity_from_place('Barrie, Canada', amenity_type='all')

# Create spatial grid (500 m resolution)
grid = pyquity.grid_from_place('Barrie, Canada', grid_size=5000)

# Attach amenities and micromobility stations to grid
grid = pyquity.amenity_in_grid(grid, amenity)
grid = pyquity.micromobility_in_grid(grid, micromobility_size=100)
```
```pyhon
# Optional: select multiple amenity types
amenity = pyquity.amenity_from_place('Barrie, Canada', amenity_type=['education', 'healthcare'])
```

Equity Analysis
```python
# Create equity properties
equity = pyquity.Equity(MG_walk, MG_bike, grid, amenity)

# Sufficientarianism: proportion of grid cells reachable within served_time
grid = equity.sufficientarianism(served_time=15, weight='travel_time')

# Utilitarianism: average accessibility score across all cells
grid = equity.utilitarianism(served_time=15, weight='travel_time')

# Egalitarianism: Gini coefficient and Lorenz curve of accessibility distribution
gini, lorenz = equity.egalitarianism(grid)
```

## Examples
See [examples](examples/main.ipynb) for a full walkthrough covering graph construction, grid setup, and equity analysis.

## License
This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.