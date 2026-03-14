"""PharmaSim decision variable constraints.

All constraints are verified against the simulator's actual validation
(error dialogs and spinner min/max attributes) as of 2026-03-14.

Usage:
    from src.constraints import CONSTRAINTS, validate_suggestion, clamp_suggestion
    errors = validate_suggestion(suggestion_dict)
    clamped = clamp_suggestion(suggestion_dict)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Constraint:
    """Constraint on a single decision variable."""
    field: str
    type: str           # "continuous", "integer", "binary", "discrete", "sum_group"
    min: float | None = None
    max: float | None = None
    options: list | None = None  # for discrete/radio/select types
    sum_group: str | None = None  # fields that must sum to a target
    sum_target: float | None = None
    description: str = ""


# ---------------------------------------------------------------------------
# All constraints, verified from the PharmaSim simulator DOM and error dialogs
# ---------------------------------------------------------------------------

CONSTRAINTS: dict[str, Constraint] = {
    # === Sales Force (8 integer fields, min=0, max=1000) ===
    "sf_independent":   Constraint("sf_independent",   "integer", min=0, max=1000, description="Independent Drugstores headcount"),
    "sf_chain":         Constraint("sf_chain",         "integer", min=0, max=1000, description="Chain Drugstores headcount"),
    "sf_grocery":       Constraint("sf_grocery",       "integer", min=0, max=1000, description="Grocery Stores headcount"),
    "sf_convenience":   Constraint("sf_convenience",   "integer", min=0, max=1000, description="Convenience Stores headcount"),
    "sf_mass":          Constraint("sf_mass",          "integer", min=0, max=1000, description="Mass Merchandisers headcount"),
    "sf_wholesaler":    Constraint("sf_wholesaler",    "integer", min=0, max=1000, description="Wholesaler Support headcount"),
    "sf_merchandisers": Constraint("sf_merchandisers", "integer", min=0, max=1000, description="Merchandisers headcount"),
    "sf_detailers":     Constraint("sf_detailers",     "integer", min=0, max=1000, description="Detailers headcount"),

    # === Pricing ===
    "msrp":               Constraint("msrp",               "continuous", min=1.0,  max=50.0, description="Manufacturer Suggested Retail Price ($)"),
    "discount_under_250":  Constraint("discount_under_250",  "continuous", min=10.0, max=50.0, description="Volume discount % for orders < 250 units"),
    "discount_under_2500": Constraint("discount_under_2500", "continuous", min=10.0, max=50.0, description="Volume discount % for orders < 2500 units"),
    "discount_2500_plus":  Constraint("discount_2500_plus",  "continuous", min=10.0, max=50.0, description="Volume discount % for orders 2500+ units"),
    "discount_wholesale":  Constraint("discount_wholesale",  "continuous", min=10.0, max=50.0, description="Wholesale discount %"),

    # === Advertising ===
    "ad_budget": Constraint("ad_budget", "continuous", min=0.0, max=None,
                            description="Advertising budget in millions ($). No hard max; limited by total budget."),
    "ad_agency": Constraint("ad_agency", "discrete", options=["1", "2", "3"],
                            description="Ad agency: '1'=Brewster,Maxwell,Wheeler(15%), '2'=Sully&Rogers(10%), '3'=LesterLoebol(5%)"),

    # Symptom targets (checkboxes — unchecking all = targeting all symptoms)
    "symptom_cold":    Constraint("symptom_cold",    "binary", description="Target cold sufferers"),
    "symptom_cough":   Constraint("symptom_cough",   "binary", description="Target cough sufferers"),
    "symptom_allergy": Constraint("symptom_allergy", "binary", description="Target allergy sufferers"),

    # Demographic targets (checkboxes — unchecking all = targeting all demographics)
    "demo_young_singles":   Constraint("demo_young_singles",   "binary", description="Target Young Singles"),
    "demo_young_families":  Constraint("demo_young_families",  "binary", description="Target Young Families"),
    "demo_mature_families": Constraint("demo_mature_families", "binary", description="Target Mature Families"),
    "demo_empty_nesters":   Constraint("demo_empty_nesters",   "binary", description="Target Empty Nesters"),
    "demo_retired":         Constraint("demo_retired",         "binary", description="Target Retired"),

    # Ad message mix — must sum to exactly 100%
    "msg_primary_pct":    Constraint("msg_primary_pct",    "continuous", min=0, max=100,
                                     sum_group="msg_mix", sum_target=100,
                                     description="Primary ad message %"),
    "msg_benefits_pct":   Constraint("msg_benefits_pct",   "continuous", min=0, max=100,
                                     sum_group="msg_mix", sum_target=100,
                                     description="Benefits ad message %"),
    "msg_comparison_pct": Constraint("msg_comparison_pct", "continuous", min=0, max=100,
                                     sum_group="msg_mix", sum_target=100,
                                     description="Comparison ad message %"),
    "msg_reminder_pct":   Constraint("msg_reminder_pct",   "continuous", min=0, max=100,
                                     sum_group="msg_mix", sum_target=100,
                                     description="Reminder ad message %"),

    "msg_comparison_target": Constraint("msg_comparison_target", "discrete",
                                        options=["2", "3", "4", "5", "6", "7", "8", "9", "10", "11"],
                                        description="Comparison target brand: 2=Besthelp,3=Believe,4=Coughcure,5=Dripstop,6=Defogg,7=Dryup,8=Effective,9=Extra,10=End,11=Coldcure"),

    # Promote benefits (checkboxes)
    "benefit_relieves_aches":         Constraint("benefit_relieves_aches",         "binary", description="Promote: Relieves Aches"),
    "benefit_clears_nasal":           Constraint("benefit_clears_nasal",           "binary", description="Promote: Clears Nasal Congestion"),
    "benefit_reduces_chest":          Constraint("benefit_reduces_chest",          "binary", description="Promote: Reduces Chest Congestion"),
    "benefit_dries_runny_nose":       Constraint("benefit_dries_runny_nose",       "binary", description="Promote: Dries Up Runny Nose"),
    "benefit_suppresses_coughing":    Constraint("benefit_suppresses_coughing",    "binary", description="Promote: Suppresses Coughing"),
    "benefit_relieves_allergies":     Constraint("benefit_relieves_allergies",     "binary", description="Promote: Relieves Allergy Symptoms"),
    "benefit_minimizes_side_effects": Constraint("benefit_minimizes_side_effects", "binary", description="Promote: Minimizes Side Effects"),
    "benefit_wont_cause_drowsiness":  Constraint("benefit_wont_cause_drowsiness",  "binary", description="Promote: Won't Cause Drowsiness"),
    "benefit_helps_you_rest":         Constraint("benefit_helps_you_rest",         "binary", description="Promote: Helps You Rest"),

    # === Promotion ===
    # Promotional allowances — hard range [10%, 20%]
    "allowance_independent": Constraint("allowance_independent", "continuous", min=10.0, max=20.0, description="Promotional allowance % for Independent Drugstores"),
    "allowance_chain":       Constraint("allowance_chain",       "continuous", min=10.0, max=20.0, description="Promotional allowance % for Chain Drugstores"),
    "allowance_grocery":     Constraint("allowance_grocery",     "continuous", min=10.0, max=20.0, description="Promotional allowance % for Grocery Stores"),
    "allowance_convenience": Constraint("allowance_convenience", "continuous", min=10.0, max=20.0, description="Promotional allowance % for Convenience Stores"),
    "allowance_mass":        Constraint("allowance_mass",        "continuous", min=10.0, max=20.0, description="Promotional allowance % for Mass Merchandisers"),
    "allowance_wholesale":   Constraint("allowance_wholesale",   "continuous", min=10.0, max=20.0, description="Promotional allowance % for Wholesalers"),

    # Co-op advertising budget + channel checkboxes
    "coop_ad_budget":      Constraint("coop_ad_budget",      "continuous", min=0.0, max=None, description="Co-op advertising budget ($M)"),
    "coop_ad_independent": Constraint("coop_ad_independent", "binary", description="Co-op ads in Independent Drugstores"),
    "coop_ad_chain":       Constraint("coop_ad_chain",       "binary", description="Co-op ads in Chain Drugstores"),
    "coop_ad_grocery":     Constraint("coop_ad_grocery",     "binary", description="Co-op ads in Grocery Stores"),
    "coop_ad_convenience": Constraint("coop_ad_convenience", "binary", description="Co-op ads in Convenience Stores"),
    "coop_ad_mass":        Constraint("coop_ad_mass",        "binary", description="Co-op ads in Mass Merchandisers"),

    # Point of Purchase budget + channel checkboxes
    "pop_budget":      Constraint("pop_budget",      "continuous", min=0.0, max=None, description="Point of Purchase display budget ($M)"),
    "pop_independent": Constraint("pop_independent", "binary", description="POP displays in Independent Drugstores"),
    "pop_chain":       Constraint("pop_chain",       "binary", description="POP displays in Chain Drugstores"),
    "pop_grocery":     Constraint("pop_grocery",     "binary", description="POP displays in Grocery Stores"),
    "pop_convenience": Constraint("pop_convenience", "binary", description="POP displays in Convenience Stores"),
    "pop_mass":        Constraint("pop_mass",        "binary", description="POP displays in Mass Merchandisers"),

    # Trial size and coupon
    "trial_budget":  Constraint("trial_budget",  "continuous", min=0.0, max=None, description="Trial size budget ($M)"),
    "coupon_budget": Constraint("coupon_budget", "continuous", min=0.0, max=None, description="Coupon budget ($M)"),
    "coupon_amount": Constraint("coupon_amount", "discrete", options=["0", "1", "2", "3"],
                                description="Coupon face value: '0'=$0.25, '1'=$0.50, '2'=$0.75, '3'=$1.00"),

    # === Brand Reformulation (Year 1+ only) ===
    "brand_reformulation": Constraint("brand_reformulation", "discrete", options=["0", "1", "2"],
                                      description="Reformulation: '2'=Keep original, '1'=Drop alcohol, '0'=Switch to expectorant"),
}

# Sum constraint groups
SUM_GROUPS = {
    "msg_mix": {
        "fields": ["msg_primary_pct", "msg_benefits_pct", "msg_comparison_pct", "msg_reminder_pct"],
        "target": 100.0,
        "description": "Ad message percentages must sum to exactly 100%",
    },
}

# Period availability: which fields are editable at each period
PERIOD_0_FIELDS = {
    "ad_agency", "symptom_cold", "symptom_cough", "symptom_allergy",
    "demo_young_singles", "demo_young_families", "demo_mature_families",
    "demo_empty_nesters", "demo_retired",
    "benefit_relieves_aches", "benefit_clears_nasal", "benefit_reduces_chest",
    "benefit_dries_runny_nose", "benefit_suppresses_coughing",
    "benefit_relieves_allergies", "benefit_minimizes_side_effects",
    "benefit_wont_cause_drowsiness", "benefit_helps_you_rest",
}

PERIOD_1_PLUS_FIELDS = set(CONSTRAINTS.keys())


def validate_suggestion(suggestion: dict[str, Any]) -> list[str]:
    """Validate a suggestion dict against all constraints.

    Returns a list of error messages (empty = valid).
    """
    errors = []
    for key, value in suggestion.items():
        if key.startswith("_"):
            continue
        if key not in CONSTRAINTS:
            errors.append(f"Unknown field: {key}")
            continue

        c = CONSTRAINTS[key]

        if c.type == "binary":
            if not isinstance(value, bool) and value not in (0, 1, True, False):
                errors.append(f"{key}: expected bool, got {value!r}")

        elif c.type == "integer":
            try:
                v = int(value)
                if c.min is not None and v < c.min:
                    errors.append(f"{key}={v} below min {c.min}")
                if c.max is not None and v > c.max:
                    errors.append(f"{key}={v} above max {c.max}")
            except (ValueError, TypeError):
                errors.append(f"{key}: expected integer, got {value!r}")

        elif c.type == "continuous":
            try:
                v = float(value)
                if c.min is not None and v < c.min:
                    errors.append(f"{key}={v} below min {c.min}")
                if c.max is not None and v > c.max:
                    errors.append(f"{key}={v} above max {c.max}")
            except (ValueError, TypeError):
                errors.append(f"{key}: expected number, got {value!r}")

        elif c.type == "discrete":
            if c.options and str(value) not in c.options:
                errors.append(f"{key}={value!r} not in {c.options}")

    # Check sum groups
    for group_name, group in SUM_GROUPS.items():
        fields = group["fields"]
        if all(f in suggestion for f in fields):
            total = sum(float(suggestion[f]) for f in fields)
            if abs(total - group["target"]) > 0.01:
                errors.append(f"{group['description']}: got {total}")

    return errors


def clamp_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    """Clamp a suggestion to valid ranges, returning a new dict.

    Does NOT fix sum constraints (caller must handle that).
    """
    result = dict(suggestion)
    for key, value in result.items():
        if key.startswith("_") or key not in CONSTRAINTS:
            continue
        c = CONSTRAINTS[key]

        if c.type == "integer":
            v = int(round(float(value)))
            if c.min is not None:
                v = max(v, int(c.min))
            if c.max is not None:
                v = min(v, int(c.max))
            result[key] = v

        elif c.type == "continuous":
            v = float(value)
            if c.min is not None:
                v = max(v, c.min)
            if c.max is not None:
                v = min(v, c.max)
            result[key] = v

        elif c.type == "binary":
            result[key] = bool(value)

        elif c.type == "discrete":
            if c.options and str(value) not in c.options:
                result[key] = c.options[0]

    return result


def get_bounds() -> dict[str, tuple[float, float]]:
    """Return (min, max) bounds for all numeric fields (for optimizer).

    Binary fields get (0, 1). Discrete fields are excluded.
    """
    bounds = {}
    for key, c in CONSTRAINTS.items():
        if c.type == "integer" or c.type == "continuous":
            lo = c.min if c.min is not None else 0.0
            hi = c.max if c.max is not None else 1000.0
            bounds[key] = (lo, hi)
        elif c.type == "binary":
            bounds[key] = (0.0, 1.0)
    return bounds


if __name__ == "__main__":
    import json

    print("PharmaSim Decision Constraints")
    print("=" * 60)

    for key, c in CONSTRAINTS.items():
        if c.type in ("integer", "continuous"):
            print(f"  {key}: [{c.min}, {c.max}] ({c.type}) — {c.description}")
        elif c.type == "binary":
            print(f"  {key}: {{0, 1}} (binary) — {c.description}")
        elif c.type == "discrete":
            print(f"  {key}: {c.options} (discrete) — {c.description}")

    print(f"\nSum constraints:")
    for name, group in SUM_GROUPS.items():
        print(f"  {name}: {group['fields']} must sum to {group['target']}")

    print(f"\nTotal fields: {len(CONSTRAINTS)}")
    print(f"  Continuous: {sum(1 for c in CONSTRAINTS.values() if c.type == 'continuous')}")
    print(f"  Integer: {sum(1 for c in CONSTRAINTS.values() if c.type == 'integer')}")
    print(f"  Binary: {sum(1 for c in CONSTRAINTS.values() if c.type == 'binary')}")
    print(f"  Discrete: {sum(1 for c in CONSTRAINTS.values() if c.type == 'discrete')}")
