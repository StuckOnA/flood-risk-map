"""Loads (and disk-caches) the Tangail drivable road network.

The first call downloads from OpenStreetMap and persists the graph as
GraphML. Subsequent calls read from disk in <100 ms. We never reproject
the cached graph — we store it once in whatever CRS osmnx gave us, and
that same graph is used for every subsequent session.

Public surface
--------------
load_tangail_graph() -> nx.MultiDiGraph
    The cached, OSM-derived road network for Tangail, Bangladesh.
"""

from __future__ import annotations

from typing import Any, Callable

import networkx as nx

# Place + buffer_distance uniquely identify the dataset we want.
PLACE_NAME = "Tangail, Bangladesh"
BUFFER_M   = 2000  # 2 km ring around the place polygon

# Import lazily so importing this module is cheap.
from . import cache_io


def _download_graph(_status: Callable[[str], None] | None = None) -> nx.MultiDiGraph:
    """Download the drivable network from OpenStreetMap.

    Tries ``graph_from_place`` first (modern osmnx), then falls back to
    ``graph_from_polygon`` for older versions. We pass the *raw* polygon
    to graph_from_polygon — pre-buffering + reprojecting can produce a
    polygon with thin slivers that osmnx's internal 500 m buffer rejects
    with "Shell empty after removing invalid points".
    """
    import osmnx as ox
    from shapely.validation import make_valid

    if _status:
        _status("📡 Querying OpenStreetMap for Tangail…")

    # Modern osmnx (>=1.6) accepts buffer_dist; older versions don't.
    try:
        if _status:
            _status("📡 Downloading via graph_from_place (buffer_dist=2000)…")
        return ox.graph_from_place(
            PLACE_NAME,
            network_type="drive",
            buffer_dist=BUFFER_M,
        )
    except TypeError:
        pass

    if _status:
        _status("📡 graph_from_place lacks buffer_dist; falling back to polygon…")

    gdf = ox.geocode_to_gdf(PLACE_NAME)
    poly = gdf.geometry.iloc[0]
    # Repair the polygon if needed (Tangail is clean, but this is cheap)
    if not poly.is_valid:
        poly = make_valid(poly)

    if _status:
        _status("📡 Downloading via graph_from_polygon…")
    try:
        return ox.graph_from_polygon(poly, network_type="drive")
    except Exception:
        # Final fallback: the polygon's bounding box.
        minx, miny, maxx, maxy = poly.bounds
        return ox.graph_from_bbox((minx, miny, maxx, maxy), network_type="drive")


def load_tangail_graph(
    _status: Callable[[str], None] | None = None,
) -> tuple[nx.MultiDiGraph, dict[str, Any]]:
    """Return the Tangail drivable network plus a small timing dict.

    The timing dict contains ``{"from_cache": bool, "elapsed_ms": float,
    "nodes": int, "edges": int}`` for caller-side display.
    """
    import time

    path = cache_io.graph_path(PLACE_NAME, BUFFER_M)
    started = time.perf_counter()

    if cache_io.graph_exists(path):
        if _status:
            _status(f"💾 Loading Tangail road network from disk cache ({path.name})…")
        G = cache_io.load_graph(path)
        from_cache = True
    else:
        if _status:
            _status(f"📡 No cache for {path.name}; downloading from OpenStreetMap…")
        G = _download_graph(_status=_status)
        if _status:
            _status("💾 Saving graph to disk for next time…")
        try:
            cache_io.save_graph(path, G)
        except Exception as exc:
            # Disk write failure shouldn't block the app.
            if _status:
                _status(f"⚠️ Could not persist graph: {exc}")
        from_cache = False

    elapsed_ms = (time.perf_counter() - started) * 1000
    info = {
        "from_cache": from_cache,
        "elapsed_ms": round(elapsed_ms, 1),
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "path": str(path),
    }
    return G, info
