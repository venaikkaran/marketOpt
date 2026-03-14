# CLAUDE.md

## ⚠️ MANDATORY: uv ONLY — NO EXCEPTIONS ⚠️

**ALL Python operations MUST use `uv`. This is non-negotiable.**

- `uv run` to execute scripts — NEVER bare `python`
- `uv add`/`uv remove` for deps — NEVER `pip`, `pip install`, `python -m pip`, `conda`, or ANY other package manager
- `uv sync` for env setup — NEVER create venvs manually
- `uv lock` to update lockfile

**VIOLATION OF THESE RULES IS A CRITICAL ERROR. ALWAYS USE UV.**

## Project

PharmaSim market simulation optimizer. Scrapes online business sim, parses results, builds decision/outcome history for optimization. Deps: openpyxl, selenium. Python 3.13.

We are developing an optimization framework for the PharmaSim simulator. 

At a high-level, the simulator is a stateful system - currently, there are three total states, and 2 decisions. So, we have financial results for "Start"/Year0, Year1, and Year2. Then, we have Decisions0 and Decisions1. Ultimately we want to write an optimizer that uses as few iterations as possible to optimize for some metrics. 

We have two ways of running Simulation in the webapp. Consider the following naming convention - we have Y0 -> D0 -> Y1 -> D1 -> Y2, where Yn are the years (states), and Dm are the decisions we pick. 
**Advance** - After selecting some simulation results at the current state, we want to lock in those and run tests. Running the tests is EXTREMELY EXPENSIVE - NEVER CLICK ON OR OTHERWISE ACCEPT OR MOVE ON WITH ADVANCE. 
**Replay** - Keep Y0 -> D0 -> Y1 LOCKED. Only retry D1 -> Y2. We have LIMITED replays. STRICTLY DO NOT CLICK **REPLAY** on your own or interact with it in any way, shape or form. This reverts back the run and is evaluation expensive. 
**Restart** - From scratch, do Y0 -> D0 -> Y1 -> D1 -> Y2. We have LIMITED restarts. STRICTLY DO NOT CLICK **RESTART** on your own or interact with it in any way, shape or form. This reverts back the run and is evaluation expensive. 

This means that sometimes, we can only run an evaluation from Year1 -> Decision1 -> Year2. Other times, we can run the whole routine i.e., Year0 -> Decision0 -> Year1 -> Decision1 -> Year2.

## The actual simulation engine 
You have the ability to play with the website yourself, if need be, using the Chrome Devtools mcp server/skill/plugin - simply use this mcp server/skill/plugin/tool and follow the steps. However, be EXTREMELY CAREFUL - DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY. DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY.
1) Go to www.interpretive.com/students
2) User Name: utda53727123
3) Password: CleverGoal2
4) Click Login
5) Go to "Simulation" tab and click "Launch Benchmark Simulation" -> this will open a new window with the actual simulation engine. 
6) On the absolute top are Start, Year 1 and 2. Year 2 may be currently greyed out which means we cant inspect it. You can select the year to review the data. The tab/menus (Company, Market, Consumer Survey) reflect the "state" of that year that we must assess and make decisions based on. Thus, if you select "Start" (year0), and navigate through Company/Market/Consumer Survey, you will see year0/state0. The decisions tab is where the user will make the choices i.e., decision0. So "Start"/year0 decisions tab is the decisions0. 
7) The "decisions" tab for a given year are the decisions made during that year given that years state, to influence the state of next year. YearN reports reflect the outcome of Decision(N-1), not DecisionN. DecisionN is made while viewing YearN and produces YearN+1. For the general case of Year0 -> Decision0 -> Year1 -> Decision1 -> Year2, when the scraper is on the start page/Year0, the information under company, market, and consumer survey is for year0. The decisions under the decisions tab is ALSO for year0. When the person manually runs these through the sim, we get the results in Year1 and the opportunity in the next round of decisions to be made in year1 (decisions1) to me made to influence year2. Study each and every file in this repo or mention and analysis and update this discrepancy.
8) Be EXTREMELY CAREFUL - DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY. DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY.

