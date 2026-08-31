"""Command-line interface for the Brunost Platform Kit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from brunost_platform.gateway import gateway_from_environment
from brunost_platform.project import TASK_KINDS, TEMPLATES, create_contest, create_project, create_task


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brunost-platform", description="Create and inspect Brunost platform applications")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="generate a platform application")
    init.add_argument("path", type=Path)
    init.add_argument("--template", choices=TEMPLATES, default="python-fastapi")
    init.add_argument("--force", action="store_true")
    templates = sub.add_parser("templates", help="list available application templates")
    templates.set_defaults(action="templates")
    task = sub.add_parser("task", help="scaffold a portable judge task")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    task_new = task_sub.add_parser("new", help="create a task package")
    task_new.add_argument("path", type=Path)
    task_new.add_argument("--kind", choices=TASK_KINDS, default="coding")
    task_new.add_argument("--force", action="store_true")
    contest = sub.add_parser("contest", help="scaffold a platform-owned contest")
    contest_sub = contest.add_subparsers(dest="contest_command", required=True)
    contest_new = contest_sub.add_parser("new", help="create a contest descriptor")
    contest_new.add_argument("path", type=Path)
    contest_new.add_argument("--id")
    contest_new.add_argument("--force", action="store_true")
    doctor = sub.add_parser("doctor", help="check connectivity to the judge")
    doctor.set_defaults(action="doctor")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "templates":
        print("\n".join(TEMPLATES))
        return 0
    if args.command == "init":
        try:
            root = create_project(args.path, template=args.template, force=args.force)
        except (FileExistsError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"created Brunost platform: {root} (template={args.template})")
        return 0
    if args.command == "task" and args.task_command == "new":
        try:
            root = create_task(args.path, kind=args.kind, force=args.force)
        except (FileExistsError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"created Brunost task: {root} (kind={args.kind})")
        return 0
    if args.command == "contest" and args.contest_command == "new":
        try:
            root = create_contest(args.path, contest_id=args.id, force=args.force)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"created Brunost contest: {root}")
        return 0
    if args.command == "doctor":
        try:
            health = gateway_from_environment().health()
        except Exception as exc:  # noqa: BLE001 - CLI should present a concise diagnostic
            print(f"judge unavailable: {exc}", file=sys.stderr)
            return 1
        print(f"judge ok: {health}")
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised by ``python -m``
    raise SystemExit(main())
