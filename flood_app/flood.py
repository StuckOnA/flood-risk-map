"""Flood-state simulation and precomputed map polylines.

For a given (place, seed), we:
  1. Randomly assign every edge a state in {Clear, Caution, Impassable}.
  2. Compute a flood_weight = length × multiplier per edge.
  3. Write flood_weight + flood_state back onto the graph for routing.
  4. Convert every edge geometry to (lat, lng) once and serialise to JSON
     so the map-rendering loop doesn't reproject on every rerun.

Public surface
--------------
assign_flood_states(edges, seed) -> GeoDataFrame
build_flood_polylines(graph, edges, status=None) -> list[(color, coords)]
"""

from __future__ import annotations

import random
from typing import Callable, Iterable

import geopandas as gpd
import networkx as nx

from . import cache_io
from .graph_loader import PLACE_NAME


FLOOD_STATES = {
    "Clear":      {"prob": 0.70, "multiplier": 1.0,    "color": "#2ecc71"},  # green
    "Caution":    {"prob": 0.20, "multiplier": 2.0,    "color": "#f39c12"},  # orange
    "Impassable": {"prob": 0.10, "multiplier": 999999, "color": "#e74c3c"},  # red
}


def assign_flood_states(edges: gpd.GeoDataFrame, seed: int) -> gpd.GeoDataFrame:
    """Return a copy of ``edges`` with flood_state / flood_weight columns."""
    random.seed(seed)
    states  = list(FLOOD_STATES.keys())
    weights = [FLOOD_STATES[s]["prob"] for s in states]
    chosen  = random.choices(states, weights=weights, k=len(edges))

    out = edges.copy()
    out["flood_state"]      = chosen
    out["flood_color"]      = [FLOOD_STATES[s]["color"] for s in chosen]
    out["flood_multiplier"] = [FLOOD_STATES[s]["multiplier"] for s in chosen]
    if "length" not in out.columns:
        out["length"] = out.geometry.length
    out["flood_weight"] = (
        out["length"].astype(float) * out["flood_multiplier"].astype(float)
    )
    return out


def write_weights_back_to_graph(
    G: nx.MultiDiGraph, edges: gpd.GeoDataFrame
) -> nx.MultiDiGraph:
    """Push flood_weight + flood_state onto each edge of ``G``."""
    for (u, v, k), row in edges.iterrows():
        if G.has_edge(u, v, key=k):
            G[u][v][k]["flood_weight"] = float(row["flood_weight"])
            G[u][v][k]["flood_state"]  = row["flood_state"]
    return G


def build_flood_polylines(
    G: nx.MultiDiGraph,
    edges: gpd.GeoDataFrame,
    status: Callable[[str], None] | None = None,
) -> list[tuple[str, list[list[float]]]]:
    """Return [(color, [[lat, lng], ...]), ...] for every road segment.

    The graph's CRS may be anything (e.g. UTM 45N); we project each edge
    geometry to WGS84 exactly once so folium can render directly.
    """
    import osmnx as ox

    if status:
        status(f"🛣️  Projecting {len(edges):,} road segments to WGS84…")

    graph_crs = G.graph.get("crs") if hasattr(G, "graph") else None
    edges_crs = getattr(edges, "crs", None)
    edges_is_wgs = (
        edges_crs is None
        or "4326" in str(edges_crs).lower()
        or "wgs" in str(edges_crs).lower()
    )
    graph_is_wgs = (
        graph_crs is None
        or "4326" in str(graph_crs).lower()
        or "wgs" in str(graph_crs).lower()
    )
    need_reproject = not (edges_is_wgs and graph_is_wgs)

    polylines: list[tuple[str, list[list[float]]]] = []
    if not need_reproject:
        for _, row in edges.iterrows():
            geom = row.geometry
            if geom is None:
                continue
            color = row["flood_color"]
            if geom.geom_type == "LineString":
                coords = [[y, x] for x, y in geom.coords]
                if coords:
                    polylines.append((color, coords))
            elif geom.geom_type == "MultiLineString":
                for ln in geom.geoms:
                    coords = [[y, x] for x, y in ln.coords]
                    if coords:
                        polylines.append((color, coords))
    else:
        for _, row in edges.iterrows():
            geom = row.geometry
            if geom is None:
                continue
            color = row["flood_color"]
            geom_w = ox.projection.project_geometry(geom, to_crs=4326)[0]
            if geom_w.geom_type == "LineString":
                coords = [[y, x] for x, y in geom_w.coords]
                if coords:
                    polylines.append((color, coords))
            elif geom_w.geom_type == "MultiLineString":
                for ln in geom_w.geoms:
                    coords = [[y, x] for x, y in ln.coords]
                    if coords:
                        polylines.append((color, coords))

    if status:
        status(f"✅ Built {len(polylines):,} road polylines")
    return polylines


def prepare_flood_state(
    G: nx.MultiDiGraph,
    seed: int,
    status: Callable[[str], None] | None = None,
) -> tuple[gpd.GeoDataFrame, list[tuple[str, list[list[float]]]], dict]:
    """Load the flood dataset for ``seed``, returning (edges, polylines, info).

    Both the polylines and the edges GeoDataFrame are disk-cached per
    (place, seed) so a warm load is just two pickle/JSON reads — no
    reprojection, no random assignment.
    """
    import time

    started = time.perf_counter()
    path = cache_io.flood_path(PLACE_NAME, seed)
    has_polylines = cache_io.flood_exists(path)
    has_edges     = cache_io.flood_edges_exist(path)

    if has_polylines and has_edges:
        if status:
            status(f"💾 Loading flood data for seed {seed} from disk cache…")
        polylines = cache_io.load_flood_polylines(path)
        edges     = cache_io.load_flood_edges(path)
        write_weights_back_to_graph(G, edges)
        from_cache = True
    else:
        if status:
            status(f"🎲 Assigning random flood states (seed={seed})…")
        edges = assign_flood_states_edges_of(G, seed)
        write_weights_back_to_graph(G, edges)
        if status:
            status(f"🛣️  Projecting {len(edges):,} road segments to WGS84…")
        polylines = build_flood_polylines(G, edges)
        if status:
            status(f"💾 Caching flood data for seed {seed}…")
        try:
            cache_io.save_flood_polylines(path, polylines)
        except Exception as exc:
            if status:
                status(f"⚠️ Could not persist flood polylines: {exc}")
        try:
            cache_io.save_flood_edges(path, edges)
        except Exception as exc:
            if status:
                status(f"⚠️ Could not persist flood edges: {exc}")
        from_cache = False

    elapsed_ms = (time.perf_counter() - started) * 1000
    info = {
        "from_cache": from_cache,
        "elapsed_ms": round(elapsed_ms, 1),
        "seed": seed,
        "polylines": len(polylines),
        "path": str(path),
    }
    return edges, polylines, info


def assign_flood_states_edges_of(G: nx.MultiDiGraph, seed: int) -> gpd.GeoDataFrame:
    """Convenience: get edges GeoDataFrame, assign flood states."""
    import osmnx as ox
    edges = ox.graph_to_gdfs(G, nodes=False, edges=True)
    return assign_flood_states(edges, seed)
