"""Comprehensive decision-page scraper for PharmaSim simulator.

Consolidates ALL decision-page scraping into one module. Generates JS that
navigates each of the 7+ decision pages/tabs and extracts everything:
  - All editable input values (name, value, type, disabled status)
  - All Previous/Current/Change table data (SF, Pricing, Review)
  - All read-only display data (budget bar, expenditures, costs/person,
    formulation, reformulation options, special page)
  - Budget overview from review page

Works with both Selenium (driver.execute_script) and Chrome DevTools MCP
(evaluate_script).

IMPORTANT: The generated JS NEVER clicks Advance, Replay, or Restart buttons.

Usage with Chrome DevTools MCP:
    1. Launch the sim, navigate to desired period
    2. Run: uv run python -m src.decision_scraper [--period 1]
       Prints JS to paste into evaluate_script
    3. Or use --parse FILE.json to pretty-print scraped results

Usage programmatic:
    from src.decision_scraper import js_scrape_all_decisions
    js = js_scrape_all_decisions()
    # Pass to Chrome DevTools MCP evaluate_script or Selenium execute_script
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Decision input variable mapping
# ---------------------------------------------------------------------------

@dataclass
class DecisionInputMap:
    """Maps all HTML input field names to their semantic meaning.

    These are the variables that the optimizer can SET on the webpage
    to submit decisions. Field values are the HTML ``name`` (or ``id``
    for checkboxes) attributes used in the simulator forms.

    Field naming convention: ``<category>_<detail>``
    Value convention: string = HTML field name/id to target.
    """

    # -- Sales Force (decisions/sales_force) --
    # Direct channels (headcount integers)
    sf_direct_independent: str = "sf1"    # Independent Drugstores
    sf_direct_chain: str = "sf2"          # Chain Drugstores
    sf_direct_grocery: str = "sf3"        # Grocery Stores
    sf_direct_convenience: str = "sf4"    # Convenience Stores
    sf_direct_mass: str = "sf5"           # Mass Merchandisers
    # Indirect channels (headcount integers)
    sf_indirect_wholesaler: str = "sf6"   # Wholesaler Support
    sf_indirect_merchandisers: str = "sf7"  # Merchandisers
    sf_indirect_detailers: str = "sf8"    # Detailers

    # -- Brand Reformulation (decisions/brands -> Reformulation tab) --
    # Radio name="choice", individual ids: choice2, choice1, choice0
    #   value "2" = Keep the original formula
    #   value "1" = Drop alcohol (alcohol -> 0, unit cost $1.00)
    #   value "0" = Switch from cough suppressant to expectorant
    #               (cough_supp -> 0, expectorant -> 200, unit cost $1.11)
    # Only available when entering Decision1+ (i.e., at Year1 or later pages).
    brand_reformulation_choice: str = "choice"

    # -- Pricing (decisions/pricing) --
    msrp: str = "msrp1"                  # Mfr. Suggested Retail Price ($)
    discount_under_250: str = "disc1-1"   # Volume discount % for orders < 250
    discount_under_2500: str = "disc1-2"  # Volume discount % for orders < 2500
    discount_2500_plus: str = "disc1-3"   # Volume discount % for orders 2500+
    discount_wholesale: str = "disc1-4"   # Wholesale discount %

    # -- Advertising (decisions/advertising) --
    ad_budget: str = "ad_budget1"  # Advertising budget in millions ($)

    # Ad agency (radio, name="agency1")
    #   value "1" = Brewster, Maxwell, & Wheeler (15% fee)
    #   value "2" = Sully and Rogers (10% fee)
    #   value "3" = Lester Loebol and Company (5% fee)
    ad_agency: str = "agency1"

    # Symptom targets (checkboxes, name="illness1[]")
    #   Checking NONE = targeting all. Checking specific = targeting those.
    symptom_target_cold: str = "illness1-COLD"        # value="4096"
    symptom_target_cough: str = "illness1-COUGH"      # value="8192"
    symptom_target_allergy: str = "illness1-ALLERGY"   # value="16384"

    # Demographic targets (checkboxes, name="demo1[]")
    #   Checking NONE = targeting all. Checking specific = targeting those.
    demo_young_singles: str = "demo1-1"    # value="1"
    demo_young_families: str = "demo1-2"   # value="2"
    demo_mature_families: str = "demo1-4"  # value="4"
    demo_empty_nesters: str = "demo1-8"    # value="8"
    demo_retired: str = "demo1-16"         # value="16"

    # Ad messaging mix (must sum to 100%)
    msg_primary_pct: str = "primary_msg1"
    msg_benefits_pct: str = "benefit_msg1"
    msg_comparison_pct: str = "compare_msg1"
    msg_comparison_target: str = "compare_target1"  # <select> -- use COMPARISON_TARGETS dict
    msg_reminder_pct: str = "reminder_msg1"

    # Promote benefits (checkboxes, name="benefit1[]")
    benefit_relieves_aches: str = "benefit1-1"           # value="1"
    benefit_clears_nasal: str = "benefit1-2"             # value="2"
    benefit_reduces_chest: str = "benefit1-3"            # value="3"
    benefit_dries_runny_nose: str = "benefit1-4"         # value="4"
    benefit_suppresses_coughing: str = "benefit1-5"      # value="5"
    benefit_relieves_allergies: str = "benefit1-6"       # value="6"
    benefit_minimizes_side_effects: str = "benefit1-7"   # value="7"
    benefit_wont_cause_drowsiness: str = "benefit1-8"    # value="8"
    benefit_helps_you_rest: str = "benefit1-9"           # value="9"

    # -- Promotion (decisions/promotion) --
    # Promotional allowance % by channel (range 10-20%)
    allowance_independent: str = "allowance1-1"    # Independent Drugstores
    allowance_chain: str = "allowance1-2"          # Chain Drugstores
    allowance_grocery: str = "allowance1-3"        # Grocery Stores
    allowance_convenience: str = "allowance1-4"    # Convenience Stores
    allowance_mass: str = "allowance1-5"           # Mass Merchandisers
    allowance_wholesale: str = "allowance1-6"      # Wholesalers

    # Co-op advertising budget (millions $) + channel participation checkboxes
    coop_ad_budget: str = "coop_ad_budget1"
    coop_ad_independent: str = "coop_ad1-1"    # checkbox value="1"
    coop_ad_chain: str = "coop_ad1-2"          # checkbox value="1"
    coop_ad_grocery: str = "coop_ad1-3"        # checkbox value="1"
    coop_ad_convenience: str = "coop_ad1-4"    # checkbox value="1"
    coop_ad_mass: str = "coop_ad1-5"           # checkbox value="1"

    # Point of Purchase budget (millions $) + channel participation checkboxes
    pop_budget: str = "display_budget1"
    pop_independent: str = "display_ad1-1"     # checkbox value="1"
    pop_chain: str = "display_ad1-2"           # checkbox value="1"
    pop_grocery: str = "display_ad1-3"         # checkbox value="1"
    pop_convenience: str = "display_ad1-4"     # checkbox value="1"
    pop_mass: str = "display_ad1-5"            # checkbox value="1"

    # Trial size budget (millions $)
    trial_budget: str = "trial_budget1"

    # Coupon budget (millions $) + coupon face value
    coupon_budget: str = "coupon_budget1"
    # <select> name="coupon_amt1"
    #   value "0" = $0.25
    #   value "1" = $0.50
    #   value "2" = $0.75
    #   value "3" = $1.00
    coupon_amount: str = "coupon_amt1"


# ---------------------------------------------------------------------------
# Decision constants
# ---------------------------------------------------------------------------

# Ad agency IDs and names
AD_AGENCIES = {
    "1": "Brewster, Maxwell, & Wheeler (15%)",
    "2": "Sully and Rogers (10%)",
    "3": "Lester Loebol and Company (5%)",
}

# Comparison target brand IDs for the advertising select dropdown
COMPARISON_TARGETS = {
    "Believe": "3",
    "Besthelp": "2",
    "Coldcure": "11",
    "Coughcure": "4",
    "Defogg": "6",
    "Dripstop": "5",
    "Dryup": "7",
    "Effective": "8",
    "End": "10",
    "Extra": "9",
}

# Coupon face values
COUPON_AMOUNTS = {
    "0": "$0.25",
    "1": "$0.50",
    "2": "$0.75",
    "3": "$1.00",
}

# Benefit checkbox value-to-label mapping
BENEFIT_LABELS = {
    "1": "Relieves Aches",
    "2": "Clears Nasal Congestion",
    "3": "Reduces Chest Congestion",
    "4": "Dries Up Runny Nose",
    "5": "Suppresses Coughing",
    "6": "Relieves Allergy Symptoms",
    "7": "Minimizes Side Effects",
    "8": "Won't Cause Drowsiness",
    "9": "Helps You Rest",
}


# ---------------------------------------------------------------------------
# Period-dependent input availability
# ---------------------------------------------------------------------------
# At Start (period 0), the Decisions tab shows Decision0 -- the decisions to be
# made given Year0 state that will influence Year1. Most inputs are READ-ONLY
# at Start (showing defaults). Only a subset of advertising inputs are editable.
#
# At Year 1 (period 1), the Decisions tab shows Decision1 -- all 63 inputs are
# editable, to be submitted to influence Year2.
#
# Verified 2026-03-14 by exhaustive DOM audit:
#
# Period 0 (Start) -- 20 editable inputs:
#   Advertising only: agency1 (3 radios), illness1[] (3 checkboxes),
#   demo1[] (5 checkboxes), benefit1[] (9 checkboxes)
#   NOT editable: ad_budget1, primary_msg1, benefit_msg1, compare_msg1,
#   compare_target1, reminder_msg1, ALL sales force, ALL pricing,
#   ALL promotion, brands reformulation
#
# Period 1+ (Year 1, Year 2) -- 63 editable inputs:
#   Sales Force: 8  (sf1-sf8)
#   Pricing: 5  (msrp1, disc1-1 to disc1-4)
#   Advertising: 26  (ad_budget1, agency1x3, illness1[]x3, demo1[]x5,
#     primary_msg1, benefit_msg1, compare_msg1, compare_target1,
#     reminder_msg1, benefit1[]x9)
#   Promotion: 21  (allowance1-1 to 1-6, coop_ad_budget1, coop_ad1-1 to 1-5,
#     display_budget1, display_ad1-1 to 1-5, trial_budget1, coupon_budget1,
#     coupon_amt1)
#   Brands Reformulation: 3  (choice radio: "2"=keep, "1"=drop alcohol,
#     "0"=switch to expectorant) -- only Years 1 and 2
#   Special: 0 (period-dependent, may have inputs in later years)

INPUTS_BY_PERIOD = {
    0: {
        "total": 20,
        "pages": {
            "decisions/advertising": [
                "agency1",  # radio (3 options)
                "illness1-COLD", "illness1-COUGH", "illness1-ALLERGY",
                "demo1-1", "demo1-2", "demo1-4", "demo1-8", "demo1-16",
                "benefit1-1", "benefit1-2", "benefit1-3", "benefit1-4",
                "benefit1-5", "benefit1-6", "benefit1-7", "benefit1-8",
                "benefit1-9",
            ],
        },
    },
    1: {
        "total": 63,
        "pages": {
            "decisions/sales_force": [
                "sf1", "sf2", "sf3", "sf4", "sf5", "sf6", "sf7", "sf8",
            ],
            "decisions/pricing": [
                "msrp1", "disc1-1", "disc1-2", "disc1-3", "disc1-4",
            ],
            "decisions/advertising": [
                "ad_budget1",
                "agency1",  # radio (3 options)
                "illness1-COLD", "illness1-COUGH", "illness1-ALLERGY",
                "demo1-1", "demo1-2", "demo1-4", "demo1-8", "demo1-16",
                "primary_msg1", "benefit_msg1", "compare_msg1",
                "compare_target1", "reminder_msg1",
                "benefit1-1", "benefit1-2", "benefit1-3", "benefit1-4",
                "benefit1-5", "benefit1-6", "benefit1-7", "benefit1-8",
                "benefit1-9",
            ],
            "decisions/promotion": [
                "allowance1-1", "allowance1-2", "allowance1-3",
                "allowance1-4", "allowance1-5", "allowance1-6",
                "coop_ad_budget1",
                "coop_ad1-1", "coop_ad1-2", "coop_ad1-3",
                "coop_ad1-4", "coop_ad1-5",
                "display_budget1",
                "display_ad1-1", "display_ad1-2", "display_ad1-3",
                "display_ad1-4", "display_ad1-5",
                "trial_budget1", "coupon_budget1", "coupon_amt1",
            ],
            "decisions/brands": [
                "choice",  # radio (3 options: "2", "1", "0")
            ],
        },
    },
    # No Decision2 exists; if period 2 is reached, inputs match period 1
    2: None,  # same as period 1
}


# ---------------------------------------------------------------------------
# Shared JS helpers for parsing numbers and extracting table data
# ---------------------------------------------------------------------------

_JS_PARSE_NUM = """
    function parseNum(s) {
        if (s == null || s === '') return null;
        s = String(s).trim();
        var neg = false;
        if (s.match(/^\\$?\\(/) && s.endsWith(')')) {
            neg = true;
            s = s.replace(/[\\$\\(\\)]/g, '');
        } else {
            s = s.replace(/^\\$/, '');
        }
        s = s.replace(/%$/, '');
        s = s.replace(/,/g, '');
        if (s.endsWith('M')) s = s.slice(0, -1);
        var v = parseFloat(s);
        if (isNaN(v)) return null;
        return neg ? -v : v;
    }
"""

_JS_EXTRACT_INPUTS = """
    function extractInputs() {
        var inputs = document.querySelectorAll(
            '#content input:not([type="hidden"]), #content select'
        );
        var result = {};
        inputs.forEach(function(inp) {
            if (inp.offsetParent === null) return;
            var name = inp.name || inp.id;
            if (!name) return;
            if (inp.type === 'radio') {
                if (inp.checked) result[name] = inp.value;
            } else if (inp.type === 'checkbox') {
                result[inp.id || name] = inp.checked;
            } else {
                result[name] = inp.value;
            }
        });
        return result;
    }
"""

_JS_EXTRACT_PREV_CURRENT_ROWS = """
    function extractPrevCurrentRows(container) {
        var root = container || document.getElementById('content');
        var allTables = root.querySelectorAll('table');
        var leafTables = [];
        allTables.forEach(function(table) {
            if (table.offsetParent === null) return;
            if (table.querySelector('table') === null) {
                leafTables.push(table);
            }
        });

        var sections = [];
        leafTables.forEach(function(table) {
            var rows = [];
            var inPrevSection = false;
            table.querySelectorAll('tr').forEach(function(tr) {
                if (tr.offsetParent === null) return;
                var tds = tr.querySelectorAll('td, th');
                var cells = [];
                tds.forEach(function(td) {
                    cells.push(td.textContent.trim().replace(/\\s+/g, ' '));
                });
                if (cells.length >= 3 && cells.indexOf('Previous') >= 0) {
                    inPrevSection = true;
                    return;
                }
                if (!inPrevSection) return;
                if (cells.length < 3) return;
                var label = cells[0];
                if (!label || label === '') return;
                if (cells.length === 1) return;
                if (tds[0] && tds[0].colSpan >= 3) return;

                rows.push({
                    label: label,
                    previous: cells[1],
                    current: cells[2],
                    extra: cells.length > 3 ? cells[3] : null
                });
            });
            if (rows.length > 0) sections.push(rows);
        });
        return sections;
    }
"""

_JS_EXTRACT_BUDGET_BAR = """
    function extractBudgetBar() {
        var content = document.getElementById('content');
        if (!content) return null;
        var text = content.textContent;
        var budgetMatch = text.match(/Budget[:\\s]*\\$([\\d.,]+)\\s*M/);
        var remainMatch = text.match(/Remaining[:\\s]*\\$([\\d.,]+)\\s*M/);
        return {
            budget_M: budgetMatch ? parseNum(budgetMatch[1]) : null,
            remaining_M: remainMatch ? parseNum(remainMatch[1]) : null
        };
    }
"""


# ---------------------------------------------------------------------------
# Per-page JS scraper functions
# ---------------------------------------------------------------------------

def js_scrape_sales_force() -> str:
    """JS that scrapes the sales force decision page."""
    return f"""
async () => {{
    {_JS_PARSE_NUM}
    {_JS_EXTRACT_INPUTS}
    {_JS_EXTRACT_PREV_CURRENT_ROWS}
    {_JS_EXTRACT_BUDGET_BAR}

    ui.menu.call(null, 'decisions', 'decisions/sales_force', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var budget = extractBudgetBar();
    var inputs = extractInputs();
    var sections = extractPrevCurrentRows();

    var headcount = {{}};
    var previous_headcount = {{}};
    if (sections.length >= 1) {{
        sections[0].forEach(function(row) {{
            headcount[row.label] = {{
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                change: parseNum(row.extra)
            }};
            previous_headcount[row.label] = parseNum(row.previous);
        }});
    }}

    var expenditures = {{}};
    if (sections.length >= 2) {{
        sections[1].forEach(function(row) {{
            expenditures[row.label] = {{
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                change: parseNum(row.extra)
            }};
        }});
    }}

    var costs_per_person = {{}};
    if (sections.length >= 3) {{
        sections[2].forEach(function(row) {{
            costs_per_person[row.label] = {{
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                change: parseNum(row.extra)
            }};
        }});
    }}

    return {{
        budget: budget,
        inputs: inputs,
        previous: previous_headcount,
        headcount: headcount,
        expenditures: expenditures,
        costs_per_person: costs_per_person
    }};
}}
"""


def js_scrape_pricing() -> str:
    """JS that scrapes the pricing decision page."""
    return f"""
async () => {{
    {_JS_PARSE_NUM}
    {_JS_EXTRACT_INPUTS}
    {_JS_EXTRACT_PREV_CURRENT_ROWS}
    {_JS_EXTRACT_BUDGET_BAR}

    ui.menu.call(null, 'decisions', 'decisions/pricing', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var budget = extractBudgetBar();
    var inputs = extractInputs();
    var sections = extractPrevCurrentRows();

    var summary = {{}};
    var previous_pricing = {{}};
    if (sections.length >= 1) {{
        sections[0].forEach(function(row) {{
            summary[row.label] = {{
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                change: parseNum(row.extra)
            }};
            previous_pricing[row.label] = parseNum(row.previous);
        }});
    }}

    var volume_discounts = {{}};
    var discounted_prices = {{}};
    if (sections.length >= 2) {{
        sections[1].forEach(function(row) {{
            volume_discounts[row.label] = {{
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                discounted_price: parseNum(row.extra)
            }};
            discounted_prices[row.label] = parseNum(row.extra);
        }});
    }}

    return {{
        budget: budget,
        inputs: inputs,
        previous: previous_pricing,
        unit_cost: summary,
        volume_discounts: volume_discounts,
        discounted_prices: discounted_prices
    }};
}}
"""


def js_scrape_advertising() -> str:
    """JS that scrapes the advertising decision page (no Previous column)."""
    return f"""
async () => {{
    {_JS_PARSE_NUM}
    {_JS_EXTRACT_INPUTS}
    {_JS_EXTRACT_BUDGET_BAR}

    ui.menu.call(null, 'decisions', 'decisions/advertising', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var budget = extractBudgetBar();
    var inputs = extractInputs();

    return {{
        budget: budget,
        inputs: inputs
    }};
}}
"""


def js_scrape_promotion() -> str:
    """JS that scrapes the promotion decision page (no Previous column)."""
    return f"""
async () => {{
    {_JS_PARSE_NUM}
    {_JS_EXTRACT_INPUTS}
    {_JS_EXTRACT_BUDGET_BAR}

    ui.menu.call(null, 'decisions', 'decisions/promotion', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var budget = extractBudgetBar();
    var inputs = extractInputs();

    return {{
        budget: budget,
        inputs: inputs
    }};
}}
"""


def js_scrape_brands() -> str:
    """JS that scrapes the brands decision page (overview + reformulation tabs)."""
    return f"""
async () => {{
    {_JS_PARSE_NUM}

    ui.menu.call(null, 'decisions', 'decisions/brands', {{}});
    await new Promise(r => setTimeout(r, 1500));

    // Extract formulation table from Overview tab
    var formulation = {{}};
    var brandTables = document.querySelectorAll('#content table');
    brandTables.forEach(function(table) {{
        if (table.offsetParent === null) return;
        var rows = table.querySelectorAll('tr');
        rows.forEach(function(tr) {{
            var cells = tr.querySelectorAll('td, th');
            var texts = [];
            cells.forEach(function(c) {{ texts.push(c.textContent.trim()); }});
            if (texts.length >= 7 && texts[0] === 'Allround') {{
                formulation = {{
                    analgesic_mg: parseNum(texts[1]),
                    antihistamine_mg: parseNum(texts[2]),
                    decongestant_mg: parseNum(texts[3]),
                    cough_suppressant_mg: parseNum(texts[4]),
                    expectorant_mg: parseNum(texts[5]),
                    alcohol_pct: parseNum(texts[6])
                }};
                if (texts.length > 7) formulation.description = texts[7];
                if (texts.length > 8) formulation.duration = texts[7];
                if (texts.length > 9) formulation.symptom = texts[8];
                if (texts.length > 10) formulation.form = texts[9];
            }}
        }});
    }});

    // Check Reformulation tab
    var reformulation_available = false;
    var reformulation_choice = null;
    var reformulation_options = [];

    var reformTab = Array.from(document.querySelectorAll('a, button')).find(
        function(el) {{ return el.textContent.trim() === 'Reformulation' && el.offsetParent !== null; }}
    );
    if (reformTab) {{
        reformTab.click();
        await new Promise(r => setTimeout(r, 1000));
        reformulation_available = true;

        var radios = document.querySelectorAll('input[name="choice"]');
        radios.forEach(function(r) {{
            var label = '';
            var row = r.closest('tr');
            if (row) {{
                label = row.textContent.trim().replace(/\\s+/g, ' ').substring(0, 100);
            }}
            reformulation_options.push({{
                value: r.value,
                checked: r.checked,
                disabled: r.disabled,
                label: label
            }});
            if (r.checked) reformulation_choice = r.value;
        }});
    }}

    return {{
        formulation: formulation,
        reformulation_available: reformulation_available,
        reformulation_choice: reformulation_choice,
        reformulation_options: reformulation_options
    }};
}}
"""


def js_scrape_special() -> str:
    """JS that scrapes the special decision page."""
    return f"""
async () => {{
    {_JS_EXTRACT_INPUTS}

    ui.menu.call(null, 'decisions', 'decisions/special', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var inputs = extractInputs();
    var content = document.getElementById('content');
    var text = content ? content.textContent.trim().replace(/\\s+/g, ' ').substring(0, 500) : '';

    return {{
        inputs: inputs,
        page_text: text,
        has_inputs: Object.keys(inputs).length > 0
    }};
}}
"""


def js_scrape_review() -> str:
    """JS that scrapes the review/summary decision page."""
    return f"""
async () => {{
    {_JS_PARSE_NUM}
    {_JS_EXTRACT_PREV_CURRENT_ROWS}
    {_JS_EXTRACT_INPUTS}

    ui.menu.call(null, 'decisions', 'decisions/review', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var sections = extractPrevCurrentRows();
    var inputs = extractInputs();

    var budget_overview = {{}};
    var allocation = {{}};

    // The review page has multiple Previous/Current sections.
    // Look for budget-related labels across all sections.
    sections.forEach(function(section) {{
        section.forEach(function(row) {{
            if (row.label === 'Budget' || row.label === 'Remaining') {{
                budget_overview[row.label] = {{
                    previous: parseNum(row.previous),
                    current: parseNum(row.current),
                    change: parseNum(row.extra)
                }};
            }}
            if (row.label === 'Sales Force' || row.label === 'Advertising' ||
                row.label === 'Promotion') {{
                allocation[row.label] = {{
                    previous: parseNum(row.previous),
                    current: parseNum(row.current),
                    change: parseNum(row.extra)
                }};
            }}
        }});
    }});

    // Extract replay/restart counts from page text
    var content = document.getElementById('content');
    var pageText = content ? content.textContent : '';
    var replayMatch = pageText.match(/Replay\\s*-\\s*(\\d+)\\s*left/i);
    var restartMatch = pageText.match(/Restart\\s*-\\s*(\\d+)\\s*/i);

    var replay_restart = {{
        replays_remaining: replayMatch ? parseInt(replayMatch[1]) : null,
        restarts_remaining: restartMatch ? parseInt(restartMatch[1]) : null
    }};

    // Capture all sections for comprehensive data
    var all_review_sections = [];
    sections.forEach(function(section) {{
        var sectionData = [];
        section.forEach(function(row) {{
            sectionData.push({{
                label: row.label,
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                change: row.extra !== null ? parseNum(row.extra) : null
            }});
        }});
        all_review_sections.push(sectionData);
    }});

    return {{
        budget_overview: budget_overview,
        allocation: allocation,
        replay_restart: replay_restart,
        inputs: inputs,
        all_sections: all_review_sections
    }};
}}
"""


# ---------------------------------------------------------------------------
# Comprehensive all-pages scraper
# ---------------------------------------------------------------------------

def js_scrape_all_decisions(period: int | None = None) -> str:
    """Generate JS that navigates ALL decision pages and extracts everything.

    If period is given, the script first switches to that period.

    Returns an async JS function string suitable for evaluate_script().
    The function returns a structured dict with data from all pages.

    IMPORTANT: This JS NEVER clicks Advance, Replay, or Restart buttons.
    """

    switch_period_js = ""
    if period is not None:
        switch_period_js = f"""
    // Switch to requested period
    var links = document.querySelectorAll('a[onclick="app.periods.activate(this);"]');
    if (links[{period}]) {{
        links[{period}].click();
        await new Promise(r => setTimeout(r, 2000));
    }}
"""

    return f"""
async () => {{
    {_JS_PARSE_NUM}
    {_JS_EXTRACT_INPUTS}
    {_JS_EXTRACT_PREV_CURRENT_ROWS}
    {_JS_EXTRACT_BUDGET_BAR}

    {switch_period_js}

    var result = {{}};

    // Get current period
    var periodEl = document.getElementById('cperiod');
    result.period = periodEl ? parseInt(periodEl.value) : null;

    // ---------------------------------------------------------------
    // 1. SALES FORCE PAGE
    // ---------------------------------------------------------------
    ui.menu.call(null, 'decisions', 'decisions/sales_force', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var sfBudget = extractBudgetBar();
    var sfInputs = extractInputs();
    var sfSections = extractPrevCurrentRows();

    var sfHeadcount = {{}};
    var sfPrevious = {{}};
    if (sfSections.length >= 1) {{
        sfSections[0].forEach(function(row) {{
            sfHeadcount[row.label] = {{
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                change: parseNum(row.extra)
            }};
            sfPrevious[row.label] = parseNum(row.previous);
        }});
    }}

    var sfExpenditures = {{}};
    if (sfSections.length >= 2) {{
        sfSections[1].forEach(function(row) {{
            sfExpenditures[row.label] = {{
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                change: parseNum(row.extra)
            }};
        }});
    }}

    var sfCostsPerPerson = {{}};
    if (sfSections.length >= 3) {{
        sfSections[2].forEach(function(row) {{
            sfCostsPerPerson[row.label] = {{
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                change: parseNum(row.extra)
            }};
        }});
    }}

    // Compute totals from headcount table
    var totalDirect = 0, totalIndirect = 0;
    sfSections[0] && sfSections[0].forEach(function(row) {{
        var cur = parseNum(row.current);
        if (cur !== null) {{
            if (['Total Direct', 'Total Indirect', 'Total'].indexOf(row.label) < 0) {{
                // Heuristic: first 5 channels are direct, last 3 are indirect
                // But better to look at the computed rows
            }}
        }}
    }});
    // Extract computed totals if present
    var computed = {{}};
    sfSections[0] && sfSections[0].forEach(function(row) {{
        if (row.label === 'Total Direct' || row.label === 'Total Indirect' || row.label === 'Total') {{
            computed[row.label.toLowerCase().replace(/ /g, '_')] = parseNum(row.current);
        }}
    }});

    result.budget = sfBudget;
    result.sales_force = {{
        inputs: sfInputs,
        previous: sfPrevious,
        headcount: sfHeadcount,
        computed: computed,
        expenditures: sfExpenditures,
        costs_per_person: sfCostsPerPerson
    }};

    // ---------------------------------------------------------------
    // 2. PRICING PAGE
    // ---------------------------------------------------------------
    ui.menu.call(null, 'decisions', 'decisions/pricing', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var pricingBudget = extractBudgetBar();
    var pricingInputs = extractInputs();
    var pricingSections = extractPrevCurrentRows();

    var pricingSummary = {{}};
    var pricingPrevious = {{}};
    if (pricingSections.length >= 1) {{
        pricingSections[0].forEach(function(row) {{
            pricingSummary[row.label] = {{
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                change: parseNum(row.extra)
            }};
            pricingPrevious[row.label] = parseNum(row.previous);
        }});
    }}

    var volumeDiscounts = {{}};
    var discountedPrices = {{}};
    if (pricingSections.length >= 2) {{
        pricingSections[1].forEach(function(row) {{
            volumeDiscounts[row.label] = {{
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                discounted_price: parseNum(row.extra)
            }};
            discountedPrices[row.label] = parseNum(row.extra);
        }});
    }}

    result.pricing = {{
        inputs: pricingInputs,
        previous: pricingPrevious,
        unit_cost: pricingSummary,
        volume_discounts: volumeDiscounts,
        discounted_prices: discountedPrices
    }};

    // ---------------------------------------------------------------
    // 3. ADVERTISING PAGE (no Previous column)
    // ---------------------------------------------------------------
    ui.menu.call(null, 'decisions', 'decisions/advertising', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var adBudget = extractBudgetBar();
    var adInputs = extractInputs();

    result.advertising = {{
        inputs: adInputs
    }};

    // ---------------------------------------------------------------
    // 4. PROMOTION PAGE (no Previous column)
    // ---------------------------------------------------------------
    ui.menu.call(null, 'decisions', 'decisions/promotion', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var promoBudget = extractBudgetBar();
    var promoInputs = extractInputs();

    result.promotion = {{
        inputs: promoInputs
    }};

    // ---------------------------------------------------------------
    // 5. BRANDS PAGE (overview + reformulation)
    // ---------------------------------------------------------------
    ui.menu.call(null, 'decisions', 'decisions/brands', {{}});
    await new Promise(r => setTimeout(r, 1500));

    // Extract formulation table
    var formulation = {{}};
    var brandTables = document.querySelectorAll('#content table');
    brandTables.forEach(function(table) {{
        if (table.offsetParent === null) return;
        var rows = table.querySelectorAll('tr');
        rows.forEach(function(tr) {{
            var cells = tr.querySelectorAll('td, th');
            var texts = [];
            cells.forEach(function(c) {{ texts.push(c.textContent.trim()); }});
            if (texts.length >= 7 && texts[0] === 'Allround') {{
                formulation = {{
                    analgesic_mg: parseNum(texts[1]),
                    antihistamine_mg: parseNum(texts[2]),
                    decongestant_mg: parseNum(texts[3]),
                    cough_suppressant_mg: parseNum(texts[4]),
                    expectorant_mg: parseNum(texts[5]),
                    alcohol_pct: parseNum(texts[6])
                }};
                if (texts.length > 7) formulation.description = texts[7];
            }}
        }});
    }});

    // Check Reformulation tab
    var reformulation_available = false;
    var reformulation_choice = null;
    var reformulation_options = [];

    var reformTab = Array.from(document.querySelectorAll('a, button')).find(
        function(el) {{ return el.textContent.trim() === 'Reformulation' && el.offsetParent !== null; }}
    );
    if (reformTab) {{
        reformTab.click();
        await new Promise(r => setTimeout(r, 1000));
        reformulation_available = true;

        var radios = document.querySelectorAll('input[name="choice"]');
        radios.forEach(function(r) {{
            var label = '';
            var row = r.closest('tr');
            if (row) {{
                label = row.textContent.trim().replace(/\\s+/g, ' ').substring(0, 100);
            }}
            reformulation_options.push({{
                value: r.value,
                checked: r.checked,
                disabled: r.disabled,
                label: label
            }});
            if (r.checked) reformulation_choice = r.value;
        }});
    }}

    result.brands = {{
        formulation: formulation,
        reformulation_available: reformulation_available,
        reformulation_choice: reformulation_choice,
        reformulation_options: reformulation_options
    }};

    // ---------------------------------------------------------------
    // 6. SPECIAL PAGE
    // ---------------------------------------------------------------
    ui.menu.call(null, 'decisions', 'decisions/special', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var specialInputs = extractInputs();
    var specialContent = document.getElementById('content');
    var specialText = specialContent ? specialContent.textContent.trim().replace(/\\s+/g, ' ').substring(0, 500) : '';

    result.special = {{
        inputs: specialInputs,
        page_text: specialText,
        has_inputs: Object.keys(specialInputs).length > 0
    }};

    // ---------------------------------------------------------------
    // 7. REVIEW/SUMMARY PAGE
    // ---------------------------------------------------------------
    ui.menu.call(null, 'decisions', 'decisions/review', {{}});
    await new Promise(r => setTimeout(r, 1500));

    var reviewSections = extractPrevCurrentRows();
    var reviewInputs = extractInputs();

    var budgetOverview = {{}};
    var allocation = {{}};

    reviewSections.forEach(function(section) {{
        section.forEach(function(row) {{
            if (row.label === 'Budget' || row.label === 'Remaining') {{
                budgetOverview[row.label] = {{
                    previous: parseNum(row.previous),
                    current: parseNum(row.current),
                    change: parseNum(row.extra)
                }};
            }}
            if (row.label === 'Sales Force' || row.label === 'Advertising' ||
                row.label === 'Promotion') {{
                allocation[row.label] = {{
                    previous: parseNum(row.previous),
                    current: parseNum(row.current),
                    change: parseNum(row.extra)
                }};
            }}
        }});
    }});

    // Extract replay/restart counts
    var reviewContent = document.getElementById('content');
    var reviewText = reviewContent ? reviewContent.textContent : '';
    var replayMatch = reviewText.match(/Replay\\s*-\\s*(\\d+)\\s*left/i);
    var restartMatch = reviewText.match(/Restart\\s*-\\s*(\\d+)\\s*/i);

    // Capture all sections from review page
    var allReviewSections = [];
    reviewSections.forEach(function(section) {{
        var sectionData = [];
        section.forEach(function(row) {{
            sectionData.push({{
                label: row.label,
                previous: parseNum(row.previous),
                current: parseNum(row.current),
                change: row.extra !== null ? parseNum(row.extra) : null
            }});
        }});
        allReviewSections.push(sectionData);
    }});

    result.review = {{
        budget_overview: budgetOverview,
        allocation: allocation,
        replay_restart: {{
            replays_remaining: replayMatch ? parseInt(replayMatch[1]) : null,
            restarts_remaining: restartMatch ? parseInt(restartMatch[1]) : null
        }},
        inputs: reviewInputs,
        all_sections: allReviewSections
    }};

    return result;
}}
"""


def js_scrape_decision_inputs() -> str:
    """JS that navigates to all Decision pages and extracts current input values.

    Returns a flat dict of input_name -> value for all decision variables.
    IMPORTANT: Only READS values, never clicks Advance/Replay/Restart.
    """
    return f"""
async () => {{
    var getInputs = function() {{
        var inputs = document.querySelectorAll(
            'input:not([type="hidden"]), select, textarea'
        );
        var result = {{}};
        inputs.forEach(function(inp) {{
            if (inp.offsetParent === null) return;
            var name = inp.name || inp.id;
            if (!name) return;
            if (inp.type === 'radio') {{
                if (inp.checked) result[name] = inp.value;
            }} else if (inp.type === 'checkbox') {{
                result[inp.id || name] = inp.checked;
            }} else {{
                result[name] = inp.value;
            }}
        }});
        return result;
    }};

    var allInputs = {{}};

    // Sales Force
    ui.menu.call(null, 'decisions', 'decisions/sales_force', {{}});
    await new Promise(function(r) {{ setTimeout(r, 1500); }});
    Object.assign(allInputs, getInputs());

    // Brands - Overview (no inputs usually)
    ui.menu.call(null, 'decisions', 'decisions/brands', {{}});
    await new Promise(function(r) {{ setTimeout(r, 1500); }});
    // Click Reformulation tab if present
    var reformTab = Array.from(document.querySelectorAll('a, button')).find(
        function(el) {{ return el.textContent.trim() === 'Reformulation' && el.offsetParent !== null; }}
    );
    if (reformTab) {{
        reformTab.click();
        await new Promise(function(r) {{ setTimeout(r, 1000); }});
        Object.assign(allInputs, getInputs());
    }}

    // Pricing
    ui.menu.call(null, 'decisions', 'decisions/pricing', {{}});
    await new Promise(function(r) {{ setTimeout(r, 1500); }});
    Object.assign(allInputs, getInputs());

    // Advertising
    ui.menu.call(null, 'decisions', 'decisions/advertising', {{}});
    await new Promise(function(r) {{ setTimeout(r, 1500); }});
    Object.assign(allInputs, getInputs());

    // Promotion
    ui.menu.call(null, 'decisions', 'decisions/promotion', {{}});
    await new Promise(function(r) {{ setTimeout(r, 1500); }});
    Object.assign(allInputs, getInputs());

    return allInputs;
}}
"""


# ---------------------------------------------------------------------------
# Pretty-print scraped decision data
# ---------------------------------------------------------------------------

def print_decision_summary(data: dict) -> None:
    """Pretty-print the full scraped decision page data."""
    print(f"\n{'='*60}")
    print(f"  Decision Page Data -- Period {data.get('period', '?')}")
    print(f"{'='*60}")

    # Budget bar
    budget = data.get("budget", {})
    if budget:
        b = budget.get("budget_M")
        r = budget.get("remaining_M")
        if b is not None or r is not None:
            print(f"\n  BUDGET BAR: ${b}M budget, ${r}M remaining")

    # Sales Force
    sf = data.get("sales_force", {})
    hc = sf.get("headcount", {})
    if hc:
        print("\n  SALES FORCE -- Headcount")
        print(f"  {'Channel':<25} {'Previous':>10} {'Current':>10} {'Change':>10}")
        print(f"  {'-'*55}")
        for label, vals in hc.items():
            prev = vals.get("previous", "")
            curr = vals.get("current", "")
            chg = vals.get("change", "")
            prev_s = f"{prev}" if prev is not None else ""
            curr_s = f"{curr}" if curr is not None else ""
            chg_s = f"{chg}" if chg is not None else ""
            print(f"  {label:<25} {prev_s:>10} {curr_s:>10} {chg_s:>10}")

    computed = sf.get("computed", {})
    if computed:
        print(f"\n  Computed totals: {computed}")

    costs = sf.get("costs_per_person", {})
    if costs:
        print("\n  SALES FORCE -- Costs per Salesperson")
        print(f"  {'Parameter':<25} {'Previous':>12} {'Current':>12} {'Change':>10}")
        print(f"  {'-'*59}")
        for label, vals in costs.items():
            prev = vals.get("previous", "")
            curr = vals.get("current", "")
            chg = vals.get("change", "")
            print(f"  {label:<25} {str(prev):>12} {str(curr):>12} {str(chg):>10}")

    expenditures = sf.get("expenditures", {})
    if expenditures:
        print("\n  SALES FORCE -- Expenditures ($M)")
        print(f"  {'Category':<25} {'Previous':>12} {'Current':>12} {'Change':>10}")
        print(f"  {'-'*59}")
        for label, vals in expenditures.items():
            prev = vals.get("previous", "")
            curr = vals.get("current", "")
            chg = vals.get("change", "")
            print(f"  {label:<25} {str(prev):>12} {str(curr):>12} {str(chg):>10}")

    sf_inputs = sf.get("inputs", {})
    if sf_inputs:
        print(f"\n  SF Inputs: {sf_inputs}")

    # Pricing
    pricing = data.get("pricing", {})
    summary = pricing.get("unit_cost", {})
    if summary:
        print("\n  PRICING -- Summary")
        print(f"  {'Item':<30} {'Previous':>12} {'Current':>12} {'Change':>10}")
        print(f"  {'-'*64}")
        for label, vals in summary.items():
            prev = vals.get("previous", "")
            curr = vals.get("current", "")
            chg = vals.get("change", "")
            print(f"  {label:<30} {str(prev):>12} {str(curr):>12} {str(chg):>10}")

    vd = pricing.get("volume_discounts", {})
    if vd:
        print("\n  PRICING -- Volume Discounts")
        print(f"  {'Tier':<25} {'Previous %':>12} {'Current %':>12} {'Disc Price':>12}")
        print(f"  {'-'*61}")
        for label, vals in vd.items():
            prev = vals.get("previous", "")
            curr = vals.get("current", "")
            dp = vals.get("discounted_price", "")
            print(f"  {label:<25} {str(prev):>12} {str(curr):>12} {str(dp):>12}")

    pricing_inputs = pricing.get("inputs", {})
    if pricing_inputs:
        print(f"\n  Pricing Inputs: {pricing_inputs}")

    # Advertising
    ad = data.get("advertising", {})
    ad_inputs = ad.get("inputs", {})
    if ad_inputs:
        print("\n  ADVERTISING -- Current Inputs (no Previous column)")
        for k, v in ad_inputs.items():
            print(f"    {k}: {v}")

    # Promotion
    promo = data.get("promotion", {})
    promo_inputs = promo.get("inputs", {})
    if promo_inputs:
        print("\n  PROMOTION -- Current Inputs (no Previous column)")
        for k, v in promo_inputs.items():
            print(f"    {k}: {v}")

    # Brands
    brands = data.get("brands", {})
    formulation = brands.get("formulation", {})
    if formulation:
        print("\n  BRAND FORMULATION -- Allround")
        for k, v in formulation.items():
            print(f"    {k}: {v}")

    if brands.get("reformulation_available"):
        choice_map = {"2": "Keep original", "1": "Drop alcohol", "0": "Switch to expectorant"}
        choice = brands.get("reformulation_choice", "?")
        print(f"  Reformulation choice: {choice} ({choice_map.get(str(choice), '?')})")
        options = brands.get("reformulation_options", [])
        if options:
            print("  Reformulation options:")
            for opt in options:
                marker = " [SELECTED]" if opt.get("checked") else ""
                disabled = " [DISABLED]" if opt.get("disabled") else ""
                print(f"    value={opt['value']}{marker}{disabled}: {opt.get('label', '')[:80]}")

    # Special
    special = data.get("special", {})
    if special:
        if special.get("has_inputs"):
            print(f"\n  SPECIAL PAGE -- Inputs: {special.get('inputs', {})}")
        else:
            print(f"\n  SPECIAL PAGE -- No inputs (text: {special.get('page_text', '')[:100]})")

    # Review
    review = data.get("review", {})
    budget_ov = review.get("budget_overview", {})
    if budget_ov:
        print("\n  REVIEW -- Budget Overview")
        print(f"  {'Item':<25} {'Previous':>12} {'Current':>12} {'Change':>10}")
        print(f"  {'-'*59}")
        for label, vals in budget_ov.items():
            prev = vals.get("previous", "")
            curr = vals.get("current", "")
            chg = vals.get("change", "")
            print(f"  {label:<25} {str(prev):>12} {str(curr):>12} {str(chg):>10}")

    alloc = review.get("allocation", {})
    if alloc:
        print("\n  REVIEW -- Allocation (%)")
        for label, vals in alloc.items():
            prev = vals.get("previous", "")
            curr = vals.get("current", "")
            chg = vals.get("change", "")
            print(f"    {label}: prev={prev}%, curr={curr}%, change={chg}%")

    rr = review.get("replay_restart", {})
    if rr:
        rep = rr.get("replays_remaining")
        res = rr.get("restarts_remaining")
        if rep is not None or res is not None:
            print(f"\n  Replays remaining: {rep}, Restarts remaining: {res}")

    print(f"\n{'='*60}\n")


# Keep backward-compatible alias
print_previous_summary = print_decision_summary


# ---------------------------------------------------------------------------
# Selenium runner
# ---------------------------------------------------------------------------

RUNS_DIR = Path(__file__).parent.parent / "runs"


def _wrap_async_for_selenium(async_js: str) -> str:
    """Wrap an async JS arrow function for Selenium execute_async_script.

    Selenium's execute_async_script passes a callback as the last argument.
    We invoke the async function, await its result, and call the callback.
    """
    return f"""
var callback = arguments[arguments.length - 1];
var fn = {async_js};
fn().then(function(result) {{
    callback(result);
}}).catch(function(err) {{
    callback({{error: err.message || String(err)}});
}});
"""


def scrape_decisions_selenium(
    period: int = 1,
    driver=None,
    output_path: str | Path | None = None,
    print_summary: bool = True,
) -> dict:
    """Run the full decision-page scrape via Selenium.

    Logs in, launches the sim, executes js_scrape_all_decisions(), saves
    results to JSON, and optionally prints a summary.

    IMPORTANT: NEVER clicks Advance, Replay, or Restart.

    Args:
        period: Period to scrape (0=Start, 1=Year1, 2=Year2).
        driver: Existing Selenium WebDriver to reuse. If None, creates one,
                logs in, launches sim, and quits when done.
        output_path: Where to save the JSON results. Defaults to
                     runs/decisions_periodN.json.
        print_summary: Whether to pretty-print the results.

    Returns:
        The scraped decision data dict.
    """
    from selenium.webdriver.support.ui import WebDriverWait

    owns_driver = driver is None

    if owns_driver:
        from src.scraper import create_driver, login_and_launch
        driver = create_driver()
        wait = WebDriverWait(driver, 20)
        login_and_launch(driver, wait)

    # Set a long script timeout — the JS navigates 7+ pages with delays
    driver.set_script_timeout(120)

    try:
        js = js_scrape_all_decisions(period=period)
        wrapped = _wrap_async_for_selenium(js)

        print(f"Scraping all decision pages for period {period}...")
        result = driver.execute_async_script(wrapped)

        if isinstance(result, dict) and "error" in result:
            raise RuntimeError(f"JS scrape failed: {result['error']}")

        # Save to JSON
        if output_path is None:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            output_path = RUNS_DIR / f"decisions_period{period}.json"
        else:
            output_path = Path(output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Saved decision data to {output_path}")

        if print_summary:
            print_decision_summary(result)

        return result

    finally:
        if owns_driver:
            driver.quit()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape PharmaSim decision pages"
    )
    parser.add_argument(
        "--periods", type=int, nargs="+", default=None,
        help="Period indices to scrape (e.g. 0 1 2). Default: 1"
    )
    parser.add_argument(
        "--page", type=str, default=None,
        choices=["sales_force", "pricing", "advertising", "promotion",
                 "brands", "special", "review"],
        help="Scrape only a specific decision page (default: all pages)"
    )
    parser.add_argument(
        "--js-only", action="store_true",
        help="Don't run Selenium — just print the JS to copy-paste or use with MCP"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output file path (default: runs/decisions_periodN.json)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output the JS as a JSON string (for programmatic use, implies --js-only)"
    )
    parser.add_argument(
        "--parse", type=str, default=None,
        help="Parse a JSON file of scraped results and print summary"
    )
    args = parser.parse_args()

    if args.parse:
        with open(args.parse) as f:
            data = json.load(f)
        print_decision_summary(data)
        return

    periods = args.periods if args.periods is not None else [1]

    if args.js_only or args.json:
        # JS-generation mode (for manual copy-paste or MCP)
        page_funcs = {
            "sales_force": js_scrape_sales_force,
            "pricing": js_scrape_pricing,
            "advertising": js_scrape_advertising,
            "promotion": js_scrape_promotion,
            "brands": js_scrape_brands,
            "special": js_scrape_special,
            "review": js_scrape_review,
        }

        if args.page:
            js = page_funcs[args.page]()
        else:
            js = js_scrape_all_decisions(period=periods[0])

        if args.json:
            print(json.dumps(js))
        else:
            print("// Copy this JS into Chrome DevTools MCP evaluate_script:")
            print("// The function navigates decision pages and returns all data.")
            print("// It does NOT click Advance/Replay/Restart.")
            print()
            print(js)
        return

    # Default: run via Selenium
    for period in periods:
        scrape_decisions_selenium(
            period=period,
            output_path=args.output,
        )


if __name__ == "__main__":
    main()
