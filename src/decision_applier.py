"""Apply decision suggestions to the PharmaSim simulator via Chrome DevTools MCP.

Reads a JSON suggestion file and sets all decision inputs on the webpage.
The human reviews and confirms before advancing.

IMPORTANT: PharmaSim blocks navigation when there are unsaved changes, and
clicking Save causes a page reload that destroys the JS execution context.
Therefore, decisions must be applied ONE PAGE AT A TIME:
  1. Navigate to page (via JS or MCP click)
  2. Run the page's set-values JS
  3. The JS clicks Save at the end (which triggers a reload)
  4. Wait for page reload to complete
  5. Repeat for next page

Usage (programmatic — generates per-page JS snippets):
    from src.decision_applier import load_suggestion, generate_page_scripts
    suggestion = load_suggestion("suggestions/decision1.json")
    scripts = generate_page_scripts(suggestion)
    for page_name, js in scripts:
        # Navigate to page first, then:
        result = evaluate_script(js)
        # Wait for reload after Save...

Usage (CLI — prints all scripts):
    uv run python -m src.decision_applier suggestions/decision1.json
    uv run python -m src.decision_applier --generate-example 1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.constraints import CONSTRAINTS, SUM_GROUPS, validate_suggestion as _validate
from src.dom_scraper import (
    AD_AGENCIES,
    BENEFIT_LABELS,
    COMPARISON_TARGETS,
    COUPON_AMOUNTS,
    DecisionInputMap,
    INPUTS_BY_PERIOD,
)

# ---------------------------------------------------------------------------
# Suggestion file schema
# ---------------------------------------------------------------------------

# Maps human-readable suggestion keys -> HTML field name/id
FIELD_MAP = {
    # Sales Force (integers)
    "sf_independent": "sf1",
    "sf_chain": "sf2",
    "sf_grocery": "sf3",
    "sf_convenience": "sf4",
    "sf_mass": "sf5",
    "sf_wholesaler": "sf6",
    "sf_merchandisers": "sf7",
    "sf_detailers": "sf8",
    # Pricing (floats)
    "msrp": "msrp1",
    "discount_under_250": "disc1-1",
    "discount_under_2500": "disc1-2",
    "discount_2500_plus": "disc1-3",
    "discount_wholesale": "disc1-4",
    # Advertising
    "ad_budget": "ad_budget1",
    "ad_agency": "agency1",  # radio: "1", "2", or "3"
    "symptom_cold": "illness1-COLD",  # checkbox
    "symptom_cough": "illness1-COUGH",  # checkbox
    "symptom_allergy": "illness1-ALLERGY",  # checkbox
    "demo_young_singles": "demo1-1",  # checkbox
    "demo_young_families": "demo1-2",  # checkbox
    "demo_mature_families": "demo1-4",  # checkbox
    "demo_empty_nesters": "demo1-8",  # checkbox
    "demo_retired": "demo1-16",  # checkbox
    "msg_primary_pct": "primary_msg1",
    "msg_benefits_pct": "benefit_msg1",
    "msg_comparison_pct": "compare_msg1",
    "msg_comparison_target": "compare_target1",  # select
    "msg_reminder_pct": "reminder_msg1",
    "benefit_relieves_aches": "benefit1-1",  # checkbox
    "benefit_clears_nasal": "benefit1-2",  # checkbox
    "benefit_reduces_chest": "benefit1-3",  # checkbox
    "benefit_dries_runny_nose": "benefit1-4",  # checkbox
    "benefit_suppresses_coughing": "benefit1-5",  # checkbox
    "benefit_relieves_allergies": "benefit1-6",  # checkbox
    "benefit_minimizes_side_effects": "benefit1-7",  # checkbox
    "benefit_wont_cause_drowsiness": "benefit1-8",  # checkbox
    "benefit_helps_you_rest": "benefit1-9",  # checkbox
    # Promotion
    "allowance_independent": "allowance1-1",
    "allowance_chain": "allowance1-2",
    "allowance_grocery": "allowance1-3",
    "allowance_convenience": "allowance1-4",
    "allowance_mass": "allowance1-5",
    "allowance_wholesale": "allowance1-6",
    "coop_ad_budget": "coop_ad_budget1",
    "coop_ad_independent": "coop_ad1-1",  # checkbox
    "coop_ad_chain": "coop_ad1-2",  # checkbox
    "coop_ad_grocery": "coop_ad1-3",  # checkbox
    "coop_ad_convenience": "coop_ad1-4",  # checkbox
    "coop_ad_mass": "coop_ad1-5",  # checkbox
    "pop_budget": "display_budget1",
    "pop_independent": "display_ad1-1",  # checkbox
    "pop_chain": "display_ad1-2",  # checkbox
    "pop_grocery": "display_ad1-3",  # checkbox
    "pop_convenience": "display_ad1-4",  # checkbox
    "pop_mass": "display_ad1-5",  # checkbox
    "trial_budget": "trial_budget1",
    "coupon_budget": "coupon_budget1",
    "coupon_amount": "coupon_amt1",  # select: "0"=$0.25, "1"=$0.50, "2"=$0.75, "3"=$1.00
    # Brand Reformulation (Year 1+ only)
    "brand_reformulation": "choice",  # radio: "2"=keep, "1"=drop alcohol, "0"=expectorant
}

# Which decision page each field lives on
FIELD_TO_PAGE = {}
for _key, _html_name in FIELD_MAP.items():
    _id = _html_name.split("-")[0] if "-" in _html_name else _html_name
    if _id.startswith("sf"):
        FIELD_TO_PAGE[_key] = "decisions/sales_force"
    elif _id in ("msrp1", "disc1"):
        FIELD_TO_PAGE[_key] = "decisions/pricing"
    elif _id in (
        "ad_budget1", "agency1", "illness1", "demo1",
        "primary_msg1", "benefit_msg1", "compare_msg1",
        "compare_target1", "reminder_msg1", "benefit1",
    ):
        FIELD_TO_PAGE[_key] = "decisions/advertising"
    elif _id in (
        "allowance1", "coop_ad_budget1", "coop_ad1",
        "display_budget1", "display_ad1", "trial_budget1",
        "coupon_budget1", "coupon_amt1",
    ):
        FIELD_TO_PAGE[_key] = "decisions/promotion"
    elif _id == "choice":
        FIELD_TO_PAGE[_key] = "decisions/brands"

# Menu path for each decision page
PAGE_MENU_PATH = {
    "decisions/sales_force": ("decisions", "decisions/sales_force"),
    "decisions/pricing": ("decisions", "decisions/pricing"),
    "decisions/advertising": ("decisions", "decisions/advertising"),
    "decisions/promotion": ("decisions", "decisions/promotion"),
    "decisions/brands": ("decisions", "decisions/brands"),
}

# Input types
CHECKBOX_FIELDS = {
    k for k, v in FIELD_MAP.items()
    if v.startswith(("illness1-", "demo1-", "benefit1-", "coop_ad1-", "display_ad1-"))
}
RADIO_FIELDS = {"ad_agency", "brand_reformulation"}
SELECT_FIELDS = {"msg_comparison_target", "coupon_amount"}


# ---------------------------------------------------------------------------
# DOM-to-suggestion key mapping
# ---------------------------------------------------------------------------
# The DOM scraper (dom_scraper.js_scrape_decision_inputs) returns a dict keyed
# by raw HTML field names (e.g., "sf1", "ad_budget1", "illness1-COLD").
# The optimizer and constraints system use human-readable suggestion keys
# (e.g., "sf_independent", "ad_budget", "symptom_cold").
#
# HTML_TO_SUGGESTION is the reverse of FIELD_MAP: it maps HTML names back to
# suggestion keys so we can convert DOM scraper output into the format that
# constraints.py and the optimizer expect.
#
# This is essential for the relative bounds (trust region) workflow:
#   1. Scrape current decisions from live DOM → HTML-keyed dict
#   2. dom_to_suggestion() → suggestion-keyed dict (reference point)
#   3. get_relative_bounds(reference) → narrowed optimizer search bounds
HTML_TO_SUGGESTION = {v: k for k, v in FIELD_MAP.items()}


def dom_to_suggestion(dom_inputs: dict[str, Any]) -> dict[str, Any]:
    """Convert DOM scraper output (HTML field names) to suggestion-key format.

    This is the bridge between the live simulator DOM and the constraint/optimizer
    system. The DOM scraper reads raw HTML input values; this function translates
    those into the canonical suggestion-key format and coerces types appropriately.

    Type conversions performed:
      - Integer fields (SF headcount): string "29" → int 29
      - Continuous fields (budgets, percentages): string "18.0" → float 18.0
      - Binary fields (checkboxes): JS true/false → Python bool
      - Discrete fields (agency, coupon): kept as string for option matching

    Unknown HTML fields (hidden inputs, non-decision fields) are silently skipped.

    Typical usage:
        # With Chrome DevTools MCP:
        result = evaluate_script(js_scrape_decision_inputs())
        reference = dom_to_suggestion(result)
        bounds = get_relative_bounds(reference)

    Args:
        dom_inputs: Dict from js_scrape_decision_inputs() keyed by HTML names
            (e.g., {"sf1": "29", "ad_budget1": "18.0", "illness1-COLD": true}).

    Returns:
        Dict in suggestion-key format (e.g., {"sf_independent": 3, "ad_budget": 18.0,
        "symptom_cold": True}) ready for use with constraints.py functions like
        get_relative_bounds(), validate_suggestion(), normalize_suggestion().
    """
    result: dict[str, Any] = {}
    for html_name, value in dom_inputs.items():
        suggestion_key = HTML_TO_SUGGESTION.get(html_name)
        if suggestion_key is None:
            continue  # skip fields not in our decision map (e.g., hidden fields)

        c = CONSTRAINTS.get(suggestion_key)
        if c is None:
            result[suggestion_key] = value
            continue

        # Type conversion based on constraint type
        if c.type == "integer":
            try:
                result[suggestion_key] = int(float(value))
            except (ValueError, TypeError):
                result[suggestion_key] = value
        elif c.type == "continuous":
            try:
                result[suggestion_key] = float(value)
            except (ValueError, TypeError):
                result[suggestion_key] = value
        elif c.type == "binary":
            # DOM scraper returns True/False for checkboxes
            result[suggestion_key] = bool(value)
        elif c.type == "discrete":
            result[suggestion_key] = str(value)
        else:
            result[suggestion_key] = value

    return result


def load_suggestion(
    path: str | Path,
    available_budget: float | None = None,
    previous_total_sf: int = 142,
    sf_cost_params: dict | None = None,
) -> dict[str, Any]:
    """Load a suggestion JSON file and validate against all constraints.

    Raises ValueError if any hard constraint is violated. Warnings (prefixed
    with "WARNING:") are printed but do NOT cause rejection.

    Args:
        path: Path to the suggestion JSON file.
        available_budget: Total available budget in $M (from income_statement.next_year_budget).
            If provided, budget validation is performed as a hard constraint.
        previous_total_sf: Prior period total SF headcount (for SF cost calculation).
        sf_cost_params: Per-person SF cost params (uses defaults if None).
    """
    path = Path(path)
    with open(path) as f:
        data = json.load(f)

    # Check for unknown fields first
    errors = []
    for key in data:
        if key.startswith("_"):
            continue
        if key not in FIELD_MAP:
            errors.append(f"Unknown field: {key}")

    # Run full constraint validation from constraints.py
    constraint_errors = _validate(data)
    errors.extend(constraint_errors)

    # Budget validation (optional — requires scraped budget data)
    if available_budget is not None:
        from src.constraints import validate_budget
        budget_errors = validate_budget(data, available_budget, previous_total_sf, sf_cost_params)
        for be in budget_errors:
            errors.append(be)

    # Separate hard errors from warnings
    warnings = [e for e in errors if e.startswith("WARNING:")]
    hard_errors = [e for e in errors if not e.startswith("WARNING:")]

    # Print warnings (they don't block application)
    for w in warnings:
        print(w)

    if hard_errors:
        msg = "Suggestion REJECTED — constraint violations found:\n  " + "\n  ".join(hard_errors)
        if warnings:
            msg += "\n\nAdditionally, the following warnings were raised:\n  " + "\n  ".join(warnings)
        msg += "\n\nNo decisions were applied. Fix the above errors and retry."
        raise ValueError(msg)

    return data


_JS_HELPERS = """
    var delay = function(ms) {
        return new Promise(function(r) { setTimeout(r, ms); });
    };

    var applied = [];
    var errors = [];

    var setText = function(nameOrId, value) {
        var el = document.querySelector('[name="' + nameOrId + '"]')
              || document.getElementById(nameOrId);
        if (!el) { errors.push('Not found: ' + nameOrId); return; }
        if (el.disabled || el.readOnly) { errors.push('Disabled/readonly: ' + nameOrId); return; }
        el.focus();
        el.value = '';
        el.value = value;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        el.blur();
        applied.push({ field: nameOrId, type: 'text', value: value });
    };

    var setCheckbox = function(id, checked) {
        var el = document.getElementById(id);
        if (!el) { errors.push('Not found: ' + id); return; }
        if (el.disabled) { errors.push('Disabled: ' + id); return; }
        if (el.checked !== checked) {
            el.click();
        }
        applied.push({ field: id, type: 'checkbox', value: checked });
    };

    var setRadio = function(name, value) {
        var radios = document.querySelectorAll('input[type="radio"][name="' + name + '"]');
        var found = false;
        radios.forEach(function(r) {
            if (r.value === value) {
                if (!r.disabled) {
                    r.click();
                    found = true;
                    applied.push({ field: name, type: 'radio', value: value });
                } else {
                    errors.push('Disabled radio: ' + name + '=' + value);
                }
            }
        });
        if (!found && errors.length === 0) errors.push('Radio not found: ' + name + '=' + value);
    };

    var setSelect = function(name, value) {
        var el = document.querySelector('select[name="' + name + '"]')
              || document.getElementById(name);
        if (!el) { errors.push('Not found select: ' + name); return; }
        if (el.disabled) { errors.push('Disabled select: ' + name); return; }
        el.value = value;
        el.dispatchEvent(new Event('change', {bubbles: true}));
        applied.push({ field: name, type: 'select', value: value });
    };

    var clickSave = function() {
        var buttons = document.querySelectorAll('button');
        buttons.forEach(function(btn) {
            if (btn.textContent.trim() === 'Save' && btn.offsetParent !== null && !btn.disabled) {
                btn.click();
            }
        });
    };
