#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from cognitive_agent_runtime import (
    get_agent_status,
    list_reminders,
    run_demo,
    run_task,
    task_registry,
    update_reminder_status,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the cognitive mirror backend agent demo.")
    parser.add_argument(
        "command",
        choices=["tasks", "status", "run", "demo", "reminders", "update-reminder"],
        help="Which agent action to execute.",
    )
    parser.add_argument(
        "--task",
        choices=sorted(task_registry().keys()),
        help="Task name used with the run command.",
    )
    parser.add_argument(
        "--profile",
        choices=["dev", "prod"],
        help="Config profile to use. Defaults to the config default.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full result as JSON.",
    )
    parser.add_argument("--date", help="Date string (YYYY-MM-DD) for journal analysis. Defaults to today.")
    parser.add_argument("--id", help="Reminder id used with update-reminder.")
    parser.add_argument(
        "--status-value",
        choices=["new", "active", "done", "snoozed", "dismissed"],
        help="Reminder status used with update-reminder.",
    )
    parser.add_argument("--snooze-until", help="ISO datetime used when status-value=snoozed.")
    return parser.parse_args()


def print_tasks() -> None:
    for task in task_registry().values():
        print(f"{task['name']}: {task['label']}")
        print(f"  {task['description']}")
        if task["prompt_path"]:
            print(f"  prompt: {task['prompt_path']}")


def print_status() -> None:
    status = get_agent_status()
    print(f"Workbench payload ready: {'yes' if status['workbench_exists'] else 'no'}")
    print(f"Profile: {status.get('profile') or '未运行'}")
    print(f"Updated at: {status.get('updated_at') or '未运行'}")
    last_run = status.get("last_run")
    if last_run:
        print(f"Last run: {last_run['task']} ({last_run['finished_at']})")
        print(f"Summary: {last_run['summary']}")
    else:
        print("Last run: none")
    print(f"Tasks: {', '.join(task['name'] for task in status['available_tasks'])}")


def print_run_result(result: dict[str, object]) -> None:
    print(f"Run id: {result['run_id']}")
    print(f"Task: {result['task']}")
    print(f"Profile: {result['profile']}")
    print(f"Finished: {result['finished_at']}")
    print(f"Summary: {result['summary']}")
    warnings = result.get("warnings", [])
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")


def print_reminders(reminders: dict[str, object]) -> None:
    items = reminders.get("items", [])
    print(f"Reminders: {len(items)}")
    for item in items:
        print(
            f"- {item['id']} [{item['status']}] ({item['horizon']}) "
            f"{item['title']} x{item.get('count', 1)}"
        )


def main() -> None:
    args = parse_args()
    if args.command == "tasks":
        print_tasks()
        return
    if args.command == "status":
        print_status()
        return
    if args.command == "reminders":
        reminders = list_reminders(profile=args.profile, refresh_if_missing=True)
        if args.json:
            print(json.dumps(reminders, ensure_ascii=False, indent=2))
            return
        print_reminders(reminders)
        return
    if args.command == "update-reminder":
        if not args.id or not args.status_value:
            raise SystemExit("--id and --status-value are required when command=update-reminder")
        result = update_reminder_status(
            reminder_id=args.id,
            status=args.status_value,
            profile=args.profile,
            snooze_until=args.snooze_until,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        print(f"Updated reminder: {result['reminder']['id']}")
        print(f"Status: {result['reminder']['status']}")
        print(f"Title: {result['reminder']['title']}")
        return
    if args.command == "demo":
        result = run_demo(profile=args.profile)
    else:
        if not args.task:
            raise SystemExit("--task is required when command=run")
        result = run_task(task_name=args.task, profile=args.profile, date_str=args.date)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print_run_result(result)


if __name__ == "__main__":
    main()
