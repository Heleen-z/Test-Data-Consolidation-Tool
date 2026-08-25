from __future__ import annotations

from typing import Any

import pandas as pd

from .normalize import normalize_header


def find_axis_columns(columns: list[str], rule: dict[str, Any]) -> list[str]:
    by_key: dict[str, str] = {}
    for column in columns:
        key = normalize_header(column)
        if key and key not in by_key:
            by_key[key] = column
    candidates = [normalize_header(item) for item in rule.get("axis_candidates", [])]
    matched = [by_key[item] for item in candidates if item in by_key]
    basis = rule.get("time_basis")
    if basis == "absolute":
        date_column = next(
            (value for key, value in by_key.items() if key == "date" or "date" in key),
            None,
        )
        time_column = next(
            (value for key, value in by_key.items() if key == "time" or key.endswith(" time")),
            None,
        )
        datetime_column = next(
            (
                value
                for key, value in by_key.items()
                if "datetime" in key or "timestamp" in key
            ),
            None,
        )
        if date_column and time_column and date_column != time_column:
            return [date_column, time_column]
        if datetime_column:
            return [datetime_column]
    return list(dict.fromkeys(matched[:1]))


def build_axis(
    frame: pd.DataFrame, time_basis: str, axis_columns: list[str]
) -> pd.Series:
    if not axis_columns:
        return pd.Series(pd.NA, index=frame.index, dtype="object")
    if time_basis == "absolute":
        if len(axis_columns) >= 2:
            combined = (
                frame[axis_columns[0]].astype(str).str.strip()
                + " "
                + frame[axis_columns[1]].astype(str).str.strip()
            )
        else:
            combined = frame[axis_columns[0]]
        return pd.to_datetime(combined, errors="coerce")
    return pd.to_numeric(frame[axis_columns[0]], errors="coerce")


def axis_bounds(axis: pd.Series) -> tuple[str, str]:
    valid = axis.dropna()
    if valid.empty:
        return "", ""
    return str(valid.min()), str(valid.max())

