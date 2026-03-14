"""Run storage and history management for PharmaSim optimization.

Manages the runs/ directory structure where each optimization iteration
gets its own folder with Excel downloads and metadata.

Directory layout:
    runs/
        run_001/
            metadata.json
            Year0_Dashboard.xlsx
            Year1_Performance_Summary.xlsx
            ...
        run_002/
            ...
        history.jsonl
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path(__file__).parent.parent / "runs"


@dataclass
class RunMetadata:
    """Metadata for a single optimization run."""

    run_id: str
    created_at: str
    mode: str  # "full" | "partial"
    status: str  # "pending" | "scraping" | "complete" | "failed"
    years_available: list[int] = field(default_factory=list)
    decisions: dict[str, dict] | None = None  # keyed by "d0", "d1", etc.
    # DEPRECATED: old flat 'decision' field, kept for backward compat loading
    decision: dict | None = None
    parent_run_id: str | None = None
    error: str | None = None
    duration_seconds: float | None = None


def _runs_dir() -> Path:
    return RUNS_DIR


def run_dir(run_id: str) -> Path:
    """Return the directory path for a run."""
    return _runs_dir() / run_id


def _metadata_path(run_id: str) -> Path:
    return run_dir(run_id) / "metadata.json"


def _history_path() -> Path:
    return _runs_dir() / "history.jsonl"


def next_run_id() -> str:
    """Determine the next sequential run ID."""
    runs = _runs_dir()
    if not runs.exists():
        return "run_001"
    existing = sorted(
        d.name for d in runs.iterdir() if d.is_dir() and d.name.startswith("run_")
    )
    if not existing:
        return "run_001"
    last_num = int(existing[-1].split("_")[1])
    return f"run_{last_num + 1:03d}"


def create_run(
    mode: str = "full",
    years_available: list[int] | None = None,
) -> RunMetadata:
    """Create a new run directory with initial metadata."""
    rid = next_run_id()
    d = run_dir(rid)
    d.mkdir(parents=True, exist_ok=True)

    meta = RunMetadata(
        run_id=rid,
        created_at=datetime.now(timezone.utc).isoformat(),
        mode=mode,
        status="pending",
        years_available=years_available or [],
    )
    _write_metadata(meta)
    return meta


def _write_metadata(meta: RunMetadata) -> None:
    path = _metadata_path(meta.run_id)
    path.write_text(json.dumps(asdict(meta), indent=2) + "\n")


def get_run(run_id: str) -> RunMetadata:
    """Load metadata for a run."""
    path = _metadata_path(run_id)
    data = json.loads(path.read_text())
    return RunMetadata(**data)


def update_run(run_id: str, **updates) -> RunMetadata:
    """Update metadata fields for a run."""
    meta = get_run(run_id)
    for key, val in updates.items():
        if hasattr(meta, key):
            setattr(meta, key, val)
    _write_metadata(meta)
    return meta


def list_runs() -> list[RunMetadata]:
    """List all runs, sorted by run_id."""
    runs = _runs_dir()
    if not runs.exists():
        return []
    result = []
    for d in sorted(runs.iterdir()):
        if d.is_dir() and d.name.startswith("run_") and (d / "metadata.json").exists():
            result.append(get_run(d.name))
    return result


def append_history(
    run_id: str,
    decision: dict,
    outcomes: dict,
    decision_index: int | None = None,
    source_year: int | None = None,
    outcome_year: int | None = None,
) -> None:
    """Append a (decision, outcomes) entry to the history log.

    Args:
        decision_index: Which decision this is (0 or 1). DecisionN is made
            while viewing YearN and produces YearN+1.
        source_year: The year whose state informed this decision (= decision_index).
        outcome_year: The year whose results reflect this decision (= decision_index + 1).
    """
    _runs_dir().mkdir(parents=True, exist_ok=True)
    entry = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision_index": decision_index,
        "source_year": source_year,
        "outcome_year": outcome_year,
        "decision": decision,
        "outcomes": outcomes,
    }
    with open(_history_path(), "a") as f:
        f.write(json.dumps(entry) + "\n")


def load_history() -> list[dict]:
    """Load all history entries."""
    path = _history_path()
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().strip().splitlines():
        if line:
            entries.append(json.loads(line))
    return entries


def import_existing(source_dir: Path) -> RunMetadata:
    """Import existing Excel files from a directory as a new run.

    Copies all .xlsx files from source_dir into a new run directory.
    """
    meta = create_run(mode="full")
    dest = run_dir(meta.run_id)

    years_found: set[int] = set()
    for f in sorted(source_dir.glob("*.xlsx")):
        shutil.copy2(f, dest / f.name)
        # Extract year from filename like "Year0_Dashboard.xlsx"
        if f.name.startswith("Year"):
            try:
                year_num = int(f.name.split("_")[0].replace("Year", ""))
                years_found.add(year_num)
            except ValueError:
                pass

    meta = update_run(
        meta.run_id,
        status="complete",
        years_available=sorted(years_found),
    )
    return meta
