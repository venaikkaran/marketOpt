"""
DOM-based scraper for PharmaSim simulator.

Extracts ALL data directly from the browser DOM using JavaScript evaluation,
eliminating the need for xlsx download/parse. Works with both Selenium
(driver.execute_script) and Chrome DevTools MCP (evaluate_script).

Extensible across Year0, Year1, and Year2.

Usage with Selenium:
    from src.dom_scraper import scrape_all_sections, scrape_period
    data = driver.execute_script(scrape_all_sections())

Usage with Chrome DevTools MCP:
    # Pass the JS string from scrape_all_sections() to evaluate_script
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# JavaScript helpers (shared across all extraction scripts)
# ---------------------------------------------------------------------------

_JS_HELPERS = """
function _parseNum(s) {
    if (s == null || s === '') return null;
    s = String(s).trim();
    // Handle $(X.X) negative format
    var neg = false;
    if (s.match(/^\\$?\\(/) && s.endsWith(')')) {
        neg = true;
        s = s.replace(/[\\$\\(\\)]/g, '');
    } else {
        s = s.replace(/^\\$/, '');
    }
    // Handle M suffix (millions)
    var mult = 1;
    if (s.endsWith('M')) { s = s.slice(0, -1); }
    // Handle % suffix
    s = s.replace(/%$/, '');
    // Remove commas
    s = s.replace(/,/g, '');
    var v = parseFloat(s);
    if (isNaN(v)) return null;
    return neg ? -v * mult : v * mult;
}

function _getVisibleTables() {
    var content = document.getElementById('content');
    if (!content) return [];
    var tables = content.querySelectorAll('table');
    var result = [];
    tables.forEach(function(table) {
        if (table.offsetParent === null) return;
        var rows = [];
        table.querySelectorAll('tr').forEach(function(tr) {
            if (tr.offsetParent === null) return;
            var cells = [];
            tr.querySelectorAll('td, th').forEach(function(cell) {
                var inp = cell.querySelector('input, select');
                cells.push({
                    text: cell.textContent.trim().replace(/\\s+/g, ' '),
                    inputName: inp ? inp.name : null,
                    inputValue: inp ? inp.value : null,
                    inputType: inp ? inp.type : null,
                    inputChecked: inp ? inp.checked : null
                });
            });
            if (cells.length > 0) rows.push(cells);
        });
        if (rows.length > 0) result.push(rows);
    });
    return result;
}

function _kvFromRows(rows) {
    // Convert label-value row pairs into a flat dict
    var out = {};
    rows.forEach(function(cells) {
        if (cells.length >= 2) {
            var label = cells[0].text;
            var val = cells[1].text;
            if (label && val) out[label] = val;
        }
    });
    return out;
}
"""

# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------

JS_SWITCH_PERIOD = """
(periodIndex) => {
    var links = document.querySelectorAll('a[onclick="app.periods.activate(this);"]');
    if (links[periodIndex]) {
        links[periodIndex].click();
    }
    return document.getElementById('cperiod') ? document.getElementById('cperiod').value : null;
}
"""

JS_GET_CURRENT_PERIOD = """
() => {
    var el = document.getElementById('cperiod');
    return el ? parseInt(el.value) : null;
}
"""

JS_NAVIGATE_SECTION = """
(parentMenu, sectionPath) => {
    ui.menu.call(null, parentMenu, sectionPath, {});
    return true;
}
"""

# ---------------------------------------------------------------------------
# All sections with their menu paths
# ---------------------------------------------------------------------------

# (parent_menu, section_path, friendly_name, category)
ALL_SECTIONS = [
    # Company
    ("company", "company/dashboard", "dashboard", "company"),
    ("company", "company/performance", "performance_summary", "company"),
    ("company", "company/income", "income_statement", "company"),
    ("company", "company/prod_contrib", "product_contribution", "company"),
    ("company", "company/sales", "sales_report", "company"),
    ("company", "company/promotion", "promotion_report", "company"),
    ("company", "company/portfolio", "portfolio_graph", "company"),
    # Market
    ("market", "market/outlook", "industry_outlook", "market"),
    ("market", "market/symptoms", "symptoms_reported", "market"),
    ("market", "market/formulations", "brand_formulations", "market"),
    ("market", "market/sales", "manufacturer_sales", "market"),
    ("market", "research/operating_stats", "operating_statistics", "market"),
    ("market", "research/sales_force", "sales_force", "market"),
    ("market", "research/advertising", "advertising", "market"),
    ("market", "research/promotion", "promotion", "market"),
    ("market", "research/channel_sales", "channel_sales", "market"),
    ("market", "research/pricing", "pricing", "market"),
    ("market", "research/shopping_habits", "shopping_habits", "market"),
    ("market", "research/shelf_space", "shelf_space", "market"),
    ("market", "research/recommendations", "recommendations", "market"),
    # Consumer Survey
    ("survey", "research/conjoint", "conjoint_analysis", "survey"),
    ("survey", "survey/brands_purchased", "brands_purchased", "survey"),
    ("survey", "survey/intentions", "purchase_intentions", "survey"),
    ("survey", "survey/satisfaction", "satisfaction", "survey"),
    ("survey", "survey/awareness", "brand_awareness", "survey"),
    ("survey", "survey/criteria", "decision_criteria", "survey"),
    ("survey", "survey/perceptions", "brand_perceptions", "survey"),
    ("survey", "survey/tradeoffs", "trade_offs", "survey"),
    # Decisions (read-only observation of current settings)
    ("decisions", "decisions/sales_force", "decisions_sales_force", "decisions"),
    ("decisions", "decisions/brands", "decisions_brands", "decisions"),
    ("decisions", "decisions/pricing", "decisions_pricing", "decisions"),
    ("decisions", "decisions/advertising", "decisions_advertising", "decisions"),
    ("decisions", "decisions/promotion", "decisions_promotion", "decisions"),
    ("decisions", "decisions/special", "decisions_special", "decisions"),
    ("decisions", "decisions/review", "decisions_summary", "decisions"),
]

# Sections that have tabbed sub-views (need special handling)
TABBED_SECTIONS = {
    "decisions/brands": ["Overview", "Reformulation"],
}

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
    #   value "1" = Drop alcohol (alcohol → 0, unit cost $1.00)
    #   value "0" = Switch from cough suppressant to expectorant
    #               (cough_supp → 0, expectorant → 200, unit cost $1.11)
    # Only available in Years 1 and 2.
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
    msg_comparison_target: str = "compare_target1"  # <select> — use COMPARISON_TARGETS dict
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

# Sections that have sub-tabs/views exposing additional data.
# The scraper must click these to capture complete data.
SECTIONS_WITH_SUBTABS = {
    "company/prod_contrib": ["View per-unit values."],
    "market/sales": ["View manufacturer sales in dollars"],
    "research/operating_stats": ["Retail Sales", "Manufacturer Sales"],
    "research/sales_force": ["View as percent of total salespeople"],
    "research/channel_sales": [
        # Per-brand discount detail tabs
        "Allround", "Believe", "Besthelp", "Coldcure", "Coughcure",
        "Defogg", "Dripstop", "Dryup", "Effective", "End", "Extra",
        # Market share view
        "View market share based on retail sales",
    ],
}

# ---------------------------------------------------------------------------
# Period-dependent input availability
# ---------------------------------------------------------------------------
# At Start (period 0), decisions have ALREADY been submitted to produce Year 1
# results. Most decision pages are READ-ONLY at Start. Only a subset of
# advertising inputs remain editable.
#
# At Year 1 (period 1) and beyond, ALL 63 decision inputs are editable.
#
# Verified 2026-03-14 by exhaustive DOM audit:
#
# Period 0 (Start) — 20 editable inputs:
#   Advertising only: agency1 (3 radios), illness1[] (3 checkboxes),
#   demo1[] (5 checkboxes), benefit1[] (9 checkboxes)
#   NOT editable: ad_budget1, primary_msg1, benefit_msg1, compare_msg1,
#   compare_target1, reminder_msg1, ALL sales force, ALL pricing,
#   ALL promotion, brands reformulation
#
# Period 1+ (Year 1, Year 2) — 63 editable inputs:
#   Sales Force: 8  (sf1–sf8)
#   Pricing: 5  (msrp1, disc1-1 to disc1-4)
#   Advertising: 26  (ad_budget1, agency1×3, illness1[]×3, demo1[]×5,
#     primary_msg1, benefit_msg1, compare_msg1, compare_target1,
#     reminder_msg1, benefit1[]×9)
#   Promotion: 21  (allowance1-1 to 1-6, coop_ad_budget1, coop_ad1-1 to 1-5,
#     display_budget1, display_ad1-1 to 1-5, trial_budget1, coupon_budget1,
#     coupon_amt1)
#   Brands Reformulation: 3  (choice radio: "2"=keep, "1"=drop alcohol,
#     "0"=switch to expectorant) — only Years 1 and 2
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
    # Year 2 expected same as Year 1 (63 inputs)
    2: None,  # same as period 1
}


# ---------------------------------------------------------------------------
# JavaScript extraction functions for each section
# ---------------------------------------------------------------------------

def js_extract_generic_tables() -> str:
    """JS to extract all visible tables as structured data."""
    return f"""
() => {{
    {_JS_HELPERS}
    return _getVisibleTables();
}}
"""


def js_extract_section_data() -> str:
    """JS to extract structured data from any currently loaded section.

    Returns {section_title, tables: [[rows]], inputs: [...]}
    """
    return f"""
() => {{
    {_JS_HELPERS}

    var content = document.getElementById('content');
    if (!content) return null;

    // Get section title
    var titleEl = content.querySelector('h1, h2, .page-title');
    var title = titleEl ? titleEl.textContent.trim() : '';

    // Get all visible tables with clean row data
    var tables = _getVisibleTables();

    // Get all visible input elements
    var inputEls = content.querySelectorAll('input:not([type="hidden"]), select, textarea');
    var inputs = [];
    inputEls.forEach(function(inp) {{
        if (inp.offsetParent === null) return;
        var row = inp.closest('tr');
        var label = '';
        if (row) {{
            var firstTd = row.querySelector('td:first-child');
            if (firstTd && !firstTd.querySelector('input'))
                label = firstTd.textContent.trim().replace(/\\s+/g, ' ');
        }}
        var entry = {{
            tag: inp.tagName,
            type: inp.type || '',
            name: inp.name || '',
            id: inp.id || '',
            value: inp.value
        }};
        if (inp.type === 'checkbox' || inp.type === 'radio')
            entry.checked = inp.checked;
        if (inp.tagName === 'SELECT')
            entry.selectedText = inp.options[inp.selectedIndex]
                ? inp.options[inp.selectedIndex].text : '';
        entry.label = label;
        inputs.push(entry);
    }});

    return {{ title: title, tables: tables, inputs: inputs }};
}}
"""


def js_scrape_all_report_data() -> str:
    """JS that navigates to ALL report sections and extracts all data.

    Returns a dict keyed by section name with table data.
    IMPORTANT: Does NOT click Advance/Replay/Restart.
    """
    # Build the section navigation list (excluding decisions for safety)
    report_sections = [
        s for s in ALL_SECTIONS
        if s[3] in ("company", "market", "survey")
    ]

    section_list_js = json.dumps([
        {"parent": s[0], "path": s[1], "name": s[2]}
        for s in report_sections
    ])

    return f"""
async () => {{
    {_JS_HELPERS}

    var sections = {section_list_js};
    var results = {{}};

    for (var i = 0; i < sections.length; i++) {{
        var sec = sections[i];
        ui.menu.call(null, sec.parent, sec.path, {{}});
        await new Promise(function(r) {{ setTimeout(r, 1500); }});

        var tables = _getVisibleTables();
        var cleanTables = [];
        tables.forEach(function(rows) {{
            var cleanRows = [];
            rows.forEach(function(cells) {{
                var cleanCells = [];
                cells.forEach(function(c) {{
                    cleanCells.push({{
                        text: c.text,
                        value: _parseNum(c.text)
                    }});
                }});
                // Skip rows that are just whitespace
                if (cleanCells.some(function(c) {{ return c.text !== ''; }}))
                    cleanRows.push(cleanCells);
            }});
            if (cleanRows.length > 0) cleanTables.push(cleanRows);
        }});

        results[sec.name] = cleanTables;
    }}

    return results;
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


def js_scrape_period_data() -> str:
    """JS that scrapes ALL report data + decision inputs for the current period.

    Returns {period, reports: {...}, decisions: {...}}.
    IMPORTANT: Does NOT click Advance/Replay/Restart.
    """
    return f"""
async () => {{
    {_JS_HELPERS}

    var period = document.getElementById('cperiod')
        ? parseInt(document.getElementById('cperiod').value)
        : null;

    // --- Scrape all report sections ---
    var reportSections = {json.dumps([
        {"parent": s[0], "path": s[1], "name": s[2]}
        for s in ALL_SECTIONS if s[3] in ("company", "market", "survey")
    ])};

    var reports = {{}};
    for (var i = 0; i < reportSections.length; i++) {{
        var sec = reportSections[i];
        ui.menu.call(null, sec.parent, sec.path, {{}});
        await new Promise(function(r) {{ setTimeout(r, 1500); }});

        var tables = _getVisibleTables();
        var parsed = [];
        tables.forEach(function(rows) {{
            var pRows = [];
            rows.forEach(function(cells) {{
                var pCells = cells.map(function(c) {{
                    return {{ t: c.text, v: _parseNum(c.text) }};
                }});
                if (pCells.some(function(c) {{ return c.t !== ''; }}))
                    pRows.push(pCells);
            }});
            if (pRows.length > 0) parsed.push(pRows);
        }});
        reports[sec.name] = parsed;
    }}

    // --- Scrape decision inputs ---
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

    var decisions = {{}};

    var decisionPages = [
        ['decisions', 'decisions/sales_force'],
        ['decisions', 'decisions/pricing'],
        ['decisions', 'decisions/advertising'],
        ['decisions', 'decisions/promotion']
    ];

    for (var d = 0; d < decisionPages.length; d++) {{
        ui.menu.call(null, decisionPages[d][0], decisionPages[d][1], {{}});
        await new Promise(function(r) {{ setTimeout(r, 1500); }});
        Object.assign(decisions, getInputs());
    }}

    // Brands reformulation
    ui.menu.call(null, 'decisions', 'decisions/brands', {{}});
    await new Promise(function(r) {{ setTimeout(r, 1500); }});
    var reformTab = Array.from(document.querySelectorAll('a, button')).find(
        function(el) {{ return el.textContent.trim() === 'Reformulation' && el.offsetParent !== null; }}
    );
    if (reformTab) {{
        reformTab.click();
        await new Promise(function(r) {{ setTimeout(r, 1000); }});
        Object.assign(decisions, getInputs());
    }}

    return {{ period: period, reports: reports, decisions: decisions }};
}}
"""


# ---------------------------------------------------------------------------
# Python-side data extraction from raw JS results
# ---------------------------------------------------------------------------

def parse_num(s: str | None) -> float | None:
    """Parse a PharmaSim formatted number string to float."""
    if s is None or s == "":
        return None
    s = str(s).strip()
    neg = False
    if s.startswith("$(") and s.endswith(")"):
        neg = True
        s = s.replace("$", "").replace("(", "").replace(")", "")
    elif s.startswith("$"):
        s = s[1:]
    s = s.replace("%", "").replace(",", "")
    if s.endswith("M"):
        s = s[:-1]
    try:
        v = float(s)
        return -v if neg else v
    except (ValueError, TypeError):
        return None


def extract_kv_from_table(table_rows: list[list[dict]]) -> dict[str, str]:
    """Extract key-value pairs from table rows where col0=label, col1+=values."""
    result = {}
    for row in table_rows:
        if len(row) >= 2:
            label = row[0].get("text", "").strip() if isinstance(row[0], dict) else str(row[0])
            if label:
                values = []
                for cell in row[1:]:
                    text = cell.get("text", "") if isinstance(cell, dict) else str(cell)
                    if text:
                        values.append(text)
                if values:
                    result[label] = values[0] if len(values) == 1 else values
    return result


def flatten_scraped_data(
    period_data: dict,
) -> dict[str, float | str | None]:
    """Flatten raw scraped period data into dot-notation keyed dict.

    Takes the output of js_scrape_period_data() and produces a flat dict
    like {'performance_summary.stock_price': 28.33, ...}.
    """
    flat: dict[str, float | str | None] = {}
    period = period_data.get("period")
    flat["period"] = period

    reports = period_data.get("reports", {})
    for section_name, tables in reports.items():
        for tidx, table in enumerate(tables):
            for ridx, row in enumerate(table):
                for cidx, cell in enumerate(row):
                    text = cell.get("t", "") if isinstance(cell, dict) else ""
                    val = cell.get("v") if isinstance(cell, dict) else None
                    if val is not None:
                        key = f"{section_name}.table{tidx}.row{ridx}.col{cidx}"
                        flat[key] = val

    decisions = period_data.get("decisions", {})
    for inp_name, inp_val in decisions.items():
        flat[f"decisions.{inp_name}"] = inp_val

    return flat


# ---------------------------------------------------------------------------
# High-level orchestration (for use with Selenium driver)
# ---------------------------------------------------------------------------

def scrape_full_period_selenium(driver, period_index: int) -> dict:
    """Scrape all data for a single period using Selenium.

    Args:
        driver: Selenium WebDriver instance.
        period_index: 0=Start/Year0, 1=Year1, 2=Year2.

    Returns:
        Dict with {period, reports, decisions} structure.
    """
    import time

    # Switch period
    driver.execute_script(f"""
        var links = document.querySelectorAll('a[onclick="app.periods.activate(this);"]');
        if (links[{period_index}]) links[{period_index}].click();
    """)
    time.sleep(2)

    # Execute the comprehensive scraper
    result = driver.execute_script(js_scrape_period_data())
    return result


def scrape_all_periods_selenium(
    driver, periods: list[int] | None = None
) -> dict[int, dict]:
    """Scrape all data for multiple periods using Selenium.

    Args:
        driver: Selenium WebDriver instance.
        periods: List of period indices. Defaults to [0, 1].

    Returns:
        Dict mapping period index to scraped data.
    """
    if periods is None:
        periods = [0, 1]
    results = {}
    for p in periods:
        results[p] = scrape_full_period_selenium(driver, p)
    return results
