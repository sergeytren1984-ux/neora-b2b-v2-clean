"""Predeclared volatility-episode semantics for the R7 successor candidate.

R6 counted every adjacent volatility-bin change as a new independent episode.
R7 requires persistence plus temporal separation, so rapid bin flicker inside one
market shock cannot manufacture the admission requirement.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Episode:
    volatility_bin: int
    start: datetime
    end: datetime
    observations: int


def _runs(anchors, bins):
    if len(anchors) != len(bins):
        raise ValueError("anchors/bins length mismatch")
    if not anchors:
        return []
    runs = []
    start = 0
    for i in range(1, len(bins) + 1):
        if i == len(bins) or bins[i] != bins[start]:
            runs.append(
                (
                    int(bins[start]),
                    anchors[start],
                    anchors[i - 1],
                    i - start,
                )
            )
            start = i
    return runs


def independent_volatility_episodes(
    anchors,
    bins,
    *,
    window_hours: int,
    minimum_duration_hours: int,
    minimum_separation_hours: int,
):
    """Return stable and separated volatility episodes.

    Duration is measured from the first anchor through the end of the last
    fixed-phase window. A qualifying run must persist for minimum_duration_hours.
    Counted episode starts must then be separated from the previous counted start
    by minimum_separation_hours. These values are protocol inputs, not inferred
    from observed performance.
    """
    if window_hours <= 0:
        raise ValueError("window_hours must be positive")
    if minimum_duration_hours < window_hours:
        raise ValueError("minimum episode duration below one window")
    if minimum_separation_hours < window_hours:
        raise ValueError("minimum episode separation below one window")

    run_rows = _runs(anchors, bins)
    qualified = []
    window = timedelta(hours=window_hours)
    min_duration = timedelta(hours=minimum_duration_hours)
    min_separation = timedelta(hours=minimum_separation_hours)

    for volatility_bin, start, last_anchor, observations in run_rows:
        end = last_anchor + window
        if end - start < min_duration:
            continue
        qualified.append(
            Episode(
                volatility_bin=volatility_bin,
                start=start,
                end=end,
                observations=observations,
            )
        )

    counted = []
    previous_start = None
    for episode in qualified:
        if (
            previous_start is None
            or episode.start - previous_start >= min_separation
        ):
            counted.append(episode)
            previous_start = episode.start

    return counted


def episode_summary(
    anchors,
    bins,
    *,
    window_hours: int,
    minimum_duration_hours: int,
    minimum_separation_hours: int,
):
    episodes = independent_volatility_episodes(
        anchors,
        bins,
        window_hours=window_hours,
        minimum_duration_hours=minimum_duration_hours,
        minimum_separation_hours=minimum_separation_hours,
    )
    return {
        "count": len(episodes),
        "bins_seen": sorted({e.volatility_bin for e in episodes}),
        "episodes": [
            {
                "volatility_bin": e.volatility_bin,
                "start_utc": e.start.isoformat(),
                "end_utc": e.end.isoformat(),
                "observations": e.observations,
            }
            for e in episodes
        ],
    }
