"""Routing helpers — nearest-node lookup + flood-adjusted shortest path.

For large graphs, ``ox.distance.nearest_nodes`` falls back to a slow O(N)
linear scan when scikit-learn isn't installed. We build a small bucket-
based spatial index once per graph, which gives sub-millisecond lookups.

Public surface
--------------
build_node_index(G)  -> NodeIndex
nearest_node(G, idx, lat, lng) -> int
shortest_path(G, origin_node, dest_node) -> (path_nodes, route_edges, polyline)
route_polyline(G, route_edges) -> [[lat, lng], ...]
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx


# ---------------------------------------------------------------------------
# Spatial index for nearest-node lookups
# ---------------------------------------------------------------------------
@dataclass
class NodeIndex:
    """Bucket-grid spatial index over a networkx graph's node positions.

    Nodes are placed into square cells of side ``cell_size`` (in the
    graph's coordinate space). ``nearest_node`` searches the cell at the
    query point and its 8 neighbours, then does a final exact scan over
    that small candidate set. This is ~O(1) per query for reasonably
    uniform graphs.
    """

    cell_size: float
    cells: dict[tuple[int, int], list[tuple[int, float, float]]]

    @classmethod
    def build(cls, G: nx.MultiDiGraph, cell_size: float | None = None) -> "NodeIndex":
        # Auto-pick a sensible cell size from the node spread.
        xs = [float(d["x"]) for _, d in G.nodes(data=True)]
        ys = [float(d["y"]) for _, d in G.nodes(data=True)]
        if cell_size is None:
            span = max(max(xs) - min(xs), max(ys) - min(ys))
            cell_size = max(span / 50.0, 1.0)
        cells: dict[tuple[int, int], list[tuple[int, float, float]]] = {}
        for nid, x, y in (
            (n, float(d["x"]), float(d["y"])) for n, d in G.nodes(data=True)
        ):
            cx = int(math.floor(x / cell_size))
            cy = int(math.floor(y / cell_size))
            cells.setdefault((cx, cy), []).append((nid, x, y))
        return cls(cell_size=cell_size, cells=cells)

    def nearest(self, x: float, y: float) -> int:
        cx = int(math.floor(x / self.cell_size))
        cy = int(math.floor(y / self.cell_size))
        best_n = None
        best_d2 = float("inf")
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                bucket = self.cells.get((cx + dx, cy + dy))
                if not bucket:
                    continue
                for nid, nx_, ny_ in bucket:
                    d2 = (nx_ - x) ** 2 + (ny_ - y) ** 2
                    if d2 < best_d2:
                        best_d2 = d2
                        best_n = nid
        # Defensive fallback: if every neighbour-bucket was empty (shouldn't
        # happen if the cell_size matches the graph spread), fall back to a
        # full scan.
        if best_n is None:
            for nid, nx_, ny_ in (
                (n, float(d["x"]), float(d["y"])) for n, d in self._all_nodes()
            ):
                d2 = (nx_ - x) ** 2 + (ny_ - y) ** 2
                if d2 < best_d2:
                    best_d2 = d2
                    best_n = nid
        return best_n

    def _all_nodes(self):
        for bucket in self.cells.values():
            for entry in bucket:
                yield entry


def build_node_index(G: nx.MultiDiGraph) -> NodeIndex:
    return NodeIndex.build(G)


# Streamlit-aware cached version: graphs aren't hashable, so we use the
# leading-underscore convention to skip hashing and rely on object
# identity. The caller is expected to pass the same graph instance on
# every rerun (it comes from a cached resource).
_NODE_INDEX_CACHE: dict[int, NodeIndex] = {}


def get_node_index_cached(G: nx.MultiDiGraph) -> NodeIndex:
    """Return a NodeIndex for ``G``, building it once per graph instance."""
    key = id(G)
    cached = _NODE_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    idx = build_node_index(G)
    _NODE_INDEX_CACHE[key] = idx
    return idx


def nearest_node(G: nx.MultiDiGraph, index: NodeIndex, lat: float, lng: float) -> int:
    """Find the nearest node to (lat, lng). ``lat`` / ``lng`` are geographic."""
    graph_crs = G.graph.get("crs") if hasattr(G, "graph") else None
    if _is_wgs84(graph_crs):
        x, y = lng, lat
    else:
        # Project query point into the graph's CRS
        from shapely.geometry import Point
        import osmnx as ox
        projected = ox.projection.project_geometry(Point(lng, lat), to_crs=graph_crs)[0]
        x, y = projected.x, projected.y
    return index.nearest(x, y)


def _is_wgs84(crs) -> bool:
    if crs is None:
        return True
    s = str(crs).lower()
    return "4326" in s or "wgs" in s


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def shortest_path(
    G: nx.MultiDiGraph,
    origin_node: int,
    dest_node: int,
) -> tuple[list[int], list[tuple[int, int, dict]]]:
    """Run flood-weighted shortest_path and return (node_list, route_edges).

    ``route_edges`` is a list of (u, v, data) for each segment of the path.
    """
    path = nx.shortest_path(
        G, source=origin_node, target=dest_node, weight="flood_weight"
    )
    route_edges = []
    for u, v in zip(path[:-1], path[1:]):
        data = min(
            G[u][v].values(),
            key=lambda d: d.get("flood_weight", float("inf")),
        )
        route_edges.append((u, v, data))
    return path, route_edges


def route_polyline(
    G: nx.MultiDiGraph,
    route_edges: list[tuple[int, int, dict]],
) -> list[list[float]]:
    """Build the route as a flat list of [lat, lng] points in WGS84."""
    import osmnx as ox
    from shapely.geometry import Point as _Pt

    graph_crs = G.graph.get("crs") if hasattr(G, "graph") else None
    is_wgs = _is_wgs84(graph_crs)

    coords: list[list[float]] = []
    for u, v, data in route_edges:
        if "geometry" in data and data["geometry"] is not None:
            geom = data["geometry"]
            if geom.geom_type == "LineString":
                if is_wgs:
                    seg = [[y, x] for x, y in geom.coords]
                else:
                    proj = ox.projection.project_geometry(geom, to_crs=4326)[0]
                    seg = [[y, x] for x, y in proj.coords]
                if coords and coords[-1] == seg[0]:
                    coords.extend(seg[1:])
                else:
                    coords.extend(seg)
        else:
            if is_wgs:
                p1 = [G.nodes[u]["y"], G.nodes[u]["x"]]
                p2 = [G.nodes[v]["y"], G.nodes[v]["x"]]
            else:
                p1_proj = ox.projection.project_geometry(
                    _Pt(G.nodes[u]["x"], G.nodes[u]["y"]), to_crs=4326
                )[0]
                p2_proj = ox.projection.project_geometry(
                    _Pt(G.nodes[v]["x"], G.nodes[v]["y"]), to_crs=4326
                )[0]
                p1 = [p1_proj.y, p1_proj.x]
                p2 = [p2_proj.y, p2_proj.x]
            if coords and coords[-1] == p1:
                coords.append(p2)
            else:
                coords.extend([p1, p2])
    return coords


def route_stats(
    G: nx.MultiDiGraph,
    route_edges: list[tuple[int, int, dict]],
) -> dict:
    """Return summary statistics for a route: length, cost, edge composition."""
    total_length = sum(d.get("length", 0) for _, _, d in route_edges)
    total_cost   = sum(d.get("flood_weight", 0) for _, _, d in route_edges)
    n_clear = sum(1 for _, _, d in route_edges if d.get("flood_state") == "Clear")
    n_caut  = sum(1 for _, _, d in route_edges if d.get("flood_state") == "Caution")
    n_impa  = sum(1 for _, _, d in route_edges if d.get("flood_state") == "Impassable")
    return {
        "length": total_length,
        "cost":   total_cost,
        "edges":  len(route_edges),
        "clear":  n_clear,
        "caut":   n_caut,
        "impa":   n_impa,
    }
