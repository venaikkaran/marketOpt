"""
DOM-based scraper for PharmaSim simulator — REPORT sections only.

Extracts report data (Company, Market, Consumer Survey) directly from the
browser DOM using JavaScript evaluation, eliminating the need for xlsx
download/parse. Works with both Selenium (driver.execute_script) and Chrome
DevTools MCP (evaluate_script).

Decision-page scraping has been consolidated into ``decision_scraper.py``.

Extensible across Year0, Year1, and Year2.

Usage with Selenium:
    from src.dom_scraper import js_scrape_all_report_data
    data = driver.execute_script(js_scrape_all_report_data())

Usage with Chrome DevTools MCP:
    # Pass the JS string from js_scrape_all_report_data() to evaluate_script
"""

from __future__ import annotations

import json
import re
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
# Report sections with their menu paths (decisions excluded)
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
]

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
# JavaScript extraction functions for report sections
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
    Only scrapes Company, Market, and Consumer Survey sections.
    IMPORTANT: Does NOT click Advance/Replay/Restart.
    """
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


def js_scrape_period_reports() -> str:
    """JS that scrapes ALL report data for the current period.

    Returns {period, reports: {...}}.
    Decision inputs are NOT scraped here; use decision_scraper.py for that.
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

    return {{ period: period, reports: reports }};
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

    Takes the output of js_scrape_period_reports() and produces a flat dict
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

    return flat


# ---------------------------------------------------------------------------
# High-level orchestration (for use with Selenium driver)
# ---------------------------------------------------------------------------

def scrape_full_period_selenium(driver, period_index: int) -> dict:
    """Scrape all report data for a single period using Selenium.

    Args:
        driver: Selenium WebDriver instance.
        period_index: 0=Start/Year0, 1=Year1, 2=Year2.

    Returns:
        Dict with {period, reports} structure.
        Decision inputs are NOT included; use decision_scraper.py for that.
    """
    import time

    # Switch period
    driver.execute_script(f"""
        var links = document.querySelectorAll('a[onclick="app.periods.activate(this);"]');
        if (links[{period_index}]) links[{period_index}].click();
    """)
    time.sleep(2)

    # Execute the report scraper
    result = driver.execute_script(js_scrape_period_reports())
    return result


def scrape_all_periods_selenium(
    driver, periods: list[int] | None = None
) -> dict[int, dict]:
    """Scrape all report data for multiple periods using Selenium.

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
