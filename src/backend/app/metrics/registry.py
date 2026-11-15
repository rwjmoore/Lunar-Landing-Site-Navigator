"""
Filename: app/metrics/registry.py
Description: The single explicit list of active metrics. To add a metric, add an
    instance here (see docs/metrics.md, 'Adding a metric'). Metric ids match the
    field names of the API's `metrics` object so the API layer can map them directly.
"""

from app.metrics.visibility import LongestOutage, VisibleFraction

DEFAULT_METRICS = (
    VisibleFraction("sun_visible_fraction", "Solar access", series="sun_visible"),
    LongestOutage("max_continuous_darkness_hours", "Longest darkness", series="sun_visible"),
    VisibleFraction("earth_visible_fraction", "Earth access", series="earth_visible"),
    LongestOutage(
        "max_continuous_earth_blackout_hours", "Longest Earth blackout", series="earth_visible"
    ),
)
