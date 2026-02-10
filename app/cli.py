from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from typing import Callable

from app import __version__
from app.core.config import load_config
from app.core.db import Database
from app.core.exiftool import find_exiftool
from app.core.models import DirectorySelection, ScanResult
from app.core.scanner import scan

TAKEN_SRC_ORDER = [
    "SubSecDateTimeOriginal",
    "DateTimeOriginal",
    "CreateDate",
    "XMP_CreateDate",
    "XMP_DateCreated",
    "mtime_fallback",
    "unknown",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Photo Indexer CLI")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode")
    parser.add_argument("--db", type=Path, help="SQLite DB file path")
    parser.add_argument("--root", type=Path, help="Root directory to scan")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to DB")
    parser.add_argument("--changed-only", action="store_true", help="Only scan changed files")
    parser.add_argument(
        "--include-root-files",
        action="store_true",
        default=True,
        help="Include files in root (default: true)",
    )
    parser.add_argument("--json", action="store_true", help="Print report as JSON")
    parser.add_argument("--report", type=Path, help="Write report to file")
    parser.add_argument("--errors-log", type=Path, help="Errors JSONL log path")
    parser.add_argument("--no-progress", action="store_true", help="Disable progress output")
    parser.add_argument(
        "--progress-every",
        type=int,
        default=200,
        help="Print progress every N files",
    )
    return parser


def _prompt_path(prompt: str) -> str:
    value = input(prompt).strip()
    return value


def _prompt_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def _resolve_errors_log_path(args: argparse.Namespace, config, db_path: Path) -> Path:
    if args.errors_log:
        return args.errors_log
    if config.errors_log_path:
        return Path(config.errors_log_path)
    return db_path.with_suffix("").with_suffix(".errors.jsonl")


def _validate_db_path(path: Path) -> Path:
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    return path


def _validate_root(path: Path) -> Path:
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Root must be an existing directory: {path}")
    return path


def _format_taken_src(dist: dict[str, int]) -> list[str]:
    lines: list[str] = []
    width = max(len(k) for k in TAKEN_SRC_ORDER)
    lines.append("taken_src distribution:")
    for key in TAKEN_SRC_ORDER:
        count = dist.get(key, 0)
        lines.append(f"  {key.ljust(width)}: {count}")
    return lines


def _build_report(
    result: ScanResult,
    taken_src_dist: dict[str, int],
    root: Path,
    args: argparse.Namespace,
) -> dict:
    payload = {
        "version": __version__,
        "root": str(root),
        "errors_log_path": "",
        "dry_run": args.dry_run,
        "changed_only": args.changed_only,
        "include_root_files": args.include_root_files,
        "directories": result.stats.directories,
        "images": result.stats.images,
        "videos": result.stats.videos,
        "warnings": result.stats.warnings,
        "errors": result.stats.errors,
        "tags_added": result.stats.tags_added,
        "file_tag_links_added": result.stats.file_tag_links_added,
        "category_tags_added": result.stats.category_tags_added,
        "value_tags_added": result.stats.value_tags_added,
        "cancelled": result.cancelled,
        "taken_src_distribution": {
            key: taken_src_dist.get(key, 0) for key in TAKEN_SRC_ORDER
        },
    }
    return payload


def _write_report_text(payload: dict) -> str:
    lines = [
        f"Version: {payload.get('version', '')}",
        f"Root: {payload.get('root', '')}",
        f"Config: {payload.get('config_path', '')}",
        f"Scanned {payload['directories']} directories",
        f"Indexed {payload['images']} images",
        f"Indexed {payload['videos']} videos",
        f"Warnings: {payload['warnings']}",
        f"Errors: {payload['errors']}",
        f"Tags added: {payload['tags_added']}",
        f"Tag links added: {payload['file_tag_links_added']}",
        f"Category tags added: {payload['category_tags_added']}",
        f"Value tags added: {payload['value_tags_added']}",
    ]
    dist = payload.get("taken_src_distribution", {})
    lines += _format_taken_src(dist)
    if payload.get("errors") and payload.get("errors_log_path"):
        lines.append(f"See errors log: {payload.get('errors_log_path')}")
    lines.append(f"Cancelled: {payload['cancelled']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.cli:
        print("Use --cli to run in headless mode.")
        return 1

    if not args.db:
        value = _prompt_path("DB path: ")
        if value:
            args.db = Path(value)
    if not args.root:
        value = _prompt_path("Scan root directory: ")
        if value:
            args.root = Path(value)
    if args.dry_run is False and args.root is not None:
        args.dry_run = _prompt_yes_no("Dry run?", default=False)

    if not args.db or not args.root:
        print("Missing required --db or --root")
        return 1

    try:
        db_path = _validate_db_path(args.db)
        root_path = _validate_root(args.root)
    except ValueError as exc:
        print(str(exc))
        return 1

    config_path = Path("config.yaml")
    config = load_config(config_path)
    if not find_exiftool(config.exiftool_path):
        print("ExifTool not found. Install it or set exiftool_path in config.yaml")
        return 1

    cancelled = False

    def handle_sigint(_signum, _frame):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGINT, handle_sigint)

    file_counter = 0

    def file_progress(path: str):
        nonlocal file_counter
        file_counter += 1
        if args.no_progress:
            return
        if args.progress_every > 0 and file_counter % args.progress_every == 0:
            print(f"Processed {file_counter} files... ({path})")

    def warning_log(message: str) -> None:
        if args.no_progress:
            return
        print(f"ExifTool warning: {message}", file=sys.stderr)

    try:
        selections = [
            DirectorySelection(
                path=root_path,
                recursive=True,
                include_root_files=args.include_root_files,
            )
        ]

        errors_log_path = _resolve_errors_log_path(args, config, db_path)
        db = Database(Path(":memory:")) if args.dry_run else Database(db_path)
        result = scan(
            db,
            config,
            root_path,
            selections=selections,
            dry_run=args.dry_run,
            changed_only=args.changed_only,
            cancel_check=lambda: cancelled,
            progress_cb=None,
            file_progress_cb=lambda p: file_progress(p),
            warning_cb=warning_log,
            errors_log_path=errors_log_path,
            db_path=db_path,
        )
        db.close()
        taken_src_dist = {}
        if not args.dry_run:
            db = Database(db_path)
            taken_src_dist = db.taken_src_distribution(str(root_path))
            db.close()
        payload = _build_report(result, taken_src_dist, root_path, args)
        payload["errors_log_path"] = str(errors_log_path) if errors_log_path else ""
        payload["config_path"] = str(config_path)
    except KeyboardInterrupt:
        cancelled = True
        payload = {
            "warnings": 0,
            "directories": 0,
            "images": 0,
            "videos": 0,
            "errors": 0,
            "tags_added": 0,
            "file_tag_links_added": 0,
            "category_tags_added": 0,
            "value_tags_added": 0,
            "cancelled": True,
            "taken_src_distribution": {},
        }

    output = json.dumps(payload, indent=2) if args.json else _write_report_text(payload)
    if args.report:
        args.report.write_text(output)
    print(output)

    if payload.get("cancelled"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
