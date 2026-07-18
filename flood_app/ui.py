"""Streamlit UI for the Flood Risk Routing Engine.

Layout:
    - Header
    - Sidebar: origin/destination text inputs, seed slider, compute button,
      legend, status / timing log.
    - Centre: Folium map with click-to-set support, color-coded road
      network, origin/destination markers, route polyline.

We avoid ``st.rerun()`` for state updates fired by widget callbacks that
re-fire every rerun (sliders, text inputs), but call it explicitly from
``handle_map_click`` so the pin visibly moves on the same interaction.
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
from .graph_loader import PLACE_NAME, get_tangail_graph_cached
from .routing import (
    build_node_index,
    get_node_index_cached,
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

# Route polyline color — a lighter, more translucent purple so the
# underlying flood-coloured road network is still visible underneath.
ROUTE_COLOR = "#a569bd"
ROUTE_WEIGHT = 6
ROUTE_OPACITY = 0.75

# Pin-banner palette (border is the dark variant of the fill).
PIN_ORIGIN_FILL,  PIN_ORIGIN_BORDER  = "#2ecc71", "#1e8449"
PIN_DEST_FILL,    PIN_DEST_BORDER    = "#e74c3c", "#922b21"
BANNER_HINT_ORIGIN, BANNER_HINT_NEXT, BANNER_HINT_DONE = "#1e8449", "#922b21", "#2c3e50"


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
    """Parse 'lat, lng' or fall back to OSM geocoding, then to fallback.

    Cached by the input text in ``session_state.parse_cache`` so repeat
    reruns with the same sidebar text skip both the split-parse and any
    network geocode call.
    """
    import osmnx as ox

    text = (text or "").strip()
    if not text:
        return fallback

    cache = st.session_state.setdefault("parse_cache", {})
    if text in cache:
        return cache[text]

    result = fallback
    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) == 2:
            result = (float(parts[0]), float(parts[1]))
            cache[text] = result
            return result
    except ValueError:
        pass
    try:
        result = tuple(ox.geocode(text))  # type: ignore[return-value]
        cache[text] = result
        return result
    except Exception:
        return fallback


def _resolve_endpoint(
    text_value: str, click_key: str
) -> tuple[float, float] | None:
    """Resolve an endpoint from sidebar text or map-click coords.

    Returns the typed coords when ``text_value`` is non-empty, else the
    session_state click pin under ``click_key``. Returns None when
    neither is set so the caller can render an un-pinned map.
    """
    if (text_value or "").strip():
        typed = parse_input(text_value, None)
        if typed is not None:
            return typed
    return st.session_state.get(click_key)


def init_session_state() -> None:
    """Initialise the keys we depend on, exactly once per session.

    On launch, both click pins are unset so the user is prompted to
    click the map to set Point A, then Point B. The ``text_input`` widgets
    carry their own version counter (``origin_text_ver`` / ``dest_text_ver``)
    so the Reset button — and a map click — can swap the widget to a
    fresh key pre-populated with the new value, without touching the
    widget-owned state Streamlit forbids us to mutate.
    """
    defaults = {
        "origin_text_ver":  0,
        "dest_text_ver":    0,
        "click_origin":     None,     # set by first map click
        "click_dest":       None,     # set by second map click
        "click_phase":      "origin", # next click sets origin/dest
        "force_compute":    0,        # only the Compute button bumps this
        "timing_log":       [],
        "graph_info":       None,
        "flood_info":       None,
        "node_index_built": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _set_widget_text(ver_key: str, widget_base: str, text: str) -> None:
    """Swap the text_input at ``{widget_base}_v{ver_key}`` to show ``text``.

    Bumps the version counter and pre-populates ``session_state`` with
    the new key's *default* value. Streamlit treats that key as fresh
    on the next render, so the widget re-mounts and displays ``text``
    without raising StreamlitAPIException for mutating widget-owned state.
    """
    st.session_state[ver_key] += 1
    ver = st.session_state[ver_key]
    st.session_state[f"{widget_base}_v{ver}"] = text


def push_timing(stage: str, ms: float, note: str = "") -> None:
    """Append a timing entry. Shown as a small table in the sidebar."""
    entry = {"stage": stage, "ms": round(ms, 1), "note": note}
    st.session_state.timing_log.append(entry)
    if len(st.session_state.timing_log) > 50:
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


def _fmt_coord(point: tuple[float, float] | None) -> str:
    """Format a (lat, lng) tuple for display, or '—' when None."""
    if point is None:
        return "—"
    return f"{point[0]:.5f}, {point[1]:.5f}"


def _render_pin_banner(
    origin: tuple[float, float] | None,
    destination: tuple[float, float] | None,
) -> None:
    """Render the click-prompt banner above the map.

    Shows the current pin coordinates and what the next click will set.
    """
    if origin is None and destination is None:
        hint = "👇 **Click on the map to set Point A (Origin).**"
        hint_color = BANNER_HINT_ORIGIN
    elif destination is None:
        hint = "👇 **Now click to set Point B (Destination).**"
        hint_color = BANNER_HINT_NEXT
    else:
        hint = "✅ Both pins are set. Adjust by clicking, or press **🚀 Compute Safe Route**."
        hint_color = BANNER_HINT_DONE

    pins_html = (
        f'<span style="display:inline-flex;align-items:center;gap:6px;">'
        f'<span style="display:inline-block;width:12px;height:12px;'
        f'border-radius:50%;background:{PIN_ORIGIN_FILL};border:2px solid {PIN_ORIGIN_BORDER};"></span>'
        f'<b>Origin:</b> {_fmt_coord(origin)}</span>'
        f'<span style="display:inline-flex;align-items:center;gap:6px;">'
        f'<span style="display:inline-block;width:12px;height:12px;'
        f'border-radius:50%;background:{PIN_DEST_FILL};border:2px solid {PIN_DEST_BORDER};"></span>'
        f'<b>Destination:</b> {_fmt_coord(destination)}</span>'
    )

    st.markdown(
        f'<div style="border:1px solid #e1e4e8;border-left:5px solid {hint_color};'
        f'border-radius:6px;padding:12px 16px;margin:4px 0 8px 0;background:#fff;'
        f'box-shadow:0 1px 2px rgba(0,0,0,0.04);">'
        f'<div style="font-weight:600;font-size:15px;color:{hint_color};'
        f'margin-bottom:8px;">{hint}</div>'
        f'<div style="display:flex;gap:24px;flex-wrap:wrap;font-size:13px;'
        f'color:#333;font-family:monospace;">{pins_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


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
        # The widget key is versioned so a map click or Reset can give the
        # input a fresh key (and thus a fresh value) without Streamlit
        # complaining about us mutating widget-owned state. The ``value=``
        # reads from the *new* key (pre-populated by _set_widget_text if
        # a click just bumped the version), so the clicked coord appears
        # in the sidebar on the same click.
        _origin_ver = st.session_state.origin_text_ver
        origin_text = st.text_input(
            "Place name or coordinates (lat, lng)",
            value=st.session_state.get(f"origin_text_v{_origin_ver}", ""),
            key=f"origin_text_v{_origin_ver}",
            help="Paste 'lat, lng' or a place name. Click on the map to override.",
        )

        st.subheader("Destination")
        _dest_ver = st.session_state.dest_text_ver
        dest_text = st.text_input(
            "Place name or coordinates (lat, lng)",
            value=st.session_state.get(f"dest_text_v{_dest_ver}", ""),
            key=f"dest_text_v{_dest_ver}",
            help="Paste 'lat, lng' or a place name. Click on the map to override.",
        )

        seed = st.slider("Random flood-pattern seed", 1, 100, 42)

        compute_clicked = st.button(
            "🚀 Compute Safe Route", type="primary", use_container_width=True
        )
        reset_clicked = st.button(
            "♻️ Reset to defaults", use_container_width=True
        )

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
                f"<span style='color:{ROUTE_COLOR};font-weight:600'>■</span> "
                "**Route** — computed optimal safe route",
                unsafe_allow_html=True,
            )

        st.divider()
        with st.expander("⏱ Performance", expanded=True):
            log = st.session_state.timing_log
            if not log:
                st.caption("No timings yet — interact with the app to populate.")
            else:
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

    if reset_clicked:
        # Bump widget keys so the inputs re-render with empty values;
        # we can't write widget-owned state directly — Streamlit raises
        # StreamlitAPIException.
        st.session_state.origin_text_ver += 1
        st.session_state.dest_text_ver   += 1
        st.session_state.click_origin = None
        st.session_state.click_dest   = None
        st.session_state.click_phase  = "origin"

    if compute_clicked:
        st.session_state.force_compute += 1

    # Parse origin / destination. Typed text wins over click coords;
    # otherwise pins default to None and we fall back to constants below
    # just for map centering.
    import time
    t0 = time.perf_counter()
    origin      = _resolve_endpoint(origin_text, "click_origin")
    destination = _resolve_endpoint(dest_text,   "click_dest")
    center_origin      = origin      or DEFAULT_ORIGIN
    center_destination = destination or DEFAULT_DEST
    push_timing("parse inputs", (time.perf_counter() - t0) * 1000)

    # Load graph (Streamlit resource-cached). First-launch spinners go
    # in the sidebar where the user is looking; warm loads are silent.
    t0 = time.perf_counter()
    needs_loading = st.session_state.graph_info is None
    if needs_loading:
        graph_spinner = st.sidebar.status(
            "🛰️  Fetching Tangail road network…", expanded=True
        )
        log = make_status_logger(graph_spinner)
    else:
        graph_spinner = None
        log = lambda _msg: None  # noqa: E731 — silent no-op logger
    try:
        G, info = get_tangail_graph_cached()
    finally:
        if graph_spinner is not None:
            graph_spinner.update(
                label="Road network ready", state="complete", expanded=False
            )
    if st.session_state.graph_info is None:
        st.session_state.graph_info = info
    push_timing(
        "load graph",
        (time.perf_counter() - t0) * 1000,
        "cache" if info["from_cache"] else "download",
    )

    # Spatial index (built once per graph instance).
    t0 = time.perf_counter()
    node_index = get_node_index_cached(G)
    if not st.session_state.node_index_built:
        st.session_state.node_index_built = True
        push_timing("build node index", (time.perf_counter() - t0) * 1000)

    # Apply / load flood state.
    t0 = time.perf_counter()
    edges_gdf, polylines, flood_info = prepare_flood_state(G, seed)
    st.session_state.flood_info = flood_info
    push_timing(
        "flood state",
        (time.perf_counter() - t0) * 1000,
        "cache" if flood_info["from_cache"] else "build",
    )

    # Routing (cached by node-pair + seed).
    t0 = time.perf_counter()
    route_info, route_error = compute_route_cached(
        G, node_index, origin, destination, seed
    )
    push_timing("compute route", (time.perf_counter() - t0) * 1000)

    # Build folium map.
    t0 = time.perf_counter()
    route_polyline = route_info["polyline"] if route_info is not None else None
    m = build_map(
        center_origin=center_origin,
        center_destination=center_destination,
        polylines=polylines,
        origin=origin if origin is not None else None,
        destination=destination if destination is not None else None,
        route_polyline=route_polyline,
    )
    push_timing("build map object", (time.perf_counter() - t0) * 1000)

    st.markdown("### 🗺️ Map")
    _render_pin_banner(origin, destination)
    map_data = st_folium(
        m, width=None, height=MAP_HEIGHT,
        returned_objects=["last_clicked"], key="flood_map",
    )
    handle_map_click(map_data)

    # Stats / status.
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
    elif (
        origin is None or destination is None
    ) and st.session_state.get("force_compute", 0) > 0:
        # User clicked Compute before setting both pins.
        missing = "Point A (Origin)" if origin is None else "Point B (Destination)"
        st.warning(
            f"⚠️ Click on the map to set **{missing}** before computing a route."
        )

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
    center_origin: tuple[float, float],
    center_destination: tuple[float, float],
    polylines: list[tuple[str, list[list[float]]]],
    origin: tuple[float, float] | None = None,
    destination: tuple[float, float] | None = None,
    route_polyline: list[list[float]] | None = None,
) -> folium.Map:
    """Construct the Folium map: road network, origin/dest markers, route.

    ``center_origin`` and ``center_destination`` are always set — they're
    used to compute the map's centre/zoom. The actual pin markers are
    only drawn when ``origin`` / ``destination`` are not None, so a
    fresh launch (no clicks yet) renders a clean map without markers.
    ``route_polyline``, if set, is drawn on top of the road network.
    """
    center_lat = (center_origin[0] + center_destination[0]) / 2
    center_lng = (center_origin[1] + center_destination[1]) / 2
    m = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=13,
        tiles="cartodbpositron",
        control_scale=True,
    )
    road_layer = folium.FeatureGroup(name="Road network (flood state)", show=True)
    # Batch all road segments per color into a single PolyLine. Going from
    # ~19k PolyLine objects to 3 (one per flood state color) is the
    # single biggest hot-path win: each PolyLine adds DOM nodes and JS
    # event handlers on the client side, so the cost is not just Python.
    by_color: dict[str, list[list[list[float]]]] = {}
    for color, coords in polylines:
        by_color.setdefault(color, []).append(coords)
    for color, segments in by_color.items():
        folium.PolyLine(
            locations=segments, color=color, weight=2, opacity=0.75,
        ).add_to(road_layer)
    road_layer.add_to(m)

    if route_polyline:
        folium.PolyLine(
            locations=route_polyline,
            color=ROUTE_COLOR,
            weight=ROUTE_WEIGHT,
            opacity=ROUTE_OPACITY,
            tooltip="Computed flood-safe route",
        ).add_to(m)

    if origin is not None:
        folium.Marker(
            location=origin,
            tooltip="Origin (A)",
            icon=folium.Icon(color="green", icon="play", prefix="fa"),
        ).add_to(m)
    if destination is not None:
        folium.Marker(
            location=destination,
            tooltip="Destination (B)",
            icon=folium.Icon(color="red", icon="stop", prefix="fa"),
        ).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    return m


# ---------------------------------------------------------------------------
# Click handling
# ---------------------------------------------------------------------------
def handle_map_click(map_data: dict | None) -> None:
    """Update click_origin / click_dest in session_state from a map click.

    The first click sets the origin and flips the phase to ``"dest"``;
    the second click sets the destination and flips it back. Subsequent
    clicks keep toggling origin/dest. Clicks never trigger routing —
    only the "🚀 Compute Safe Route" button does.

    We guard against ping-pong reruns: ``streamlit-folium`` re-emits the
    last click on the rerun triggered by this handler, so without the
    change-detection guard a single map click would flip origin→dest
    and then immediately flip dest→origin on the auto-rerun.
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

    clicked = (lat, lng)
    coord_text = f"{lat:.6f}, {lng:.6f}"
    if st.session_state.click_phase == "origin":
        if st.session_state.click_origin == clicked:
            return
        st.session_state.click_origin = clicked
        st.session_state.click_phase = "dest"
        _set_widget_text("origin_text_ver", "origin_text", coord_text)
    else:
        if st.session_state.click_dest == clicked:
            return
        st.session_state.click_dest = clicked
        st.session_state.click_phase = "origin"
        _set_widget_text("dest_text_ver", "dest_text", coord_text)

    st.rerun()


# ---------------------------------------------------------------------------
# Routing cache
# ---------------------------------------------------------------------------
def compute_route_cached(
    G, node_index, origin, destination, seed
):
    """Compute a route, caching by (origin_node, dest_node, seed).

    Only runs when the user has clicked "🚀 Compute Safe Route", which
    bumps ``force_compute``. Every other interaction (text edits, map
    clicks, seed changes, Reset) leaves force at 0 and produces no route.
    """
    import time

    # Skip if both points haven't been set yet.
    if origin is None or destination is None:
        return None, None

    force = st.session_state.get("force_compute", 0)
    if force == 0:
        return None, None

    t0 = time.perf_counter()
    o_node = nearest_node(G, node_index, origin[0], origin[1])
    d_node = nearest_node(G, node_index, destination[0], destination[1])
    push_timing("nearest_node (×2)", (time.perf_counter() - t0) * 1000)

    # Cache key excludes ``force`` so repeat Compute clicks with the same
    # (seed, origin, destination) skip shortest_path entirely.
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