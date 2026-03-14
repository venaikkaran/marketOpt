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

## The actualy simulation engine 
You have the ability to play with the website yourself, if need be, using the Chrome Devtools mcp server/skill/plugin - simply use this mcp server/skill/plugin/tool and follow the steps. However, be EXTREMELY CAREFUL - DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY. DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY.
1) Go to www.interpretive.com/students
2) User Name: utda53727123
3) Password: CleverGoal2
4) Click Login
5) Go to "Simulation" tab and click "Launch Benchmark Simulation" -> this will open a new window with the actual simulation engine. 
6) On the absolute top are Start, Year 1 and 2. Year 2 may be currently greyed out which means we cant inspect it. You can select the year to review the data. The tab/menus (Company, Market, Consumer Survey) reflect the "state" of that year that we must assess and make decisions based on. Thus, if you select "Start" (year0), and navigate through Company/Market/Consumer Survey, you will see year0/state0. The decisions tab is where the user will make the choices i.e., decision0. So "Start"/year0 decisions tab is the decisions0. 
7) The "decisions" tab for a given year are the decisions made during that year given that years state, to influence the state of next year. YearN reports reflect the outcome of Decision(N-1), not DecisionN. DecisionN is made while viewing YearN and produces YearN+1. For the general case of Year0 -> Decision0 -> Year1 -> Decision1 -> Year2, when the scraper is on the start page/Year0, the information under company, market, and consumer survey is for year0. The decisions under the decisions tab is ALSO for year0. When the person manually runs these through the sim, we get the results in Year1 and the opportunity in the next round of decisions to be made in year1 (decisions1) to me made to influence year2. Study each and every file in this repo or mention and analysis and update this discrepancy.
8) Be EXTREMELY CAREFUL - DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY. DO NOT CLICK THE "ADVANCE", "REPLAY - XXX left in period", and "RESTART - 89 LEFT" buttons. Again, strictly do NOT press/click/touch ANY of these buttons or interact with them in ANY WAY.

## src/

- `pipeline.py` — Main entry point. Orchestrates scrape→parse→flatten→history. CLI: `--periods`, `--parse-only`
- `scraper.py` — Selenium login + XLS download from PharmaSim portal (~25 reports/period)
- `dom_scraper.py` — Faster DOM-based scraper via JS eval. `DecisionInputMap` (63 fields), also extracts editable decision inputs
- `parser.py` — Parses XLS into 46 dataclasses. `YearData` aggregates all reports for one year
- `decision.py` — `DecisionVector`: 25 controllable vars (price, formulation, ads, sales force, promos). `to_array`/`from_array` for optimizer
- `flatten.py` — Nested `YearData` → flat dot-notation dict. `flatten_numeric_only()` for ML/optimization
- `run_store.py` — Run directory mgmt + JSONL history. `RunMetadata`, `create_run()`, `append_history()`

## Data

- `runs/run_NNN/` — `metadata.json` + `YearN_ReportName.xlsx`
- `runs/history.jsonl` — decision vectors + outcomes log

## Entry Points

```
uv run python -m src.pipeline              # full scrape + parse
uv run python -m src.pipeline --parse-only run_001
uv run python -m src.scraper               # standalone scrape
uv run python -m src.parser                # debug: print parsed summary
```
