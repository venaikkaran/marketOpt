# Human-in-the-Loop Optimization Architecture

## Problem Shape

PharmaSim is a two-stage decision process:

- `Y0`, `Y1`, and `Y2` are the simulator states/years.
- The `Decisions` menu is not a separate state. It is where the human enters
  the decision for the current state.
- While at `Y0`/Start, the human enters the decision that drives `Y0 -> Y1`.
- While at `Y1`, the human enters the decision that drives `Y1 -> Y2`.
- `Y0 --D0--> Y1 --D1--> Y2`
- `D0` can only be tested via a scarce full-chain run.
- `D1` can be tested more often via a scarce-but-less-expensive half-chain replay from a fixed `Y1`.

The optimization target lives in `Y2`, but `Y2` depends on both:

- the upstream transition `T0(Y0, D0) -> Y1`
- the downstream transition `T1(Y1, D1) -> Y2`

This means the system should not store data as a flat `decision -> final outcome` log.
It should store **transitions** and **context**.

## Why The Current Repo Is Close But Not Enough

Existing primitives:

- `src/parser.py` parses rich `YearData` for each year.
- `src/flatten.py` converts `YearData` into flat numeric features.
- `src/dom_scraper.py` can safely read report data and editable decision inputs without touching `Advance`, `Replay`, or `Restart`.
- `src/run_store.py` stores runs and a basic history log.

Current gaps:

- `src/run_store.py` now stores `decisions` (keyed by `d0`, `d1`) in metadata, and `decision_index`, `source_year`, `outcome_year` in history entries. ~~Previously it stored only a flat `decision` and `outcomes` with no source state.~~
- `src/pipeline.py` appends one history entry per parse, which makes re-parsing non-idempotent.
- `src/decision.py` models 25 numeric fields plus `ad_agency`, but `src/dom_scraper.py` documents 63 editable inputs at `Y1+`.
- one repo comment in `src/dom_scraper.py` appears to describe a specific
  audited Start-period UI condition; that should not be treated as the
  authoritative simulator semantics without re-verification in your actual flow.
- the current history format does not distinguish:
  - `D0` vs `D1`
  - full-chain vs half-chain
  - proposed decision vs human-edited final decision
  - parent/child lineage between a replayed `Y1` context and its resulting `Y2`

## Core Design Principle

Treat the simulator as a dataset of linked transitions:

- Stage 0 transition: `(state_y0, decision_entered_while_at_y0) -> state_y1`
- Stage 1 transition: `(state_y1, decision_entered_while_at_y1) -> state_y2`

Equivalently:

- `D0` is the decision staged from the `Decisions` menu while viewing `Y0`
- `D1` is the decision staged from the `Decisions` menu while viewing `Y1`

Then learn:

- a downstream value model `f1(state_y1, d1) -> y2_metrics`
- an upstream transition model `g0(state_y0, d0) -> state_y1`
- an induced value function `V(state_y1) = max_d1 f1(state_y1, d1)`

The scarce full-chain problem becomes:

- choose `D0` that produces a `Y1` with high `V(Y1)`

The cheaper half-chain problem becomes:

- given fixed `Y1`, choose the best `D1`

## Recommended Data Model

Use five record types.

### 1. `StateSnapshot`

Represents one captured page state (`Y0`, `Y1`, or `Y2`).

Fields:

- `state_id`
- `period_index`
- `state_role`: `y0 | y1 | y2`
- `chain_type`: `full | half`
- `source_run_id`
- `parent_state_id` (optional)
- `raw_reports_path` or embedded DOM/XLS payload reference
- `flat_state`
- `selected_state_features`
- `state_fingerprint`
- `captured_at`

### 2. `DecisionProposal`

Represents what the optimizer suggested before the human touched the UI.

Fields:

- `proposal_id`
- `state_id`
- `decision_stage`: `d0 | d1`
- `candidate_rank`
- `proposed_decision`
- `predicted_objective_mean`
- `predicted_objective_std`
- `acquisition_score`
- `rationale`
- `optimizer_version`
- `created_at`

### 3. `DecisionExecution`

Represents what the human actually staged in the UI before clicking `Advance`.

Fields:

- `execution_id`
- `state_id`
- `decision_stage`
- `proposal_id` (nullable)
- `actual_decision`
- `was_edited_by_human`
- `human_notes`
- `captured_at`

### 4. `TransitionRecord`

Represents one expensive outcome-producing transition.

Fields:

- `transition_id`
- `decision_stage`: `d0 | d1`
- `chain_type`: `full | half`
- `pre_state_id`
- `execution_id`
- `post_state_id`
- `objective_value`
- `objective_components`
- `status`
- `created_at`

### 5. `Episode`

Groups a full-chain attempt.

Fields:

- `episode_id`
- `root_state_id`
- `d0_transition_id` (optional until completed)
- `d1_transition_id` (optional until completed)
- `status`
- `human_notes`

## Safe Human-in-the-Loop Workflow

The optimizer must never submit actions directly. It should only recommend and capture.

### Half-Chain Loop (`Y1 -> D1 -> Y2`)