"""


def _field_js(key: str, html_name: str, value: Any, delay_ms: int) -> str:
    """Generate JS to set a single field."""
    if key in CHECKBOX_FIELDS:
        checked = bool(value) if not isinstance(value, bool) else value
        return (
            f"    setCheckbox('{html_name}', {str(checked).lower()});\n"
            f"    await delay({delay_ms});"
        )
    elif key in RADIO_FIELDS:
        return (
            f"    setRadio('{html_name}', '{value}');\n"
            f"    await delay({delay_ms});"
        )
    elif key in SELECT_FIELDS:
        return (
            f"    setSelect('{html_name}', '{value}');\n"
            f"    await delay({delay_ms});"
        )
    else:
        return (
            f"    setText('{html_name}', '{value}');\n"
            f"    await delay({delay_ms});"
        )


def generate_page_scripts(
    suggestion: dict[str, Any],
    human_delay_ms: int = 300,
    auto_save: bool = True,
) -> list[tuple[str, str, str]]:
    """Generate per-page JS snippets to apply a suggestion.

    Each script assumes it's already on the correct decision page.
    If auto_save is True, each script clicks Save after setting values.
    Save triggers a page reload, so the caller must wait for the reload
    before running the next script.

    Args:
        suggestion: Validated suggestion dict.
        human_delay_ms: Delay between fields (ms).
        auto_save: Whether to click Save at the end of each page script.

    Returns:
        List of (page_path, nav_js, set_values_js) tuples.
        - page_path: e.g. "decisions/sales_force"
        - nav_js: JS to navigate to the page (run first, wait for load)
        - set_values_js: JS to set values and save (run after page loads)
    """
    # Group fields by page
    pages: dict[str, list[tuple[str, str, Any]]] = {}
    for key, value in suggestion.items():
        if key.startswith("_"):
            continue
        html_name = FIELD_MAP[key]
        page = FIELD_TO_PAGE.get(key)
        if page:
            pages.setdefault(page, []).append((key, html_name, value))

    page_order = [
        "decisions/sales_force",
        "decisions/pricing",
        "decisions/advertising",
        "decisions/promotion",
        "decisions/brands",
    ]

    result = []
    for page_path in page_order:
        if page_path not in pages:
            continue
        fields = pages[page_path]
        parent, path = PAGE_MENU_PATH[page_path]

        # Navigation JS
        if page_path == "decisions/brands":
            nav_js = f"""() => {{
    ui.menu.call(null, '{parent}', '{path}', {{}});
    return true;
}}"""
        else:
            nav_js = f"""() => {{
    ui.menu.call(null, '{parent}', '{path}', {{}});
    return true;
}}"""

        # Build field-setting lines
        field_lines = []
        for key, html_name, value in fields:
            field_lines.append(_field_js(key, html_name, value, human_delay_ms))

        # For brands, need to click Reformulation tab first
        pre_js = ""
        if page_path == "decisions/brands":
            pre_js = """
    // Click Reformulation tab
    var reformTab = Array.from(document.querySelectorAll('a, button')).find(
        function(el) { return el.textContent.trim() === 'Reformulation' && el.offsetParent !== null; }
    );
    if (reformTab) {
        reformTab.click();
        await delay(1500);
    }
