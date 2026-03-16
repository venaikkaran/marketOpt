"""Year0 optimization workflow for the locked Y0 -> D0 -> Y1 loop.

This mirrors the Year1 optimizer, but keeps all artifacts under
``runs/year0_opt`` and uses the Start-period editable decision surface:

1. Capture a locked Start / Year0 state and current editable decisions.
2. Propose a constrained suggestion in the reduced search space.
3. Let the human edit the JSON.
4. Validate + register the edited suggestion before application.
5. After the human runs the sim, scrape Y1 and record the outcome.

IMPORTANT:
  - This routine assumes the simulator is currently at a live editable Start
    state. If Start is historical/read-only, session creation will fail fast.
  - This command never clicks Advance, Replay, or Restart.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import src.year1_optimizer as base

YEAR0_OPT_DIR = base.RUNS_DIR / "year0_opt"
YEAR0_LATEST_SESSION_PATH = YEAR0_OPT_DIR / "latest_session.txt"


@contextmanager
def _use_year0_paths():
    old_opt_dir = base.YEAR1_OPT_DIR
    old_latest = base.LATEST_SESSION_PATH
    base.YEAR1_OPT_DIR = YEAR0_OPT_DIR
    base.LATEST_SESSION_PATH = YEAR0_LATEST_SESSION_PATH
    try:
        yield
    finally:
        base.YEAR1_OPT_DIR = old_opt_dir
        base.LATEST_SESSION_PATH = old_latest


def create_session_from_existing(
    run_id: str,
    decisions_path: str | Path,
    *,
    requested_discount_max: float = 75.0,
    name: str | None = None,
) -> dict[str, Any]:
    with _use_year0_paths():
        return base.create_session_from_existing(
            run_id,
            decisions_path,
            requested_discount_max=requested_discount_max,
            name=name,
            state_year=0,
            decision_period=0,
            outcome_year=1,
        )


def capture_session(
    *,
    requested_discount_max: float = 75.0,
    name: str | None = None,
) -> dict[str, Any]:
    with _use_year0_paths():
        return base.capture_session(
            requested_discount_max=requested_discount_max,
            name=name,
            state_year=0,
            decision_period=0,
            outcome_year=1,
        )


def _prepare_guided_args(args) -> argparse.Namespace:
    if args.session:
        return args

    with _use_year0_paths():
        session = base._resolve_session_for_guided(
            args,
            state_year=0,
            decision_period=0,
            outcome_year=1,
        )
    prepared = argparse.Namespace(**vars(args))
    prepared.session = session["session_id"]
    prepared.capture = False
    prepared.run_id = None
    prepared.decisions = None
    return prepared


def guided_round(args) -> dict[str, Any]:
    with _use_year0_paths():
        return base.guided_round(_prepare_guided_args(args))


def main() -> None:
    parser = argparse.ArgumentParser(description="Year0 optimization workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create-session", help="Create a session from existing Year0 artifacts")
    create_parser.add_argument("--run-id", required=True, help="Existing run_id with year0_parsed.json")
    create_parser.add_argument("--decisions", required=True, help="Path to decisions_period0.json")
    create_parser.add_argument("--name", default=None, help="Optional session name")
    create_parser.add_argument("--discount-max", type=float, default=75.0, help="Requested upper discount bound")

    capture_parser = subparsers.add_parser("capture-session", help="Scrape Start/Year0 and create a session")
    capture_parser.add_argument("--name", default=None, help="Optional session name")
    capture_parser.add_argument("--discount-max", type=float, default=75.0, help="Requested upper discount bound")

    suggest_parser = subparsers.add_parser("suggest", help="Generate the next suggestion")
    suggest_parser.add_argument("--session", required=True, help="Session id")

    applied_parser = subparsers.add_parser("register-applied", help="Register the human-edited JSON and emit apply scripts")
    applied_parser.add_argument("--session", required=True, help="Session id")
    applied_parser.add_argument("--round", required=True, help="Round id")
    applied_parser.add_argument("--suggestion", required=True, help="Edited suggestion JSON path")

    outcome_parser = subparsers.add_parser("record-outcome", help="Record the Y1 outcome for a completed round")
    outcome_parser.add_argument("--session", required=True, help="Session id")
    outcome_parser.add_argument("--round", required=True, help="Round id")
    outcome_parser.add_argument("--scrape", action="store_true", help="Scrape Y1 with the existing pipeline")
    outcome_parser.add_argument("--run-id", default=None, help="Existing run_id containing Year1")

    guided_parser = subparsers.add_parser("guided-round", help="Run an end-to-end guided Year0 round")
    guided_parser.add_argument("--session", default=None, help="Existing session id")
    guided_parser.add_argument("--round", default=None, help="Existing round id")
    guided_parser.add_argument("--capture", action="store_true", help="Capture a fresh Year0 session first")
    guided_parser.add_argument("--run-id", default=None, help="Existing run_id for session creation")
    guided_parser.add_argument("--decisions", default=None, help="Existing decisions_period0.json for session creation")
    guided_parser.add_argument("--name", default=None, help="Optional session name when creating one")
    guided_parser.add_argument("--discount-max", type=float, default=75.0, help="Requested upper discount bound")
    guided_parser.add_argument("--suggestion", default=None, help="Use this suggestion path instead of the round default")
    guided_parser.add_argument("--accept-current", action="store_true", help="Skip the edit pause and use the current suggestion file as-is")
    guided_parser.add_argument("--apply-selenium", action="store_true", help="Apply the registered suggestion in a Selenium browser")
    guided_parser.add_argument("--scrape-outcome", action="store_true", help="After manual advance, scrape Year1 and record the outcome in the same command")
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
        with _use_year0_paths():
            round_record = base.suggest_round(args.session)
        print(f"Created round: {round_record['round_id']}")
        print(f"  Suggestion: {round_record['proposal_suggestion_path']}")
        print(f"  Plots: {round_record['plot_report_path']}")
        print(
            "  Prediction: "
            f"mean={base._format_num(round_record.get('predicted_objective_mean'), 4)}, "
            f"std={base._format_num(round_record.get('predicted_objective_std'), 4)}, "
            f"acquisition={base._format_num(round_record.get('acquisition_score'), 4)}"
        )
        base.print_suggestion_summary(round_record["proposal_suggestion"])
        return

    if args.command == "register-applied":
        with _use_year0_paths():
            round_record = base.register_applied(args.session, args.round, args.suggestion)
        print(f"Registered applied decision for {args.round}")
        print(f"  Applied suggestion: {round_record['applied_suggestion_path']}")
        print(f"  Apply scripts: {round_record['apply_scripts_path']}")
        print(f"  Human edited: {round_record['was_human_edited']}")
        return

    if args.command == "record-outcome":
        with _use_year0_paths():
            round_record = base.record_outcome(
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
        with _use_year0_paths():
            base.print_status(args.session)
        return


if __name__ == "__main__":
    main()