1. Capture the current locked `Y1` state with the DOM scraper.
2. Compute a state fingerprint and create a `StateSnapshot`.
3. Generate top `K` `D1` candidates.
4. Show the candidates with:
   - expected objective
   - uncertainty
   - nearest historical analogs
   - constraint warnings
5. Human selects one candidate or edits it manually in the web UI.
6. Before the human clicks `Advance`, scrape decision inputs again and store `DecisionExecution`.
7. Human manually clicks `Advance`.
8. Once `Y2` is visible, capture the resulting state and create a `TransitionRecord`.

### Full-Chain Loop (`Y0 -> D0 -> Y1 -> D1 -> Y2`)

1. Capture `Y0`.
2. Suggest the decision to be entered from the `Decisions` menu while at `Y0`.
3. Human applies one candidate.
4. Capture actual staged `D0`.
5. Human manually clicks `Advance`.
6. Capture resulting `Y1`.
7. Suggest the decision to be entered from the `Decisions` menu while at `Y1`, using the downstream model conditioned on the actual `Y1`.
8. Human applies or edits `D1`.
9. Capture actual staged `D1`.
10. Human manually clicks `Advance`.
11. Capture `Y2`.
12. Store two linked transitions:
    - `(Y0, D0) -> Y1`
    - `(Y1, D1) -> Y2`

## What To Optimize First

Do **not** start with all 63 editable inputs.

Start with a smaller decision subspace that is:

- high-impact
- mostly continuous
- easy for a human to review

Recommended first-pass decision space:

- `msrp`
- `ad_budget`
- message mix percentages
- major sales-force allocations
- promotional allowance
- co-op ad budget
- point-of-purchase budget
- coupon budget / amount

Keep these fixed initially:

- symptom targeting checkboxes
- demographic targeting checkboxes
- benefit checkboxes
- comparison target
- reformulation choice
- all channel-specific participation toggles

Those discrete/categorical controls can be added later once the logging loop is stable.

## State Features For The Model

Do not feed all ~1400 numeric features directly into a Gaussian process at the start.

Begin with a curated state vector of roughly 30 to 80 features:

- performance summary metrics
- focal-brand awareness, purchase intention, satisfaction, shelf space
- focal-brand price/promo position
- major channel sales and sales-force distribution
- category outlook / shopping habits / decision criteria
- top competitor summary features

Store the full flat state anyway, but train on a curated subset first.

## Modeling Strategy

### Stage 1: Learn `f1(Y1, D1) -> Y2`

This should be the main data collection engine because half-chain runs are less scarce.

Practical recommendation:

- treat `Y1` as context
- train a surrogate for the scalar objective and a few key secondary metrics
- use acquisition over `D1` conditioned on the current `Y1`

If the active decision space stays modest, a Bayesian surrogate is reasonable.
If the decision/state space grows, switch to an ensemble-based surrogate with calibrated uncertainty.

### Stage 0: Learn `g0(Y0, D0) -> Y1`

This model will be data-poor, so keep it simple:

- predict a small curated `Y1` feature vector, not the full state
- or directly predict `V(Y1)` if full-chain sample count stays very small

With very limited full-chain budget, the outer loop should focus on:

- exploration of qualitatively different `D0` regions
- only a few high-confidence `D0` candidates

### Decision-Theoretic View

The right outer-loop target is not:

- "find `D0` that directly predicts good `Y2`"

It is:

- "find `D0` that creates a `Y1` from which a strong `D1` exists"

That is why the downstream model should be built first.

## Objective Design

Define one scalar optimization target before collecting serious data.

Example:

- maximize weighted score from:
  - `Y2.net_income`
  - `Y2.stock_price`
  - `Y2.market_share`
- with penalties for:
  - invalid or extreme decisions
  - undesirable side effects
  - budget overruns

Also log raw components separately so you can re-score historical runs later.

## Recommended Glue Logic

Add the following modules:

- `src/state_features.py`
  - curated feature extraction
  - state fingerprinting
- `src/experiment_store.py`
  - append/load for `StateSnapshot`, `DecisionProposal`, `DecisionExecution`, `TransitionRecord`, `Episode`
- `src/recommender.py`
  - candidate generation
  - acquisition scoring
  - constraint validation
- `src/session_cli.py`
  - safe CLI flow:
    - `capture-state`
    - `suggest`
    - `capture-decision`
    - `record-outcome`

## Operational Recommendation

Prefer DOM capture for the human-in-the-loop loop:

- it is faster than XLS download/parse
- it captures editable decision inputs directly
- it avoids the ambiguity of inferring staged decisions from report outputs

Use XLS capture as an audit/archive path, not as the primary live-loop interface.

## Immediate Backlog

1. Make the data model transition-based instead of decision/outcome-only.
2. Add explicit `decision_stage` and `chain_type` to every logged record.
3. Add state fingerprinting so all half-chain replays against the same locked `Y1` can be grouped.
4. Split "optimizer proposal" from "human executed decision".
5. Build a small curated state feature set before attempting Bayesian optimization.
6. Start optimization on a reduced decision subspace, not all 63 inputs.
7. Make parse/history ingestion idempotent.
