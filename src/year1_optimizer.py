"""Year1 optimization workflow for the locked Y1 -> D1 -> Y2 loop.

This module wraps the existing scrape / parse / apply primitives with a
session-oriented optimization loop for Year 1 decisions:

1. Capture a locked Y1 state and the current editable decisions.
2. Propose a constrained suggestion in the reduced search space.
3. Let the human edit the JSON.
4. Validate + register the edited suggestion before application.
5. After the human runs the sim, scrape Y2 and record the outcome.

No extra dependencies are required. The surrogate is a small Gaussian process
implemented with the standard library, and plots are emitted as HTML/SVG.

Usage:
    # Create a session from existing artifacts
    uv run python -m src.year1_optimizer create-session \
        --run-id run_001 --decisions runs/decisions_period1.json

    # Capture a fresh locked Y1 state using the existing scrapers
    uv run python -m src.year1_optimizer capture-session

    # Generate the next suggestion for the session
    uv run python -m src.year1_optimizer suggest --session session_001

    # Register the human-edited JSON and emit per-page apply scripts
    uv run python -m src.year1_optimizer register-applied \
        --session session_001 --round round_001 --suggestion path/to/edited.json

    # One guided command for the common loop
    uv run python -m src.year1_optimizer guided-round \
        --capture --apply-selenium --scrape-outcome

    # After the human manually runs the sim and Y2 is visible:
    uv run python -m src.year1_optimizer record-outcome \
        --session session_001 --round round_001 --scrape

    # Inspect the current status
    uv run python -m src.year1_optimizer status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import time
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path
from statistics import NormalDist
from typing import Any, Iterable

from src.constraints import CONSTRAINTS, compute_sf_cost, normalize_suggestion
from src.decision_applier import (
    generate_page_scripts,
    print_suggestion_summary,
    scraped_to_suggestion,
)
from src.decision_scraper import scrape_decisions_selenium
from src.pipeline import run_parse, run_scrape
from src.run_store import create_run, get_run, run_dir, update_run
from src.scraper import create_driver, download_all_sections, login_and_launch, switch_period

PROJECT_ROOT = Path(__file__).parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"
YEAR1_OPT_DIR = RUNS_DIR / "year1_opt"
LATEST_SESSION_PATH = YEAR1_OPT_DIR / "latest_session.txt"

PAGE_MARKERS = {
    "decisions/sales_force": ("field", "sf1"),
    "decisions/pricing": ("field", "msrp1"),
    "decisions/advertising": ("field", "ad_budget1"),
    "decisions/promotion": ("field", "allowance1-1"),
    "decisions/brands": ("text", "Reformulation"),
    "decisions/review": ("review", "Budget"),
}

SF_FIELDS = [
    "sf_independent",
    "sf_chain",
    "sf_grocery",
    "sf_convenience",
    "sf_mass",
    "sf_wholesaler",
    "sf_merchandisers",
    "sf_detailers",
]

ALLOWANCE_FIELDS = [
    "allowance_independent",
    "allowance_chain",
    "allowance_grocery",
    "allowance_convenience",
    "allowance_mass",
    "allowance_wholesale",
]

COOP_CHANNEL_FIELDS = [
    "coop_ad_independent",
    "coop_ad_chain",
    "coop_ad_grocery",
    "coop_ad_convenience",
    "coop_ad_mass",
]

POP_CHANNEL_FIELDS = [
    "pop_independent",
    "pop_chain",
    "pop_grocery",
    "pop_convenience",
    "pop_mass",
]

LATENT_FIELDS = [
    "total_budget",
    "ad_budget",
    "coop_ad_budget",
    "coupon_budget",
    "pop_budget",
    "msg_benefits_pct",
    "msrp",
    "discount_under_250",
    "discount_under_2500",
    "discount_2500_plus",
    "discount_wholesale",
]

LATENT_LABELS = {
    "total_budget": "Total Spend Target ($M)",
    "ad_budget": "Advertising Budget ($M)",
    "coop_ad_budget": "Co-op Budget ($M)",
    "coupon_budget": "Coupon Budget ($M)",
    "pop_budget": "Display Budget ($M)",
    "msg_benefits_pct": "Benefit Message (%)",
    "msrp": "MSRP ($)",
    "discount_under_250": "Discount <250 (%)",
    "discount_under_2500": "Discount <2500 (%)",
    "discount_2500_plus": "Discount 2500+ (%)",
    "discount_wholesale": "Wholesale Discount (%)",
}

AD_MIX_FREE_TOTAL = 95
AD_MIX_COMPARISON_LOCK = 5
AD_MIX_PRIMARY_LOCK = 0
ONE_DP0 = Decimal("1")
BUDGET_FILL_FIELDS = [
    "ad_budget",
    "coop_ad_budget",
    "coupon_budget",
    "pop_budget",
]
DISCOUNT_FIELDS = [
    "discount_under_250",
    "discount_under_2500",
    "discount_2500_plus",
    "discount_wholesale",
]
TARGET_BUDGET_BUFFER_M = 1.0
OPTIONAL_STRATEGY_FIELDS = {"brand_reformulation"}

BASELINE_FIXED_COPY_FIELDS = [
    "ad_agency",
    "symptom_cold",
    "symptom_cough",
    "symptom_allergy",
    "demo_young_singles",
    "demo_young_families",
    "demo_mature_families",
    "demo_empty_nesters",
    "demo_retired",
    "msg_comparison_target",
    "benefit_relieves_aches",
    "benefit_clears_nasal",
    "benefit_reduces_chest",
    "benefit_dries_runny_nose",
    "benefit_suppresses_coughing",
    "benefit_relieves_allergies",
    "benefit_minimizes_side_effects",
    "benefit_wont_cause_drowsiness",
    "benefit_helps_you_rest",
    "brand_reformulation",
]

OBJECTIVE_KEYS = [
    "performance_summary.unit_sales",
    "income_statement.net_income",
    "income_statement.manufacturer_sales",
    "income_statement.cost_of_goods_sold",
    "income_statement.total_marketing",
    "performance_summary.promotional_allowance",
    "performance_summary.fixed_costs",
]

NORMAL = NormalDist()


def _stage_label(year: int) -> str:
    return f"Year{int(year)}"


def _stage_display(year: int) -> str:
    return "Start" if int(year) == 0 else f"Year {int(year)}"


def _session_decision_period(session: dict[str, Any]) -> int:
    return int(session.get("decision_period", session.get("state_year", 1)))


def _session_outcome_year(session: dict[str, Any]) -> int:
    return int(session.get("outcome_year", int(session.get("state_year", 1)) + 1))


def _policy_label(session: dict[str, Any]) -> str:
    return _stage_label(int(session.get("state_year", 1)))


def _strategy_required_fields() -> list[str]:
    fields = (
        SF_FIELDS
        + ["msrp"]
        + DISCOUNT_FIELDS
        + BUDGET_FILL_FIELDS
        + [
            "ad_agency",
            "msg_primary_pct",
            "msg_benefits_pct",
            "msg_comparison_pct",
            "msg_comparison_target",
            "msg_reminder_pct",
            "coupon_amount",
            "trial_budget",
        ]
        + ALLOWANCE_FIELDS
        + COOP_CHANNEL_FIELDS
        + POP_CHANNEL_FIELDS
        + BASELINE_FIXED_COPY_FIELDS
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for field in fields:
        if field in OPTIONAL_STRATEGY_FIELDS or field in seen:
            continue
        seen.add(field)
        deduped.append(field)
    return deduped


def _ensure_strategy_surface_available(
    baseline_suggestion: dict[str, Any],
    *,
    state_year: int,
) -> None:
    missing = [
        field for field in _strategy_required_fields()
        if field not in baseline_suggestion
    ]
    if not missing:
        return
    preview = ", ".join(missing[:12])
    extra = "" if len(missing) <= 12 else f", and {len(missing) - 12} more"
    raise ValueError(
        f"{_stage_display(state_year)} strategy requires a full editable decision surface, "
        f"but the scrape is missing {len(missing)} required fields: {preview}{extra}. "
        "This usually means the captured period is historical/read-only instead of the live editable decision period."
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _write_json(path: str | Path, data: Any) -> None:
    out = Path(path)
    _ensure_dir(out.parent)
    out.write_text(json.dumps(data, indent=2) + "\n")


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _session_dir(session_id: str) -> Path:
    return YEAR1_OPT_DIR / session_id


def _session_meta_path(session_id: str) -> Path:
    return _session_dir(session_id) / "session.json"


def _round_dir(session_id: str, round_id: str) -> Path:
    return _session_dir(session_id) / round_id


def _round_index_path(session_id: str) -> Path:
    return _session_dir(session_id) / "rounds.json"


def _list_ids(base_dir: Path, prefix: str) -> list[str]:
    if not base_dir.exists():
        return []
    return sorted(
        p.name for p in base_dir.iterdir()
        if p.is_dir() and p.name.startswith(prefix)
    )


def _next_id(base_dir: Path, prefix: str) -> str:
    ids = _list_ids(base_dir, prefix)
    if not ids:
        return f"{prefix}_001"
    last_num = int(ids[-1].split("_")[1])
    return f"{prefix}_{last_num + 1:03d}"


def next_session_id() -> str:
    return _next_id(YEAR1_OPT_DIR, "session")


def next_round_id(session_id: str) -> str:
    return _next_id(_session_dir(session_id), "round")


def load_session(session_id: str) -> dict[str, Any]:
    path = _session_meta_path(session_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown session: {session_id}")
    return _read_json(path)


def save_session(session: dict[str, Any]) -> None:
    _write_json(_session_meta_path(session["session_id"]), session)
    _ensure_dir(YEAR1_OPT_DIR)
    LATEST_SESSION_PATH.write_text(session["session_id"] + "\n")


def load_rounds(session_id: str) -> list[dict[str, Any]]:
    path = _round_index_path(session_id)
    if not path.exists():
        return []
    return _read_json(path)


def save_rounds(session_id: str, rounds: list[dict[str, Any]]) -> None:
    _write_json(_round_index_path(session_id), rounds)


def upsert_round(session_id: str, round_record: dict[str, Any]) -> None:
    rounds = load_rounds(session_id)
    updated = False
    for idx, current in enumerate(rounds):
        if current["round_id"] == round_record["round_id"]:
            rounds[idx] = round_record
            updated = True
            break
    if not updated:
        rounds.append(round_record)
        rounds.sort(key=lambda item: item["round_id"])
    save_rounds(session_id, rounds)


def _copy_into_session(session_dir: Path, name: str, source: Path) -> Path:
    dest = session_dir / name
    shutil.copy2(source, dest)
    return dest


def _hash_obj(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_available_budget(year1_flat: dict[str, Any], decisions: dict[str, Any]) -> float:
    from_flat = year1_flat.get("income_statement.next_year_budget")
    if from_flat is not None:
        return float(from_flat)
    budget = decisions.get("budget", {}).get("budget_M")
    if budget is None:
        raise ValueError("Unable to determine Year1 available budget")
    return float(budget)


def _extract_current_total_spend(decisions: dict[str, Any]) -> float:
    budget = decisions.get("budget", {}).get("budget_M")
    remaining = decisions.get("budget", {}).get("remaining_M")
    if budget is None or remaining is None:
        raise ValueError("Decision scrape is missing budget or remaining budget")
    return round(float(budget) - float(remaining), 4)


def _extract_sf_profile(decisions: dict[str, Any]) -> dict[str, Any]:
    sf_data = decisions.get("sales_force", {})
    costs = sf_data.get("costs_per_person", {})
    previous = sf_data.get("previous", {})
    inputs = sf_data.get("inputs", {})
    expenditures = sf_data.get("expenditures", {})

    field_map = {
        "sf_independent": "sf1",
        "sf_chain": "sf2",
        "sf_grocery": "sf3",
        "sf_convenience": "sf4",
        "sf_mass": "sf5",
        "sf_wholesaler": "sf6",
        "sf_merchandisers": "sf7",
        "sf_detailers": "sf8",
    }
    previous_counts = {
        key: int(float(inputs.get(html_name, 0)))
        for key, html_name in field_map.items()
    }

    previous_total = int(float(previous.get("Total Sales Force", sum(previous_counts.values()))))
    salary_per = float(costs["Salary"]["current"])
    expense_per = float(costs["Expenses"]["current"])
    training_per = float(costs["New-Hire Training"]["current"])
    turnover_people = float(costs["Turnover"]["current"])
    turnover_rate = turnover_people / previous_total if previous_total else 0.0
    max_total = int(sum(int(CONSTRAINTS[field].max or 1000) for field in SF_FIELDS))

    return {
        "previous_counts": previous_counts,
        "previous_total_sf": previous_total,
        "current_total_sf": int(sum(previous_counts.values())),
        "salary_per": salary_per,
        "expense_per": expense_per,
        "training_per": training_per,
        "turnover_people": turnover_people,
        "turnover_rate": turnover_rate,
        "max_total_sf": max_total,
        "current_sf_budget": float(expenditures.get("Total", {}).get("current", 0.0)),
    }


def _sf_params_for_constraints(session: dict[str, Any]) -> dict[str, float]:
    profile = session["sf_profile"]
    return {
        "salary_per": float(profile["salary_per"]),
        "expense_per": float(profile["expense_per"]),
        "training_per": float(profile["training_per"]),
        "turnover": float(profile["turnover_people"]),
    }


def _sf_cost_for_total(total_sf: int, session: dict[str, Any]) -> float:
    profile = session["sf_profile"]
    previous_total = int(profile["previous_total_sf"])
    change = total_sf - previous_total
    training_people = max(0.0, change + float(profile["turnover_people"]))
    salaries = float(profile["salary_per"]) * total_sf * 1e-6
    expenses = float(profile["expense_per"]) * total_sf * 1e-6
    training = float(profile["training_per"]) * training_people * 1e-6
    return salaries + expenses + training


def solve_total_sf_for_budget(target_budget: float, session: dict[str, Any]) -> tuple[int, float]:
    profile = session["sf_profile"]
    max_total = int(profile["max_total_sf"])
    best_total = 0
    best_cost = 0.0
    for total_sf in range(max_total + 1):
        cost = _sf_cost_for_total(total_sf, session)
        if cost <= target_budget + 1e-9:
            best_total = total_sf
            best_cost = cost
        else:
            break
    return best_total, best_cost


def distribute_sf_counts(target_total: int, session: dict[str, Any]) -> dict[str, int]:
    previous_counts = session["sf_profile"]["previous_counts"]
    counts = {field: int(previous_counts[field]) for field in SF_FIELDS}
    target_total = max(0, min(int(target_total), int(session["sf_profile"]["max_total_sf"])))
    current_total = sum(counts.values())

    if current_total == target_total:
        return counts

    mins = {field: int(CONSTRAINTS[field].min or 0) for field in SF_FIELDS}
    maxes = {field: int(CONSTRAINTS[field].max or 1000) for field in SF_FIELDS}
    delta = target_total - current_total
    keys = list(SF_FIELDS)
    cursor = 0
    safety = 0
    limit = 100000

    if delta > 0:
        while delta > 0:
            field = keys[cursor % len(keys)]
            if counts[field] < maxes[field]:
                counts[field] += 1
                delta -= 1
            cursor += 1
            safety += 1
            if safety > limit:
                raise RuntimeError("Failed to distribute positive SF delta")
    else:
        delta = abs(delta)
        while delta > 0:
            field = keys[cursor % len(keys)]
            if counts[field] > mins[field]:
                counts[field] -= 1
                delta -= 1
            cursor += 1
            safety += 1
            if safety > limit:
                raise RuntimeError("Failed to distribute negative SF delta")

    return counts


def build_search_space(session: dict[str, Any]) -> dict[str, dict[str, float]]:
    available_budget = float(session["available_budget"])
    target_total_budget = _target_total_budget(session)
    baseline = session["baseline_suggestion"]
    requested_discount_max = float(session["requested_discount_max"])
    validated_discount_max = min(
        requested_discount_max,
        float(CONSTRAINTS["discount_under_250"].max or requested_discount_max),
    )
    min_total = target_total_budget
    max_total = target_total_budget

    return {
        "total_budget": {"low": min_total, "high": max_total},
        "ad_budget": {
            "low": max(0.0, float(baseline["ad_budget"]) - 4.0),
            "high": min(available_budget, float(baseline["ad_budget"]) + 4.0),
        },
        "coop_ad_budget": {
            "low": max(0.0, float(baseline["coop_ad_budget"]) - 1.0),
            "high": min(available_budget, float(baseline["coop_ad_budget"]) + 1.8),
        },
        "coupon_budget": {
            "low": max(0.0, float(baseline["coupon_budget"]) - 1.5),
            "high": min(available_budget, float(baseline["coupon_budget"]) + 2.5),
        },
        "pop_budget": {
            "low": max(0.0, float(baseline["pop_budget"]) - 1.5),
            "high": min(available_budget, float(baseline["pop_budget"]) + 2.0),
        },
        "msg_benefits_pct": {
            "low": max(0.0, float(baseline["msg_benefits_pct"]) - 30.0),
            "high": min(95.0, float(baseline["msg_benefits_pct"]) + 30.0),
        },
        "msrp": {"low": 5.3, "high": 5.5},
        "discount_under_250": {
            "low": max(15.0, float(baseline["discount_under_250"]) - 8.0),
            "high": min(validated_discount_max, float(baseline["discount_under_250"]) + 8.0),
        },
        "discount_under_2500": {
            "low": max(15.0, float(baseline["discount_under_2500"]) - 8.0),
            "high": min(validated_discount_max, float(baseline["discount_under_2500"]) + 8.0),
        },
        "discount_2500_plus": {
            "low": max(15.0, float(baseline["discount_2500_plus"]) - 8.0),
            "high": min(validated_discount_max, float(baseline["discount_2500_plus"]) + 8.0),
        },
        "discount_wholesale": {
            "low": max(15.0, float(baseline["discount_wholesale"]) - 8.0),
            "high": min(validated_discount_max, float(baseline["discount_wholesale"]) + 8.0),
        },
    }


def _base_suggestion_template(session: dict[str, Any]) -> dict[str, Any]:
    baseline = deepcopy(session["baseline_suggestion"])
    result = {
        key: value
        for key, value in baseline.items()
        if not key.startswith("_")
    }

    for field in BASELINE_FIXED_COPY_FIELDS:
        if field in baseline:
            result[field] = baseline[field]

    result["msg_primary_pct"] = 0.0
    result["msg_comparison_pct"] = 5.0

    for field in ALLOWANCE_FIELDS:
        result[field] = 16.66
    for field in COOP_CHANNEL_FIELDS:
        result[field] = True
    for field in POP_CHANNEL_FIELDS:
        result[field] = True

    result["coupon_amount"] = "1"
    result["trial_budget"] = 0.0

    return result


def _quantize_int(value: float | Decimal) -> int:
    return int(Decimal(str(value)).quantize(ONE_DP0, rounding=ROUND_HALF_UP))


def _coerce_pct(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _floor_to_places(value: Any, places: int) -> float:
    quant = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_FLOOR))


def _compute_total_spend(session: dict[str, Any], suggestion: dict[str, Any]) -> float:
    clean = {
        key: value for key, value in suggestion.items()
        if not key.startswith("_")
    }
    return round(
        sum(float(clean.get(field, 0.0)) for field in BUDGET_FILL_FIELDS)
        + float(clean.get("trial_budget", 0.0))
        + compute_sf_cost(
            clean,
            previous_total_sf=int(session["sf_profile"]["previous_total_sf"]),
            sf_cost_params=_sf_params_for_constraints(session),
        ),
        6,
    )


def _target_total_budget(session: dict[str, Any]) -> float:
    return round(max(0.0, float(session["available_budget"]) - TARGET_BUDGET_BUFFER_M), 6)


def enforce_year1_locked_fields(suggestion: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Force non-optimized Year1 fields to their requested locked values."""

    result = dict(suggestion)
    notes: list[str] = []

    for field in ALLOWANCE_FIELDS:
        current = float(result.get(field, 16.6))
        if abs(current - 16.6) > 1e-9:
            notes.append(f"{field} was reset to 16.6")
        result[field] = 16.6

    for field in COOP_CHANNEL_FIELDS:
        if bool(result.get(field, True)) is not True:
            notes.append(f"{field} was reset to True")
        result[field] = True

    for field in POP_CHANNEL_FIELDS:
        if bool(result.get(field, True)) is not True:
            notes.append(f"{field} was reset to True")
        result[field] = True

    if str(result.get("coupon_amount", "1")) != "1":
        notes.append("coupon_amount was reset to 1")
    result["coupon_amount"] = "1"

    if abs(float(result.get("trial_budget", 0.0))) > 1e-9:
        notes.append("trial_budget was reset to 0.0")
    result["trial_budget"] = 0.0
    return result, notes


