"""End-to-end pipeline: scrape → parse → extract decisions → flatten.

Usage:
    # Full scrape (Year0 + Year1) into a new run:
    uv run python -m src.pipeline

    # Scrape specific periods:
    uv run python -m src.pipeline --periods 0 1 2

    # Parse an existing run (no scraping):
    uv run python -m src.pipeline --parse-only run_001
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from src.decision import DecisionVector
from src.flatten import flatten_year, flatten_numeric_only
from src.parser import load_year
from src.run_store import (
    append_history,
    create_run,
    get_run,
    run_dir,
    update_run,
)
from src.scraper import ALL_PERIODS, scrape


def run_scrape(periods: list[int] | None = None) -> str:
    """Create a new run and scrape data into it.

    Args:
        periods: Year indices to scrape (e.g. [0, 1] or [0, 1, 2]).
                 Defaults to [0, 1].

    Returns:
        The run_id of the created run.
    """
    if periods is None:
        periods = [0, 1]

    period_tuples = [(i, f"Year{i}") for i in periods]

    meta = create_run(mode="full" if 0 in periods else "partial")
    rd = run_dir(meta.run_id)
    print(f"Created run: {meta.run_id} -> {rd}")

    update_run(meta.run_id, status="scraping")
    start = time.time()

    try:
        scrape(download_dir=str(rd), periods=period_tuples)
        elapsed = time.time() - start
        update_run(
            meta.run_id,
            status="complete",
            years_available=periods,
            duration_seconds=round(elapsed, 1),
        )
        print(f"Scrape complete in {elapsed:.0f}s")
    except Exception as e:
        update_run(meta.run_id, status="failed", error=str(e))
        raise

    return meta.run_id


def run_parse(run_id: str) -> None:
    """Parse a completed run: extract decisions, flatten, save to history."""
    meta = get_run(run_id)
    rd = run_dir(run_id)

    # Always detect years from actual files on disk
    years = sorted({
        int(f.name.split("_")[0].replace("Year", ""))
        for f in rd.glob("Year*.xlsx")
    })
    if years and years != meta.years_available:
        update_run(run_id, years_available=years)

    if not years:
        print(f"  No Excel files found in {rd}")
        return

    print(f"Parsing run {run_id} (years: {years})")

    OUTCOME_METRICS = [
        "performance_summary.stock_price",
        "performance_summary.net_income",
        "performance_summary.cumulative_net_income",
        "performance_summary.unit_sales",
        "performance_summary.market_share_unit_pct",
        "performance_summary.market_share_dollar_pct",
        "performance_summary.marketing_efficiency_index",
    ]

    # Parse and flatten each year, write JSON for review
    year_data: dict[int, Any] = {}
    year_flat: dict[int, dict[str, float | str | None]] = {}

    for y in years:
        yd = load_year(y, downloads_dir=rd)
        flat = flatten_year(yd)
        numeric = flatten_numeric_only(flat)
        print(f"  Year {y}: {len(numeric)} numeric fields")

        # Write full parsed data to JSON for manual review
        parsed_path = rd / f"year{y}_parsed.json"
        with open(parsed_path, "w") as f:
            json.dump(flat, f, indent=2, default=str)
        print(f"  Written: {parsed_path}")

        year_data[y] = yd
        year_flat[y] = flat

    # Extract decision→outcome pairs for each transition.
    # YearN+1 reports reflect Decision(N): the decision made at YearN.
    # So we extract the decision from YearN+1 data and pair it with
    # YearN+1 outcomes.
    decisions: dict[str, dict] = {}

    for outcome_year in sorted(year_data.keys()):
        if outcome_year == 0:
            continue  # Year0 is initial state, no prior decision produced it
        decision_index = outcome_year - 1  # Decision(N) produces Year(N+1)

        dv = DecisionVector.from_year_data(year_data[outcome_year])
        decisions[f"d{decision_index}"] = dv.to_dict()

        outcomes = {}
        for metric in OUTCOME_METRICS:
            if metric in year_flat[outcome_year]:
                outcomes[metric] = year_flat[outcome_year][metric]

        append_history(
            run_id,
            dv.to_dict(),
            outcomes,
            decision_index=decision_index,
            source_year=decision_index,
            outcome_year=outcome_year,
        )
        print(
            f"  D{decision_index} (Year{decision_index}→Year{outcome_year}): "
            f"MSRP={dv.msrp}, media={dv.media_expenditure}M"
        )
        print(f"    Outcomes: {outcomes}")

    if decisions:
        update_run(run_id, decisions=decisions, decision=None)


def main():
    parser = argparse.ArgumentParser(description="PharmaSim pipeline")
    parser.add_argument(
        "--periods",
        type=int,
        nargs="+",
        default=None,
        help="Year indices to scrape (e.g. 0 1 2). Default: 0 1",
    )
    parser.add_argument(
        "--parse-only",
        type=str,
        default=None,
        metavar="RUN_ID",
        help="Skip scraping, just parse an existing run",
    )
    args = parser.parse_args()

    if args.parse_only:
        run_parse(args.parse_only)
    else:
        run_id = run_scrape(periods=args.periods)
        run_parse(run_id)


if __name__ == "__main__":
    main()