"""

        save_js = ""
        if auto_save:
            save_js = """
    // Click Save (triggers page reload — JS context will be destroyed)
    await delay(500);
    clickSave();
"""

        set_values_js = f"""async () => {{
{_JS_HELPERS}
{pre_js}
{chr(10).join(field_lines)}
{save_js}
    return {{
        page: '{page_path}',
        success: errors.length === 0,
        applied: applied.length,
        errors: errors
    }};
}}"""

        result.append((page_path, nav_js, set_values_js))

    return result


def generate_apply_js(suggestion: dict[str, Any], human_delay_ms: int = 300) -> str:
    """Generate a single JS that applies ALL decisions without saving.

    Use this when you want to set all values in one shot and let the
    human review + save manually. Navigation between pages uses
    ui.menu.call which works when there are no unsaved changes.

    NOTE: This does NOT save. The human must click Save on each page.
    To auto-save, use generate_page_scripts() instead.
    """
    pages: dict[str, list[tuple[str, str, Any]]] = {}
    for key, value in suggestion.items():
        if key.startswith("_"):
            continue
        html_name = FIELD_MAP[key]
        page = FIELD_TO_PAGE.get(key)
        if page:
            pages.setdefault(page, []).append((key, html_name, value))

    page_order = [
        "decisions/sales_force",
        "decisions/pricing",
        "decisions/advertising",
        "decisions/promotion",
        "decisions/brands",
    ]

    page_blocks = []
    for page_path in page_order:
        if page_path not in pages:
            continue
        fields = pages[page_path]
        parent, path = PAGE_MENU_PATH[page_path]

        field_lines = []
        for key, html_name, value in fields:
            field_lines.append(_field_js(key, html_name, value, human_delay_ms))

        pre_js = ""
        if page_path == "decisions/brands":
            pre_js = """
    // Click Reformulation tab
    var reformTab = Array.from(document.querySelectorAll('a, button')).find(
        function(el) { return el.textContent.trim() === 'Reformulation' && el.offsetParent !== null; }
    );
    if (reformTab) {
        reformTab.click();
        await delay(1500);
    }"""

        block = f"""
    // --- {page_path} ---
    ui.menu.call(null, '{parent}', '{path}', {{}});
    await delay(2500);
{pre_js}
{chr(10).join(field_lines)}

    // Save this page before moving to next
    clickSave();
    await delay(3000);  // Wait for save + reload