def floor_year1_precision(suggestion: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Floor Year1 fields to the simulator-safe display precision."""

    result = dict(suggestion)
    notes: list[str] = []
    sf_changed = False
    budget_changed = False
    allowance_changed = False
    msrp_changed = False
    discount_changed = False

    for field in SF_FIELDS:
        if field not in result:
            continue
        floored = int(math.floor(float(result[field])))
        if floored != int(float(result[field])):
            sf_changed = True
        result[field] = floored

    for field in BUDGET_FILL_FIELDS + ["trial_budget"]:
        if field not in result:
            continue
        floored = _floor_to_places(result[field], 1)
        if abs(float(result[field]) - floored) > 1e-9:
            budget_changed = True
        result[field] = floored

    for field in ALLOWANCE_FIELDS:
        if field not in result:
            continue
        floored = _floor_to_places(result[field], 1)
        if abs(float(result[field]) - floored) > 1e-9:
            allowance_changed = True
        result[field] = floored

    if "msrp" in result:
        floored = _floor_to_places(result["msrp"], 2)
        if abs(float(result["msrp"]) - floored) > 1e-9:
            msrp_changed = True
        result["msrp"] = floored

    for field in DISCOUNT_FIELDS:
        if field not in result:
            continue
        floored = _floor_to_places(result[field], 2)
        if abs(float(result[field]) - floored) > 1e-9:
            discount_changed = True
        result[field] = floored

    if sf_changed:
        notes.append("sales force fields were floored to integers")
    if budget_changed:
        notes.append("budget fields were floored to 1 decimal place")
    if allowance_changed:
        notes.append("allowance fields were floored to 1 decimal place")
    if msrp_changed:
        notes.append("msrp was floored to 2 decimal places")
    if discount_changed:
        notes.append("discount fields were floored to 2 decimal places")
    return result, notes


def enforce_year1_full_budget(
    session: dict[str, Any],
    suggestion: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Fill toward the Year1 target budget by spreading leftover equally."""

    result = dict(suggestion)
    notes: list[str] = []
    target_total = _target_total_budget(session)
    total_spend = _compute_total_spend(session, result)
    remaining = round(target_total - total_spend, 6)

    if remaining <= 1e-9:
        return result, notes

    tenths = int(math.floor(remaining * 10.0 + 1e-9))
    if tenths <= 0:
        return result, notes

    per_field, extra = divmod(tenths, len(BUDGET_FILL_FIELDS))
    for idx, field in enumerate(BUDGET_FILL_FIELDS):
        increment = per_field + (1 if idx < extra else 0)
        result[field] = round(float(result.get(field, 0.0)) + increment / 10.0, 1)

    notes.append(
        "remaining target-budget capacity was allocated equally across "
        "ad_budget, coop_ad_budget, coupon_budget, and pop_budget"
    )
    return result, notes


def enforce_year1_policy(
    session: dict[str, Any],
    suggestion: dict[str, Any],
    *,
    reference: dict[str, Any] | None = None,
    fill_budget: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Canonicalize a Year1 suggestion onto the intended reduced search space."""

    result = dict(suggestion)
    notes: list[str] = []

    result, locked_notes = enforce_year1_locked_fields(result)
    notes.extend(locked_notes)

    result, ad_notes = enforce_year1_ad_policy(result, reference=reference)
    notes.extend(ad_notes)

    result, precision_notes = floor_year1_precision(result)
    notes.extend(precision_notes)

    if fill_budget:
        result, budget_notes = enforce_year1_full_budget(session, result)
        notes.extend(budget_notes)
    return result, notes


def enforce_year1_ad_policy(
    suggestion: dict[str, Any],
    *,
    reference: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Force the Year1 advertising mix onto the reduced search manifold.

    Policy:
      - msg_primary_pct is always 0
      - msg_comparison_pct is always 5
      - all ad-message percentages are integers
      - msg_benefits_pct + msg_reminder_pct must equal 95

    If the human edits only one of benefit/reminder, the other is derived.
    If both are edited inconsistently, benefit takes precedence and reminder
    is recomputed so the total still matches the locked policy.
    """

    result = dict(suggestion)
    notes: list[str] = []
    ref = reference or {}

    raw_benefit = _coerce_pct(
        result.get("msg_benefits_pct"),
        default=_coerce_pct(ref.get("msg_benefits_pct"), default=47.5),
    )
    raw_reminder = _coerce_pct(
        result.get("msg_reminder_pct"),
        default=_coerce_pct(ref.get("msg_reminder_pct"), default=47.5),
    )
    ref_benefit = _coerce_pct(ref.get("msg_benefits_pct"), default=raw_benefit)
    ref_reminder = _coerce_pct(ref.get("msg_reminder_pct"), default=raw_reminder)

    benefit_changed = "msg_benefits_pct" in result and abs(raw_benefit - ref_benefit) > 1e-9
    reminder_changed = "msg_reminder_pct" in result and abs(raw_reminder - ref_reminder) > 1e-9

    if benefit_changed and not reminder_changed:
        benefit = min(95, max(0, _quantize_int(raw_benefit)))
        reminder = AD_MIX_FREE_TOTAL - benefit
    elif reminder_changed and not benefit_changed:
        reminder = min(95, max(0, _quantize_int(raw_reminder)))
        benefit = AD_MIX_FREE_TOTAL - reminder
    else:
        benefit = min(95, max(0, _quantize_int(raw_benefit)))
        reminder = AD_MIX_FREE_TOTAL - benefit

    if abs(float(result.get("msg_primary_pct", AD_MIX_PRIMARY_LOCK)) - AD_MIX_PRIMARY_LOCK) > 1e-9:
        notes.append("msg_primary_pct was reset to integer 0")
    if abs(float(result.get("msg_comparison_pct", AD_MIX_COMPARISON_LOCK)) - AD_MIX_COMPARISON_LOCK) > 1e-9:
        notes.append("msg_comparison_pct was reset to integer 5")
    if "msg_benefits_pct" in result and abs(_coerce_pct(result.get("msg_benefits_pct"), default=benefit) - benefit) > 1e-9:
        notes.append("msg_benefits_pct was rounded/clamped to an integer")
    if "msg_reminder_pct" in result and abs(_coerce_pct(result.get("msg_reminder_pct"), default=reminder) - reminder) > 1e-9:
        notes.append("msg_reminder_pct was recomputed as an integer so benefit+reminder=95")

    result["msg_primary_pct"] = AD_MIX_PRIMARY_LOCK
    result["msg_comparison_pct"] = AD_MIX_COMPARISON_LOCK
    result["msg_benefits_pct"] = benefit
    result["msg_reminder_pct"] = reminder
    return result, notes


def _project_discounts(latent: dict[str, float], session: dict[str, Any]) -> dict[str, float]:
    space = build_search_space(session)
    fields = [
        "discount_under_250",
        "discount_under_2500",
        "discount_2500_plus",
        "discount_wholesale",
    ]
    lows = [float(space[field]["low"]) for field in fields]
    highs = [float(space[field]["high"]) for field in fields]
    raw = [
        max(lows[idx], min(float(latent[field]), highs[idx]))
        for idx, field in enumerate(fields)
    ]

    projected = [raw[0]]
    for idx in range(1, len(raw)):
        value = max(projected[-1], raw[idx])
        value = min(value, highs[idx])
        projected.append(value)

    for idx in range(len(projected) - 2, -1, -1):
        projected[idx] = min(projected[idx], projected[idx + 1], highs[idx])
        projected[idx] = max(projected[idx], lows[idx])

    return {
        "discount_under_250": projected[0],
        "discount_under_2500": projected[1],
        "discount_2500_plus": projected[2],
        "discount_wholesale": projected[3],
    }


def validate_full_suggestion(session: dict[str, Any], suggestion: dict[str, Any]) -> list[str]:
    from src.constraints import validate_budget, validate_suggestion

    policy_label = _policy_label(session)
    errors = list(validate_suggestion(suggestion))
    for field in (
        "msg_primary_pct",
        "msg_benefits_pct",
        "msg_comparison_pct",
        "msg_reminder_pct",
    ):
        value = float(suggestion[field])
        if abs(value - round(value)) > 1e-9:
            errors.append(f"{policy_label} policy requires {field} to be an integer percentage")
    if int(round(float(suggestion["msg_primary_pct"]))) != 0:
        errors.append(f"{policy_label} policy requires msg_primary_pct=0")
    if int(round(float(suggestion["msg_comparison_pct"]))) != 5:
        errors.append(f"{policy_label} policy requires msg_comparison_pct=5")
    if (
        int(round(float(suggestion["msg_benefits_pct"])))
        + int(round(float(suggestion["msg_reminder_pct"])))
        != 95
    ):
        errors.append(f"{policy_label} policy requires msg_benefits_pct + msg_reminder_pct = 95")
    if str(suggestion.get("coupon_amount")) != "1":
        errors.append(f"{policy_label} policy requires coupon_amount=1")
    if abs(float(suggestion.get("trial_budget", 0.0))) > 1e-9:
        errors.append(f"{policy_label} policy requires trial_budget=0.0")
    for field in ALLOWANCE_FIELDS:
        if abs(float(suggestion[field]) - 16.6) > 0.01:
            errors.append(f"{policy_label} policy requires {field}=16.6")
    for field in COOP_CHANNEL_FIELDS + POP_CHANNEL_FIELDS:
        if bool(suggestion[field]) is not True:
            errors.append(f"{policy_label} policy requires {field}=True")

    for field in BUDGET_FILL_FIELDS + ["trial_budget"]:
        value = float(suggestion.get(field, 0.0))
        if abs(value - _floor_to_places(value, 1)) > 1e-9:
            errors.append(f"{policy_label} policy requires {field} to be floored to 1 decimal place")
    for field in ALLOWANCE_FIELDS:
        value = float(suggestion[field])
        if abs(value - _floor_to_places(value, 1)) > 1e-9:
            errors.append(f"{policy_label} policy requires {field} to be floored to 1 decimal place")
    if abs(float(suggestion["msrp"]) - _floor_to_places(suggestion["msrp"], 2)) > 1e-9:
        errors.append(f"{policy_label} policy requires msrp to be floored to 2 decimal places")
    for field in DISCOUNT_FIELDS:
        value = float(suggestion[field])
        if abs(value - _floor_to_places(value, 2)) > 1e-9:
            errors.append(f"{policy_label} policy requires {field} to be floored to 2 decimal places")

    errors.extend(
        validate_budget(
            suggestion,
            available_budget=float(session["available_budget"]),
            previous_total_sf=int(session["sf_profile"]["previous_total_sf"]),
            sf_cost_params=_sf_params_for_constraints(session),
        )
    )
    total_spend = _compute_total_spend(session, suggestion)
    target_total_budget = _target_total_budget(session)
    if total_spend > target_total_budget + 1e-6:
        errors.append(
            f"{policy_label} policy requires total spend to stay within the target budget "
            f"({target_total_budget:.3f} M)"
        )
    return errors


def project_latent_to_suggestion(
    session: dict[str, Any],
    latent: dict[str, float],
) -> tuple[dict[str, Any], dict[str, Any]]:
    search_space = build_search_space(session)
    projected = {
        field: max(bounds["low"], min(bounds["high"], float(latent[field])))
        for field, bounds in search_space.items()
    }

    suggestion = _base_suggestion_template(session)
    suggestion["ad_budget"] = round(projected["ad_budget"], 3)
    suggestion["coop_ad_budget"] = round(projected["coop_ad_budget"], 3)
    suggestion["coupon_budget"] = round(projected["coupon_budget"], 3)
    suggestion["pop_budget"] = round(projected["pop_budget"], 3)
    suggestion["msrp"] = round(projected["msrp"], 3)

    discounts = _project_discounts(projected, session)
    suggestion.update({key: round(value, 3) for key, value in discounts.items()})

    suggestion["msg_benefits_pct"] = projected["msg_benefits_pct"]
    suggestion["msg_reminder_pct"] = 95.0 - suggestion["msg_benefits_pct"]
    locked_suggestion, _ = enforce_year1_locked_fields(suggestion)
    ad_suggestion, _ = enforce_year1_ad_policy(
        locked_suggestion,
        reference=session["baseline_suggestion"],
    )
    suggestion, _ = floor_year1_precision(ad_suggestion)

    total_budget_target = round(projected["total_budget"], 3)
    sf_budget_target = round(
        total_budget_target
        - suggestion["ad_budget"]
        - suggestion["coop_ad_budget"]
        - suggestion["coupon_budget"]
        - suggestion["pop_budget"],
        6,
    )
    if sf_budget_target < -1e-6:
        raise ValueError(
            "Budget split is infeasible: ad/promo budgets exceed the total budget target"
        )

    sf_budget_target = max(0.0, sf_budget_target)
    min_sf_budget_target = max(
        5.0,
        round(float(session["sf_profile"].get("current_sf_budget", 0.0)) * 0.75, 6),
    )
    if sf_budget_target + 1e-9 < min_sf_budget_target:
        raise ValueError(
            f"SF budget {sf_budget_target:.3f} is below the floor {min_sf_budget_target:.3f}"
        )
    total_sf, sf_cost_actual = solve_total_sf_for_budget(sf_budget_target, session)
    sf_counts = distribute_sf_counts(total_sf, session)
    suggestion.update(sf_counts)

    suggestion = normalize_suggestion(suggestion)
    suggestion, _ = enforce_year1_policy(
        session,
        suggestion,
        reference=session["baseline_suggestion"],
        fill_budget=True,
    )

    actual_total_spend = _compute_total_spend(session, suggestion)
    remaining_budget = round(float(session["available_budget"]) - actual_total_spend, 6)
    derived = {
        "target_total_budget": total_budget_target,
        "target_sf_budget": sf_budget_target,
        "actual_sf_headcount_total": total_sf,
        "actual_sf_budget": round(sf_cost_actual, 6),
        "actual_total_spend": actual_total_spend,
        "remaining_budget": remaining_budget,
        "sf_counts": sf_counts,
    }

    suggestion["_session_id"] = session["session_id"]
    suggestion["_state_fingerprint"] = session["state_fingerprint"]
    suggestion["_target_total_budget"] = total_budget_target
    suggestion["_derived_sf_budget"] = round(sf_cost_actual, 6)
    suggestion["_derived_total_spend"] = actual_total_spend
    suggestion["_derived_remaining_budget"] = remaining_budget

    errors = validate_full_suggestion(session, suggestion)
    hard_errors = [error for error in errors if not error.startswith("WARNING:")]
    if hard_errors:
        raise ValueError("; ".join(hard_errors))

    return suggestion, derived


def suggestion_to_latent(session: dict[str, Any], suggestion: dict[str, Any]) -> dict[str, float]:
    clean = {
        key: value for key, value in suggestion.items()
        if not key.startswith("_")
    }
    return {
        "total_budget": _target_total_budget(session),
        "ad_budget": float(clean["ad_budget"]),
        "coop_ad_budget": float(clean["coop_ad_budget"]),
        "coupon_budget": float(clean["coupon_budget"]),
        "pop_budget": float(clean["pop_budget"]),
        "msg_benefits_pct": float(clean["msg_benefits_pct"]),
        "msrp": float(clean["msrp"]),
        "discount_under_250": float(clean["discount_under_250"]),
        "discount_under_2500": float(clean["discount_under_2500"]),
        "discount_2500_plus": float(clean["discount_2500_plus"]),
        "discount_wholesale": float(clean["discount_wholesale"]),
    }


def compute_objective(flat_year: dict[str, Any]) -> dict[str, float]:
    missing = [key for key in OBJECTIVE_KEYS if key not in flat_year or flat_year[key] is None]
    if missing:
        raise ValueError(f"Missing objective inputs: {missing}")

    unit_sales = float(flat_year["performance_summary.unit_sales"])
    net_income = float(flat_year["income_statement.net_income"])
    manufacturer_sales = float(flat_year["income_statement.manufacturer_sales"])
    denominator = (
        float(flat_year["income_statement.cost_of_goods_sold"])
        + float(flat_year["income_statement.total_marketing"])
        + float(flat_year["performance_summary.promotional_allowance"])
        + float(flat_year["performance_summary.fixed_costs"])
    )
    if denominator <= 0:
        raise ValueError("Objective denominator is non-positive")

    components = {
        "unit_sales_component": unit_sales * 3.5,
        "net_income_component": net_income * 4.52,
        "manufacturer_sales_component": manufacturer_sales * 5.0,
        "efficiency_component": manufacturer_sales / denominator * 6.0,
    }
    components["objective_value"] = sum(components.values())
    return components


def _reference_latent(session: dict[str, Any]) -> dict[str, float]:
    return suggestion_to_latent(session, session["baseline_suggestion"])


def _prime_list(count: int) -> list[int]:
    primes: list[int] = []
    n = 2
    while len(primes) < count:
        is_prime = True
        for prime in primes:
            if prime * prime > n:
                break
            if n % prime == 0:
                is_prime = False
                break
        if is_prime:
            primes.append(n)
        n += 1
    return primes


def _van_der_corput(index: int, base: int) -> float:
    result = 0.0
    denom = 1.0
    i = index
    while i > 0:
        i, remainder = divmod(i, base)
        denom *= base
        result += remainder / denom
    return result


def halton_point(index: int, dimension: int) -> list[float]:
    bases = _prime_list(dimension)
    return [_van_der_corput(index, base) for base in bases]


def _euclidean(a: Iterable[float], b: Iterable[float]) -> float:
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def _space_as_vector(space: dict[str, dict[str, float]], latent: dict[str, float]) -> list[float]:
    return [
        (
            float(latent[field]) - float(space[field]["low"])
        ) / max(1e-9, float(space[field]["high"]) - float(space[field]["low"]))
        for field in LATENT_FIELDS
    ]


def _vector_as_latent(space: dict[str, dict[str, float]], point: list[float]) -> dict[str, float]:
    return {
        field: float(space[field]["low"]) + max(0.0, min(1.0, point[idx])) * (
            float(space[field]["high"]) - float(space[field]["low"])
        )
        for idx, field in enumerate(LATENT_FIELDS)
    }


def _latent_list(latent: dict[str, float]) -> list[float]:
    return [float(latent[field]) for field in LATENT_FIELDS]


class GaussianProcess:
    def __init__(self, lengthscale: float = 0.32, noise: float = 1e-6):
        self.lengthscale = float(lengthscale)
        self.noise = float(noise)
        self.fitted = False
        self.x: list[list[float]] = []
        self.y_raw: list[float] = []
        self.y_mean = 0.0
        self.y_std = 1.0
        self.alpha: list[float] = []
        self.cholesky: list[list[float]] = []

    def _kernel(self, a: list[float], b: list[float]) -> float:
        dist_sq = sum(((ai - bi) / self.lengthscale) ** 2 for ai, bi in zip(a, b))
        return math.exp(-0.5 * dist_sq)

    def fit(self, x: list[list[float]], y: list[float]) -> None:
        if not x:
            self.fitted = False
            self.x = []
            self.y_raw = []
            self.y_mean = 0.0
            self.y_std = 1.0
            self.alpha = []
            self.cholesky = []
            return

        self.x = [list(row) for row in x]
        self.y_raw = [float(value) for value in y]
        self.y_mean = sum(self.y_raw) / len(self.y_raw)
        variance = sum((value - self.y_mean) ** 2 for value in self.y_raw) / max(1, len(self.y_raw))
        self.y_std = math.sqrt(variance) if variance > 1e-12 else 1.0
        y_norm = [(value - self.y_mean) / self.y_std for value in self.y_raw]

        n = len(self.x)
        kernel = [[0.0 for _ in range(n)] for _ in range(n)]
        for i in range(n):
            for j in range(i, n):
                value = self._kernel(self.x[i], self.x[j])
                if i == j:
                    value += self.noise
                kernel[i][j] = value
                kernel[j][i] = value

        self.cholesky = cholesky_decomposition(kernel)
        self.alpha = solve_cholesky(self.cholesky, y_norm)
        self.fitted = True

    def predict(self, x_new: list[float]) -> tuple[float, float]:
        if not self.fitted:
            return 0.0, 1.0

        k_star = [self._kernel(x_new, row) for row in self.x]
        mean_norm = sum(weight * alpha for weight, alpha in zip(k_star, self.alpha))
        v = forward_substitution(self.cholesky, k_star)
        variance_norm = max(1e-9, 1.0 - sum(value * value for value in v))
        return (
            self.y_mean + mean_norm * self.y_std,
            math.sqrt(variance_norm) * self.y_std,
        )


def cholesky_decomposition(matrix: list[list[float]]) -> list[list[float]]:
    n = len(matrix)
    lower = [[0.0 for _ in range(n)] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            total = matrix[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if total <= 0:
                    total = 1e-10
                lower[i][j] = math.sqrt(total)
            else:
                lower[i][j] = total / lower[j][j]
    return lower


def forward_substitution(lower: list[list[float]], b: list[float]) -> list[float]:
    y = [0.0 for _ in b]
    for i in range(len(lower)):
        total = b[i] - sum(lower[i][j] * y[j] for j in range(i))
        y[i] = total / lower[i][i]
    return y


def back_substitution(upper: list[list[float]], y: list[float]) -> list[float]:
    x = [0.0 for _ in y]
    n = len(upper)
    for i in range(n - 1, -1, -1):
        total = y[i] - sum(upper[i][j] * x[j] for j in range(i + 1, n))
        x[i] = total / upper[i][i]
    return x


def solve_cholesky(lower: list[list[float]], b: list[float]) -> list[float]:
    y = forward_substitution(lower, b)
    upper = [[lower[j][i] if j >= i else 0.0 for j in range(len(lower))] for i in range(len(lower))]
    return back_substitution(upper, y)


def _rounds_with_status(session_id: str, statuses: set[str]) -> list[dict[str, Any]]:
    return [
        round_record for round_record in load_rounds(session_id)
        if round_record.get("status") in statuses
    ]


def _completed_observations(session_id: str) -> list[dict[str, Any]]:
    completed = _rounds_with_status(session_id, {"completed"})
    return [round_record for round_record in completed if round_record.get("objective_value") is not None]


def _seen_latents(session: dict[str, Any]) -> list[list[float]]:
    rounds = _rounds_with_status(
        session["session_id"],
        {"proposed", "applied_prepared", "completed"},
    )
    latents: list[list[float]] = []
    for round_record in rounds:
        latent = round_record.get("actual_latent") or round_record.get("proposal_latent")
        if latent:
            latents.append(_latent_list(latent))
    return latents


def _completed_xy(session: dict[str, Any]) -> tuple[list[list[float]], list[float]]:
    space = build_search_space(session)
    x_rows: list[list[float]] = []
    y_values: list[float] = []
    for observation in _completed_observations(session["session_id"]):
        latent = observation.get("actual_latent")
        objective = observation.get("objective_value")
        if latent is None or objective is None:
            continue
        x_rows.append(_space_as_vector(space, latent))
        y_values.append(float(objective))
    return x_rows, y_values


def _initial_design_score(
    point_unit: list[float],
    seen_unit: list[list[float]],
) -> float:
    if not seen_unit:
        return 0.0
    center = [0.5] * len(point_unit)
    min_dist = min(_euclidean(point_unit, prior) for prior in seen_unit)
    center_penalty = _euclidean(point_unit, center)
    target_radius = 0.42
    return -abs(min_dist - target_radius) - 0.35 * center_penalty


def _expected_improvement(mean: float, std: float, best_y: float, xi: float = 0.01) -> float:
    if std <= 1e-9:
        return 0.0
    improvement = mean - best_y - xi
    z = improvement / std
    return improvement * NORMAL.cdf(z) + std * NORMAL.pdf(z)


def propose_candidates(
    session: dict[str, Any],
    top_k: int = 5,
    candidate_count: int = 2048,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    space = build_search_space(session)
    reference_unit = _space_as_vector(space, _reference_latent(session))
    seen_raw = _seen_latents(session)
    seen_unit = [list(row) for row in seen_raw]
    if not seen_unit:
        seen_unit = [reference_unit]
    else:
        seen_unit.append(reference_unit)

    train_x, train_y = _completed_xy(session)
    gp = GaussianProcess()
    gp.fit(train_x, train_y)
    best_observed = max(train_y) if train_y else None

    ranked: list[dict[str, Any]] = []
    for index in range(5, 5 + candidate_count):
        point_unit = halton_point(index, len(LATENT_FIELDS))
        latent = _vector_as_latent(space, point_unit)
        try:
            suggestion, derived = project_latent_to_suggestion(session, latent)
        except ValueError:
            continue

        point_unit_projected = _space_as_vector(space, suggestion_to_latent(session, suggestion))
        if train_y:
            mean, std = gp.predict(point_unit_projected)
            acquisition = _expected_improvement(mean, std, best_observed or 0.0)
            mode = "expected_improvement"
        else:
            mean, std = (None, None)
            acquisition = _initial_design_score(point_unit_projected, seen_unit)
            mode = "initial_design"

        ranked.append({
            "latent": {field: round(float(latent[field]), 6) for field in LATENT_FIELDS},
            "suggestion": suggestion,
            "derived": derived,
            "predicted_objective_mean": None if mean is None else round(float(mean), 6),
            "predicted_objective_std": None if std is None else round(float(std), 6),
            "acquisition_score": round(float(acquisition), 6),
            "acquisition_mode": mode,
        })

    if not ranked:
        raise RuntimeError("Failed to generate any feasible candidates")

    ranked.sort(key=lambda item: item["acquisition_score"], reverse=True)
    summary = {
        "model_mode": "gaussian_process" if train_y else "initial_design",
        "candidate_count": len(ranked),
        "observation_count": len(train_y),
        "best_observed_objective": None if best_observed is None else round(float(best_observed), 6),
    }
    return ranked[:top_k], summary


def _min_max(values: list[float]) -> tuple[float, float]:
    if not values:
        return (0.0, 1.0)
    lo = min(values)
    hi = max(values)
    if math.isclose(lo, hi):
        pad = 1.0 if abs(lo) < 1.0 else abs(lo) * 0.05
        return (lo - pad, hi + pad)
    pad = (hi - lo) * 0.08
    return (lo - pad, hi + pad)


def _format_num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _chart_svg(
    title: str,
    x_values: list[float],
    y_values: list[float | None],
    *,
    y_band_low: list[float | None] | None = None,
    y_band_high: list[float | None] | None = None,
    points: list[tuple[float, float]] | None = None,
    baseline_x: float | None = None,
    proposed_x: float | None = None,
    width: int = 520,
    height: int = 180,
) -> str:
    valid = [(x, y) for x, y in zip(x_values, y_values) if y is not None]
    if not valid:
        return (
            f"<svg viewBox='0 0 {width} {height}' class='chart'>"
            f"<rect width='{width}' height='{height}' fill='#fffaf1' stroke='#d7ccb8'/>"
            f"<text x='16' y='26' font-size='14' font-family='monospace'>{title}</text>"
            f"<text x='16' y='94' font-size='12' font-family='monospace'>No data yet</text>"
            f"</svg>"
        )

    margin_left = 54
    margin_right = 18
    margin_top = 22
    margin_bottom = 28
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    x_lo, x_hi = _min_max(x_values)
    y_samples = [y for _, y in valid]
    if y_band_low:
        y_samples.extend(y for y in y_band_low if y is not None)
    if y_band_high:
        y_samples.extend(y for y in y_band_high if y is not None)
    if points:
        y_samples.extend(y for _, y in points)
    y_lo, y_hi = _min_max(y_samples)

    def sx(value: float) -> float:
        return margin_left + (value - x_lo) / max(1e-9, x_hi - x_lo) * plot_w

    def sy(value: float) -> float:
        return margin_top + (1.0 - (value - y_lo) / max(1e-9, y_hi - y_lo)) * plot_h

    polyline = " ".join(f"{sx(x):.2f},{sy(y):.2f}" for x, y in valid)
    band_path = ""
    if y_band_low and y_band_high:
        upper = [
            (x, y)
            for x, y in zip(x_values, y_band_high)
            if y is not None
        ]
        lower = [
            (x, y)
            for x, y in zip(x_values, y_band_low)
            if y is not None
        ]
        if upper and lower:
            path_points = upper + list(reversed(lower))
            band_path = " ".join(f"{sx(x):.2f},{sy(y):.2f}" for x, y in path_points)

    grid = []
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = margin_top + frac * plot_h
        grid.append(
            f"<line x1='{margin_left}' y1='{y:.2f}' x2='{width - margin_right}' y2='{y:.2f}' "
            "stroke='#efe3cf' stroke-width='1'/>"
        )

    markers = []
    if points:
        for x, y in points:
            markers.append(
                f"<circle cx='{sx(x):.2f}' cy='{sy(y):.2f}' r='3.5' fill='#7a3d15' opacity='0.85'/>"
            )

    verticals = []
    if baseline_x is not None:
        x = sx(baseline_x)
        verticals.append(
            f"<line x1='{x:.2f}' y1='{margin_top}' x2='{x:.2f}' y2='{height - margin_bottom}' "
            "stroke='#0f766e' stroke-dasharray='5 4' stroke-width='1.4'/>"
        )
    if proposed_x is not None:
        x = sx(proposed_x)
        verticals.append(
            f"<line x1='{x:.2f}' y1='{margin_top}' x2='{x:.2f}' y2='{height - margin_bottom}' "
            "stroke='#c2410c' stroke-dasharray='6 3' stroke-width='1.6'/>"
        )

    y_ticks = []
    for frac in (0.0, 0.5, 1.0):
        value = y_hi - frac * (y_hi - y_lo)
        y = margin_top + frac * plot_h
        y_ticks.append(
            f"<text x='{margin_left - 8}' y='{y + 4:.2f}' text-anchor='end' font-size='10' "
            f"font-family='monospace' fill='#5e5245'>{_format_num(value)}</text>"
        )

    x_ticks = []
    for frac in (0.0, 0.5, 1.0):
        value = x_lo + frac * (x_hi - x_lo)
        x = margin_left + frac * plot_w
        x_ticks.append(
            f"<text x='{x:.2f}' y='{height - 8}' text-anchor='middle' font-size='10' "
            f"font-family='monospace' fill='#5e5245'>{_format_num(value)}</text>"
        )

    band_svg = (
        f"<polygon points='{band_path}' fill='#facc15' opacity='0.22' stroke='none'/>"
        if band_path else ""
    )

    return (
        f"<svg viewBox='0 0 {width} {height}' class='chart'>"
        f"<rect width='{width}' height='{height}' rx='10' fill='#fffaf1' stroke='#d7ccb8'/>"
        f"<text x='16' y='18' font-size='14' font-family='monospace' fill='#3d3228'>{title}</text>"
        f"{''.join(grid)}"
        f"{band_svg}"
        f"{''.join(verticals)}"
        f"<polyline points='{polyline}' fill='none' stroke='#1d4ed8' stroke-width='2.2'/>"
        f"{''.join(markers)}"
        f"{''.join(y_ticks)}"
        f"{''.join(x_ticks)}"
        f"</svg>"
    )


def _build_slice_data(
    session: dict[str, Any],
    base_latent: dict[str, float],
    field: str,
    model_summary: dict[str, Any],
) -> dict[str, Any]:
    space = build_search_space(session)
    train_x, train_y = _completed_xy(session)
    gp = GaussianProcess()
    gp.fit(train_x, train_y)
    best_observed = max(train_y) if train_y else None
    seen_raw = _seen_latents(session)
    reference_unit = _space_as_vector(space, _reference_latent(session))
    seen_unit = [list(row) for row in seen_raw] or [reference_unit]

    bounds = space[field]
    grid_x = [
        bounds["low"] + i * (bounds["high"] - bounds["low"]) / 60.0
        for i in range(61)
    ]
    objective_mean: list[float | None] = []
    objective_std: list[float | None] = []
    acquisition: list[float | None] = []

    for value in grid_x:
        latent = dict(base_latent)
        latent[field] = value
        try:
            suggestion, _ = project_latent_to_suggestion(session, latent)
        except ValueError:
            objective_mean.append(None)
            objective_std.append(None)
            acquisition.append(None)
            continue

        point_unit = _space_as_vector(space, suggestion_to_latent(session, suggestion))
        if train_y:
            mean, std = gp.predict(point_unit)
            objective_mean.append(mean)
            objective_std.append(std)
            acquisition.append(_expected_improvement(mean, std, best_observed or 0.0))
        else:
            objective_mean.append(None)
            objective_std.append(None)
            acquisition.append(_initial_design_score(point_unit, seen_unit + [reference_unit]))

    observed_points = []
    for observation in _completed_observations(session["session_id"]):
        latent = observation.get("actual_latent")
        objective = observation.get("objective_value")
        if latent and objective is not None:
            observed_points.append((float(latent[field]), float(objective)))

    return {
        "field": field,
        "label": LATENT_LABELS[field],
        "grid_x": [round(value, 6) for value in grid_x],
        "objective_mean": [None if value is None else round(float(value), 6) for value in objective_mean],
        "objective_std": [None if value is None else round(float(value), 6) for value in objective_std],
        "acquisition": [None if value is None else round(float(value), 6) for value in acquisition],
        "observed_points": observed_points,
        "baseline_x": float(_reference_latent(session)[field]),
        "proposed_x": float(base_latent[field]),
        "model_mode": model_summary["model_mode"],
    }


def render_plot_report(
    session: dict[str, Any],
    round_record: dict[str, Any],
    model_summary: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    base_latent = round_record.get("actual_latent") or round_record["proposal_latent"]
    slices = [
        _build_slice_data(session, base_latent, field, model_summary)
        for field in LATENT_FIELDS
    ]

    completed = _completed_observations(session["session_id"])
    history_points = [
        (idx + 1, float(observation["objective_value"]))
        for idx, observation in enumerate(completed)
        if observation.get("objective_value") is not None
    ]
    history_svg = _chart_svg(
        "Objective History by Completed Round",
        [x for x, _ in history_points] or [0.0, 1.0],
        [y for _, y in history_points] or [None, None],
        points=history_points or None,
    )

    cards = []
    for slice_data in slices:
        mean = slice_data["objective_mean"]
        std = slice_data["objective_std"]
        acquisition = slice_data["acquisition"]
        band_low = [
            None if m is None or s is None else m - 2.0 * s
            for m, s in zip(mean, std)
        ]
        band_high = [
            None if m is None or s is None else m + 2.0 * s
            for m, s in zip(mean, std)
        ]
        mean_svg = _chart_svg(
            f"{slice_data['label']} — Objective Mean",
            slice_data["grid_x"],
            mean,
            y_band_low=band_low,
            y_band_high=band_high,
            points=slice_data["observed_points"],
            baseline_x=slice_data["baseline_x"],
            proposed_x=slice_data["proposed_x"],
        )
        std_svg = _chart_svg(
            f"{slice_data['label']} — Surrogate Std",
            slice_data["grid_x"],
            std,
            baseline_x=slice_data["baseline_x"],
            proposed_x=slice_data["proposed_x"],
        )
        acq_title = (
            f"{slice_data['label']} — Acquisition"
            if model_summary["model_mode"] == "gaussian_process"
            else f"{slice_data['label']} — Initial Design Score"
        )
        acq_svg = _chart_svg(
            acq_title,
            slice_data["grid_x"],
            acquisition,
            baseline_x=slice_data["baseline_x"],
            proposed_x=slice_data["proposed_x"],
        )
        cards.append(
            "<section class='card'>"
            f"<h2>{slice_data['label']}</h2>"
            f"{mean_svg}{std_svg}{acq_svg}"
            "</section>"
        )

    proposal = round_record["proposal_suggestion"]
    predicted_mean = round_record.get("predicted_objective_mean")
    predicted_std = round_record.get("predicted_objective_std")
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{session['session_id']} {round_record['round_id']} plots</title>
  <style>
    :root {{
      --bg: #f4efe6;
      --paper: #fffaf1;
      --ink: #2e2621;
      --muted: #6b5f51;
      --accent: #c2410c;
      --line: #d7ccb8;
    }}
    body {{
      margin: 0;
      padding: 24px;
      background:
        radial-gradient(circle at top left, #fbe7c6 0, transparent 34%),
        linear-gradient(180deg, #f7f1e8 0%, var(--bg) 100%);
      color: var(--ink);
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
    }}
    h1, h2, h3 {{
      margin: 0 0 10px 0;
      font-weight: 600;
    }}
    .intro {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 20px 22px;
      margin-bottom: 18px;
      box-shadow: 0 10px 24px rgba(92, 63, 40, 0.08);
    }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px 18px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 14px;
    }}
    .history {{
      margin: 18px 0 22px 0;
    }}
    .card {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      margin-bottom: 18px;
      box-shadow: 0 10px 24px rgba(92, 63, 40, 0.08);
    }}
    .chart {{
      display: block;
      width: 100%;
      margin-bottom: 12px;
    }}
    .mono {{
      font-family: "SFMono-Regular", "Menlo", monospace;
    }}
    pre {{
      margin: 0;
      padding: 14px;
      border-radius: 12px;
      background: #f8f2e8;
      border: 1px solid #eadbc5;
      overflow-x: auto;
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <section class="intro">
    <h1>{_stage_label(int(session.get('state_year', 1)))} → {_stage_label(_session_outcome_year(session))} Optimization Report</h1>
    <div class="meta">
      <div><strong>Session</strong><br><span class="mono">{session['session_id']}</span></div>
      <div><strong>Round</strong><br><span class="mono">{round_record['round_id']}</span></div>
      <div><strong>Mode</strong><br>{model_summary['model_mode']}</div>
      <div><strong>Observations</strong><br>{model_summary['observation_count']}</div>
      <div><strong>Predicted Objective</strong><br>{_format_num(predicted_mean, 3)}</div>
      <div><strong>Predicted Std</strong><br>{_format_num(predicted_std, 3)}</div>
      <div><strong>Acquisition</strong><br>{_format_num(round_record.get('acquisition_score'), 4)}</div>
      <div><strong>Remaining Budget</strong><br>{_format_num(proposal.get('_derived_remaining_budget'), 3)} M</div>
    </div>
  </section>
  <section class="card history">
    <h2>Completed Objective History</h2>
    {history_svg}
  </section>
  {''.join(cards)}
  <section class="card">
    <h2>Current Proposal JSON</h2>
    <pre>{json.dumps(proposal, indent=2)}</pre>
  </section>
</body>
</html>
"""
    data = {
        "session_id": session["session_id"],
        "round_id": round_record["round_id"],
        "model_summary": model_summary,
        "slices": slices,
        "history": history_points,
        "proposal": proposal,
    }
    return html, data


def create_session_from_existing(
    run_id: str,
    decisions_path: str | Path,
    *,
    requested_discount_max: float = 75.0,
    name: str | None = None,
    state_year: int = 1,
    decision_period: int | None = None,
    outcome_year: int | None = None,
) -> dict[str, Any]:
    if decision_period is None:
        decision_period = state_year
    if outcome_year is None:
        outcome_year = state_year + 1

    year1_run_dir = run_dir(run_id)
    state_flat_path = year1_run_dir / f"year{state_year}_parsed.json"
    if not state_flat_path.exists():
        raise FileNotFoundError(
            f"{state_flat_path} is missing. Parse the run first or use capture-session."
        )

    session_id = next_session_id()
    session_dir = _session_dir(session_id)
    _ensure_dir(session_dir)
    _ensure_dir(YEAR1_OPT_DIR)

    copied_state = _copy_into_session(session_dir, f"year{state_year}_state.json", state_flat_path)
    copied_decisions = _copy_into_session(
        session_dir,
        f"decisions_period{decision_period}.json",
        Path(decisions_path),
    )

    year1_flat = _read_json(copied_state)
    decisions = _read_json(copied_decisions)
    baseline_suggestion = scraped_to_suggestion(decisions)
    _ensure_strategy_surface_available(baseline_suggestion, state_year=state_year)
    baseline_path = session_dir / "baseline_suggestion.json"
    _write_json(baseline_path, baseline_suggestion)

    session = {
        "session_id": session_id,
        "name": name or session_id,
        "created_at": _now_iso(),
        "source_run_id": run_id,
        "state_year": state_year,
        "decision_period": decision_period,
        "outcome_year": outcome_year,
        "state_flat_path": _rel(copied_state),
        "decision_scrape_path": _rel(copied_decisions),
        "baseline_suggestion_path": _rel(baseline_path),
        "available_budget": _extract_available_budget(year1_flat, decisions),
        "current_total_spend": _extract_current_total_spend(decisions),
        "sf_profile": _extract_sf_profile(decisions),
        "requested_discount_max": float(requested_discount_max),
        "validated_discount_max": min(
            float(requested_discount_max),
            float(CONSTRAINTS["discount_under_250"].max or requested_discount_max),
        ),
        "state_fingerprint": _hash_obj({
            "year1_state": year1_flat,
            "baseline_decision": baseline_suggestion,
        }),
        "baseline_suggestion": baseline_suggestion,
        "search_space": build_search_space({
            "available_budget": _extract_available_budget(year1_flat, decisions),
            "current_total_spend": _extract_current_total_spend(decisions),
            "baseline_suggestion": baseline_suggestion,
            "requested_discount_max": float(requested_discount_max),
        }),
    }
    save_session(session)
    save_rounds(session_id, [])
    return session


def capture_session(
    *,
    requested_discount_max: float = 75.0,
    name: str | None = None,
    state_year: int = 1,
    decision_period: int | None = None,
    outcome_year: int | None = None,
) -> dict[str, Any]:
    if decision_period is None:
        decision_period = state_year
    if outcome_year is None:
        outcome_year = state_year + 1

    run_id = run_scrape(periods=[state_year])
    run_parse(run_id)

    temp_dir = YEAR1_OPT_DIR / "_capture_tmp"
    _ensure_dir(temp_dir)
    decision_output = temp_dir / f"decisions_period{decision_period}_raw.json"
    scrape_decisions_selenium(
        period=decision_period,
        output_path=decision_output,
        print_summary=False,
    )
    session = create_session_from_existing(
        run_id,
        decision_output,
        requested_discount_max=requested_discount_max,
        name=name,
        state_year=state_year,
        decision_period=decision_period,
        outcome_year=outcome_year,
    )
    if decision_output.exists():
        decision_output.unlink()
    if temp_dir.exists():
        try:
            temp_dir.rmdir()
        except OSError:
            pass
    return session


def suggest_round(session_id: str) -> dict[str, Any]:
    session = load_session(session_id)
    round_id = next_round_id(session_id)
    round_dir = _round_dir(session_id, round_id)
    _ensure_dir(round_dir)

    ranked, model_summary = propose_candidates(session)
    best = ranked[0]
    best_suggestion = deepcopy(best["suggestion"])
    best_suggestion["_round_id"] = round_id
    best_suggestion["_proposal_created_at"] = _now_iso()

    suggestion_path = round_dir / "suggestion.json"
    proposal_path = round_dir / "proposal.json"
    ranking_path = round_dir / "proposal_rankings.json"
    _write_json(suggestion_path, best_suggestion)
    _write_json(proposal_path, best)
    _write_json(ranking_path, ranked)

    round_record = {
        "round_id": round_id,
        "status": "proposed",
        "created_at": _now_iso(),
        "proposal_suggestion_path": _rel(suggestion_path),
        "proposal_path": _rel(proposal_path),
        "proposal_rankings_path": _rel(ranking_path),
        "proposal_suggestion": best_suggestion,
        "proposal_latent": best["latent"],
        "proposal_derived": best["derived"],
        "predicted_objective_mean": best["predicted_objective_mean"],
        "predicted_objective_std": best["predicted_objective_std"],
        "acquisition_score": best["acquisition_score"],
        "acquisition_mode": best["acquisition_mode"],
        "model_summary": model_summary,
    }

    html, plot_data = render_plot_report(session, round_record, model_summary)
    plots_dir = round_dir / "plots"
    _ensure_dir(plots_dir)
    plot_html_path = plots_dir / "report.html"
    plot_data_path = plots_dir / "report_data.json"
    plot_html_path.write_text(html)
    _write_json(plot_data_path, plot_data)

    round_record["plot_report_path"] = _rel(plot_html_path)
    round_record["plot_data_path"] = _rel(plot_data_path)
    upsert_round(session_id, round_record)
    return round_record


def _diff_suggestions(
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[dict[str, Any]]:
    diffs = []
    keys = sorted({
        key for key in before.keys() | after.keys()
        if not key.startswith("_")
    })
    for key in keys:
        if before.get(key) != after.get(key):
            diffs.append({
                "field": key,
                "before": before.get(key),
                "after": after.get(key),
            })
    return diffs


def register_applied(
    session_id: str,
    round_id: str,
    suggestion_path: str | Path,
) -> dict[str, Any]:
    session = load_session(session_id)
    rounds = load_rounds(session_id)
    round_record = next(
        (item for item in rounds if item["round_id"] == round_id),
        None,
    )
    if round_record is None:
        raise FileNotFoundError(f"Unknown round {round_id} in {session_id}")

    raw = _read_json(suggestion_path)
    actual_suggestion, policy_notes = enforce_year1_policy(
        session,
        raw,
        reference=round_record.get("proposal_suggestion") or session["baseline_suggestion"],
        fill_budget=False,
    )
    errors = validate_full_suggestion(session, actual_suggestion)
    hard_errors = [error for error in errors if not error.startswith("WARNING:")]
    if hard_errors:
        raise ValueError("Suggestion rejected:\n  " + "\n  ".join(hard_errors))

    round_dir = _round_dir(session_id, round_id)
    applied_path = round_dir / "applied_suggestion.json"
    _write_json(applied_path, actual_suggestion)

    scripts = generate_page_scripts(actual_suggestion, auto_save=True)
    scripts_payload = [
        {
            "page_path": page_path,
            "navigation_js": nav_js,
            "set_values_js": set_js,
        }
        for page_path, nav_js, set_js in scripts
    ]
    scripts_path = round_dir / "apply_scripts.json"
    _write_json(scripts_path, scripts_payload)

    actual_latent = suggestion_to_latent(session, actual_suggestion)
    diffs = _diff_suggestions(round_record["proposal_suggestion"], actual_suggestion)
    round_record.update({
        "status": "applied_prepared",
        "applied_at": _now_iso(),
        "applied_suggestion_path": _rel(applied_path),
        "apply_scripts_path": _rel(scripts_path),
        "actual_suggestion": actual_suggestion,
        "actual_latent": actual_latent,
        "was_human_edited": bool(diffs),
        "edit_diff": diffs,
        "policy_adjustments": policy_notes,
        "year1_policy_adjustments": policy_notes,
    })
    upsert_round(session_id, round_record)
    return round_record


def _prompt(message: str, assume_yes: bool = False) -> str:
    print(message)
    if assume_yes:
        return ""
    try:
        return input("> ")
    except EOFError:
        return ""


def _wrap_async_for_selenium(async_js: str) -> str:
    return f"""
var callback = arguments[arguments.length - 1];
var fn = {async_js};
fn().then(function(result) {{
    callback(result);
}}).catch(function(err) {{
    callback({{error: err.message || String(err)}});
}});
"""


def _execute_sync_arrow(driver, js_code: str) -> Any:
    return driver.execute_script(f"return ({js_code})();")


def _execute_async_arrow(driver, async_js: str) -> Any:
    return driver.execute_async_script(_wrap_async_for_selenium(async_js))


def _wait_for_ready(driver, timeout: int = 20) -> None:
    from selenium.webdriver.support.ui import WebDriverWait

    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    wait.until(
        lambda d: d.execute_script(
            "return typeof ui !== 'undefined' && typeof ui.menu !== 'undefined';"
        )
    )


def _wait_for_page_marker(driver, page_path: str, timeout: int = 20) -> None:
    from selenium.webdriver.support.ui import WebDriverWait

    marker = PAGE_MARKERS.get(page_path)
    if marker is None:
        return

    marker_kind, marker_value = marker
    wait = WebDriverWait(driver, timeout)
    if marker_kind == "field":
        wait.until(
            lambda d: d.execute_script(
                """
                var nameOrId = arguments[0];
                var el = document.querySelector('[name="' + nameOrId + '"]')
                      || document.getElementById(nameOrId);
                return !!el && el.offsetParent !== null;
                """,
                marker_value,
            )
        )
        return

    if marker_kind == "text":
        wait.until(
            lambda d: d.execute_script(
                """
                var needle = arguments[0];
                var nodes = document.querySelectorAll('#content a, #content button, #content th, #content td, #content h1, #content h2, #content h3, #content span, #content div');
                for (var i = 0; i < nodes.length; i++) {
                    var el = nodes[i];
                    if (el.offsetParent === null) continue;
                    if ((el.textContent || '').trim() === needle) return true;
                }
                return false;
                """,
                marker_value,
            )
        )
        return

    if marker_kind == "review":
        wait.until(
            lambda d: d.execute_script(
                """
                var content = document.getElementById('content');
                if (!content || content.offsetParent === null) return false;
                var text = (content.textContent || '').replace(/\\s+/g, ' ');
                return (
                    text.indexOf('Budget') >= 0 &&
                    text.indexOf('Remaining') >= 0 &&
                    text.indexOf('Sales Force') >= 0 &&
                    text.indexOf('Advertising') >= 0 &&
                    text.indexOf('Promotion') >= 0
                );
                """
            )
        )


def _click_save(driver) -> str:
    return str(driver.execute_script("""
        function isVisible(el) {
            return !!el && el.offsetParent !== null;
        }

        function clickSaveElement(el) {
            try {
                el.scrollIntoView({block: 'center'});
            } catch (err) {}
            el.click();
            return 'clicked';
        }

        var candidates = document.querySelectorAll('button, input[type="button"], input[type="submit"], a');
        for (var i = 0; i < candidates.length; i++) {
            var el = candidates[i];
            var label = '';
            if (el.tagName === 'INPUT') {
                label = (el.value || '').trim();
            } else {
                label = (el.textContent || '').trim();
            }
            if (label === 'Save' && isVisible(el) && !el.disabled) {
                return clickSaveElement(el);
            }
        }

        return 'not_found';
    """))


def apply_suggestion_selenium(
    suggestion: dict[str, Any],
    *,
    period: int = 1,
    driver=None,
    keep_driver: bool = False,
) -> dict[str, Any]:
    from selenium.webdriver.support.ui import WebDriverWait

    owns_driver = driver is None
    current_driver = driver
    if current_driver is None:
        current_driver = create_driver()
        wait = WebDriverWait(current_driver, 20)
        login_and_launch(current_driver, wait)

    results: list[dict[str, Any]] = []
    review_status = "unknown"
    try:
        _wait_for_ready(current_driver)
        switch_period(current_driver, period)
        _wait_for_ready(current_driver)

        scripts = generate_page_scripts(suggestion, auto_save=False)
        last_save_status: str | None = None
        for page_path, nav_js, set_js in scripts:
            _execute_sync_arrow(current_driver, nav_js)
            try:
                _wait_for_ready(current_driver)
                _wait_for_page_marker(current_driver, page_path)
            except Exception as exc:
                if last_save_status is None:
                    detail = "the decision page did not become active"
                else:
                    detail = (
                        "the decision page did not become active; the prior page may still "
                        f"have unsaved changes after save_status={last_save_status}"
                    )
                raise RuntimeError(f"{page_path}: {detail}") from exc
            time.sleep(1.2)

            result = _execute_async_arrow(current_driver, set_js)
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(f"{page_path}: {result['error']}")
            if isinstance(result, dict) and result.get("errors"):
                raise RuntimeError(f"{page_path}: {result['errors']}")

            save_status = _click_save(current_driver)
            if save_status == "clicked":
                time.sleep(2.0)
                _wait_for_ready(current_driver)
            else:
                time.sleep(0.75)
                _wait_for_ready(current_driver)
            last_save_status = save_status
            results.append({
                "page_path": page_path,
                "result": result,
                "save_status": save_status,
            })

        _execute_sync_arrow(
            current_driver,
            "() => { ui.menu.call(null, 'decisions', 'decisions/review', {}); return true; }",
        )
        _wait_for_ready(current_driver)
        try:
            _wait_for_page_marker(current_driver, "decisions/review")
            review_status = "confirmed"
        except Exception:
            review_status = "unconfirmed"

        payload = {
            "driver": current_driver if keep_driver else None,
            "pages": results,
            "review_status": review_status,
        }
        if owns_driver and not keep_driver:
            current_driver.quit()
        return payload
    except Exception:
        if owns_driver and current_driver is not None:
            try:
                current_driver.quit()
            except Exception:
                pass
        raise


def scrape_periods_with_driver(
    driver,
    periods: list[int],
) -> str:
    period_tuples = [(i, f"Year{i}") for i in periods]
    meta = create_run(mode="full" if 0 in periods else "partial")
    rd = run_dir(meta.run_id)
    update_run(meta.run_id, status="scraping")
    start = time.time()

    try:
        try:
            driver.execute_cdp_cmd(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(rd)},
            )
        except Exception:
            try:
                driver.execute_cdp_cmd(
                    "Page.setDownloadBehavior",
                    {"behavior": "allow", "downloadPath": str(rd)},
                )
            except Exception:
                pass
        download_all_sections(driver, str(rd), periods=period_tuples)
        elapsed = time.time() - start
        update_run(
            meta.run_id,
            status="complete",
            years_available=periods,
            duration_seconds=round(elapsed, 1),
        )
    except Exception as exc:
        update_run(meta.run_id, status="failed", error=str(exc))
        raise

    run_parse(meta.run_id)
    return meta.run_id


def _current_period(driver) -> int | None:
    value = driver.execute_script("""
        var el = document.getElementById('cperiod');
        return el ? parseInt(el.value) : null;
    """)
    return int(value) if value is not None else None


def _resolve_session_for_guided(
    args,
    *,
    state_year: int = 1,
    decision_period: int | None = None,
    outcome_year: int | None = None,
) -> dict[str, Any]:
    if args.session:
        return load_session(args.session)
    if args.capture:
        return capture_session(
            requested_discount_max=args.discount_max,
            name=args.name,
            state_year=state_year,
            decision_period=decision_period,
            outcome_year=outcome_year,
        )
    if args.run_id and args.decisions:
        return create_session_from_existing(
            args.run_id,
            args.decisions,
            requested_discount_max=args.discount_max,
            name=args.name,
            state_year=state_year,
            decision_period=decision_period,
            outcome_year=outcome_year,
        )
    if LATEST_SESSION_PATH.exists():
        latest = LATEST_SESSION_PATH.read_text().strip()
        if latest:
            return load_session(latest)
    raise ValueError("Provide --session, --capture, or both --run-id and --decisions")


def _resolve_round_for_guided(session_id: str, round_id: str | None) -> dict[str, Any]:
    if round_id is None:
        return suggest_round(session_id)
    round_record = next(
        (item for item in load_rounds(session_id) if item["round_id"] == round_id),
        None,
    )
    if round_record is None:
        raise FileNotFoundError(f"Unknown round {round_id} in {session_id}")
    return round_record


def guided_round(args) -> dict[str, Any]:
    if args.scrape_outcome and not args.apply_selenium:
        raise ValueError("--scrape-outcome requires --apply-selenium")

    session = _resolve_session_for_guided(args)
    round_record = _resolve_round_for_guided(session["session_id"], args.round)

    if args.suggestion:
        suggestion_path = Path(args.suggestion)
    else:
        suggestion_rel = round_record.get("proposal_suggestion_path")
        if not suggestion_rel:
            suggestion_rel = round_record.get("applied_suggestion_path")
        if not suggestion_rel:
            raise FileNotFoundError(
                f"No suggestion file recorded for {session['session_id']} {round_record['round_id']}"
            )
        suggestion_path = PROJECT_ROOT / suggestion_rel

    print(f"Session: {session['session_id']}")
    print(f"Round: {round_record['round_id']}")
    print(f"Suggestion file: {_rel(suggestion_path)}")
    print(f"Suggestion file (abs): {suggestion_path.resolve()}")
    if round_record.get("plot_report_path"):
        print(f"Plots: {round_record['plot_report_path']}")

    if not args.accept_current:
        response = _prompt(
            "Edit the suggestion file if you want, then press Enter to continue. "
            "Type 'stop' to exit without registering it.",
            assume_yes=args.assume_yes,
        )
        if response.strip().lower() in {"stop", "quit", "exit"}:
            return {
                "session_id": session["session_id"],
                "round_id": round_record["round_id"],
                "status": "stopped_before_register",
            }

    applied = register_applied(session["session_id"], round_record["round_id"], suggestion_path)
    print(f"Registered applied suggestion: {applied['applied_suggestion_path']}")
    policy_label = _policy_label(session)
    for note in applied.get("policy_adjustments", applied.get("year1_policy_adjustments", [])):
        print(f"  {policy_label} policy adjustment: {note}")
    ad_mix = applied["actual_suggestion"]
    print(
        f"  {policy_label} ad mix to apply: "
        f"primary={int(ad_mix['msg_primary_pct'])}, "
        f"benefit={int(ad_mix['msg_benefits_pct'])}, "
        f"compare={int(ad_mix['msg_comparison_pct'])}, "
        f"reminder={int(ad_mix['msg_reminder_pct'])}"
    )

    if not args.apply_selenium:
        return applied

    driver = None
    try:
        apply_result = apply_suggestion_selenium(
            applied["actual_suggestion"],
            period=_session_decision_period(session),
            keep_driver=True,
        )
        driver = apply_result["driver"]
        review_status = apply_result.get("review_status", "unknown")
        autosaved_pages = [
            item["page_path"]
            for item in apply_result["pages"]
            if item.get("save_status") == "not_found"
        ]
        if autosaved_pages:
            joined = ", ".join(autosaved_pages)
            print(
                "Values applied. No visible Save button was found on: "
                f"{joined}. Those pages were treated as autosaved or unchanged."
            )
        else:
            print("Values applied and saved.")
        if review_status == "confirmed":
            print("Browser is on the decision review page.")
        else:
            print("Review page could not be confirmed, but the browser session is still open.")
        print("I will not click Advance, Replay, or Restart.")

        if not args.scrape_outcome:
            _prompt(
                "Use the browser now for your manual step. Press Enter when you are done and want this command to close.",
                assume_yes=args.assume_yes,
            )
            return applied

        while True:
            current_period = _current_period(driver)
            if current_period == _session_outcome_year(session):
                break
            outcome_display = _stage_display(_session_outcome_year(session))
            response = _prompt(
                f"Manual step required: advance the sim until {outcome_display} is visible, then press Enter. "
                f"Type 'stop' to exit without scraping {_stage_label(_session_outcome_year(session))}.",
                assume_yes=args.assume_yes,
            )
            if response.strip().lower() in {"stop", "quit", "exit"}:
                return {
                    "session_id": session["session_id"],
                    "round_id": round_record["round_id"],
                    "status": f"waiting_for_{_stage_label(_session_outcome_year(session)).lower()}",
                }
            if args.assume_yes and _current_period(driver) != _session_outcome_year(session):
                raise RuntimeError(
                    f"{_stage_display(_session_outcome_year(session))} is not visible yet; "
                    "rerun without --assume-yes for the manual pause"
                )

        outcome_run_id = scrape_periods_with_driver(driver, [_session_outcome_year(session)])
        completed = record_outcome(
            session["session_id"],
            round_record["round_id"],
            run_id=outcome_run_id,
        )
        print(f"Outcome scraped into run: {completed['outcome_run_id']}")
        print(f"Objective: {completed['objective_value']:.6f}")
        print(f"Plots: {completed['plot_report_path']}")
        return completed
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def record_outcome(
    session_id: str,
    round_id: str,
    *,
    scrape: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    session = load_session(session_id)
    rounds = load_rounds(session_id)
    round_record = next(
        (item for item in rounds if item["round_id"] == round_id),
        None,
    )
    if round_record is None:
        raise FileNotFoundError(f"Unknown round {round_id} in {session_id}")
    if not round_record.get("actual_suggestion"):
        raise ValueError("No applied suggestion recorded for this round")

    outcome_year = _session_outcome_year(session)
    outcome_run_id = run_id
    if scrape:
        outcome_run_id = run_scrape(periods=[outcome_year])
        run_parse(outcome_run_id)
    if not outcome_run_id:
        raise ValueError("Provide --run-id or use --scrape")

    meta = get_run(outcome_run_id)
    if outcome_year not in meta.years_available:
        run_parse(outcome_run_id)

    flat_path = run_dir(outcome_run_id) / f"year{outcome_year}_parsed.json"
    if not flat_path.exists():
        raise FileNotFoundError(f"Expected {flat_path} after parsing {outcome_run_id}")

    outcome_flat = _read_json(flat_path)
    objective = compute_objective(outcome_flat)

    round_dir = _round_dir(session_id, round_id)
    outcome_copy = round_dir / f"year{outcome_year}_outcome.json"
    objective_path = round_dir / "objective.json"
    _write_json(outcome_copy, outcome_flat)
    _write_json(objective_path, objective)

    round_record.update({
        "status": "completed",
        "completed_at": _now_iso(),
        "outcome_run_id": outcome_run_id,
        "outcome_path": _rel(outcome_copy),
        "objective_path": _rel(objective_path),
        "objective_components": objective,
        "objective_value": objective["objective_value"],
    })

    refreshed_model_summary = dict(round_record.get("model_summary", {}))
    refreshed_model_summary["model_mode"] = "gaussian_process"
    refreshed_model_summary["observation_count"] = len(_completed_observations(session_id)) + 1
    refreshed_model_summary["best_observed_objective"] = max(
        [float(objective["objective_value"])]
        + [
            float(item["objective_value"])
            for item in _completed_observations(session_id)
            if item.get("objective_value") is not None
        ]
    )
    round_record["model_summary"] = refreshed_model_summary

    upsert_round(session_id, round_record)
    html, plot_data = render_plot_report(session, round_record, refreshed_model_summary)
    plots_dir = round_dir / "plots"
    _ensure_dir(plots_dir)
    plot_html_path = plots_dir / "report.html"
    plot_data_path = plots_dir / "report_data.json"
    plot_html_path.write_text(html)
    _write_json(plot_data_path, plot_data)
    round_record["plot_report_path"] = _rel(plot_html_path)
    round_record["plot_data_path"] = _rel(plot_data_path)

    upsert_round(session_id, round_record)
    return round_record


def print_status(session_id: str | None = None) -> None:
    if session_id is None and LATEST_SESSION_PATH.exists():
        latest = LATEST_SESSION_PATH.read_text().strip()
        if latest:
            session_id = latest

    if session_id:
        session = load_session(session_id)
        rounds = load_rounds(session_id)
        print(f"Session: {session_id}")
        print(f"  Name: {session.get('name')}")
        print(f"  Source run: {session['source_run_id']}")
        print(f"  Available budget: {session['available_budget']:.3f} M")
        print(f"  Current total spend: {session['current_total_spend']:.3f} M")
        print(
            "  Discount bound request: "
            f"{session['requested_discount_max']:.1f} requested, "
            f"{session['validated_discount_max']:.1f} enforced"
        )
        if not rounds:
            print("  Rounds: none yet")
            return

        print("  Rounds:")
        for round_record in rounds:
            objective = round_record.get("objective_value")
            print(
                f"    {round_record['round_id']}: {round_record['status']}"
                + (f", objective={objective:.4f}" if objective is not None else "")
            )
            if round_record.get("proposal_suggestion_path"):
                print(f"      proposal: {round_record['proposal_suggestion_path']}")
            if round_record.get("applied_suggestion_path"):
                print(f"      applied: {round_record['applied_suggestion_path']}")
            if round_record.get("plot_report_path"):
                print(f"      plots: {round_record['plot_report_path']}")
        return

    sessions = _list_ids(YEAR1_OPT_DIR, "session")
    if not sessions:
        print("No optimization sessions found.")
        return

    print("Sessions:")
    for sid in sessions:
        session = load_session(sid)
        rounds = load_rounds(sid)
        completed = [item for item in rounds if item.get("objective_value") is not None]
        best = max((item["objective_value"] for item in completed), default=None)
        print(
            f"  {sid}: source_run={session['source_run_id']}, rounds={len(rounds)}, "
            + (f"best_objective={best:.4f}" if best is not None else "best_objective=n/a")
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Year1 optimization workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create-session", help="Create a session from existing Year1 artifacts")
    create_parser.add_argument("--run-id", required=True, help="Existing run_id with year1_parsed.json")
    create_parser.add_argument("--decisions", required=True, help="Path to decisions_period1.json")
    create_parser.add_argument("--name", default=None, help="Optional session name")
    create_parser.add_argument("--discount-max", type=float, default=75.0, help="Requested upper discount bound")

    capture_parser = subparsers.add_parser("capture-session", help="Scrape Year1 and create a session")
    capture_parser.add_argument("--name", default=None, help="Optional session name")
    capture_parser.add_argument("--discount-max", type=float, default=75.0, help="Requested upper discount bound")

    suggest_parser = subparsers.add_parser("suggest", help="Generate the next suggestion")
    suggest_parser.add_argument("--session", required=True, help="Session id")

    applied_parser = subparsers.add_parser("register-applied", help="Register the human-edited JSON and emit apply scripts")
    applied_parser.add_argument("--session", required=True, help="Session id")
    applied_parser.add_argument("--round", required=True, help="Round id")
    applied_parser.add_argument("--suggestion", required=True, help="Edited suggestion JSON path")

    outcome_parser = subparsers.add_parser("record-outcome", help="Record the Y2 outcome for a completed round")
    outcome_parser.add_argument("--session", required=True, help="Session id")
    outcome_parser.add_argument("--round", required=True, help="Round id")
    outcome_parser.add_argument("--scrape", action="store_true", help="Scrape Y2 with the existing pipeline")
    outcome_parser.add_argument("--run-id", default=None, help="Existing run_id containing Year2")

    guided_parser = subparsers.add_parser("guided-round", help="Run an end-to-end guided Year1 round")
    guided_parser.add_argument("--session", default=None, help="Existing session id")
    guided_parser.add_argument("--round", default=None, help="Existing round id")
    guided_parser.add_argument("--capture", action="store_true", help="Capture a fresh Year1 session first")
    guided_parser.add_argument("--run-id", default=None, help="Existing run_id for session creation")
    guided_parser.add_argument("--decisions", default=None, help="Existing decisions_period1.json for session creation")
    guided_parser.add_argument("--name", default=None, help="Optional session name when creating one")
    guided_parser.add_argument("--discount-max", type=float, default=75.0, help="Requested upper discount bound")
    guided_parser.add_argument("--suggestion", default=None, help="Use this suggestion path instead of the round default")
    guided_parser.add_argument("--accept-current", action="store_true", help="Skip the edit pause and use the current suggestion file as-is")
    guided_parser.add_argument("--apply-selenium", action="store_true", help="Apply the registered suggestion in a Selenium browser")
    guided_parser.add_argument("--scrape-outcome", action="store_true", help="After manual advance, scrape Year2 and record the outcome in the same command")
    guided_parser.add_argument("--assume-yes", action="store_true", help="Auto-continue through non-manual prompts")

    status_parser = subparsers.add_parser("status", help="Show session status")
    status_parser.add_argument("--session", default=None, help="Optional session id")

    args = parser.parse_args()

    if args.command == "create-session":
        session = create_session_from_existing(
            args.run_id,
            args.decisions,
            requested_discount_max=args.discount_max,
            name=args.name,
        )
        print(f"Created session: {session['session_id']}")
        print(f"  State snapshot: {session['state_flat_path']}")
        print(f"  Decisions snapshot: {session['decision_scrape_path']}")
        print(f"  Baseline suggestion: {session['baseline_suggestion_path']}")
        print(
            "  Discount bound request: "
            f"{session['requested_discount_max']:.1f} requested, "
            f"{session['validated_discount_max']:.1f} enforced"
        )
        return

    if args.command == "capture-session":
        session = capture_session(
            requested_discount_max=args.discount_max,
            name=args.name,
        )
        print(f"Created session: {session['session_id']}")
        print(f"  Source run: {session['source_run_id']}")
        print(f"  State snapshot: {session['state_flat_path']}")
        print(f"  Decisions snapshot: {session['decision_scrape_path']}")
        return

    if args.command == "suggest":
        round_record = suggest_round(args.session)
        print(f"Created round: {round_record['round_id']}")
        print(f"  Suggestion: {round_record['proposal_suggestion_path']}")
        print(f"  Plots: {round_record['plot_report_path']}")
        print(
            "  Prediction: "
            f"mean={_format_num(round_record.get('predicted_objective_mean'), 4)}, "
            f"std={_format_num(round_record.get('predicted_objective_std'), 4)}, "
            f"acquisition={_format_num(round_record.get('acquisition_score'), 4)}"
        )
        print_suggestion_summary(round_record["proposal_suggestion"])
        return

    if args.command == "register-applied":
        round_record = register_applied(args.session, args.round, args.suggestion)
        print(f"Registered applied decision for {args.round}")
        print(f"  Applied suggestion: {round_record['applied_suggestion_path']}")
        print(f"  Apply scripts: {round_record['apply_scripts_path']}")
        print(f"  Human edited: {round_record['was_human_edited']}")
        return

    if args.command == "record-outcome":
        round_record = record_outcome(
            args.session,
            args.round,
            scrape=args.scrape,
            run_id=args.run_id,
        )
        print(f"Recorded outcome for {args.round}")
        print(f"  Outcome run: {round_record['outcome_run_id']}")
        print(f"  Objective: {round_record['objective_value']:.6f}")
        print(f"  Objective details: {round_record['objective_path']}")
        print(f"  Plots: {round_record['plot_report_path']}")
        return

    if args.command == "guided-round":
        result = guided_round(args)
        print("Guided round complete.")
        if result.get("session_id"):
            print(f"  Session: {result['session_id']}")
        if result.get("round_id"):
            print(f"  Round: {result['round_id']}")
        if result.get("status"):
            print(f"  Status: {result['status']}")
        if result.get("applied_suggestion_path"):
            print(f"  Applied suggestion: {result['applied_suggestion_path']}")
        if result.get("apply_scripts_path"):
            print(f"  Apply scripts: {result['apply_scripts_path']}")
        if result.get("objective_value") is not None:
            print(f"  Objective: {result['objective_value']:.6f}")
        if result.get("plot_report_path"):
            print(f"  Plots: {result['plot_report_path']}")
        return

    if args.command == "status":
        print_status(args.session)


if __name__ == "__main__":
    main()
