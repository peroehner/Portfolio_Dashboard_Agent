"""Full Timeline spans the entire downloaded history, not just the trend window."""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.technical_signals_service import TechnicalSignalsService


def _synthetic_history(n: int = 120) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=n)
    # Gentle zig-zag so adaptive pivots produce a truncated window.
    wave = np.sin(np.linspace(0, 8 * np.pi, n)) * 12
    close = 100 + np.linspace(0, 40, n) + wave
    high = close + 1.5
    low = close - 1.5
    volume = np.full(n, 1_000_000)
    return pd.DataFrame(
        {"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


def test_compute_chart_exposes_full_timeline_longer_than_window():
    df = _synthetic_history(160)
    chart = TechnicalSignalsService.compute_chart(df, symbol="TEST", period="2y", max_waves=4)
    assert chart is not None
    window = chart["chartTimeline"]
    full = chart["chartTimelineFull"]
    assert full is not None
    assert full.get("span") == "full"
    assert len(full["points"]) == len(df)
    assert len(window["points"]) <= len(full["points"])
    assert full["points"][0]["date"] == df.index[0].strftime("%Y-%m-%d")
    assert full["points"][-1]["date"] == df.index[-1].strftime("%Y-%m-%d")
    # Window is a suffix of the full series (trend legs start at first selected pivot).
    assert window["points"][-1]["date"] == full["points"][-1]["date"]
    assert window["startDate"] >= full["startDate"]
