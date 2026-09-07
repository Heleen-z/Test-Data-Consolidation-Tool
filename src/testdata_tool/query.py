from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_dataset(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(path, columns=columns)


def filter_dataset(
    frame: pd.DataFrame,
    source_ids: list[str] | None,
    axis_min,
    axis_max,
) -> pd.DataFrame:
    """Filter chart data without removing, aggregating, or sampling any rows."""
    selected = frame
    if source_ids:
        selected = selected[selected["__source_id"].isin(source_ids)]
    if axis_min is not None:
        selected = selected[selected["__axis_value"] >= axis_min]
    if axis_max is not None:
        selected = selected[selected["__axis_value"] <= axis_max]
    return selected
