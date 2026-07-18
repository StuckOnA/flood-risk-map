"""Streamlit UI for the Flood Risk Routing Engine.

Layout:
    - Header
    - Sidebar: origin/destination text inputs, seed slider, compute button,
      legend, status / timing log.
    - Centre: Folium map with click-to-set support, color-coded road
      network, origin/destination markers, route polyline.

We deliberately avoid ``st.rerun()`` — every Streamlit rerun already
re-renders the whole page, so we just update ``session_state`` and let
the next natural rerun pick up the changes. This is the single biggest
perf fix over the previous version.
"""

from __future__ import annotations

from typing import Any, Callable

import folium
import streamlit as st
from streamlit_folium import st_folium

from .flood import (
    FLOOD_STATES,
    prepare_flood_state,
)
from .graph_loader import PLACE_NAME, load_tangail_graph
from .routing import (
    build_node_index,
    nearest_node,
    route_polyline,
    route_stats,
    shortest_path,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_ORIGIN = (24.2513, 89.9167)  # Tangail city center
DEFAULT_DEST   = (24.2780, 89.9530)  # Tangail Sadar / east side
MAP_HEIGHT     = 620


# ---------------------------------------------------------------------------
# Hidden CSS for clean map chrome (no JS observers, no rerenders)
# ---------------------------------------------------------------------------
_HIDE_MAP_CHROME_CSS = """
<style id="hide-map-chrome">
.leaflet-draw, .leaflet-draw-toolbar, .leaflet-bar.leaflet-draw-toolbar,
.leaflet-control-draw, .leaflet-pm-toolbar, .leaflet-pm-icons-container,
a.leaflet-pm-icon, .leaflet-pm-icon,
.leaflet-pm-icon-marker, .leaflet-pm-icon-polyline, .leaflet-pm-icon-rectangle,
.leaflet-pm-icon-circle, .leaflet-pm-icon-edit, .leaflet-pm-icon-delete,
.leaflet-pm-icon-drag, .leaflet-pm-icon-cut, .leaflet-pm-icon-rotate,
.leaflet-pm-icon-text,
.leaflet-control-locate, .leaflet-control-measure, .leaflet-control-search,
.leaflet-control-minimap, .leaflet-control-easyprint,
.leaflet-control-mouseposition, .leaflet-control-coordinate,
.leaflet-control-geocoder, .leaflet-control-zoomhistory,
.leaflet-control-permalink, .leaflet-control-bookmarks,
.leaflet-control-button, .leaflet-control-toolbar,
.leaflet-bar a:not(.leaflet-control-zoom-in):not(.leaflet-control-zoom-out) {
    display: none !important;
    visibility: hidden !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
}
.glyphicon { display: none !important; }
.leaflet-control-attribution {
    font-size: 9px !important;
    opacity: 0.55 !important;
    padding: 0 4px !important;
}
</style>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_input(text: str, fallback: tuple[float, float]) -> tuple[float, float]:
    """Parse 'lat, lng' or fall back to OSM geocoding, then to fallback."""
    import osmnx as ox

    text = (text or "").strip()
    if not text:
        return fallback
    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) == 2:
            return (float(parts[0]), float(parts[1]))
    except ValueError:
        pass
    try:
        return tuple(ox.geocode(text))  # type: ignore[return-value]
    except Exception:
        return fallback


def init_session_state() -> None:
    """Initialise the keys we depend on, exactly once per session."""
    defaults = {
        "origin_text":     f"{DEFAULT_ORIGIN[0]}, {DEFAULT_ORIGIN[1]}",
        "dest_text":       f"{DEFAULT_DEST[0]}, {DEFAULT_DEST[1]}",
        "click_origin":    DEFAULT_ORIGIN,
        "click_dest":      DEFAULT_DEST,
        "click_phase":     "origin",     # next click sets origin/dest
        "last_click_sig":  None,
        "auto_route":      True,         # auto-route when both clicks exist
        "force_compute":   0,            # bump to force recomputation
        "timing_log":      [],
        "graph_info":      None,
        "flood_info":      None,
        "node_index_built": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def push_timing(stage: str, ms: float, note: str = "") -> None:
    """Append a timing entry. Shown as a small table in the sidebar."""
    entry = {"stage": stage, "ms": round(ms, 1), "note": note}
    st.session_state.timing_log.append(entry)
    if len(st.session_state.timing_log) > 50:
        # Keep the log bounded.
        st.session_state.timing_log = st.session_state.timing_log[-50:]


def make_status_logger(target) -> Callable[[str], None]:
    """Return a callable that writes status messages into a streamlit container.

    ``target`` may be a plain ``st`` module (uses ``st.write``) or any object
    with a ``.write(str)`` method (e.g. ``st.status``, ``st.empty``).
    """
    def _log(msg: str) -> None:
        try:
            target.write(msg)
        except Exception:
            pass
    return _log


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------
def render() -> None:
    init_session_state()
    st.markdown(_HIDE_MAP_CHROME_CSS, unsafe_allow_html=True)

    # --- Header --------------------------------------------------------
    st.title("🌊 Flood Risk Routing Engine")
    st.caption(
        f"Prototype · {PLACE_NAME} · Flood-aware shortest-path routing "
        "on OpenStreetMap data"
    )
    st.markdown(
        """
        This prototype simulates **dynamic flood conditions** across the road
        network of *Tangail, Bangladesh*. Each road segment is randomly
        classified as **Clear**, **Caution**, or **Impassable**, and a flood-
        adjusted travel cost is computed. The route planner then avoids
        impassable roads and prefers safe, clear ones.
        """
    )

    # --- Sidebar -------------------------------------------------------
    with st.sidebar:
        st.header("🧭 Trip Planner")

        st.subheader("Origin")
        origin_text = st.text_input(
            "Place name or coordinates (lat, lng)",
            key="origin_text",
            help="Paste 'lat, lng' or a place name. Click on the map to override.",
        )

        st.subheader("Destination")
        dest_text = st.text_input(
            "Place name or coordinates (lat, lng)",
            key="dest_text",
            help="Paste 'lat, lng' or a place name. Click on the map to override.",
        )

        seed = st.slider("Random flood-pattern seed", 1, 100, 42)

        compute_clicked = st.button(
            "🚀 Compute Safe Route", type="primary", use_container_width=True
        )
        reset_clicked = st.button(
            "♻️ Reset to defaults", use_container_width=True
        )

        # Click-to-set hint
        next_phase = st.session_state.click_phase
        if next_phase == "origin":
            st.caption(
                "💡 **Click on the map** to set the **origin** (point A)."
            )
        else:
            st.caption(
                "💡 **Click on the map** to set the **destination** (point B)."
            )

        st.divider()
        with st.expander("Legend", expanded=False):
            for name, meta in FLOOD_STATES.items():
                st.markdown(
                    f"<span style='color:{meta['color']};font-weight:600'>■</span> "
                    f"**{name}** — {int(meta['prob']*100)}% chance — "
                    f"weight ×{meta['multiplier']}",
                    unsafe_allow_html=True,
                )
            st.markdown(
                "<span style='color:#5b2c6f;font-weight:600'>■</span> "
                "**Route** — computed optimal safe route",
                unsafe_allow_html=True,
            )

        st.divider()
        with st.expander("⏱ Performance", expanded=True):
            log = st.session_state.timing_log
            if not log:
                st.caption("No timings yet — interact with the app to populate.")
            else:
                # Last 10 entries, newest first
                for entry in reversed(log[-10:]):
                    ms = entry["ms"]
                    badge = (
                        "🟢" if ms < 50
                        else "🟡" if ms < 200
                        else "🔴" if ms < 1000
                        else "⏳"
                    )
                    st.caption(f"{badge} **{entry['stage']}** — {ms:.0f} ms")

            info_g = st.session_state.graph_info
            if info_g:
                st.caption(
                    f"Graph: {info_g['nodes']:,} nodes, {info_g['edges']:,} edges — "
                    f"{'cache' if info_g['from_cache'] else 'download'} "
                    f"({info_g['elapsed_ms']:.0f} ms)"
                )
            info_f = st.session_state.flood_info
            if info_f:
                st.caption(
                    f"Flood polylines (seed {info_f['seed']}): "
                    f"{info_f['polylines']:,} — "
                    f"{'cache' if info_f['from_cache'] else 'build'} "
                    f"({info_f['elapsed_ms']:.0f} ms)"
                )

    # --- Reset button --------------------------------------------------
    if reset_clicked:
        st.session_state.origin_text = f"{DEFAULT_ORIGIN[0]}, {DEFAULT_ORIGIN[1]}"
        st.session_state.dest_text   = f"{DEFAULT_DEST[0]}, {DEFAULT_DEST[1]}"
        st.session_state.click_origin = DEFAULT_ORIGIN
        st.session_state.click_dest   = DEFAULT_DEST
        st.session_state.click_phase  = "origin"
        st.session_state.last_click_sig = None
        st.session_state.auto_route   = True
        st.session_state.force_compute += 1

    # --- Force recompute when the user explicitly clicks Compute -----
    if compute_clicked:
        st.session_state.force_compute += 1

    # --- Parse origin / destination -----------------------------------
    import time
    t0 = time.perf_counter()
    text_origin      = parse_input(st.session_state.origin_text, DEFAULT_ORIGIN)
    text_destination = parse_input(st.session_state.dest_text,   DEFAULT_DEST)
    origin      = st.session_state.click_origin    or text_origin
    destination = st.session_state.click_dest      or text_destination
    push_timing("parse inputs", (time.perf_counter() - t0) * 1000)

    # --- Load graph (disk-cached) -------------------------------------
    t0 = time.perf_counter()
    progress = st.sidebar.status(
        "🛰️  Fetching Tangail road network…", expanded=True
    )
    log = make_status_logger(progress)
    try:
        G, info = load_tangail_graph(_status=log)
    finally:
        progress.update(label="Road network ready", state="complete", expanded=False)
    st.session_state.graph_info = info
    push_timing(
        "load graph",
        (time.perf_counter() - t0) * 1000,
        "cache" if info["from_cache"] else "download",
    )

    # --- Build spatial index for nearest-node (once per graph) --------
    t0 = time.perf_counter()
    node_index = build_node_index(G)
    push_timing("build node index", (time.perf_counter() - t0) * 1000)

    # --- Apply / load flood state --------------------------------------
    t0 = time.perf_counter()
    edges_gdf, polylines, flood_info = prepare_flood_state(G, seed)
    st.session_state.flood_info = flood_info
    push_timing(
        "flood state",
        (time.perf_counter() - t0) * 1000,
        "cache" if flood_info["from_cache"] else "build",
    )

    # --- Build folium map ---------------------------------------------
    t0 = time.perf_counter()
    m = build_map(origin, destination, polylines)
    push_timing("build map object", (time.perf_counter() - t0) * 1000)

    # --- Routing (cached by node-pair + seed) -------------------------
    t0 = time.perf_counter()
    route_info, route_error = compute_route_cached(
        G, node_index, origin, destination, seed
    )
    push_timing("compute route", (time.perf_counter() - t0) * 1000)

    # If we have a route, draw it on the map.
    if route_info is not None:
        folium.PolyLine(
            locations=route_info["polyline"],
            color="#5b2c6f",
            weight=7,
            opacity=0.95,
            tooltip="Computed flood-safe route",
        ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # --- Render the map + process clicks ------------------------------
    st.markdown("### 🗺️ Map")
    map_data = st_folium(
        m, width=None, height=MAP_HEIGHT,
        returned_objects=["last_clicked"], key="flood_map",
    )
    handle_map_click(map_data)

    # --- Stats / status ----------------------------------------------
    if route_info is not None:
        st.success("✅ Safe route found!")
        stats = route_info["stats"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Route length", f"{stats['length']/1000:.2f} km")
        c2.metric("Flood cost", f"{stats['cost']:,.0f}")
        c3.metric("Edges used", stats["edges"])
        c4.metric(
            "Composition",
            f"🟢{stats['clear']} 🟠{stats['caut']} 🔴{stats['impa']}",
        )
    elif route_error is not None:
        st.error(route_error)

    # --- Footer -------------------------------------------------------
    st.divider()
    with st.expander("About this prototype", expanded=False):
        st.markdown(
            """
            **How it works**
            1. The drivable road network of *Tangail, Bangladesh* is downloaded
               from OpenStreetMap via `osmnx` and **persisted to disk** under
               `.flood_cache/graph/` so subsequent launches read it instantly.
            2. Each road segment is randomly assigned a **flood state** with
               these probabilities:
               - 🟢 Clear — 70 % — weight ×1
               - 🟠 Caution — 20 % — weight ×2
               - 🔴 Impassable — 10 % — weight ×999 999
            3. The flood polylines are **cached to disk per seed** under
               `.flood_cache/flood/`. Switching seeds is instant after the
               first visit.
            4. `networkx.shortest_path` is run with `weight="flood_weight"`,
               producing a route that avoids blocked roads and prefers safe
               ones. The result is keyed by `(origin_node, dest_node, seed)`
               so repeat requests hit a tiny in-memory cache.
            5. The map is rendered by Folium with the underlying network
               colour-coded by its flood state.

            **Tech stack:** Streamlit · OSMnx · NetworkX · GeoPandas · Folium ·
            streamlit-folium.
            """
        )


# ---------------------------------------------------------------------------
# Map building
# ---------------------------------------------------------------------------
def build_map(
    origin: tuple[float, float],
    destination: tuple[float, float],
    polylines: list[tuple[str, list[list[float]]]],
) -> folium.Map:
    """Construct the Folium map: road network, origin/dest markers."""
    center_lat = (origin[0] + destination[0]) / 2
    center_lng = (origin[1] + destination[1]) / 2
    m = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=13,
        tiles="cartodbpositron",
        control_scale=True,
    )
    road_layer = folium.FeatureGroup(name="Road network (flood state)", show=True)
    for color, coords in polylines:
        # ``coords`` is [[lat, lng], ...]
        folium.PolyLine(
            locations=coords, color=color, weight=2, opacity=0.75,
        ).add_to(road_layer)
    road_layer.add_to(m)

    folium.Marker(
        location=origin,
        tooltip="Origin (A)",
        icon=folium.Icon(color="green", icon="play", prefix="fa"),
    ).add_to(m)
    folium.Marker(
        location=destination,
        tooltip="Destination (B)",
        icon=folium.Icon(color="red", icon="stop", prefix="fa"),
    ).add_to(m)
    return m


# ---------------------------------------------------------------------------
# Click handling
# ---------------------------------------------------------------------------
def handle_map_click(map_data: dict | None) -> None:
    """Update click_origin / click_dest in session_state from a map click.

    No ``st.rerun()`` here — the natural rerun on next interaction picks
    up the new state. We detect a *new* click by hashing the click coords
    and comparing to the last one we processed.
    """
    if not map_data:
        return
    last = map_data.get("last_clicked")
    if not isinstance(last, dict):
        return
    lat = last.get("lat")
    lng = last.get("lng")
    if lat is None or lng is None:
        return

    sig = (round(lat, 6), round(lng, 6))
    if sig == st.session_state.last_click_sig:
        return  # Same click as last time — no-op
    st.session_state.last_click_sig = sig

    if st.session_state.click_phase == "origin":
        st.session_state.click_origin = (lat, lng)
        st.session_state.click_dest = None  # force re-pick
        st.session_state.click_phase = "dest"
        st.session_state.auto_route = False  # wait for second click
    else:
        st.session_state.click_dest = (lat, lng)
        st.session_state.click_phase = "origin"
        st.session_state.auto_route = True   # compute immediately


# ---------------------------------------------------------------------------
# Routing cache
# ---------------------------------------------------------------------------
def compute_route_cached(
    G, node_index, origin, destination, seed
):
    """Compute a route, caching by (origin_node, dest_node, seed, force_compute)."""
    import time

    force = st.session_state.get("force_compute", 0)

    # Skip if both points haven't been set yet.
    if origin is None or destination is None:
        return None, None

    auto_route = st.session_state.get("auto_route", False)
    if not auto_route and force == 0:
        return None, None

    t0 = time.perf_counter()
    o_node = nearest_node(G, node_index, origin[0], origin[1])
    d_node = nearest_node(G, node_index, destination[0], destination[1])
    push_timing("nearest_node (×2)", (time.perf_counter() - t0) * 1000)

    cache_key = ("route", seed, force, o_node, d_node)
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
        # Once we've successfully routed, the user has to explicitly click
        # Compute again to re-route.
        st.session_state.auto_route = False
        return result, None
    except Exception as exc:
        import networkx as nx
        if isinstance(exc, nx.NetworkXNoPath):
            msg = (
                "❌ No route could be found between the origin and destination. "
                "At least one road along every possible path is marked "
                "**Impassable**. Try changing the random seed and recomputing."
            )
        else:
            msg = f"⚠️ Unexpected error while routing: {exc}"
        st.session_state[cache_key] = {"error": msg}
        return None, msg