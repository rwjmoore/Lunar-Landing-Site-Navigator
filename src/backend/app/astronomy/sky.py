"""
Filename: app/astronomy/sky.py
Description: Runtime side of the sky model (docs/physics/sky.md section 5).

    Loads the precomputed sky grid (apparent Sun/Earth vectors from the Moon's
    center, MOON_ME, hourly UTC) and converts it to topocentric azimuth and
    elevation for a site by subtracting the site position and applying the P1
    LocalFrame. NumPy only: no SPICE at runtime.

    Mission sampling must align with the grid: start on a whole grid hour and
    step by a whole number of grid steps, so no interpolation is needed.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from app.coordinates.frames import LocalFrame

DEFAULT_SKY_GRID_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "sky" / "sky_grid_de421_2026_2040_1h.npz"
)


class SkyGridRangeError(ValueError):
    """The requested mission sampling falls outside, or does not align with, the grid."""


@dataclass(frozen=True)
class SkyGrid:
    """Apparent Sun/Earth vectors from the Moon's center on a regular UTC grid.

    Attributes:
        utc_start: First grid instant (timezone-aware UTC).
        step_s: Grid spacing in seconds.
        sun_m, earth_m: MOON_ME vectors in metres, shape (N, 3).
        provenance: JSON text describing kernels and how the grid was built.
    """

    utc_start: datetime
    step_s: int
    sun_m: np.ndarray
    earth_m: np.ndarray
    provenance: str = ""

    @classmethod
    def load(cls, path: Path = DEFAULT_SKY_GRID_PATH) -> "SkyGrid":
        with np.load(path) as data:
            return cls(
                utc_start=parse_utc(str(data["utc_start"])),
                step_s=int(data["step_s"]),
                sun_m=data["sun_m"],
                earth_m=data["earth_m"],
                provenance=str(data["provenance"]),
            )

    @property
    def size(self) -> int:
        return len(self.sun_m)

    @property
    def utc_end(self) -> datetime:
        """Last grid instant (inclusive)."""
        return self.utc_start + timedelta(seconds=self.step_s * (self.size - 1))

    def mission_indices(self, start_utc: datetime, duration_s: float, step_s: int) -> np.ndarray:
        """Grid indices of the mission samples.

        Sample count follows SCIENCE_CONVENTIONS.md section 2:
        N = floor(duration / step) + 1. Raises SkyGridRangeError if the start is
        not on a grid instant, the step is not a whole multiple of the grid step,
        or any sample falls outside the grid.
        """
        if start_utc.tzinfo is None:
            raise ValueError("start_utc must be timezone-aware UTC")
        if duration_s <= 0 or step_s <= 0:
            raise ValueError("duration_s and step_s must be positive")
        if step_s % self.step_s != 0:
            raise SkyGridRangeError(f"step must be a whole multiple of {self.step_s} s")

        offset_s = (start_utc - self.utc_start).total_seconds()
        if offset_s % self.step_s != 0:
            raise SkyGridRangeError("mission start must fall on a whole grid hour (UTC)")

        count = int(np.floor(duration_s / step_s)) + 1
        first = int(offset_s // self.step_s)
        indices = first + np.arange(count) * (step_s // self.step_s)
        if first < 0 or indices[-1] >= self.size:
            raise SkyGridRangeError(
                f"mission must lie within {format_utc(self.utc_start)} .. {format_utc(self.utc_end)}"
            )
        return indices


@dataclass(frozen=True)
class SkyTrack:
    """Topocentric Sun/Earth directions for one site over a mission (radians)."""

    timestamps_utc: list[str]
    sun_azimuth: np.ndarray
    sun_elevation: np.ndarray
    earth_azimuth: np.ndarray
    earth_elevation: np.ndarray


def sky_track(
    grid: SkyGrid, frame: LocalFrame, start_utc: datetime, duration_s: float, step_s: int
) -> SkyTrack:
    """Sun/Earth azimuth and elevation seen from `frame`'s site at each mission sample."""
    indices = grid.mission_indices(start_utc, duration_s, step_s)
    sun_az, sun_el = frame.azimuth_elevation(grid.sun_m[indices])
    earth_az, earth_el = frame.azimuth_elevation(grid.earth_m[indices])
    timestamps = [
        format_utc(grid.utc_start + timedelta(seconds=int(i) * grid.step_s)) for i in indices
    ]
    return SkyTrack(timestamps, sun_az, sun_el, earth_az, earth_el)


def parse_utc(text: str) -> datetime:
    """Parse an ISO 8601 UTC string such as '2030-11-20T12:00:00Z'."""
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError(f"timestamp must include a UTC offset or 'Z': {text!r}")
    return value.astimezone(UTC)


def format_utc(value: datetime) -> str:
    """Format as ISO 8601 UTC with a 'Z' suffix, whole seconds."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
