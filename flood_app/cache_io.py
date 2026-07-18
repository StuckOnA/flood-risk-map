"""Disk-cached persistence for the road network and flood polylines.

The Tangail road network is fetched from OpenStreetMap on first launch
(5–20 s on a cold start). After that we serialise the graph as GraphML
under ``.flood_cache/graph/<hash>.graphml`` so subsequent launches read
the network from disk in <50 ms.

The flood polylines — a flat list of (color, [(lat, lng), ...]) tuples
in WGS84 — are written to ``.flood_cache/flood/<hash>_seed_<n>.json`` so
that switching the seed slider doesn't trigger a full reprojection pass
for every visited seed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

# Where the cache lives. We deliberately use a hidden dot-directory so
# it doesn't clutter the user's view of the project.
CACHE_DIR = Path(os.environ.get("FLOOD_CACHE_DIR", Path.cwd() / ".flood_cache"))
GRAPH_DIR = CACHE_DIR / "graph"
FLOOD_DIR = CACHE_DIR / "flood"


def _ensure_dirs() -> None:
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    FLOOD_DIR.mkdir(parents=True, exist_ok=True)


def graph_path(place: str, buffer_m: int = 0) -> Path:
    """Return the on-disk path for a cached graph."""
    key = f"{place}|buf={buffer_m}".encode("utf-8")
    h = hashlib.sha1(key).hexdigest()[:16]
    return GRAPH_DIR / f"{h}.graphml"


def flood_path(place: str, seed: int) -> Path:
    """Return the on-disk path for cached flood polylines."""
    key = f"{place}|seed={seed}".encode("utf-8")
    h = hashlib.sha1(key).hexdigest()[:16]
    return FLOOD_DIR / f"{h}_seed_{seed}.json"


def save_graph(graph_path: Path, G) -> None:
    """Persist a networkx graph.

    Speed matters here — every cold launch hits this, and every warm
    launch reads it back. GraphML is portable but slow to parse (≈1s
    for an 8k-node graph). Pickle is ~50× faster but isn't portable
    across networkx versions. We write both: pickle for speed, GraphML
    as a fallback if the pickle can't be read.
    """
    import pickle

    _ensure_dirs()
    import osmnx as ox

    # Save as GraphML (portable, slow).
    graphml_path = graph_path.with_suffix(".graphml")
    try:
        try:
            G_w = ox.project_graph(G, to_crs=4326)
        except Exception:
            G_w = G
        ox.io.save_graphml(G_w, filepath=str(graphml_path))
    except Exception:
        graphml_path = None  # type: ignore[assignment]

    # Save as pickle (fast, single-file).
    pickle_path = graph_path.with_suffix(".pkl")
    tmp = pickle_path.with_suffix(pickle_path.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(G, fh, protocol=pickle.HIGHEST_PROTOCOL)
    import os as _os
    _os.replace(tmp, pickle_path)

    # Stash which representation we're using under the canonical path
    # (the .graphml suffix used by graph_path()). We just leave the
    # canonical path empty-ish and have load_graph() check both files.


def load_graph(graph_path: Path):
    """Load a graph previously saved by ``save_graph``.

    Prefers pickle (fast). Falls back to GraphML if the pickle is missing
    or fails to deserialize (e.g. after a networkx upgrade).
    """
    import osmnx as ox
    import pickle

    pickle_path = graph_path.with_suffix(".pkl")
    if pickle_path.exists():
        try:
            with open(pickle_path, "rb") as fh:
                return pickle.load(fh)
        except Exception:
            pass  # fall through to GraphML

    graphml_path = graph_path.with_suffix(".graphml")
    if graphml_path.exists():
        G = ox.io.load_graphml(str(graphml_path))
        # Heal the missing pickle so next call is fast.
        try:
            save_graph(graph_path, G)
        except Exception:
            pass
        return G

    raise FileNotFoundError(f"No cached graph at {graph_path} ({pickle_path} or {graphml_path})")


def graph_exists(graph_path: Path) -> bool:
    return graph_path.with_suffix(".pkl").exists() or graph_path.with_suffix(".graphml").exists()


def graph_exists(graph_path: Path) -> bool:
    return graph_path.exists()


def save_flood_polylines(flood_path: Path, polylines: Iterable[tuple]) -> None:
    """Persist precomputed flood polylines.

    We write *both* a JSON file (portable, debuggable) and a pickle file
    (much faster to read back). The loader prefers the pickle.

    ``polylines`` is an iterable of (color, [[lat, lng], ...]) tuples.
    """
    import pickle

    _ensure_dirs()

    # JSON (portable)
    payload = [{"c": color, "p": coords} for color, coords in polylines]
    json_path = flood_path
    tmp = json_path.with_suffix(json_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, json_path)

    # Pickle (fast)
    pickle_path = flood_path.with_suffix(".polylines.pkl")
    tmp = pickle_path.with_suffix(pickle_path.suffix + ".tmp")
    payload_as_tuples = [(entry["c"], entry["p"]) for entry in payload]
    with open(tmp, "wb") as fh:
        pickle.dump(payload_as_tuples, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, pickle_path)


def load_flood_polylines(flood_path: Path) -> list[tuple[str, list[list[float]]]]:
    """Load precomputed flood polylines. Returns list of (color, coords).

    Prefers pickle; falls back to JSON.
    """
    import pickle

    pickle_path = flood_path.with_suffix(".polylines.pkl")
    if pickle_path.exists():
        try:
            with open(pickle_path, "rb") as fh:
                return pickle.load(fh)
        except Exception:
            pass

    with open(flood_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return [(entry["c"], entry["p"]) for entry in payload]


def save_flood_edges(flood_path: Path, edges) -> None:
    """Persist the flood-assigned edges GeoDataFrame as pickle."""
    import pickle

    _ensure_dirs()
    pickle_path = flood_path.with_suffix(".edges.pkl")
    tmp = pickle_path.with_suffix(pickle_path.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(edges, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, pickle_path)


def load_flood_edges(flood_path: Path):
    """Load the flood-assigned edges GeoDataFrame."""
    import pickle

    pickle_path = flood_path.with_suffix(".edges.pkl")
    with open(pickle_path, "rb") as fh:
        return pickle.load(fh)


def flood_edges_exist(flood_path: Path) -> bool:
    return flood_path.with_suffix(".edges.pkl").exists()


def flood_exists(flood_path: Path) -> bool:
    return flood_path.exists()


def cache_root() -> Path:
    """Return the cache root, ensuring it exists."""
    _ensure_dirs()
    return CACHE_DIR
