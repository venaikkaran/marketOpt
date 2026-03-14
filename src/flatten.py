"""Flatten YearData into flat dicts for optimizer consumption.

Converts nested dataclass structures into dot-notation keyed dicts
like {'performance_summary.stock_price': 32.5, ...}.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from src.parser import YearData, load_year
from src.run_store import run_dir


def _flatten_value(prefix: str, value: Any, out: dict[str, float | str | None]) -> None:
    """Recursively flatten a value into the output dict."""
    if value is None:
        out[prefix] = None
    elif isinstance(value, (int, float)):
        out[prefix] = float(value)
    elif isinstance(value, str):
        out[prefix] = value
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _flatten_value(f"{prefix}.{i}", item, out)
    elif isinstance(value, dict):
        for k, v in value.items():
            _flatten_value(f"{prefix}.{k}", v, out)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for f in dataclasses.fields(value):
            _flatten_value(f"{prefix}.{f.name}", getattr(value, f.name), out)


def flatten_year(yd: YearData) -> dict[str, float | str | None]:
    """Flatten all YearData fields into a single flat dict.

    Keys use dot-notation:
        'performance_summary.stock_price'
        'brand_awareness.Allround.brand_awareness_pct'
        'brand_formulations.Allround.analgesic_mg'
    """
    out: dict[str, float | str | None] = {}
    for f in dataclasses.fields(yd):
        if f.name == "year":
            out["year"] = yd.year
            continue
        _flatten_value(f.name, getattr(yd, f.name), out)
    return out


def flatten_run(
    run_id: str, years: list[int] | None = None
) -> dict[str, float | str | None]:
    """Load all years for a run, flatten, prefix with year.

    Keys: 'year0.performance_summary.stock_price',
          'year1.income_statement.net_income', etc.
    """
    if years is None:
        years = [0, 1]
    rd = run_dir(run_id)
    out: dict[str, float | str | None] = {}
    for y in years:
        yd = load_year(y, downloads_dir=rd)
        year_flat = flatten_year(yd)
        for k, v in year_flat.items():
            out[f"year{y}.{k}"] = v
    return out


def flatten_numeric_only(flat: dict[str, Any]) -> dict[str, float]:
    """Filter a flat dict to only numeric (non-None) values."""
    return {k: v for k, v in flat.items() if isinstance(v, (int, float))}
