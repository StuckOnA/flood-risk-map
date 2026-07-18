"""Flood Risk Routing Engine — Streamlit entry point.

Run with:
    streamlit run flood_routing_app.py

All logic lives in the ``flood_app`` package. This file is intentionally
short so it's obvious where the action is.
"""

from flood_app.ui import render


if __name__ == "__main__":
    render()