## Optimization Loop (Human-in-the-Loop)

```
Scrape State → Optimizer Suggests → Validate Constraints → Human Reviews → Apply to Sim → Human Advances → Scrape Outcome → repeat
```

1. **Scrape**: `pipeline.py` extracts Year N state (Company/Market/Consumer Survey)
2. **Suggest**: Optimizer (future) outputs a suggestion JSON to `suggestions/`
3. **Validate**: `load_suggestion()` checks ALL constraints from `constraints.py` — rejects if ANY fail, nothing touches the sim
4. **Review**: Human sees `print_suggestion_summary()`, edits JSON if needed
5. **Apply**: `decision_applier.py` sets values page-by-page via Chrome DevTools MCP, ends on Decision Summary
6. **Advance**: Human clicks Advance/Replay in browser (NEVER automated)
7. **Outcome**: Scrape Year N+1, log decision→outcome to `history.jsonl`

## Decision Applier Behavior

- PharmaSim blocks navigation on unsaved changes; Save triggers page reload destroying JS context
- Therefore apply ONE PAGE AT A TIME: navigate → set values → Save → wait for reload → next page
- `ui.menu.call(null, 'decisions', 'decisions/XXX', {})` for JS navigation (only works when no unsaved changes)
- `generate_page_scripts()` for sequential MCP execution; `generate_apply_js()` for single-shot

## Decision Constraints (from `src/constraints.py`)

### Per-field bounds
- **Sales Force** (8 fields): integers [0, 1000]
- **MSRP**: continuous [$1, $50]
- **Volume Discounts** (4 fields): continuous [10%, 50%]
- **Ad Budget**: continuous [0, budget-limited]
- **Ad Agency**: discrete {1, 2, 3}
- **Symptom/Demo/Benefit targets**: binary (checkbox)
- **Ad Message Mix** (4 fields): continuous [0, 100], **must sum to exactly 100%**
- **Comparison Target**: discrete {2..11} (brand IDs)
- **Allowances** (6 fields): continuous [10%, 20%]
- **Promo budgets** (coop, POP, trial, coupon): continuous [0, budget-limited]
- **Coupon Amount**: discrete {0, 1, 2, 3} ($0.25–$1.00)
- **Brand Reformulation**: discrete {0, 1, 2} (Year 1+ only)
- Total: 59 fields (20 continuous, 8 integer, 27 binary, 4 discrete)

### Cross-field constraints
- **Sum groups**: Ad message mix must sum to exactly 100% (server-enforced)
- **Ordering**: Volume discounts must be monotonically non-decreasing (server-enforced)
- **Conditional irrelevance**: Channel checkboxes are don't-care when their budget gate is $0
- **Equivalence groups**: All-checked = all-unchecked for symptom/demo targets (canonicalized to all-False)
- **Formulation-benefit consistency**: Reformulation choice restricts valid benefit claims
- **Budget ceiling**: Total spending vs. available budget (NOT server-enforced, but practically critical)

## Data Contracts

Three distinct data formats flow through the system. They use **different key names** for the same concepts.

### 1. Scraper Output → `DecisionVector` (read from sim results)
Extracted by `DecisionVector.from_year_data()` from parsed XLS reports. Reflects the decision that *produced* this year's results (YearN data reflects Decision(N-1)). Uses descriptive field names. Stored in `history.jsonl` under `"decision"`.

```json
{"msrp": 5.44, "media_expenditure": 20.0, "ad_agency": "BMW",
 "sf_direct_chain": 29.0, "promotional_allowance_pct": 0.187,
 "coop_advertising": 1400.0, "analgesic_mg": 1000.0, ...}
```
25 fields. Includes formulation (read-only except reformulation). Units vary: `media_expenditure` in millions, `coop_advertising` in thousands, `promotional_allowance_pct` as decimal.

### 2. Suggestion JSON → Applier Input (written to sim)
The format `decision_applier.py` accepts. Maps directly to HTML form fields. Uses short keys matching the `FIELD_MAP` in `decision_applier.py`. Validated against `constraints.py` before application.

