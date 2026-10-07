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


def stress_episode_skill_summary(
    anchors,
    bins,
    brier_gain,
    logloss_gain,
    *,
    window_hours: int,
    minimum_duration_hours: int,
    minimum_separation_hours: int,
    stress_bin: int = 2,
):
    """Report skill separately inside persistent high-volatility stress episodes.

    This is deliberately distinct from the diversity-episode count. It does not
    claim statistical independence of shocks; it is a robustness slice whose
    thresholds are frozen in protocol before the prospective epoch.
    """
    if not (
        len(anchors) == len(bins)
        == len(brier_gain) == len(logloss_gain)
    ):
        raise ValueError("stress inputs length mismatch")

    run_rows = _runs(anchors, bins)
    window = timedelta(hours=window_hours)
    min_duration = timedelta(hours=minimum_duration_hours)
    min_separation = timedelta(hours=minimum_separation_hours)

    qualified = []
    for volatility_bin, start, last_anchor, observations in run_rows:
        if int(volatility_bin) != int(stress_bin):
            continue
        end = last_anchor + window
        if end - start < min_duration:
            continue
        qualified.append(
            Episode(
                volatility_bin=int(volatility_bin),
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

    rows = []
    for episode in counted:
        ids = [
            i for i, anchor in enumerate(anchors)
            if episode.start <= anchor < episode.end
        ]
        if not ids:
            continue
        bg = [float(brier_gain[i]) for i in ids]
        lg = [float(logloss_gain[i]) for i in ids]
        rows.append(
            {
                "start_utc": episode.start.isoformat(),
                "end_utc": episode.end.isoformat(),
                "observations": len(ids),
                "mean_brier_gain": sum(bg) / len(bg),
                "mean_logloss_gain": sum(lg) / len(lg),
            }
        )

    return {
        "interpretation": (
            "ROBUSTNESS_DIAGNOSTIC_NOT_STATISTICAL_INDEPENDENCE_PROOF"
        ),
        "stress_bin": int(stress_bin),
        "count": len(rows),
        "episodes": rows,
        "episode_weighted_mean_brier_gain": (
            None if not rows
            else sum(x["mean_brier_gain"] for x in rows) / len(rows)
        ),
        "episode_weighted_mean_logloss_gain": (
            None if not rows
            else sum(x["mean_logloss_gain"] for x in rows) / len(rows)
        ),
    }
