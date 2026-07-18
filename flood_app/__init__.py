"""Flood-aware routing app — package root.

Modules:
    cache_io      Disk persistence for the road network and flood polylines.
    graph_loader  Builds the Tangail drivable network (disk-cached).
    flood         Flood-state assignment + precomputed lat/lng polylines.
    routing       Nearest-node lookup + flood-adjusted shortest path.
    ui            Streamlit page layout and map rendering.
"""

__version__ = "1.1.0"
