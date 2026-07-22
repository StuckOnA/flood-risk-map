# 🌊 Flood Risk Routing Engine — A Complete Walkthrough

> A teaching-grade README. By the end you should understand every line of
> this codebase, even if today you only know variables, functions, and
> `if` statements.

---

## Table of contents

1. [What does this program actually do?](#1-what-does-this-program-actually-do)
2. [Glossary for newcomers](#2-glossary-for-newcomers)
3. [Project layout (file-by-file)](#3-project-layout-file-by-file)
4. [How to run it](#4-how-to-run-it)
5. [Deep dive — `flood_routing_app.py`](#5-deep-dive--flood_routing_apppy)
6. [Deep dive — `flood_app/__init__.py`](#6-deep-dive--flood_app__init__py)
7. [Deep dive — `flood_app/cache_io.py`](#7-deep-dive--flood_appcache_iopy)
8. [Deep dive — `flood_app/graph_loader.py`](#8-deep-dive--flood_appgraph_loaderpy)
9. [Deep dive — `flood_app/routing.py`](#9-deep-dive--flood_appsroutingpy)
10. [Deep dive — `flood_app/flood.py`](#10-deep-dive--flood_appfloodpy)
11. [Deep dive — `flood_app/ui.py`](#11-deep-dive--flood_appuipy)
12. [Every performance optimization explained](#12-every-performance-optimization-explained)
13. [Streamlit concepts used here](#13-streamlit-concepts-used-here)
14. [Data formats and file shapes](#14-data-formats-and-file-shapes)
15. [Glossary of advanced terms](#15-glossary-of-advanced-terms)
16. [Exercises for the curious](#16-exercises-for-the-curious)

---

## 1. What does this program actually do?

It is a **web app** that lets you:

1. **Pick two points on a map** of Tangail, Bangladesh (Point A and Point B).
2. **Simulate a flood** by randomly classifying every road into one of three states:
   - 🟢 **Clear** (70% of roads) — drive normally, weight = road length × 1
   - 🟠 **Caution** (20% of roads) — possible flooding, weight = road length × 2
   - 🔴 **Impassable** (10% of roads) — flooded, weight = road length × 999,999
3. **Find the safest route** between the two points, treating the flood-adjusted
   weights as "cost", so the path naturally prefers Clear roads, uses Caution
   roads reluctantly, and avoids Impassable ones entirely.
4. **Show the route on a real OpenStreetMap** (Folium/Leaflet), with the
   road network colour-coded by flood state so you can see *why* the route
   chose the roads it did.

It runs entirely on your machine using free OpenStreetMap data — no API keys
needed, no server costs.

### What is "Tangail, Bangladesh"?

A city and district in central Bangladesh, about 100 km northwest of Dhaka.
It's chosen here because Bangladesh is highly flood-prone and the road
network is small enough (~8,000 nodes) to be computed instantly.

---

## 2. Glossary for newcomers

Before reading the code, let's agree on some vocabulary:

| Word | What it means here |
|---|---|
| **Streamlit** | A Python library that turns a Python script into a web app. `st.button(...)` makes a button. `st.slider(...)` makes a slider. Run with `streamlit run script.py`. |
| **Folium** | A Python library that builds interactive maps (it produces HTML/JS Leaflet maps). |
| **streamlit-folium** | A small bridge that lets you embed a Folium map *inside* a Streamlit page and detect clicks on it. |
| **NetworkX (nx)** | A Python library for **graph** data structures — nodes connected by edges. Used here for the road network. |
| **OSMnx (ox)** | A Python library that downloads OpenStreetMap data and exposes it as a NetworkX graph (intersections = nodes, roads = edges). |
| **GeoPandas (gpd)** | Like `pandas` (think Excel tables) but for geographic data — every row has a `.geometry` field (point, line, polygon). |
| **Shapely** | The library that actually does the geometry math (intersections, distances, projections). GeoPandas wraps it. |
| **Graph (in the network theory sense)** | A collection of `nodes` and `edges`. Not a chart. Here: nodes = road intersections, edges = road segments. |
| **Node** | An intersection or endpoint of a road. |
| **Edge** | A road segment between two intersections. Has properties like `length`, `name`, `geometry` (the actual shape). |
| **Polyline** | A list of coordinate points that, when drawn on a map, makes a line (e.g. the shape of a road). |
| **CRS** | "Coordinate Reference System" — which coordinate system we're using. WGS84 (`EPSG:4326`) is the lat/lng one used by Google Maps. UTM is a flat metric system. Routing math needs metric, but Folium needs lat/lng, so we convert. |
| **WGS84** | The worldwide standard lat/lng coordinate system. Folium wants this. |
| **Shortest path** | Given a graph with weighted edges, find the cheapest path between two nodes. NetworkX has Dijkstra built in. |
| **GeoDataFrame** | Like a spreadsheet where one column is a `shapely` geometry (Point, Line, Polygon). |
| **Pickle** | Python's binary serialization format. Lets you save any Python object to disk and load it back later. Not portable across Python versions or major library upgrades, but very fast. |
| **GraphML** | An XML-based portable format for graphs. Slower to parse than pickle, but text-readable and portable. |
| **JSON** | Text-based, human-readable format. We use it for debugging the flood polylines. |
| **Tuple** | An immutable (unchangeable) sequence. `(24.25, 89.92)` is a tuple. You can't modify it after creation. |
| **MultiDiGraph** | A NetworkX graph that allows **multiple edges between the same two nodes** (a one-way street alongside a one-way street in the opposite direction) and **direction**. |
| **`from __future__ import annotations`** | A line at the top of modern Python files. It makes type hints lazy (not evaluated at runtime), so you can write hints like `list[int]` even on Python 3.8. |

---

## 3. Project layout (file-by-file)

```
map-thing/
├── README.md                  ← this file
├── requirements.txt           ← list of Python packages to install
├── flood_routing_app.py       ← tiny entry point (10 lines)
├── .gitignore                 ← tells Git what NOT to commit
├── flood_app/                 ← a "package" containing all the real code
│   ├── __init__.py            ← package metadata
│   ├── cache_io.py            ← disk read/write for graphs and flood data
│   ├── graph_loader.py        ← downloads the Tangail road network
│   ├── flood.py               ← flood-state simulation + polylines
│   ├── routing.py             ← shortest path + spatial index
│   └── ui.py                  ← Streamlit page (the actual app)
├── backups/                   ← OLD versions of the app (gitignored)
│   ├── v3.0-stable-click-fix-perf/
│   ├── v3.1-prompt-and-spinners/
│   └── v3.2-sidebar-mirror/   ← current state
└── .flood_cache/              ← disk cache (gitignored, recreated on first launch)
    ├── graph/                 ← pickled NetworkX graphs
    └── flood/                 ← pickled + JSON flood polylines
```

### How the files depend on each other

```
flood_routing_app.py
       │
       ▼
   flood_app/ui.py ─────┬──▶ flood_app/flood.py ──▶ flood_app/cache_io.py
                       │                            flood_app/graph_loader.py
                       ├──▶ flood_app/routing.py  ──▶ flood_app/cache_io.py
                       ├──▶ flood_app/graph_loader.py
                       └──▶ flood_app/cache_io.py
```

`ui.py` is the orchestrator. Everything else is a helper.

---

## 4. How to run it

```bash
# 1. Install Python 3.10 or newer.

# 2. Create a virtual environment (recommended).
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 3. Install dependencies.
pip install -r requirements.txt

# 4. Run the app.
streamlit run flood_routing_app.py
```

The browser opens automatically (or visit `http://localhost:8501`).

**First launch** will take ~10–30 seconds because it downloads Tangail from
OpenStreetMap and persists it to `.flood_cache/`. **Every launch after that**
is fast (1–2 seconds) because the graph is on disk.

### What's in `requirements.txt`?

```
streamlit>=1.30       # the web framework
osmnx>=1.6            # OpenStreetMap -> graph
networkx>=3.0         # graph data structure + shortest-path
folium>=0.15          # map generation
streamlit-folium>=0.15 # embed Folium in Streamlit + capture clicks
geopandas>=0.14       # tabular geo data
shapely>=2.0          # geometry primitives
pandas>=1.5           # dataframes (used by GeoPandas)
```

The `>=` means "this version or anything newer compatible with it".

---

## 5. Deep dive — `flood_routing_app.py`

This file is intentionally tiny. It exists only so Streamlit has something
to run.

```python
"""Flood Risk Routing Engine — Streamlit entry point.

Run with:
    streamlit run flood_routing_app.py

All logic lives in the ``flood_app`` package. This file is intentionally
short so it's obvious where the action is.
"""

from flood_app.ui import render


if __name__ == "__main__":
    render()
```

**Line by line:**

- The docstring explains why this file exists.
- `from flood_app.ui import render` — Python's `import` statement. `flood_app`
  is a folder next to this file; `.ui` means "the file `ui.py` inside it".
  `render` is the function we'll call.
- `if __name__ == "__main__":` — A Python idiom. When you run this file
  directly (e.g. `streamlit run ...`), `__name__` is `"__main__"`. When
  another file imports this one, `__name__` is `"flood_routing_app"`. So
  this `if` makes sure `render()` only runs when the file is the entry
  point. (Streamlit actually imports it as a module, so technically this
  guard isn't strictly necessary here — but it's good practice.)
- `render()` calls the main function that draws the entire Streamlit page.

That's the whole file. Move on.

---

## 6. Deep dive — `flood_app/__init__.py`

```python
"""Flood-aware routing app — package root.

Modules:
    cache_io      Disk persistence for the road network and flood polylines.
    graph_loader  Builds the Tangail drivable network (disk-cached).
    flood         Flood-state assignment + precomputed lat/lng polylines.
    routing       Nearest-node lookup + flood-adjusted shortest path.
    ui            Streamlit page layout and map rendering.
"""

__version__ = "1.1.0"
```

**What's a package?** A folder containing an `__init__.py` file. Python
treats it as a single importable unit. So you can write `import flood_app`
instead of `from flood_app import ui, flood, ...` etc.

The docstring just lists what each sibling file does (handy reminder).

`__version__ = "1.1.0"` is a convention. Many tools (setuptools, poetry)
read this automatically.

---

## 7. Deep dive — `flood_app/cache_io.py`

This file owns **everything disk-related**. It has zero Streamlit
dependencies, which means you could lift it out and use it from any
Python program. It does four jobs:

1. Compute file paths in `.flood_cache/`.
2. Save the road network (as GraphML + pickle for speed).
3. Load the road network (pickle first, GraphML fallback).
4. Save/load the flood polylines (JSON + pickle).

### What is `.flood_cache/`?

A hidden folder (the leading `.` hides it on macOS/Linux) that the app
creates on first launch. Inside it:

```
.flood_cache/
├── graph/
│   ├── abc123def456.pkl          ← the road network (binary, ~5 MB)
│   └── abc123def456.graphml      ← same data, text format, ~10 MB
└── flood/
    ├── abc123def456_seed_42.polylines.pkl
    ├── abc123def456_seed_42.json
    ├── abc123def456_seed_42.edges.pkl
    └── ... one set per seed
```

Deleting it forces a re-download from OpenStreetMap.

### The `hashlib` magic — why filenames are hashes

```python
def graph_path(place: str, buffer_m: int = 0) -> Path:
    """Return the on-disk path for a cached graph."""
    key = f"{place}|buf={buffer_m}".encode("utf-8")
    h = hashlib.sha1(key).hexdigest()[:16]
    return GRAPH_DIR / f"{h}.graphml"
```

We don't want to put `"Tangail, Bangladesh|buf=2000"` as a filename (it
contains spaces, commas, and could collide with case-sensitivity rules on
some filesystems). Instead we hash it: SHA-1 gives a 40-character
hexadecimal string like `a3f5e9c2b8d4...`. We take the first 16 characters,
which is overwhelmingly unique for our purposes.

Why SHA-1 (and not SHA-256)? SHA-1 is faster, and we're not worried about
adversarial collision attacks here — we just want stable, short names.

### Why GraphML AND pickle?

```python
def save_graph(graph_path: Path, G) -> None:
    # Save as GraphML (portable, slow).
    ...
    # Save as pickle (fast, single-file).
    pickle_path = graph_path.with_suffix(".pkl")
    ...
```

- **Pickle** is Python's native binary format. It's ~50× faster than
  GraphML but only works in Python, and only with the same major versions
  of NetworkX. We use it as the **fast path**.
- **GraphML** is an XML-based standard. Slow to parse, but text-readable
  and survives library upgrades. We use it as the **fallback**.

Same trick for flood polylines (JSON + pickle).

### The atomic-write pattern (`tmp` + `replace`)

```python
tmp = pickle_path.with_suffix(pickle_path.suffix + ".tmp")
with open(tmp, "wb") as fh:
    pickle.dump(G, fh, protocol=pickle.HIGHEST_PROTOCOL)
import os as _os
_os.replace(tmp, pickle_path)
```

This pattern prevents **partial writes** corrupting the cache. Imagine the
power cable is yanked mid-write:

- WITHOUT this pattern: `pickle_path` ends up half-written and unreadable
  next time. Cache is busted, you re-download from OSM.
- WITH this pattern: the write goes to `*.tmp`. Only AFTER it finishes
  does `os.replace()` atomically rename it over the real file. On most
  filesystems, `os.replace` is *atomic* — at any instant, the file is
  either the old version or the new version, never garbage.

`pickle.HIGHEST_PROTOCOL` is the most compact/fast protocol your current
Python supports.

### Other things in this file

- `graph_exists(path)` → `True` if either `.pkl` or `.graphml` exists.
  (Note: at one point this had a bug where two definitions existed and
  only the second ran, ignoring the `.pkl` cache and forcing re-downloads
  on every cold launch. The first definition is the correct one — read it.)
- `flood_exists(path)` / `flood_edges_exist(path)` — same idea for the
  two flood cache files.
- `cache_root()` — public entry point if you want to inspect the cache.

### What is `.with_suffix(".pkl")`?

`Path("a.graphml").with_suffix(".pkl")` → `Path("a.pkl")`. We use the
suffix as a "type tag" on the file name.

---

## 8. Deep dive — `flood_app/graph_loader.py`

This file is responsible for **getting the road network**. It downloads
from OpenStreetMap once, then forever after just reads from disk.

### The constants

```python
PLACE_NAME = "Tangail, Bangladesh"
BUFFER_M   = 2000  # 2 km ring around the place polygon
```

`PLACE_NAME` is the human-readable query string. `BUFFER_M` is how much
extra to extend the city's polygon by before downloading roads, in
meters. A 2-km ring catches highways that pass near the city but miss the
strict polygon.

### Why the try/except around `graph_from_place`?

```python
try:
    return ox.graph_from_place(
        PLACE_NAME,
        network_type="drive",
        buffer_dist=BUFFER_M,
    )
except TypeError:
    pass
```

Older versions of `osmnx` (< 1.6) didn't accept `buffer_dist`. The
`TypeError` raised by passing an unexpected keyword triggers the fallback
path below.

### The fallback chain

```python
gdf = ox.geocode_to_gdf(PLACE_NAME)
poly = gdf.geometry.iloc[0]
if not poly.is_valid:
    poly = make_valid(poly)

try:
    return ox.graph_from_polygon(poly, network_type="drive")
except Exception:
    minx, miny, maxx, maxy = poly.bounds
    return ox.graph_from_bbox((minx, miny, maxx, maxy), network_type="drive")
```

If `graph_from_place` fails, OSMnx gives us just the city polygon
(`geocode_to_gdf`), we ask for the road network over that polygon, and if
THAT fails (sometimes Tangail's polygon is "weird" and OSMnx rejects it),
we fall back to the bounding-box download — slower but always works.

### `load_tangail_graph` — the main function

```python
def load_tangail_graph(_status=None) -> tuple[Graph, dict]:
    path = cache_io.graph_path(PLACE_NAME, BUFFER_M)
    if cache_io.graph_exists(path):
        G = cache_io.load_graph(path)
        from_cache = True
    else:
        G = _download_graph(_status=_status)
        cache_io.save_graph(path, G)
        from_cache = False
    return G, {"from_cache": ..., "elapsed_ms": ..., ...}
```

Three steps:

1. **Find the cache file** for Tangail+2 km buffer.
2. **Load from disk if cached**, else **download from OpenStreetMap**.
3. **Return** the graph + a dictionary with timing info.

The `_status` parameter is a callback for status messages. The leading
underscore is a Python convention meaning "this is a private/optional
argument". The function calls it like `if _status: _status("...")` — i.e.
the function only emits status messages if the caller passed one in.

### The `@st.cache_resource` wrapper — the big speedup

```python
@st.cache_resource(show_spinner=False)
def get_tangail_graph_cached() -> tuple[Graph, dict]:
    return load_tangail_graph()
```

**This is a HUGE performance optimization.**

`@st.cache_resource` is a Streamlit decorator. It memoizes the function's
result across reruns (and even across browser sessions) for as long as
the Streamlit script-run is alive. The first call downloads/loads the
graph (50–1000 ms); every subsequent call is essentially free.

`show_spinner=False` means "don't show Streamlit's automatic 'Running...'
indicator". We have our own spinner.

`@st.cache_resource` (vs `@st.cache_data`): use `_resource` for things
that aren't pure data — like a NetworkX graph object that you only want
one copy of in memory. Use `_data` for serializable data (DataFrames,
dicts, lists) which `cache_resource` would store in the same singleton
slot anyway.

The function returns a tuple, which is hashable (so the cache can
recognize "we already did this"), but tuples are mutable in some senses,
so caching a tuple is fine.

---

## 9. Deep dive — `flood_app/routing.py`

This file has two parts:

1. **A spatial index** for "find the road intersection nearest to a given
   (lat, lng)" — used to snap user clicks to the road network.
2. **The shortest-path function** and helpers that build a polyline and
   statistics from the resulting path.

### The `NodeIndex` — a bucket grid

NetworkX has a built-in `ox.distance.nearest_nodes(...)` function, but
without scikit-learn installed it falls back to a slow O(N) linear scan
where N = number of nodes. For 8,000 nodes that's 8,000 distance checks
**per query**. The user can click the map multiple times; this adds up.

```python
@dataclass
class NodeIndex:
    cell_size: float
    cells: dict[tuple[int, int], list[tuple[int, float, float]]]
```

A `@dataclass` is a class auto-generated from its fields (Python 3.7+).
You get `__init__`, `__repr__`, `__eq__` for free.

**How does the bucket grid work?**

Imagine the city's bounding box. We cover it with square cells of side
`cell_size` (auto-picked so we get ~50 cells across the longest side).

```
cell_size = max(max(xs)-min(xs), max(ys)-min(ys)) / 50
```

Then for each node we compute which cell it's in:

```python
cx = int(math.floor(x / cell_size))
cy = int(math.floor(y / cell_size))
cells.setdefault((cx, cy), []).append((nid, x, y))
```

So `cells[(3, 7)]` is a list of all nodes in cell (3, 7).

To find the nearest node to query (qx, qy):

```python
def nearest(self, x: float, y: float) -> int:
    cx = int(math.floor(x / self.cell_size))
    cy = int(math.floor(y / self.cell_size))
    # Look at the 9 cells around (cx, cy): the cell itself plus its 8 neighbours
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            bucket = self.cells.get((cx + dx, cy + dy))
            ...
```

Why the 9-cell neighbourhood? Because the nearest node could be in any of
the cells adjacent to the query's cell — we don't know which direction.

Each cell typically has only a handful of nodes. So we go from O(N) → O(1).

There's a defensive fallback (`if best_n is None: ... full scan`) that
should never fire in practice.

### The id-keyed memo

```python
_NODE_INDEX_CACHE: dict[int, NodeIndex] = {}

def get_node_index_cached(G: nx.MultiDiGraph) -> NodeIndex:
    key = id(G)
    cached = _NODE_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    idx = build_node_index(G)
    _NODE_INDEX_CACHE[key] = idx
    return idx
```

`id(G)` returns the memory address of the object — since the graph comes
from `@st.cache_resource`, it's always the *same* object, so the second
and subsequent calls return the cached index instantly.

### `nearest_node` — coordinate-system aware

```python
def nearest_node(G, index, lat: float, lng: float) -> int:
    graph_crs = G.graph.get("crs") if hasattr(G, "graph") else None
    if _is_wgs84(graph_crs):
        x, y = lng, lat
    else:
        # Project query point into the graph's CRS
        ...
        x, y = projected.x, projected.y
    return index.nearest(x, y)
```

The graph's coordinates may be in UTM (meters east/north) but the user
gives us (lat, lng). If the graph is in UTM we must convert; if it's
already WGS84 we just rename `lng → x`, `lat → y`.

`_is_wgs84` is a defensive helper: a CRS can be `None`, the string
`"EPSG:4326"`, or `"WGS 84"` — we check for `"4326"` and `"wgs"`.

### The shortest-path algorithm

```python
def shortest_path(G, origin_node, dest_node):
    path = nx.shortest_path(
        G, source=origin_node, target=dest_node, weight="flood_weight"
    )
    ...
```

NetworkX's `shortest_path` with `weight="flood_weight"` runs Dijkstra's
algorithm (for non-negative weights, which ours are). It returns the
**ordered list of node IDs** along the cheapest path.

```python
for u, v in zip(path[:-1], path[1:]):
    data = min(
        G[u][v].values(),
        key=lambda d: d.get("flood_weight", float("inf")),
    )
    route_edges.append((u, v, data))
```

`zip(path[:-1], path[1:])` is the standard "sliding window" trick — it
pairs adjacent elements: `[(1, 2), (2, 5), (5, 9), ...]`. We then look up
the edge data. Because the graph is `MultiDiGraph` (multiple edges
allowed between two nodes), `G[u][v]` is a *dict* of edge-key → data. We
pick the cheapest one.

### `route_polyline` — flatten the path to (lat, lng)

Each road edge has either a `geometry` attribute (a `LineString` shapely
object with all its bend points) or no geometry (just straight from u to
v). We turn the sequence of edge geometries into a single flat
`[[lat, lng], ...]` list that Folium can draw.

The tricky bit: if two consecutive edges share an endpoint, we don't want
to duplicate that point. So:

```python
if coords and coords[-1] == seg[0]:
    coords.extend(seg[1:])   # skip the duplicate start
else:
    coords.extend(seg)       # include both endpoints
```

### `route_stats` — summary numbers

Just sums and counts over the `route_edges`. Returned dict:

```python
{
    "length": 4532.1,    # total road length, meters
    "cost":   7890,      # total flood-weighted cost
    "edges":  37,        # number of segments
    "clear":  30,        # edges in Clear state
    "caut":   6,         # edges in Caution
    "impa":   1,         # edges in Impassable (this would be weird — should be 0)
}
```

The UI displays these so users can see "this route is 30 green edges, 6
orange edges, and only 1 unfortunate red edge."

---

## 10. Deep dive — `flood_app/flood.py`

This file owns the **flood simulation logic**. It does three things:

1. **Randomly classify every edge** into Clear / Caution / Impassable.
2. **Compute flood weights** = length × multiplier.
3. **Push the weights back onto the graph** so `shortest_path` can use them.
4. **Project every edge to (lat, lng) once** and cache the result.

### The `FLOOD_STATES` table

```python
FLOOD_STATES = {
    "Clear":      {"prob": 0.70, "multiplier": 1.0,    "color": "#2ecc71"},
    "Caution":    {"prob": 0.20, "multiplier": 2.0,    "color": "#f39c12"},
    "Impassable": {"prob": 0.10, "multiplier": 999999, "color": "#e74c3c"},
}
```

Notice the multiplier for "Impassable" is `999999` — astronomically high
so that no sensible route will ever include an Impassable edge unless
it's the only option. With 10% of roads impassable, this means we WILL
get some routes with red edges when points are far apart — and the UI
makes that visible to the user.

### Random assignment

```python
def assign_flood_states(edges, seed):
    random.seed(seed)
    states  = list(FLOOD_STATES.keys())
    weights = [FLOOD_STATES[s]["prob"] for s in states]
    chosen  = random.choices(states, weights=weights, k=len(edges))
```

`random.seed(seed)` makes the random assignment reproducible — given the
same seed, the same edges get the same states. So when you slide the
"Random seed" in the UI from 42 → 43, you get a different distribution.

`random.choices(states, weights=weights, k=len(edges))` is the weighted
sampling version of `random.choice`. Each call returns `k` independent
samples, each drawn with probability proportional to `weights[i]`.

The function adds new columns to the edges GeoDataFrame: `flood_state`,
`flood_color`, `flood_multiplier`, and `flood_weight`.

### `write_weights_back_to_graph`

After assigning, we **push the weights onto the NetworkX graph itself**.
Why? Because `nx.shortest_path(G, weight="flood_weight")` reads the
weight directly from the graph's edge data, not from a separate
GeoDataFrame. So we have to mirror the values.

```python
for (u, v, k), row in edges.iterrows():
    if G.has_edge(u, v, key=k):
        G[u][v][k]["flood_weight"] = float(row["flood_weight"])
        G[u][v][k]["flood_state"]  = row["flood_state"]
```

This loop is slow — ~19,000 iterations on Tangail. The `_FLOOD_CACHE` (see
below) skips it on reruns.

### `build_flood_polylines`

The graph is downloaded in UTM (meters east/north), but Folium wants
latitude/longitude. This function projects every edge geometry to WGS84
**once** and returns a flat list:

```
[(color, [[lat, lng], [lat, lng], ...]), ...]
```

The colour is the flood colour of that edge. So the UI can render the
whole network as a multi-coloured polyline, OR can pre-bucket by colour
and render 3 large polylines (the optimization in `build_map`).

### `_FloodCache` and `prepare_flood_state` — three-layer caching

```python
@dataclass
class _FloodCache:
    seed:      int | None = None
    edges:     gpd.GeoDataFrame | None = None
    polylines: list[...] | None = None

_FLOOD_CACHE = _FloodCache()
```

A module-level singleton (lives in memory as long as the Python process is
alive). Holds the last used seed + its edges + polylines.

`prepare_flood_state` is the entry point. It tries three layers:

```
1. In-memory hit (seed matches _FLOOD_CACHE.seed)?
   YES → return _FLOOD_CACHE.edges and .polylines, done.

2. Disk hit (both flood polylines and edges pkl exist in .flood_cache/)?
   YES → load both pkl files, run write_weights_back_to_graph, return.
         Then populate _FLOOD_CACHE so next rerun is even faster.

3. Cache miss → randomly assign states, project to WGS84, persist to disk,
                populate _FLOOD_CACHE, return.
```

Why three layers? Memory is fastest. Disk avoids re-running the random
assignment (which is ~50 ms) and the projection (which is ~150 ms).
Full computation is rare (only first launch or visiting a new seed).

### What the dataclass `@dataclass` decorator does

```python
@dataclass
class _FloodCache:
    seed:      int | None = None
    ...
```

Python automatically generates `__init__(self, seed=None, edges=None,
polylines=None)`, `__repr__`, and `__eq__`. You just declare the fields.

### What `random.choices` does

`random.choices(population, weights=None, k=1)` — return a `k`-sized list
of elements chosen from `population` with probability `weights[i] /
sum(weights)`. So with `weights=[0.7, 0.2, 0.1]`, Clear has 70% chance,
Caution 20%, Impassable 10%.

---

## 11. Deep dive — `flood_app/ui.py`

This is the **only file the user sees**. It does four things:

1. Set up the page (title, hidden CSS, sidebar).
2. Read the user's input (text boxes, slider, buttons, map clicks).
3. Compute the route (calls into the other files).
4. Display the result (map + stats).

It is ~686 lines but it's mostly straightforward Streamlit.

### Imports & module docstring

```python
from __future__ import annotations      # makes type hints lazy
from typing import Any, Callable
import folium
import streamlit as st
from streamlit_folium import st_folium   # the bridging component

from .flood import FLOOD_STATES, prepare_flood_state
from .graph_loader import PLACE_NAME, get_tangail_graph_cached
from .routing import build_node_index, get_node_index_cached, ...
```

The relative imports (`from .flood import ...`) mean "from inside the
`flood_app` package". Equivalent to `from flood_app.flood import ...`
but more relocatable.

### The constants block (lines 38–54)

```python
DEFAULT_ORIGIN = (24.2513, 89.9167)
DEFAULT_DEST   = (24.2780, 89.9530)
MAP_HEIGHT     = 620

ROUTE_COLOR    = "#a569bd"
ROUTE_WEIGHT   = 6
ROUTE_OPACITY  = 0.75

PIN_ORIGIN_FILL,  PIN_ORIGIN_BORDER  = "#2ecc71", "#1e8449"
PIN_DEST_FILL,    PIN_DEST_BORDER    = "#e74c3c", "#922b21"
BANNER_HINT_ORIGIN, BANNER_HINT_NEXT, BANNER_HINT_DONE = "#1e8449", "#922b21", "#2c3e50"
```

These are the *only* place to change visual colours/coordinates. Lifting
literals to constants makes the code easier to tweak in one place.

### The `_HIDE_MAP_CHROME_CSS` block

Streamlit-folium hands you a full Leaflet map, which has dozens of
toolbar buttons we don't want (draw, edit, geocode, etc.). This is raw
CSS that hides them. `display: none !important;` means "no matter what
other CSS says, this element is not displayed".

You inject raw HTML/CSS into Streamlit via:

```python
st.markdown(_HIDE_MAP_CHROME_CSS, unsafe_allow_html=True)
```

The `unsafe_allow_html` flag is required because Streamlit sanitises user
content by default.

### `parse_input` — turn text into coords

```python
def parse_input(text: str, fallback):
    text = (text or "").strip()
    if not text:
        return fallback

    cache = st.session_state.setdefault("parse_cache", {})
    if text in cache:
        return cache[text]

    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) == 2:
            return (float(parts[0]), float(parts[1]))
    except ValueError:
        pass

    try:
        return tuple(ox.geocode(text))
    except Exception:
        return fallback
```

The user can type either:

1. `"24.25, 89.92"` — comma-separated lat/lng.
2. `"Dhaka"` — a place name (looked up via OSMnx's geocode which uses
   OpenStreetMap's Nominatim search).

The function tries (1) first; on failure, tries (2); on any failure,
returns the fallback.

**Critical perf detail**: results are cached in `st.session_state.parse_cache`
keyed by the input text. So typing `"Dhaka"` once, then triggering reruns
via map clicks or seed changes, doesn't re-hit OSMnx's geocode API each
time (which would otherwise be slow and rate-limited).

### `_resolve_endpoint` — pick text vs click coords

```python
def _resolve_endpoint(text_value, click_key):
    if (text_value or "").strip():
        typed = parse_input(text_value, None)
        if typed is not None:
            return typed
    return st.session_state.get(click_key)
```

The "merged input" rule: if the user typed anything in the sidebar,
that wins. Otherwise, use the map-click coordinate stored in
`session_state.click_origin` or `session_state.click_dest`. If neither is
set, return `None` (the map will render without a pin).

### `init_session_state` — populate `session_state` with defaults

`st.session_state` is a Python dict that Streamlit persists across reruns.
Like Flask's `g`, it's per-user, per-session. We initialise our keys
once on first launch:

```python
def init_session_state():
    defaults = {
        "origin_text_ver":  0,
        "dest_text_ver":    0,
        "click_origin":     None,
        "click_dest":       None,
        "click_phase":      "origin",
        "force_compute":    0,
        "timing_log":       [],
        "graph_info":       None,
        "flood_info":       None,
        "node_index_built": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
```

Why `if key not in st.session_state`? Because `init_session_state` is
called on *every rerun*, but reruns already have these keys set. So we
only fill in keys that are missing.

What do the keys mean?

- `origin_text_ver` / `dest_text_ver` — counter used to make the
  `text_input` widget re-mount with a fresh value (see
  `_set_widget_text`).
- `click_origin`, `click_dest` — last coords captured from a map click.
- `click_phase` — `"origin"` or `"dest"`; tells `handle_map_click`
  which pin to set next.
- `force_compute` — number of times the user clicked Compute. Routing
  only happens when this is > 0 (so typing in the sidebar doesn't
  automatically recompute).
- `timing_log` — list of `{"stage", "ms", "note"}` dicts for the
  performance expander.
- `graph_info`, `flood_info` — last result of those loaders, for the
  sidebar's timing display.
- `node_index_built` — so the timing log only shows "build node index"
  once.

### `_set_widget_text` — the version-counter trick

This is a subtle but important pattern. Here's the problem it solves:

> You have an `st.text_input` widget. The user clicks the map; you want
> the text box to update with the clicked coordinate. But Streamlit
> raises `StreamlitAPIException` if you write to
> `session_state.origin_text` after the widget has been instantiated.

The fix:

```python
def _set_widget_text(ver_key, widget_base, text):
    st.session_state[ver_key] += 1
    ver = st.session_state[ver_key]
    st.session_state[f"{widget_base}_v{ver}"] = text
```

1. Bump the version counter (`origin_text_ver` now becomes 1, was 0).
2. Pre-populate the new session_state key (`origin_text_v1`) with the
   target text.
3. On the next render, the `text_input` is constructed with
   `key=f"origin_text_v1"` and `value=st.session_state.get("origin_text_v1")`,
   so Streamlit sees a fresh widget at a fresh key and uses the
   pre-populated text as the default — no exception.

For Reset, we bump the version without pre-populating, so the new
widget at `v2` has `value=""` (the `.get(..., "")` default).

### `make_status_logger` — adapt anything-writeable to a logger

```python
def make_status_logger(target):
    def _log(msg):
        try:
            target.write(msg)
        except Exception:
            pass
    return _log
```

`st.sidebar.status(...)` returns an object with `.write()` (it shows a
new line in the collapsible status box). Plain `st` doesn't have a
targetable `.write` function, but it has `st.write`. We unify them so
the same callback signature works either way.

### `_render_pin_banner` — the click-prompt banner above the map

Builds a chunk of HTML with inline CSS showing:

- A green/red pin emoji for each endpoint.
- The coordinate value or "—" if not set.
- A coloured left border and hint text depending on state.

It's called once per rerun. Not expensive (small string concat), but if
you ever profile and find it hot, you could lift the static CSS to a
constant string injected once.

### `render()` — the main function

Most of the work happens here. Let me walk through it section by section.

#### Section 1: header

```python
init_session_state()
st.markdown(_HIDE_MAP_CHROME_CSS, unsafe_allow_html=True)

st.title("🌊 Flood Risk Routing Engine")
st.caption(...)
st.markdown("...intro paragraph...")
```

#### Section 2: sidebar

```python
with st.sidebar:
    st.header("🧭 Trip Planner")
    ...
    origin_text = st.text_input(..., key=f"origin_text_v{ver}", value=...)
    dest_text   = st.text_input(..., key=f"dest_text_v{ver}", value=...)
    seed        = st.slider(...)
    compute_clicked = st.button(...)
    reset_clicked   = st.button(...)
```

`with st.sidebar:` is Streamlit's "context manager" — everything inside
goes to the left panel.

The text inputs use the version-counter + `value=` trick so they can be
updated externally (see `_set_widget_text`).

The slider's value is captured into `seed`. Sliders re-fire on every
micro-movement, so we don't want a slider to *also* trigger a route
recompute — that's why `force_compute` is separate.

#### Section 3: button handlers

```python
if reset_clicked:
    st.session_state.origin_text_ver += 1
    st.session_state.dest_text_ver   += 1
    st.session_state.click_origin = None
    st.session_state.click_dest   = None
    st.session_state.click_phase  = "origin"

if compute_clicked:
    st.session_state.force_compute += 1
```

We don't do work in response to the click — we just bump a counter and
let the next render use it. This is the Streamlit idiom.

#### Section 4: parse + load + compute

```python
origin      = _resolve_endpoint(origin_text, "click_origin")
destination = _resolve_endpoint(dest_text,   "click_dest")
center_origin      = origin      or DEFAULT_ORIGIN
center_destination = destination or DEFAULT_DEST
push_timing("parse inputs", ...)

G, info = get_tangail_graph_cached()
st.session_state.graph_info = info
push_timing("load graph", ..., "cache" if info["from_cache"] else "download")

node_index = get_node_index_cached(G)
if not st.session_state.node_index_built:
    st.session_state.node_index_built = True
    push_timing("build node index", ...)

edges_gdf, polylines, flood_info = prepare_flood_state(G, seed)
st.session_state.flood_info = flood_info
push_timing("flood state", ...)

route_info, route_error = compute_route_cached(G, node_index, origin, destination, seed)
push_timing("compute route", ...)
```

Each pipeline step is wrapped in a `t0 = time.perf_counter()` /
`push_timing(stage, elapsed)` pair so the user can see milliseconds per
step in the performance expander.

#### Section 5: build map

```python
route_polyline = route_info["polyline"] if route_info is not None else None
m = build_map(
    center_origin=center_origin,
    center_destination=center_destination,
    polylines=polylines,
    origin=origin if origin is not None else None,
    destination=destination if destination is not None else None,
    route_polyline=route_polyline,
)
push_timing("build map object", ...)
```

`build_map` returns a Folium `Map` object. It doesn't render yet —
Folium objects build up a tree of DOM nodes; rendering happens when
Streamlit hands them to `st_folium`.

#### Section 6: render map + handle clicks

```python
st.markdown("### 🗺️ Map")
_render_pin_banner(origin, destination)
map_data = st_folium(
    m, width=None, height=MAP_HEIGHT,
    returned_objects=["last_clicked"], key="flood_map",
)
handle_map_click(map_data)
```

`st_folium` does three things:

1. Embeds the Folium map as an iframe.
2. (Optional) returns data about user interactions.
3. Reruns the script when something changes (e.g. the user pans/zooms
   enough, or clicks the map with `returned_objects=["last_clicked"]`).

`handle_map_click(map_data)` reads `map_data["last_clicked"]` and, if
present, updates session_state and calls `st.rerun()`.

#### Section 7: status / metrics

```python
if route_info is not None:
    st.success("✅ Safe route found!")
    stats = route_info["stats"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Route length", f"{stats['length']/1000:.2f} km")
    ...
elif route_error is not None:
    st.error(route_error)
elif (origin is None or destination is None) and st.session_state.get("force_compute", 0) > 0:
    missing = "Point A (Origin)" if origin is None else "Point B (Destination)"
    st.warning(f"⚠️ Click on the map to set **{missing}** ...")
```

Three states: success, error, "you forgot a pin". The warning only fires
when the user has clicked Compute (`force_compute > 0`) but pins aren't
both set — so they get a helpful message instead of a silent nothing.

### `build_map` — the Folium cartographer

```python
def build_map(center_origin, center_destination, polylines,
              origin=None, destination=None, route_polyline=None):
    center_lat = (center_origin[0] + center_destination[0]) / 2
    center_lng = (center_origin[1] + center_destination[1]) / 2
    m = folium.Map(location=[center_lat, center_lng], zoom_start=13, ...)
```

`folium.Map(...)` creates the map. `zoom_start=13` is about city-level
zoom. `tiles="cartodbpositron"` is the light grey basemap (so the
flood-coloured roads stand out).

#### The big batching optimization

```python
road_layer = folium.FeatureGroup(name="Road network (flood state)", show=True)
by_color: dict[str, list[list[list[float]]]] = {}
for color, coords in polylines:
    by_color.setdefault(color, []).append(coords)
for color, segments in by_color.items():
    folium.PolyLine(locations=segments, color=color, weight=2, opacity=0.75).add_to(road_layer)
```

Tangail has ~19,248 road segments. If we render each as its own PolyLine,
that's 19k DOM nodes + 19k JS event handlers in the browser — and the
browser visibly stutters.

The optimization: **group by colour first**, then create ONE PolyLine per
colour with all segments inside it. Since Tangail has only 3 flood
states, we go from ~19k objects down to 3.

Each `folium.PolyLine` accepts a list of *lists* of coordinates — when you
give it multiple disconnected shapes inside one PolyLine, it draws them
all in a single style/colour without overhead per-shape.

`folium.FeatureGroup` is just a logical group that we can toggle in the
LayerControl (you can hide the road network and just see the route).

#### Markers and route polyline

```python
if route_polyline:
    folium.PolyLine(locations=route_polyline, color=ROUTE_COLOR, ...).add_to(m)
if origin is not None:
    folium.Marker(location=origin, tooltip="Origin (A)",
                  icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(m)
```

`folium.Icon(color="green", icon="play", prefix="fa")` — the `prefix="fa"`
means "Font Awesome" icon set; `"play"` is a triangle.

### `handle_map_click` — capture map clicks

```python
def handle_map_click(map_data):
    if not map_data: return
    last = map_data.get("last_clicked")
    if not isinstance(last, dict): return
    lat = last.get("lat")
    lng = last.get("lng")
    if lat is None or lng is None: return

    clicked = (lat, lng)
    coord_text = f"{lat:.6f}, {lng:.6f}"
    if st.session_state.click_phase == "origin":
        if st.session_state.click_origin == clicked:
            return                       # ← ping-pong guard
        st.session_state.click_origin = clicked
        st.session_state.click_phase = "dest"
        _set_widget_text("origin_text_ver", "origin_text", coord_text)
    else:
        if st.session_state.click_dest == clicked:
            return                       # ← ping-pong guard
        st.session_state.click_dest = clicked
        st.session_state.click_phase = "origin"
        _set_widget_text("dest_text_ver", "dest_text", coord_text)

    st.rerun()
```

**The ping-pong guard** at `if click_origin == clicked: return`. Why?
`streamlit-folium` re-emits the last click on the rerun we trigger.
Without the guard, a single map click would:

1. Click A → handler sets origin=A, phase=dest, calls `st.rerun()`.
2. The rerun re-emits the same click. Handler now thinks "phase=dest, click=B"
   (because A is now the old click), so it sets dest=A, phase=origin,
   reruns again.
3. Infinite loop until the user closes the tab.

With the guard, step 2 sees `click_dest` is already `(24.25, 89.92)`
(matching the new click), bails early, no second rerun.

### `compute_route_cached` — the route cache

```python
def compute_route_cached(G, node_index, origin, destination, seed):
    if origin is None or destination is None:
        return None, None
    force = st.session_state.get("force_compute", 0)
    if force == 0:
        return None, None

    o_node = nearest_node(G, node_index, origin[0], origin[1])
    d_node = nearest_node(G, node_index, destination[0], destination[1])

    cache_key = ("route", seed, o_node, d_node)
    if cache_key in st.session_state:
        cached = st.session_state[cache_key]
        if isinstance(cached, dict) and "error" in cached:
            return None, cached["error"]
        return cached, None

    try:
        _, route_edges = shortest_path(G, o_node, d_node)
        polyline = route_polyline(G, route_edges)
        stats = route_stats(G, route_edges)
        result = {"polyline": polyline, "stats": stats}
        st.session_state[cache_key] = result
        return result, None
    except Exception as exc:
        if isinstance(exc, nx.NetworkXNoPath):
            msg = "❌ No route could be found..."
        else:
            msg = f"⚠️ Unexpected error while routing: {exc}"
        st.session_state[cache_key] = {"error": msg}
        return None, msg
```

Three jobs:

1. **Skip early** when there's nothing to compute.
2. **Hit the cache** by `(seed, origin_node, dest_node)`. This is why
   clicking Compute twice with the same points is instant.
3. **Compute on miss**, store result (or error message) in the cache.

Note: `force_compute` is NOT in the cache key. Even though each click
bumps it, we don't change the cache key, so repeat Compute clicks hit
cache.

---

## 12. Every performance optimization explained

This project went through several iterations of perf work. Here is every
optimization, listed in rough order of impact.

### 🚀 `#1: Fixed the `graph_exists` shadow bug`

**Before**:
```python
def graph_exists(graph_path):
    return graph_path.with_suffix(".pkl").exists() or graph_path.with_suffix(".graphml").exists()

def graph_exists(graph_path):   # shadows the above!
    return graph_path.exists()
```

Python silently uses whichever definition comes last. The second one
checks the canonical `<hash>.graphml` (which `save_graph` doesn't write),
so the existence check always returned `False`, forcing a full re-download
from OpenStreetMap on every cold launch. **5–20 s wasted.** Fixed by deleting
the duplicate.

### 🚀 `#2: @st.cache_resource on the graph loader`

```python
@st.cache_resource(show_spinner=False)
def get_tangail_graph_cached():
    return load_tangail_graph()
```

`@st.cache_resource` memoizes the function's *return value* across Streamlit
reruns. Without it, every rerun would re-pickle-deserialize the graph
(50–100 ms). With it, the first call costs that 50 ms; every subsequent
call is essentially free (microseconds — just a dict lookup).

The graph is heavy (5 MB pickled) and never changes during a session,
so caching it is safe.

### 🚀 `#3: get_node_index_cached — id-keyed memo for the spatial index`

```python
_NODE_INDEX_CACHE: dict[int, NodeIndex] = {}

def get_node_index_cached(G):
    key = id(G)
    cached = _NODE_INDEX_CACHE.get(key)
    if cached is not None: return cached
    idx = build_node_index(G)
    _NODE_INDEX_CACHE[key] = idx
    return idx
```

`id(G)` returns the unique id of a Python object. Since `G` always comes
from `@st.cache_resource`, it's the same object on every rerun. The
spatial index is computed once per session, not per rerun. Saves ~30 ms
per rerun.

### 🚀 `#4: `_FLOOD_CACHE` — in-memory flood cache`

```python
@dataclass
class _FloodCache:
    seed:      int | None = None
    edges:     gpd.GeoDataFrame | None = None
    polylines: list[...] | None = None

_FLOOD_CACHE = _FloodCache()
```

On warm reruns with the same seed, we skip:

- The disk read of `polylines.pkl` (80–150 ms).
- The disk read of `edges.pkl` (50–100 ms).
- The `write_weights_back_to_graph` loop (15–25 ms over 19k edges).

Total save: ~150 ms per rerun.

### 🚀 `#5: Drop `force` from the route cache key`

```python
cache_key = ("route", seed, o_node, d_node)   # NO force
```

Originally the key included `force` (the bumped-on-Compute counter),
which meant every Compute click was a cache *miss*. Removing it means
repeat Compute clicks hit cache. Saves 50–200 ms (the `shortest_path`
Dijkstra).

### 🚀 `#6: The `handle_map_click` ping-pong guard`

```python
if st.session_state.click_origin == clicked:
    return
```

`streamlit-folium` re-emits the last click on every rerun. Without this
guard, a single click triggers two reruns (and therefore two full graph
loads). With it, exactly one.

### 🚀 `#7: `build_map` batches polylines per colour`

Going from ~19,000 `folium.PolyLine` objects to 3 reduces the client-side
DOM weight from megabytes to kilobytes. The browser panning and zooming
goes from "stuttery" to "smooth".

### 🚀 `#8: `parse_cache` in session_state`

```python
cache = st.session_state.setdefault("parse_cache", {})
if text in cache:
    return cache[text]
```

If the user types the same place name many times, we only geocode it
once. Saves the 200-1000 ms OSMnx `ox.geocode` call on every rerun.

### 🚀 `#9: Atomic tmp+replace for cache writes`

```python
tmp = path.with_suffix(path.suffix + ".tmp")
with open(tmp, "wb") as fh:
    pickle.dump(G, fh, ...)
os.replace(tmp, path)
```

If the laptop crashes mid-write, the cache file is *never* a partial.
On the next launch it's either completely old or completely new.

### 🚀 `#10: `_resolve_endpoint` centralises the parse logic`

Before, there was duplicated origin-vs-destination parse logic. Extracting
the helper makes the code simpler and *marginally* faster (function-call
overhead is dwarfed by the saved `parse_input` cache hits).

### 🧹 `#11: No spinners on warm paths`

We only show spinners on first graph load. Warm reruns are silent. Every
`st.spinner` adds a tiny DOM round-trip, so we avoid them.

### 🧹 `#12: Lazy imports`

`import osmnx as ox` is inside `parse_input`, not at the top of the file.
`import networkx as nx` happens inside `compute_route_cached` and
`route_polyline`. This means importing `ui.py` is cheap, which matters
when Streamlit re-imports the module after edits.

### 🧹 `#13: 50-entry bound on `timing_log`**

```python
if len(st.session_state.timing_log) > 50:
    st.session_state.timing_log = st.session_state.timing_log[-50:]
```

Unbounded growth would eventually slow the app. 50 entries is enough for
the user to see the recent past without growing forever.

### 🧹 `#14: Module-level constants instead of repeated literals**

`ROUTE_COLOR`, `BANNER_HINT_NEXT`, etc. — instead of repeating `#a569bd`
inline. Negligible perf, big readability win.

---

## 13. Streamlit concepts used here

### `st.session_state`

A `dict` that persists across reruns. Per-user, per-session. Like Flask's
`g`, but persistent. Keys must be hashable (strings, ints, tuples of
hashables).

**Read**:
```python
if "click_origin" not in st.session_state:
    st.session_state.click_origin = None
lat = st.session_state.click_origin[0]
```

**Write**:
```python
st.session_state.force_compute += 1
```

**Cannot write to widget-owned keys**: After
`st.text_input("...", key="foo")`, you cannot do
`st.session_state.foo = "new"` — it raises `StreamlitAPIException`.
The version-counter trick in `_set_widget_text` is how we work around
this.

### `st.rerun()`

Tells Streamlit to throw away the current render and start from scratch.
Useful when you want the page to update *immediately* after a side
effect, instead of waiting for the next widget change to trigger a rerun.

### Reruns

Streamlit reruns the entire script top-to-bottom on every user interaction
(button click, slider drag, text edit, map click). This is by design — no
manual DOM diffing, no virtual DOM, no frameworks. Just rerun the script.

The cost of rerun is the cost of building a new Folium Map, running
`shortest_path`, etc. — hence all the perf work above.

### `st.cache_resource` vs `st.cache_data`

- `cache_resource`: stores *one* shared object (singleton). Use for
  graphs, database connections, ML models.
- `cache_data`: stores the function's *return value*, keyed on hashed
  arguments. Multiple versions possible. Use for DataFrames, dictionaries.

`@st.cache_resource` doesn't hash arguments (it doesn't need to — there's
only one instance). `@st.cache_data` does.

### `with st.sidebar:`

A context manager. Everything `st.X(...)` inside the block lands in the
left sidebar.

### `st.expander("...", expanded=False)`

A collapsible section. The user can click to expand; you can set the
default with `expanded=True`.

### `st.status("...", expanded=True)`

A fancy spinner with multi-line status. Each `.write(...)` adds a line.
Call `.update(label="...", state="complete")` to mark it done.

### `streamlit-folium`'s `last_clicked`

Returns a dict like `{"lat": 24.25, "lng": 89.92}` when the user clicks,
or `None` when they didn't. Plus a bunch of other return values
(bounding box, all clicked objects, etc.) — we only request the last
clicked.

---

## 14. Data formats and file shapes

### `edges` GeoDataFrame

A tabular structure where each row is a road edge. Columns:

| Column | Type | Meaning |
|---|---|---|
| `u`, `v`, `key` | int, int, int | The edge identifier (from, to, multi-edge index) |
| `osmid` | int (or list) | OpenStreetMap way ID |
| `length` | float | Edge length in meters |
| `geometry` | shapely | The shape of the road |
| (after flood.py) `flood_state` | str | `"Clear"` / `"Caution"` / `"Impassable"` |
| (after flood.py) `flood_color` | str | Hex color |
| (after flood.py) `flood_multiplier` | float | Cost multiplier |
| (after flood.py) `flood_weight` | float | `length × multiplier` |

### `G` (NetworkX MultiDiGraph)

A directed graph with multi-edges. Nodes have:

| Node attribute | Type | Meaning |
|---|---|---|
| `x` | float | Easting (in graph CRS, often UTM) |
| `y` | float | Northing |
| `osmid` | int | OSM node ID |
| (sometimes) `street_count` | int | Number of streets meeting at this intersection |

Edges (in the graph metadata) have:

| Edge attribute | Type | Meaning |
|---|---|---|
| `osmid` | int | OSM way ID |
| `length` | float | Edge length in meters |
| `geometry` | shapely | Actual shape |
| `name` | str | Street name |
| `highway` | str | OSM highway tag (`primary`, `residential`, etc.) |
| `flood_weight` | float | Added by flood.py; routing uses this |
| `flood_state` | str | Added by flood.py; for stats |

### `polylines` list

```python
[(color, [[lat, lng], [lat, lng], ...]), ...]
```

A flat list. Each entry is one road segment coloured by flood state.
Total length ~19,248 for Tangail.

---

## 15. Glossary of advanced terms

| Term | Meaning |
|---|---|
| **Annotation** | A Python type hint, `: int` on a function signature. Not enforced at runtime unless you use a type checker like `mypy`. |
| **PEP 8** | The official Python style guide. We mostly follow it. |
| **PR** | Pull request — a proposed change to a shared codebase. |
| **CRS** | Coordinate Reference System. Mathematically, a way to map (lat, lng) ↔ (x, y) on a 2D plane. |
| **EPSG code** | A standard numeric ID for CRSes. 4326 = WGS84. 32645 = UTM zone 45N. |
| **GeoJSON** | A JSON-based format for geographic features. Not used here but related to the .graphml files. |
| **Nominatim** | OpenStreetMap's geocoder — "Dhaka" → (lat, lng). |
| **Dijkstra's algorithm** | The shortest-path algorithm NetworkX uses for non-negative weights. O(E log V). |
| **A\* (A-star)** | A faster shortest-path algorithm when you have a heuristic (e.g. straight-line distance). We could use it but our graph is small enough that Dijkstra is fine. |
| **Degenerate cell** | An empty bucket in the spatial grid. The defensive fallback in `NodeIndex.nearest` handles a query that lands in a degenerate cell. |
| **MultiDiGraph** | A NetworkX graph that allows multiple edges between the same two nodes (think divided highway) and direction (one-way streets). |
| **TOCTOU** | Time-of-check to time-of-use. A class of bugs where you check existence, then operate, and between the two the file changes. Atomic operations (`os.replace`) avoid it. |
| **Memoization** | Caching the result of a function call based on its arguments. `@functools.cache`, `@st.cache_data`, `@st.cache_resource` are all memoizers. |
| **Decorator** | A function that takes another function and returns a wrapped version. `@st.cache_resource` is a decorator. The `@` syntax is syntactic sugar: `@decorator\ndef fn(): ...` is `fn = decorator(fn)`. |
| **`from __future__ import annotations`** | Make type hints strings rather than evaluated types. Allows forward references, `list[int]` on Python 3.8, and avoids import cycles. |
| **Context manager** | An object that you use with `with`: it has `__enter__` and `__exit__` methods. `st.sidebar`, `open(...)`, `st.status(...)` are all context managers. |
| **`st.rerun()`** | Forces Streamlit to re-execute the whole script right now, instead of waiting for the next widget change. |
| **`streamlit-folium`** | A community-built Streamlit component that wraps Folium. Lets you embed interactive maps and receive click events. |
| **`# noqa`** | "No quality assurance" — a comment that tells linters (like flake8) to ignore the line's warnings. We use `# noqa: E731` when assigning a lambda. |
| **`tuple` vs `list`** | Tuples are immutable (can't be appended to, can't change length). Lists are mutable. Tuples are hashable (can be dict keys); lists aren't. |

---

## 16. Exercises for the curious

1. **Add a "Cautions only" mode**: render the route in a different colour
   when it uses zero Caution edges ("all-green route!").
2. **Add multiple seeds at once**: let the user pin multiple seeds and
   overlay the resulting flood networks in different translucencies.
3. **Make the city configurable**: a sidebar text input where the user
   types `"Dhaka, Bangladesh"` and the app downloads the new graph.
4. **Switch to A\***: add a heuristic to `nx.astar_path` and compare
   timing in the perf expander.
5. **Persist the slider state**: if `seed=42` produces a nice route,
   remember it across browser refreshes via Streamlit's URL query string.
6. **Add elevation**: download the GraphML from a different source that
   includes elevation, and colour-code the route by climb.
7. **Export the route as GeoJSON**: a button that lets the user download
   the route line for use in QGIS or Google Earth.

---

That's it. You now know everything in this codebase. Run it, change it,
break it, fix it. The flood router is yours.