"""
        page_blocks.append(block)

    return f"""async () => {{
{_JS_HELPERS}
{chr(10).join(page_blocks)}
    // Navigate to review page
    ui.menu.call(null, 'decisions', 'decisions/review', {{}});
    await delay(1500);

    return {{
        success: errors.length === 0,
        applied: applied.length,
        errors: errors
    }};
}}"""


def generate_example(period: int = 1) -> dict[str, Any]:
    """Generate an example suggestion file with current default values."""
    example: dict[str, Any] = {
        "_comment": f"PharmaSim Decision suggestion for Period {period}",
        "_period": period,
    }

    if period == 0:
        example.update({
            "ad_agency": "1",
            "symptom_cold": True,
            "symptom_cough": False,
            "symptom_allergy": False,
            "demo_young_singles": True,
            "demo_young_families": True,
            "demo_mature_families": True,
            "demo_empty_nesters": False,
            "demo_retired": False,
            "benefit_relieves_aches": True,
            "benefit_clears_nasal": True,
            "benefit_reduces_chest": True,
            "benefit_dries_runny_nose": True,
            "benefit_suppresses_coughing": True,
            "benefit_relieves_allergies": False,
            "benefit_minimizes_side_effects": False,
            "benefit_wont_cause_drowsiness": False,
            "benefit_helps_you_rest": True,
        })
    else:
        example.update({
            "sf_independent": 3,
            "sf_chain": 29,
            "sf_grocery": 43,
            "sf_convenience": 3,
            "sf_mass": 22,
            "sf_wholesaler": 18,
            "sf_merchandisers": 12,
            "sf_detailers": 12,
            "msrp": 5.44,
            "discount_under_250": 25.0,
            "discount_under_2500": 30.5,
            "discount_2500_plus": 35.0,
            "discount_wholesale": 40.8,
            "ad_budget": 18.0,
            "ad_agency": "1",
            "symptom_cold": True,
            "symptom_cough": False,
            "symptom_allergy": False,
            "demo_young_singles": True,
            "demo_young_families": True,
            "demo_mature_families": True,
            "demo_empty_nesters": False,
            "demo_retired": False,
            "msg_primary_pct": 0,
            "msg_benefits_pct": 50,
            "msg_comparison_pct": 40,
            "msg_comparison_target": "2",
            "msg_reminder_pct": 10,
            "benefit_relieves_aches": True,
            "benefit_clears_nasal": True,
            "benefit_reduces_chest": True,
            "benefit_dries_runny_nose": True,
            "benefit_suppresses_coughing": True,
            "benefit_relieves_allergies": False,
            "benefit_minimizes_side_effects": False,
            "benefit_wont_cause_drowsiness": False,
            "benefit_helps_you_rest": True,
            "allowance_independent": 17.0,
            "allowance_chain": 18.5,
            "allowance_grocery": 18.5,
            "allowance_convenience": 17.5,
            "allowance_mass": 19.0,
            "allowance_wholesale": 19.0,
            "coop_ad_budget": 1.4,
            "coop_ad_independent": True,
            "coop_ad_chain": True,
            "coop_ad_grocery": True,
            "coop_ad_convenience": True,
            "coop_ad_mass": True,
            "pop_budget": 2.0,
            "pop_independent": True,
            "pop_chain": True,
            "pop_grocery": True,
            "pop_convenience": True,
            "pop_mass": True,
            "trial_budget": 0.0,
            "coupon_budget": 4.2,
            "coupon_amount": "1",
            "brand_reformulation": "2",
        })

    return example


def print_suggestion_summary(suggestion: dict[str, Any]) -> None:
    """Print a human-readable summary of a suggestion."""
    print("=" * 60)
    print("Decision Suggestion Summary")
    print("=" * 60)

    if "_period" in suggestion:
        print(f"Period: {suggestion['_period']}")
    if "_comment" in suggestion:
        print(f"Comment: {suggestion['_comment']}")
    print()

    categories = {
        "Sales Force": [k for k in suggestion if k.startswith("sf_")],
        "Pricing": [k for k in suggestion if k in (
            "msrp", "discount_under_250", "discount_under_2500",
            "discount_2500_plus", "discount_wholesale",
        )],
        "Advertising": [k for k in suggestion if k in (
            "ad_budget", "ad_agency",
            "symptom_cold", "symptom_cough", "symptom_allergy",
            "demo_young_singles", "demo_young_families", "demo_mature_families",
            "demo_empty_nesters", "demo_retired",
            "msg_primary_pct", "msg_benefits_pct", "msg_comparison_pct",
            "msg_comparison_target", "msg_reminder_pct",
        ) or k.startswith("benefit_")],
        "Promotion": [k for k in suggestion if k.startswith((
            "allowance_", "coop_ad_", "pop_", "trial_", "coupon_",
        ))],
        "Brand Reformulation": [k for k in suggestion if k == "brand_reformulation"],
    }

    for cat_name, keys in categories.items():
        if not keys:
            continue
        print(f"  {cat_name}:")
        for key in keys:
            val = suggestion[key]
            extra = ""
            if key == "ad_agency":
                extra = f"  ({AD_AGENCIES.get(str(val), '?')})"
            elif key == "msg_comparison_target":
                rev = {v: k for k, v in COMPARISON_TARGETS.items()}
                extra = f"  ({rev.get(str(val), '?')})"
            elif key == "coupon_amount":
                extra = f"  ({COUPON_AMOUNTS.get(str(val), '?')})"
            elif key == "brand_reformulation":
                labels = {"2": "Keep original", "1": "Drop alcohol", "0": "Switch to expectorant"}
                extra = f"  ({labels.get(str(val), '?')})"
            print(f"    {key}: {val}{extra}")
        print()

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Apply PharmaSim decision suggestions")
    parser.add_argument(
        "suggestion_file",
        nargs="?",
        help="Path to suggestion JSON file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary only, don't generate JS",
    )
    parser.add_argument(
        "--generate-example",
        type=int,
        metavar="PERIOD",
        help="Generate an example suggestion file for the given period (0 or 1)",
    )
    parser.add_argument(
        "--page-scripts",
        action="store_true",
        help="Output per-page JS scripts (for sequential MCP execution)",
    )
    args = parser.parse_args()

    if args.generate_example is not None:
        example = generate_example(args.generate_example)
        print(json.dumps(example, indent=2))
        return

    if not args.suggestion_file:
        parser.error("Please provide a suggestion file or use --generate-example")

    suggestion = load_suggestion(args.suggestion_file)
    print_suggestion_summary(suggestion)

    if args.dry_run:
        return

    if args.page_scripts:
        scripts = generate_page_scripts(suggestion)
        for page_path, nav_js, set_js in scripts:
            print(f"\n{'='*60}")
            print(f"PAGE: {page_path}")
            print(f"{'='*60}")
            print(f"\n--- Navigation JS ---\n{nav_js}")
            print(f"\n--- Set Values + Save JS ---\n{set_js}")
    else:
        js = generate_apply_js(suggestion)
        print(f"\n--- Single-shot JS (sets values + saves each page) ---\n")
        print(js)


if __name__ == "__main__":
    main()
