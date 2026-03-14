"""PharmaSim decision variable constraints.

All constraints are verified against the simulator's actual validation
(error dialogs and spinner min/max attributes) as of 2026-03-14.

Constraint categories defined here:
  - CONSTRAINTS: Per-field bounds, types, and allowed values (59 fields total).
  - SUM_GROUPS: Fields that must sum to a fixed target (ad message mix = 100%).
  - ORDERING_CONSTRAINTS: Monotonicity requirements (volume discounts).
  - CONDITIONAL_IRRELEVANCE: Fields that become don't-care when a gate is inactive.
  - EQUIVALENCE_GROUPS: Sets where all-True is identical to all-False in the sim.
  - FORMULATION_CONSTRAINTS: Logical consistency between reformulation and benefit claims.
  - PERIOD_0_FIELDS / PERIOD_1_PLUS_FIELDS: Which fields are editable per period.
  - Budget validation: Total spending vs. available budget (soft constraint).
  - SF_COST_DEFAULTS: Sales force cost parameters for budget estimation.

Usage:
    from src.constraints import CONSTRAINTS, validate_suggestion, clamp_suggestion, normalize_suggestion
    errors = validate_suggestion(suggestion_dict)
    clamped = clamp_suggestion(suggestion_dict)
    canonical = normalize_suggestion(suggestion_dict)
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
# All constraints, verified from the PharmaSim simulator DOM and error dialogs.
#
# Server-side validation (empirically verified 2026-03-14 via direct POST):
#   - Ad message mix must sum to exactly 100% (server rejects otherwise)
#   - Sales force headcount per channel: [0, 1000] (server: "too high")
#   - Volume discounts must be monotonically ordered (server: "cannot be higher")
#   - Promotional allowances must be in [10%, 20%] (server: "between 10% and 20%")
#   - MSRP must be in [$1, $50] (HTML min/max attributes)
#
# NOT enforced server-side (cosmetic UI warning only):
#   - Total budget ceiling — server silently accepts over-budget decisions
#     (tested: $500M ad budget on $44M budget was accepted)
#   - Channel checkbox relevance when budget=0
#   - Equivalence groups (all-checked vs all-unchecked)
#
# Client-side JS (app.com.js) provides display-only calculations:
#   - Budget remaining tracker (app.com.budget.budgeter) — cosmetic
#   - SF cost calculator (app.com.sales_force.recalculate) — cosmetic
#   - Ad message sum display (app.com.advertising.recalculateAdMessage) — cosmetic
#   - Pricing discount calculator (app.com.pricing.recalculate) — cosmetic
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

# Ordering constraints: server-enforced monotonicity.
# Empirically verified 2026-03-14: the server rejects saves where a smaller-volume
# tier has a higher discount than a larger-volume tier. The exact server error messages:
#   "The < 250 Discount for Allround cannot be higher than the < 2500 Discount."
#   "The < 2500 Discount for Allround cannot be higher than the 2500+ Discount."
#   "The 2500+ Discount for Allround cannot be higher than the Wholesale Discount."
# These are hard errors — the server refuses to save the page until corrected.
ORDERING_CONSTRAINTS = [
    {
        "fields": ["discount_under_250", "discount_under_2500", "discount_2500_plus", "discount_wholesale"],
        "description": "Volume discounts must be monotonically non-decreasing: disc_250 ≤ disc_2500 ≤ disc_2500+ ≤ disc_wholesale",
    },
]

# Conditional irrelevance: when a "gate" field is zero/false, the "dependent"
# fields have no effect on the simulation. The optimizer should not explore
# different values for dependent fields when the gate is inactive.
# normalize_suggestion() canonicalizes these to default values.
#
# Why this matters for optimization with limited trials:
#   Each sim evaluation is expensive (limited Replays/Restarts). If the optimizer
#   treats channel checkboxes as independent variables when their budget gate is $0,
#   it wastes evaluations exploring states that are functionally identical. By
#   canonicalizing gated fields to defaults, we collapse the search space and avoid
#   burning scarce evaluations on no-op variations.
CONDITIONAL_IRRELEVANCE = [
    {
        "gate": "coop_ad_budget",
        "gate_inactive": 0.0,  # when budget is 0
        "dependents": ["coop_ad_independent", "coop_ad_chain", "coop_ad_grocery",
                        "coop_ad_convenience", "coop_ad_mass"],
        "default_value": False,
        "description": "Co-op ad channel checkboxes are irrelevant when co-op budget is $0",
    },
    {
        "gate": "pop_budget",
        "gate_inactive": 0.0,
        "dependents": ["pop_independent", "pop_chain", "pop_grocery",
                        "pop_convenience", "pop_mass"],
        "default_value": False,
        "description": "POP channel checkboxes are irrelevant when POP budget is $0",
    },
    {
        "gate": "coupon_budget",
        "gate_inactive": 0.0,
        "dependents": ["coupon_amount"],
        "default_value": "0",
        "description": "Coupon face value is irrelevant when coupon budget is $0",
    },
    {
        "gate": "msg_comparison_pct",
        "gate_inactive": 0.0,
        "dependents": ["msg_comparison_target"],
        "default_value": "2",
        "description": "Comparison target brand is irrelevant when comparison message % is 0",
    },
]

# Equivalence groups: all-checked ≡ all-unchecked in the sim.
# The optimizer should not explore both; we canonicalize to all-False.
EQUIVALENCE_GROUPS = {
    "symptom_targets": {
        "fields": ["symptom_cold", "symptom_cough", "symptom_allergy"],
        "description": "Symptom targeting: all checked = all unchecked (targets everyone)",
    },
    "demo_targets": {
        "fields": [
            "demo_young_singles", "demo_young_families", "demo_mature_families",
            "demo_empty_nesters", "demo_retired",
        ],
        "description": "Demographic targeting: all checked = all unchecked (targets everyone)",
    },
}

# ---------------------------------------------------------------------------
# Budget ceiling constraint (NOT server-enforced, but practically critical)
# ---------------------------------------------------------------------------

# Sales force cost parameters extracted from the Decisions/Sales Force page.
# The page displays: Salary $61,620, Expenses $15,405, Turnover 21, Training $10,270.
# These are per-person annual costs. The JS formula (app.com.sales_force.recalculate):
#   salaries = salary_per × total_headcount × 1e-6
#   expenses = expense_per × total_headcount × 1e-6
#   training = training_per × max(0, headcount_change + turnover) × 1e-6
#   total_sf_cost = salaries + expenses + training
# Values may change between simulation periods.
SF_COST_DEFAULTS = {
    "salary_per": 61620,
    "expense_per": 15405,
    "training_per": 10270,
    "turnover": 21,
}

SF_FIELDS = ["sf_independent", "sf_chain", "sf_grocery", "sf_convenience",
             "sf_mass", "sf_wholesaler", "sf_merchandisers", "sf_detailers"]

# Budget fields: all spending categories that draw from the marketing budget.
# These are the continuous ($M) fields that the optimizer controls.
BUDGET_SPENDING_FIELDS = ["ad_budget", "coop_ad_budget", "pop_budget", "trial_budget", "coupon_budget"]


def compute_sf_cost(
    suggestion: dict[str, Any],
    previous_total_sf: int = 142,
    sf_cost_params: dict | None = None,
) -> float:
    """Compute sales force cost in millions from a suggestion.

    Args:
        suggestion: Decision suggestion dict with sf_* fields.
        previous_total_sf: Total SF headcount from prior period (for training calc).
        sf_cost_params: Per-person cost params. Uses SF_COST_DEFAULTS if None.

    Returns:
        Total SF cost in millions ($M).
    """
    params = sf_cost_params or SF_COST_DEFAULTS
    total_sf = sum(int(suggestion.get(f, 0)) for f in SF_FIELDS)
    headcount_change = total_sf - previous_total_sf

    salaries = params["salary_per"] * total_sf * 1e-6
    expenses = params["expense_per"] * total_sf * 1e-6
    training = params["training_per"] * max(0, headcount_change + params["turnover"]) * 1e-6

    return salaries + expenses + training


# NOTE: The PharmaSim server does NOT enforce budget limits. Over-budget
# decisions are silently accepted. However, exceeding the budget severely
# degrades simulation outcomes (stock price, net income, etc.), so this
# validation is practically critical even though it is not a hard constraint.
def validate_budget(
    suggestion: dict[str, Any],
    available_budget: float,
    previous_total_sf: int = 142,
    sf_cost_params: dict | None = None,
) -> list[str]:
    """Validate that total spending does not exceed available budget.

    The PharmaSim server does NOT enforce this — it silently accepts over-budget
    decisions. However, over-budget spending devastates simulation performance.

    Args:
        suggestion: Decision suggestion dict.
        available_budget: Total available budget in $M (from income_statement.next_year_budget).
        previous_total_sf: Prior period total SF headcount.
        sf_cost_params: Per-person SF cost params.

    Returns:
        List of error strings (empty = within budget).
    """
    errors = []

    # Sum direct spending fields
    direct_spending = sum(float(suggestion.get(f, 0.0)) for f in BUDGET_SPENDING_FIELDS)

    # Compute SF cost
    sf_cost = compute_sf_cost(suggestion, previous_total_sf, sf_cost_params)

    total_spending = direct_spending + sf_cost
    remaining = available_budget - total_spending

    if remaining < -0.05:  # small tolerance for rounding
        errors.append(
            f"Over budget: total spending ${total_spending:.1f}M exceeds "
            f"available budget ${available_budget:.1f}M by ${-remaining:.1f}M "
            f"(direct=${direct_spending:.1f}M + SF=${sf_cost:.1f}M)"
        )

    return errors


def get_budget_bounded_max(
    available_budget: float,
    previous_total_sf: int = 142,
    sf_cost_params: dict | None = None,
) -> float:
    """Get the maximum any single spending field can be, given the budget.

    This provides a practical upper bound for the optimizer's search space
    on the 5 unbounded continuous spending fields.

    Returns:
        Maximum budget in $M that any single field could theoretically use
        (assuming all other spending is at minimum).
    """
    # Minimum SF cost (0 headcount, but training for turnover)
    params = sf_cost_params or SF_COST_DEFAULTS
    min_sf_cost = params["training_per"] * max(0, -previous_total_sf + params["turnover"]) * 1e-6
    if min_sf_cost < 0:
        min_sf_cost = 0.0

    return max(0.0, available_budget - min_sf_cost)


# ---------------------------------------------------------------------------
# Formulation-benefit consistency constraints
# ---------------------------------------------------------------------------
# These enforce logical consistency between brand_reformulation choice and
# benefit promotion claims.
#
# Allround's original formulation contains: Analgesic 1000mg, Antihistamine 4mg,
# Decongestant 60mg, Cough Suppressant 30mg, Alcohol 10%, Expectorant 0mg.
#
# Reformulation options (brand_reformulation values):
#   "2" = Keep original formulation (no change to ingredients)
#   "1" = Drop alcohol: sets Alcohol to 0%. Removes sedative/rest benefit,
#         but may reduce "drowsiness" side effect concerns.
#   "0" = Switch to expectorant: replaces Cough Suppressant (30mg -> 0mg) with
#         Expectorant (0mg -> 200mg). Fundamentally changes the cough mechanism
#         from suppression to expectoration. Cannot credibly claim "Suppresses Coughing".
#
# These constraints are not server-enforced but prevent misleading ad claims
# that would reduce ad effectiveness in the simulation.

FORMULATION_CONSTRAINTS = [
    {
        "condition": {"brand_reformulation": "0"},  # switch to expectorant
        "incompatible": ["benefit_suppresses_coughing"],
        "severity": "error",
        "description": "Cannot promote 'Suppresses Coughing' after switching from cough suppressant to expectorant",
    },
    {
        "condition": {"brand_reformulation": "1"},  # drop alcohol
        "incompatible": ["benefit_helps_you_rest"],
        "severity": "warning",
        "description": "Promoting 'Helps You Rest' may be less effective after dropping alcohol",
    },
]


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


def normalize_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    """Normalize a suggestion to canonical form.

    Converts all-True equivalence groups to all-False (canonical),
    since PharmaSim treats them identically. This prevents the optimizer
    from wasting evaluations on duplicate states.

    Returns a new dict (does not mutate the input).
    """
    result = dict(suggestion)
    for group in EQUIVALENCE_GROUPS.values():
        fields = group["fields"]
        present = [f for f in fields if f in result]
        if present and all(bool(result.get(f, False)) for f in fields):
            for f in fields:
                result[f] = False

    # Normalize conditional irrelevance: set dependents to defaults when gate is inactive
    for ci in CONDITIONAL_IRRELEVANCE:
        gate = ci["gate"]
        if gate in result:
            gate_val = result[gate]
            # Check if gate is inactive (zero for numeric, False for binary)
            inactive = False
            if isinstance(ci["gate_inactive"], (int, float)):
                try:
                    inactive = float(gate_val) == ci["gate_inactive"]
                except (ValueError, TypeError):
                    pass
            elif gate_val == ci["gate_inactive"]:
                inactive = True
            if inactive:
                for dep in ci["dependents"]:
                    if dep in result:
                        result[dep] = ci["default_value"]

    return result


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

    # Check ordering constraints (server-enforced monotonicity)
    for oc in ORDERING_CONSTRAINTS:
        fields = oc["fields"]
        present = [f for f in fields if f in suggestion]
        if len(present) >= 2:
            for i in range(len(fields) - 1):
                f_lo, f_hi = fields[i], fields[i + 1]
                if f_lo in suggestion and f_hi in suggestion:
                    v_lo = float(suggestion[f_lo])
                    v_hi = float(suggestion[f_hi])
                    if v_lo > v_hi + 0.01:  # small tolerance
                        errors.append(
                            f"{oc['description']}: {f_lo}={v_lo} > {f_hi}={v_hi}"
                        )

    # Warn about equivalence groups (all-True == all-False in the sim)
    for group_name, group in EQUIVALENCE_GROUPS.items():
        fields = group["fields"]
        present = [f for f in fields if f in suggestion]
        if present and all(bool(suggestion.get(f, False)) for f in fields):
            errors.append(
                f"WARNING: {group['description']} — all fields are True, "
                f"equivalent to all False. Use normalize_suggestion() to canonicalize."
            )

    # Warn about conditional irrelevance (budget=0 makes channels don't-care)
    for ci in CONDITIONAL_IRRELEVANCE:
        gate = ci["gate"]
        if gate not in suggestion:
            continue
        gate_val = suggestion[gate]
        inactive = False
        if isinstance(ci["gate_inactive"], (int, float)):
            try:
                inactive = float(gate_val) == ci["gate_inactive"]
            except (ValueError, TypeError):
                pass
        elif gate_val == ci["gate_inactive"]:
            inactive = True
        if inactive:
            active_deps = [d for d in ci["dependents"]
                           if d in suggestion and suggestion[d] != ci["default_value"]]
            if active_deps:
                errors.append(
                    f"WARNING: {ci['description']}. "
                    f"Non-default values for: {', '.join(active_deps)}. "
                    f"Use normalize_suggestion() to canonicalize."
                )

    # Check formulation-benefit consistency constraints
    for fc in FORMULATION_CONSTRAINTS:
        condition = fc["condition"]
        # Check if all condition fields match
        if all(
            k in suggestion and str(suggestion[k]) == str(v)
            for k, v in condition.items()
        ):
            for field in fc["incompatible"]:
                if field in suggestion and bool(suggestion[field]):
                    if fc["severity"] == "warning":
                        errors.append(f"WARNING: {fc['description']}")
                    else:
                        errors.append(fc["description"])

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

    # Enforce ordering constraints by adjusting upward
    for oc in ORDERING_CONSTRAINTS:
        fields = oc["fields"]
        for i in range(len(fields) - 1):
            f_lo, f_hi = fields[i], fields[i + 1]
            if f_lo in result and f_hi in result:
                if float(result[f_lo]) > float(result[f_hi]):
                    result[f_hi] = result[f_lo]

    return result


# ---------------------------------------------------------------------------
# Relative bounds (trust region) configuration
# ---------------------------------------------------------------------------
# When optimizing with only ~25 trials, we can't explore the entire feasible
# space. Instead, we define a "trust region" around the previous period's
# decision values. The optimizer searches only within this neighborhood,
# which dramatically reduces the effective dimensionality of the search.
#
# HOW IT WORKS:
#   The reference point comes from the live DOM scraper (dom_scraper.py's
#   js_scrape_decision_inputs()), converted to suggestion-key format via
#   decision_applier.dom_to_suggestion(). This gives us the current/previous
#   decision values already set in the simulator.
#
#   Each entry has two parameters that together define the window width:
#     "pct": proportional offset as a fraction of the reference value
#            (e.g., 0.5 means ±50% of ref). Scales with the magnitude of
#            the current value — larger values get wider absolute windows.
#     "abs": fixed offset added regardless of reference value (in field units).
#            Guarantees a minimum window width even when ref is 0 or very small.
#
#   The delta from reference is: delta = ref * pct + abs
#   The relative window is: [ref - delta, ref + delta]
#   The final bounds are: intersect(relative_window, absolute_hard_bounds)
#
#   Example with sf_chain=29, pct=0.0, abs=250:
#     delta = 29*0.0 + 250 = 250
#     relative window = [29-250, 29+250] = [-221, 279]
#     absolute bounds = [0, 1000]
#     final bounds = [0, 279] (clamped at 0; the symmetric 500-wide window
#       covers 50% of the [0,1000] range when ref is centered, but near
#       boundaries the effective width is smaller)
#
# WHICH FIELDS GET RELATIVE BOUNDS:
#   - Only numeric fields (integer + continuous) are bounded here.
#   - Binary fields (checkboxes) are excluded — you can't say "±50% of True".
#   - Discrete fields (ad_agency, coupon_amount, reformulation) are excluded.
#   - Fields omitted from this dict use their full absolute range from CONSTRAINTS.
#
# OVERRIDING AT RUNTIME:
#   Pass a custom config dict to get_relative_bounds(reference, config=my_config).
#   This lets the optimizer adaptively widen/tighten the trust region:
#     - After an improving iteration: tighten (exploit the promising region)
#     - After a stagnant iteration: widen (explore more broadly)

RELATIVE_BOUNDS: dict[str, dict[str, float]] = {
    # ── Sales Force (8 fields) ──
    # Absolute range: [0, 1000] per channel (1000 wide).
    # Trust region: ±250 headcount = 500 wide = 50% of absolute range.
    # Rationale: hiring/firing hundreds of salespeople per year is realistic
    # in the sim, but the full [0, 1000] range is wasteful to explore.
    # Note: when ref is small (e.g., sf_independent=3), the window is
    # asymmetric: [0, 253] since we can't go below 0.
    "sf_independent":   {"pct": 0.0, "abs": 250},
    "sf_chain":         {"pct": 0.0, "abs": 250},
    "sf_grocery":       {"pct": 0.0, "abs": 250},
    "sf_convenience":   {"pct": 0.0, "abs": 250},
    "sf_mass":          {"pct": 0.0, "abs": 250},
    "sf_wholesaler":    {"pct": 0.0, "abs": 250},
    "sf_merchandisers": {"pct": 0.0, "abs": 250},
    "sf_detailers":     {"pct": 0.0, "abs": 250},

    # ── MSRP ──
    # Absolute range: [$1, $50] (49 wide).
    # Trust region: ±$6.125 = $12.25 wide = 25% of absolute range.
    # Rationale: pricing is a sensitive lever — large swings alienate
    # customers. A 25% window still allows meaningful price experiments
    # (e.g., ref=$5.44 → [$1.00, $11.57]).
    "msrp": {"pct": 0.0, "abs": 6.125},

    # ── Ad budget ──
    # Absolute range: [0, 1000] (but practically limited by total budget ~$44M).
    # Trust region: NONE (100% of absolute range).
    # Rationale: ad spend is a major strategic lever; the optimizer should
    # be free to explore large shifts. The budget ceiling constraint
    # (validate_budget) already caps effective spending.
    # Omitted from this dict → uses full absolute bounds.

    # ── Promotional budgets (4 fields) ──
    # Absolute range: [0, 1000] each (but practically <<$44M total budget).
    # Trust region: ±100% of ref + $0.5M floor.
    # Rationale: these are smaller budget items where the optimizer might
    # want to double down or zero out. The +$0.5M floor ensures a nonzero
    # window when ref is $0 (e.g., trial_budget=0 → [0, 0.5]).
    "coop_ad_budget": {"pct": 1.00, "abs": 0.5},
    "pop_budget":     {"pct": 1.00, "abs": 0.5},
    "trial_budget":   {"pct": 1.00, "abs": 0.5},
    "coupon_budget":  {"pct": 1.00, "abs": 0.5},

    # ── Allowances (6 fields) ──
    # Absolute range: [10%, 20%] (only 10pp wide — already very tight).
    # Trust region: NONE (full absolute range).
    # Rationale: with only a 10pp range, further narrowing would leave
    # almost no room for the optimizer to explore. Let it use the full range.
    # Omitted from this dict → uses full [10%, 20%] absolute bounds.

    # ── Volume discounts (4 fields) ──
    # Absolute range: [10%, 50%] (40pp wide).
    # Trust region: NONE (full absolute range).
    # Rationale: discount structure is a strategic choice the optimizer
    # should explore freely. The ordering constraint (monotonicity) already
    # restricts the feasible region substantially.
    # Omitted from this dict → uses full [10%, 50%] absolute bounds.

    # ── Ad message mix (4 fields) ──
    # Absolute range: [0, 100] each (but must sum to exactly 100%).
    # Trust region: ±20 percentage points.
    # Rationale: the sum=100% constraint already limits freedom. A ±20pp
    # window around each component allows meaningful rebalancing without
    # completely abandoning the current messaging strategy.
    "msg_primary_pct":    {"pct": 0.0, "abs": 20.0},
    "msg_benefits_pct":   {"pct": 0.0, "abs": 20.0},
    "msg_comparison_pct": {"pct": 0.0, "abs": 20.0},
    "msg_reminder_pct":   {"pct": 0.0, "abs": 20.0},
}


def get_relative_bounds(
    reference: dict[str, Any],
    config: dict[str, dict[str, float]] | None = None,
) -> dict[str, tuple[float, float]]:
    """Compute tightened bounds by intersecting relative bounds with absolute bounds.

    This is the primary interface for the optimizer to get its search bounds.
    It takes a reference decision (the previous/current period's values) and
    returns narrowed (min, max) ranges centered around those values.

    Typical usage:
        # 1. Scrape current decision values from the live simulator DOM
        dom_inputs = evaluate_script(js_scrape_decision_inputs())
        # 2. Convert HTML field names to suggestion keys
        reference = dom_to_suggestion(dom_inputs)
        # 3. Get narrowed bounds for the optimizer
        bounds = get_relative_bounds(reference)
        # bounds["sf_chain"] might be (0.0, 279.0) instead of (0.0, 1000.0)

    Fields NOT in reference or NOT in the config dict fall back to their
    full absolute bounds from CONSTRAINTS. This means you only need to
    provide reference values for fields you want to tighten.

    Binary and discrete fields are excluded from the output — they don't
    have meaningful numeric ranges to tighten.

    Args:
        reference: Decision dict in suggestion-key format (e.g., from
            decision_applier.dom_to_suggestion()). Keys like 'sf_chain',
            'ad_budget', etc. Values are the current/previous period's settings.
        config: Per-field relative bound config. Each entry is
            {"pct": float, "abs": float}. Uses RELATIVE_BOUNDS if None.
            Pass a custom dict to widen/tighten the trust region dynamically.

    Returns:
        Dict mapping field name -> (min, max) for all numeric (integer +
        continuous) fields. Binary and discrete fields are excluded.
    """
    cfg = config if config is not None else RELATIVE_BOUNDS
    abs_bounds = get_bounds()
    result = {}

    for field, (abs_lo, abs_hi) in abs_bounds.items():
        c = CONSTRAINTS[field]
        # Binary fields (checkboxes) have no meaningful numeric range to narrow
        if c.type == "binary":
            continue

        if field in cfg and field in reference:
            try:
                ref_val = float(reference[field])
            except (ValueError, TypeError):
                # Non-numeric reference value (shouldn't happen, but be safe)
                result[field] = (abs_lo, abs_hi)
                continue

            # Compute the half-width of the trust region window:
            #   delta = ref * pct + abs
            # "pct" scales with the reference value (proportional component)
            # "abs" is a fixed offset (guarantees minimum window width)
            pct = cfg[field].get("pct", 0.0)
            abs_delta = cfg[field].get("abs", 0.0)
            delta = ref_val * pct + abs_delta

            # Build the relative window centered on the reference
            rel_lo = ref_val - delta
            rel_hi = ref_val + delta

            # Intersect with absolute hard bounds from CONSTRAINTS
            # (can't go below server-enforced minimums or above maximums)
            lo = max(abs_lo, rel_lo)
            hi = min(abs_hi, rel_hi)

            # Edge case: if reference is outside absolute bounds (shouldn't
            # happen with valid data), collapse to the nearest valid point
            if lo > hi:
                lo = hi = max(abs_lo, min(abs_hi, ref_val))

            # Integer fields: truncate to whole numbers
            if c.type == "integer":
                lo = float(int(lo))
                hi = float(int(hi))

            result[field] = (lo, hi)
        else:
            # Field has no relative config entry or no reference value —
            # fall back to full absolute bounds (no narrowing applied)
            result[field] = (abs_lo, abs_hi)

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

    print(f"\nEquivalence groups (all-checked ≡ all-unchecked):")
    for name, group in EQUIVALENCE_GROUPS.items():
        print(f"  {name}: {group['fields']} — {group['description']}")

    print(f"\nOrdering constraints (server-enforced monotonicity):")
    for oc in ORDERING_CONSTRAINTS:
        print(f"  {' ≤ '.join(oc['fields'])}")
        print(f"    {oc['description']}")

    print(f"\nConditional irrelevance (gate=0 → dependents are don't-care):")
    for ci in CONDITIONAL_IRRELEVANCE:
        print(f"  {ci['gate']}=0 → {ci['dependents']} default to {ci['default_value']}")
        print(f"    {ci['description']}")

    print(f"\nFormulation-benefit consistency constraints:")
    for fc in FORMULATION_CONSTRAINTS:
        severity = fc["severity"].upper()
        cond_str = ", ".join(f"{k}='{v}'" for k, v in fc["condition"].items())
        incompat_str = ", ".join(fc["incompatible"])
        print(f"  [{severity}] When {cond_str}: cannot set {incompat_str}=True")
        print(f"    {fc['description']}")

    print(f"\nTotal fields: {len(CONSTRAINTS)}")
    print(f"  Continuous: {sum(1 for c in CONSTRAINTS.values() if c.type == 'continuous')}")
    print(f"  Integer: {sum(1 for c in CONSTRAINTS.values() if c.type == 'integer')}")
    print(f"  Binary: {sum(1 for c in CONSTRAINTS.values() if c.type == 'binary')}")
    print(f"  Discrete: {sum(1 for c in CONSTRAINTS.values() if c.type == 'discrete')}")

    print(f"\nBudget constraint (NOT server-enforced, but practically critical):")
    print(f"  Spending fields: {BUDGET_SPENDING_FIELDS}")
    print(f"  SF cost fields: {SF_FIELDS}")
    print(f"  SF cost defaults: {SF_COST_DEFAULTS}")
    print(f"  Formula: sum(spending_fields) + sf_cost(headcount) \u2264 available_budget")
    print(f"  Budget comes from income_statement.next_year_budget in scraped data")
