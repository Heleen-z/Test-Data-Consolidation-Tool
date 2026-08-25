from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def load_dataset(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(path, columns=columns)


def filter_and_downsample(
    frame: pd.DataFrame,
    source_ids: list[str] | None,
    axis_min,
    axis_max,
    max_points: int,
) -> pd.DataFrame:
    selected = frame
    if source_ids:
        selected = selected[selected["__source_id"].isin(source_ids)]
    if axis_min is not None:
        selected = selected[selected["__axis_value"] >= axis_min]
    if axis_max is not None:
        selected = selected[selected["__axis_value"] <= axis_max]
    if len(selected) <= max_points:
        return selected
    positions = np.linspace(0, len(selected) - 1, max_points, dtype=int)
    return selected.iloc[positions]

