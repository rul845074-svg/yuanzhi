#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
GENERATOR_PATH = Path(__file__).resolve().with_name("generate_cognitive_workbench_data.py")


def load_generator_module():
    spec = importlib.util.spec_from_file_location("growth_console_data", GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def expect_keys(payload: dict[str, Any], keys: list[str], label: str) -> list[str]:
    missing = [key for key in keys if key not in payload]
    if not missing:
        return []
    return [f"{label} missing keys: {', '.join(missing)}"]


def load_json(path: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, [f"{label} not found: {path}"]
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except json.JSONDecodeError as exc:
        return None, [f"{label} is not valid JSON: {exc}"]


def main() -> int:
    module = load_generator_module()
    parser = argparse.ArgumentParser(description="Run a smoke test for the cognitive backend flow.")
    parser.add_argument(
        "--profile",
        choices=module.get_available_profiles(),
        help="Config profile to use. Defaults to the generator default.",
    )
    args = parser.parse_args()

    payload = module.build_payload(args.profile)
    errors: list[str] = []

    errors.extend(
        expect_keys(
            payload,
            ["generated_at", "profile", "artifact_paths", "pages", "state", "report_index", "reminders", "suggestion_index"],
            "payload",
        )
    )
    errors.extend(expect_keys(payload["artifact_paths"], ["cognitive_state", "report_index", "reminders", "suggestion_index"], "artifact_paths"))
    errors.extend(
        expect_keys(
            payload["pages"],
            ["home", "daily_report", "tenday_report", "monthly_report"],
            "pages",
        )
    )
    errors.extend(
        expect_keys(
            payload["pages"]["home"],
            [
                "page_type",
                "last_updated",
                "patterns",
                "belief_migrations",
                "capabilities",
                "verified_mechanisms",
                "library_stats",
                "active_reminders",
            ],
            "home",
        )
    )
    errors.extend(
        expect_keys(
            payload["pages"]["daily_report"],
            ["page_type", "date", "title", "season_window", "mystic_focus", "psychology_analysis", "cbt_event_analysis", "physics_mirror", "daily_actions", "term_heatmap"],
            "daily_report",
        )
    )
    errors.extend(
        expect_keys(
            payload["pages"]["tenday_report"],
            ["page_type", "title", "range", "emotion_bars", "action_bars", "phase_segments", "capability_heatmap", "physics_explanations", "tracking_patterns"],
            "tenday_report",
        )
    )
    errors.extend(
        expect_keys(
            payload["pages"]["monthly_report"],
            ["page_type", "month", "title", "panorama_cards", "active_patterns", "open_topics"],
            "monthly_report",
        )
    )

    cognitive_state_path = Path(payload["artifact_paths"]["cognitive_state"])
    report_index_path = Path(payload["artifact_paths"]["report_index"])
    reminders_path = Path(payload["artifact_paths"]["reminders"])
    suggestion_index_path = Path(payload["artifact_paths"]["suggestion_index"])
    cognitive_state, cognitive_errors = load_json(cognitive_state_path, "cognitive_state")
    report_index, report_errors = load_json(report_index_path, "report_index")
    reminders, reminder_errors = load_json(reminders_path, "reminders")
    suggestion_index, suggestion_errors = load_json(suggestion_index_path, "suggestion_index")
    errors.extend(cognitive_errors)
    errors.extend(report_errors)
    errors.extend(reminder_errors)
    errors.extend(suggestion_errors)

    if cognitive_state:
        errors.extend(expect_keys(cognitive_state, ["meta", "patterns", "beliefs", "metrics"], "cognitive_state"))
    if report_index:
        errors.extend(expect_keys(report_index, ["generated_at", "items"], "report_index"))
        if not isinstance(report_index.get("items"), list):
            errors.append("report_index.items must be a list")
    if reminders:
        errors.extend(expect_keys(reminders, ["generated_at", "items"], "reminders"))
    if suggestion_index:
        errors.extend(expect_keys(suggestion_index, ["generated_at", "items"], "suggestion_index"))

    if errors:
        print("Backend smoke test failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Backend smoke test passed.")
    print(f"Profile: {payload['profile']}")
    print(f"Vault root: {payload['vault_root']}")
    report_types = {}
    for item in payload["report_index"]["items"]:
        report_types[item["type"]] = report_types.get(item["type"], 0) + 1
    print(
        "Counts: "
        f"daily={report_types.get('daily', 0)} "
        f"ten_day={report_types.get('ten_day', 0)} "
        f"monthly={report_types.get('monthly', 0)} "
        f"patterns={len(payload['pages']['home']['patterns'])} "
        f"reminders={len(payload['reminders']['items'])}"
    )
    print(f"Artifacts: {cognitive_state_path}")
    print(f"Artifacts: {report_index_path}")
    print(f"Artifacts: {reminders_path}")
    print(f"Artifacts: {suggestion_index_path}")
    if payload["warnings"]:
        print("Warnings:")
        for warning in payload["warnings"]:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