```json
{"msrp": 5.44, "ad_budget": 18.0, "ad_agency": "1",
 "sf_chain": 29, "allowance_chain": 18.5,
 "coop_ad_budget": 1.4, "symptom_cold": true, ...}
```
59 fields. `ad_agency` is HTML value ("1"/"2"/"3"), not name. Budgets in millions. Allowances as percentages 10-20. Booleans for checkboxes.

### 3. Flattened State (optimizer features)
Produced by `flatten.py` from parsed `YearData`. Dot-notation keys covering all Company/Market/Consumer Survey reports. Used as optimizer input features.

```json
{"performance_summary.stock_price": 28.33,
 "performance_summary.net_income": 64.6,
 "brand_awareness.Allround.brand_awareness_pct": 78.2, ...}
```
~200+ numeric fields per year. `flatten_numeric_only()` filters to floats only.

### 4. History Log (`runs/history.jsonl`)
Each line is one decision→outcome pair:
```json
{"run_id": "run_001", "decision_index": 0, "source_year": 0, "outcome_year": 1,
 "decision": {DecisionVector dict}, "outcomes": {subset of flattened state}}
```
`decision_index` N means the decision made at Year N that produced Year N+1. Outcome metrics are the 7 key performance fields from `performance_summary`.

### Key Name Mapping (same concept, different names)

| Concept | DecisionVector | Suggestion JSON | HTML field |
|---------|---------------|-----------------|------------|
| Ad budget | `media_expenditure` | `ad_budget` | `ad_budget1` |
| Ad agency | `ad_agency` ("BMW") | `ad_agency` ("1") | `agency1` |
| Chain SF | `sf_direct_chain` | `sf_chain` | `sf2` |
| Co-op budget | `coop_advertising` (thousands) | `coop_ad_budget` (millions) | `coop_ad_budget1` |
| Allowance | `promotional_allowance_pct` (decimal) | `allowance_*` (percent) | `allowance1-*` |

**The optimizer must translate between DecisionVector (history) and Suggestion JSON (applier) formats.** These are intentionally different: DecisionVector is extracted from reports (backward-looking), Suggestion JSON maps to form fields (forward-looking).

## src/

- `pipeline.py` — Main entry point. Orchestrates scrape→parse→flatten→history. CLI: `--periods`, `--parse-only`
- `scraper.py` — Selenium login + XLS download from PharmaSim portal (~25 reports/period)
- `dom_scraper.py` — DOM-based scraper via JS eval. `DecisionInputMap` (63 fields), extracts editable decision inputs
- `parser.py` — Parses XLS into 46 dataclasses. `YearData` aggregates all reports for one year
- `decision.py` — `DecisionVector`: 25 controllable vars. `to_array`/`from_array` for optimizer
- `flatten.py` — Nested `YearData` → flat dot-notation dict. `flatten_numeric_only()` for optimization
- `run_store.py` — Run directory mgmt + JSONL history. `RunMetadata`, `create_run()`, `append_history()`
- `decision_applier.py` — Validates suggestion JSON against constraints, generates JS to apply decisions page-by-page via MCP
- `constraints.py` — All 59 decision variable constraints (bounds, types, sum groups). `validate_suggestion()`, `clamp_suggestion()`, `get_bounds()`

## Data

- `runs/run_NNN/` — `metadata.json` + `YearN_ReportName.xlsx`
- `runs/history.jsonl` — decision vectors + outcomes log
- `suggestions/` — Decision suggestion JSON files (optimizer output / manual)

## Entry Points

```
uv run python -m src.pipeline                              # full scrape + parse
uv run python -m src.pipeline --parse-only run_001         # parse existing run
uv run python -m src.decision_applier FILE.json            # validate + generate apply JS
uv run python -m src.decision_applier FILE.json --dry-run  # validate + print summary only
uv run python -m src.decision_applier --generate-example 1 # generate template for period 1
uv run python -m src.constraints                           # print all constraints
```
