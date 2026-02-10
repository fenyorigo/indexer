from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from app.core.config import AppConfig
from app.core.db import Database
from app.core.exiftool import (
    ExiftoolError,
    ExiftoolParseError,
    find_exiftool,
    parse_dimensions,
    parse_gps,
    parse_make_model,
    parse_tags,
    parse_taken_ts,
    run_exiftool,
)
from app.core.models import DirectorySelection, ScanResult, ScanStats

import traceback
from datetime import datetime, timezone


def _iter_files_non_recursive(directory: Path) -> Iterable[Path]:
    for entry in directory.iterdir():
        if entry.is_file():
            yield entry


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _hash_file(path: Path, mode: str) -> Optional[str]:
    if mode == "none":
        return None
    hasher = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            if mode == "quick":
                chunk = handle.read(1024 * 1024)
                hasher.update(chunk)
                if path.stat().st_size > 2 * 1024 * 1024:
                    handle.seek(-1024 * 1024, os.SEEK_END)
                    hasher.update(handle.read(1024 * 1024))
            else:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def _mime_type(path: Path, mode: str) -> Optional[str]:
    if mode == "ext":
        return mimetypes.guess_type(str(path))[0]
    if mode == "filecmd":
        try:
            proc = subprocess.run(
                ["file", "--mime-type", "-b", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                return proc.stdout.strip() or None
        except OSError:
            return None
        return None
    if mode == "magic":
        try:
            import magic  # type: ignore

            return magic.from_file(str(path), mime=True)
        except Exception:
            return None
    return None


def scan(
    db: Database,
    config: AppConfig,
    root_path: Path,
    selections: list[DirectorySelection],
    *,
    dry_run: bool = False,
    changed_only: bool = False,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    file_progress_cb: Optional[Callable[[str], None]] = None,
    warning_cb: Optional[Callable[[str], None]] = None,
    errors_log_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> ScanResult:
    root_id = db.ensure_root(str(root_path)) if not dry_run else -1
    stats = ScanStats(
        directories=0,
        images=0,
        videos=0,
        warnings=0,
        errors=0,
        tags_added=0,
        file_tag_links_added=0,
        category_tags_added=0,
        value_tags_added=0,
    )
    counted_dirs: set[str] = set()
    cancelled = False

    exiftool_path = find_exiftool(config.exiftool_path)
    if not exiftool_path:
        if not dry_run:
            db.log_error("exiftool", "ExifTool not found", None)
        stats = ScanStats(
            directories=stats.directories,
            images=stats.images,
            videos=stats.videos,
            warnings=stats.warnings,
            errors=stats.errors + 1,
            tags_added=stats.tags_added,
            file_tag_links_added=stats.file_tag_links_added,
            category_tags_added=stats.category_tags_added,
            value_tags_added=stats.value_tags_added,
        )
        return ScanResult(stats=stats, cancelled=False)

    errors_log = _resolve_errors_log_path(errors_log_path, db_path)
    jobs = _build_jobs(selections)
    total_jobs = len(jobs)
    processed_jobs = 0

    for job in jobs:
        if cancel_check and cancel_check():
            cancelled = True
            break

        directory_path = job.path
        if db.directory_exists(str(directory_path)) and not dry_run and not changed_only:
            db.delete_directory_subtree(str(directory_path))

        if _is_hidden(directory_path):
            continue

        directory_id = None
        if not dry_run:
            db.begin()
            directory_id = _ensure_directory_chain(db, root_id, root_path, directory_path)
            db.update_directory_status(directory_id, "scanning")

        files = _collect_files(directory_path, job.include_files)
        if files and changed_only and not dry_run:
            files = _filter_changed_files(db, files, config.hash_mode)
        error_in_dir = False

        exif_records = []
        if files:
            try:
                exif_records, warning = run_exiftool(exiftool_path, files)
                if warning:
                    stats = ScanStats(
                        directories=stats.directories,
                        images=stats.images,
                        videos=stats.videos,
                        warnings=stats.warnings + 1,
                        errors=stats.errors,
                        tags_added=stats.tags_added,
                        file_tag_links_added=stats.file_tag_links_added,
                        category_tags_added=stats.category_tags_added,
                        value_tags_added=stats.value_tags_added,
                    )
                    if warning_cb:
                        warning_cb(warning)
            except ExiftoolError as exc:
                error_in_dir = True
                _log_error(
                    errors_log,
                    root_path,
                    directory_path,
                    None,
                    None,
                    "exiftool",
                    exc,
                    exiftool_exit_code=exc.exit_code,
                    exiftool_stderr=exc.stderr,
                    exiftool_stdout=exc.stdout,
                )
                if not dry_run:
                    db.rollback()
                    db.log_error("exiftool", str(directory_path), str(exc))
                    if directory_id is not None:
                        db.update_directory_status(directory_id, "error")
                stats = ScanStats(
                    directories=stats.directories,
                    images=stats.images,
                    videos=stats.videos,
                    errors=stats.errors + 1,
                    warnings=stats.warnings,
                    tags_added=stats.tags_added,
                    file_tag_links_added=stats.file_tag_links_added,
                    category_tags_added=stats.category_tags_added,
                    value_tags_added=stats.value_tags_added,
                )
                processed_jobs += 1
                if progress_cb:
                    progress_cb(processed_jobs, total_jobs, str(directory_path))
                continue
            except ExiftoolParseError as exc:
                error_in_dir = True
                _log_error(
                    errors_log,
                    root_path,
                    directory_path,
                    None,
                    None,
                    "parse_json",
                    exc,
                    exiftool_stdout=exc.stdout,
                )
                if not dry_run:
                    db.rollback()
                    db.log_error("parse_json", str(directory_path), str(exc))
                    if directory_id is not None:
                        db.update_directory_status(directory_id, "error")
                stats = ScanStats(
                    directories=stats.directories,
                    images=stats.images,
                    videos=stats.videos,
                    warnings=stats.warnings,
                    errors=stats.errors + 1,
                    tags_added=stats.tags_added,
                    file_tag_links_added=stats.file_tag_links_added,
                    category_tags_added=stats.category_tags_added,
                    value_tags_added=stats.value_tags_added,
                )
                processed_jobs += 1
                if progress_cb:
                    progress_cb(processed_jobs, total_jobs, str(directory_path))
                continue
            except Exception as exc:
                error_in_dir = True
                _log_error(
                    errors_log,
                    root_path,
                    directory_path,
                    None,
                    None,
                    "exiftool",
                    exc,
                )
                if not dry_run:
                    db.rollback()
                    db.log_error("exiftool", str(directory_path), str(exc))
                    if directory_id is not None:
                        db.update_directory_status(directory_id, "error")
                stats = ScanStats(
                    directories=stats.directories,
                    images=stats.images,
                    videos=stats.videos,
                    warnings=stats.warnings,
                    errors=stats.errors + 1,
                    tags_added=stats.tags_added,
                    file_tag_links_added=stats.file_tag_links_added,
                    category_tags_added=stats.category_tags_added,
                    value_tags_added=stats.value_tags_added,
                )
                processed_jobs += 1
                if progress_cb:
                    progress_cb(processed_jobs, total_jobs, str(directory_path))
                continue

        record_map = {record.get("SourceFile"): record for record in exif_records if record}

        for file_path in files:
            if cancel_check and cancel_check():
                cancelled = True
                if not dry_run:
                    db.rollback()
                    if directory_id is not None:
                        db.update_directory_status(directory_id, "partial")
                break
            stats, had_error = _process_file(
                db,
                config,
                root_id,
                root_path,
                file_path,
                stats,
                record_map.get(str(file_path)),
                dry_run=dry_run,
                errors_log=errors_log,
                directory_path=directory_path,
            )
            if file_progress_cb:
                file_progress_cb(str(file_path))
            error_in_dir = error_in_dir or had_error

        if cancelled:
            break

        if not dry_run and directory_id is not None:
            db.update_directory_scan_time(directory_id)
            db.update_directory_status(directory_id, "partial" if error_in_dir else "done")
            db.commit()

        _mark_directory(db, counted_dirs, root_id, root_path, directory_path, dry_run=dry_run)
        stats = _recount_dirs(stats, counted_dirs)
        processed_jobs += 1
        if progress_cb:
            progress_cb(processed_jobs, total_jobs, str(directory_path))

    if not dry_run:
        db.update_root_scan_time(root_id)
    return ScanResult(stats=stats, cancelled=cancelled)


def _ensure_directory_chain(db: Database, root_id: int, root_path: Path, dir_path: Path) -> int:
    try:
        rel_path = str(dir_path.relative_to(root_path))
    except ValueError:
        rel_path = dir_path.name

    parts = Path(rel_path).parts if rel_path else ()
    current_path = root_path
    parent_id = None
    depth = 0

    if rel_path == "" or rel_path == ".":
        return db.ensure_directory(root_id, None, str(root_path), "", 0)

    for part in parts:
        depth += 1
        current_path = current_path / part
        rel = str(current_path.relative_to(root_path))
        dir_id = db.ensure_directory(root_id, parent_id, str(current_path), rel, depth)
        parent_id = dir_id

    db.update_directory_scan_time(parent_id)
    return int(parent_id)


def _mark_directory(
    db: Database,
    counted_dirs: set[str],
    root_id: int,
    root_path: Path,
    dir_path: Path,
    *,
    dry_run: bool,
) -> None:
    if not dry_run:
        _ensure_directory_chain(db, root_id, root_path, dir_path)
    counted_dirs.add(str(dir_path))


def _recount_dirs(stats: ScanStats, counted_dirs: set[str]) -> ScanStats:
    return ScanStats(
        directories=len(counted_dirs),
        images=stats.images,
        videos=stats.videos,
        warnings=stats.warnings,
        errors=stats.errors,
        tags_added=stats.tags_added,
        file_tag_links_added=stats.file_tag_links_added,
        category_tags_added=stats.category_tags_added,
        value_tags_added=stats.value_tags_added,
    )


def _process_file(
    db: Database,
    config: AppConfig,
    root_id: int,
    root_path: Path,
    file_path: Path,
    stats: ScanStats,
    exif_record: Optional[dict],
    *,
    dry_run: bool,
    errors_log: Optional[Path],
    directory_path: Path,
) -> tuple[ScanStats, bool]:
    if _is_hidden(file_path):
        return stats, False
    if file_path.suffix.lower() in {".xmp", ".aae"}:
        return stats, False

    try:
        rel_path = str(file_path.relative_to(root_path))
    except ValueError:
        rel_path = str(file_path.name)

    ext = file_path.suffix.lower()
    file_type = "other"
    if config.is_image(file_path):
        file_type = "image"
    elif config.is_video(file_path):
        file_type = "video"

    try:
        stat = file_path.stat()
    except OSError as exc:
        _log_error(
            errors_log,
            root_path,
            directory_path,
            file_path,
            rel_path,
            "stat",
            exc,
            file_type=file_type,
            ext=ext,
        )
        if not dry_run:
            db.log_error("stat", str(file_path), str(exc))
        return ScanStats(
            directories=stats.directories,
            images=stats.images,
            videos=stats.videos,
            warnings=stats.warnings,
            errors=stats.errors + 1,
            tags_added=stats.tags_added,
            file_tag_links_added=stats.file_tag_links_added,
            category_tags_added=stats.category_tags_added,
            value_tags_added=stats.value_tags_added,
        ), True

    try:
        taken_ts, taken_src = parse_taken_ts(exif_record or {}, int(stat.st_mtime))
    except Exception as exc:
        _log_error(
            errors_log,
            root_path,
            directory_path,
            file_path,
            rel_path,
            "taken_ts_parse",
            exc,
            file_type=file_type,
            ext=ext,
        )
        return ScanStats(
            directories=stats.directories,
            images=stats.images,
            videos=stats.videos,
            warnings=stats.warnings,
            errors=stats.errors + 1,
            tags_added=stats.tags_added,
            file_tag_links_added=stats.file_tag_links_added,
            category_tags_added=stats.category_tags_added,
            value_tags_added=stats.value_tags_added,
        ), True
    width, height = parse_dimensions(exif_record or {})
    lat, lon = parse_gps(exif_record or {})
    make, model = parse_make_model(exif_record or {})
    hash_value = _hash_file(file_path, config.hash_mode)
    mime = _mime_type(file_path, config.mime_mode)
    exiftool_json = json.dumps(exif_record, ensure_ascii=False) if exif_record else None

    if not dry_run:
        try:
            directory_id = _ensure_directory_chain(db, root_id, root_path, file_path.parent)
            file_id = db.insert_file(
                directory_id=directory_id,
                path=str(file_path),
                rel_path=rel_path,
                name=file_path.name,
                ext=ext,
                size=stat.st_size,
                mtime=int(stat.st_mtime),
                ctime=int(stat.st_ctime),
                taken_ts=taken_ts,
                taken_src=taken_src,
                file_type=file_type,
                width=width,
                height=height,
                lat=lat,
                lon=lon,
                make=make,
                model=model,
                hash_value=hash_value,
                mime=mime,
                exiftool_json=exiftool_json,
            )
        except Exception as exc:
            _log_error(
                errors_log,
                root_path,
                directory_path,
                file_path,
                rel_path,
                "db_write",
                exc,
                file_type=file_type,
                ext=ext,
            )
            db.log_error("db_write", str(file_path), str(exc))
            if db.conn.in_transaction:
                db.rollback()
                db.begin()
            return ScanStats(
                directories=stats.directories,
                images=stats.images,
                videos=stats.videos,
                warnings=stats.warnings,
                errors=stats.errors + 1,
                tags_added=stats.tags_added,
                file_tag_links_added=stats.file_tag_links_added,
                category_tags_added=stats.category_tags_added,
                value_tags_added=stats.value_tags_added,
            ), True

        if exif_record:
            try:
                db.clear_file_tags(file_id)
                tag_items = parse_tags(exif_record)
                seen = set()
                for item in tag_items:
                    key = (item.tag, item.kind, item.source)
                    if key in seen:
                        continue
                    seen.add(key)
                    tag_id, created = db.ensure_tag(item.tag, item.kind, item.source)
                    if created:
                        stats = ScanStats(
                            directories=stats.directories,
                            images=stats.images,
                            videos=stats.videos,
                            warnings=stats.warnings,
                            errors=stats.errors,
                            tags_added=stats.tags_added + 1,
                            file_tag_links_added=stats.file_tag_links_added,
                            category_tags_added=stats.category_tags_added
                            + (1 if item.kind == "category" else 0),
                            value_tags_added=stats.value_tags_added + (1 if item.kind == "person" else 0),
                        )
                    if db.link_file_tag(file_id, tag_id):
                        stats = ScanStats(
                            directories=stats.directories,
                            images=stats.images,
                            videos=stats.videos,
                            warnings=stats.warnings,
                            errors=stats.errors,
                            tags_added=stats.tags_added,
                            file_tag_links_added=stats.file_tag_links_added + 1,
                            category_tags_added=stats.category_tags_added,
                            value_tags_added=stats.value_tags_added,
                        )
            except Exception as exc:
                _log_error(
                    errors_log,
                    root_path,
                    directory_path,
                    file_path,
                    rel_path,
                    "tag_normalize",
                    exc,
                    file_type=file_type,
                    ext=ext,
                )
                db.log_error("tag_normalize", str(file_path), str(exc))
                if db.conn.in_transaction:
                    db.rollback()
                    db.begin()
                return ScanStats(
                    directories=stats.directories,
                    images=stats.images,
                    videos=stats.videos,
                    warnings=stats.warnings,
                    errors=stats.errors + 1,
                    tags_added=stats.tags_added,
                    file_tag_links_added=stats.file_tag_links_added,
                    category_tags_added=stats.category_tags_added,
                    value_tags_added=stats.value_tags_added,
                ), True

    if file_type == "image":
        return (
            ScanStats(
                directories=stats.directories,
                images=stats.images + 1,
                videos=stats.videos,
                warnings=stats.warnings,
                errors=stats.errors,
                tags_added=stats.tags_added,
                file_tag_links_added=stats.file_tag_links_added,
                category_tags_added=stats.category_tags_added,
                value_tags_added=stats.value_tags_added,
            ),
            False,
        )
    if file_type == "video":
        return (
            ScanStats(
                directories=stats.directories,
                images=stats.images,
                videos=stats.videos + 1,
                warnings=stats.warnings,
                errors=stats.errors,
                tags_added=stats.tags_added,
                file_tag_links_added=stats.file_tag_links_added,
                category_tags_added=stats.category_tags_added,
                value_tags_added=stats.value_tags_added,
            ),
            False,
        )
    return stats, False


def _resolve_errors_log_path(
    errors_log_path: Optional[Path],
    db_path: Optional[Path],
) -> Optional[Path]:
    if errors_log_path:
        return errors_log_path
    if db_path:
        return db_path.with_suffix("").with_suffix(".errors.jsonl")
    return None


def _truncate(value: Optional[str], limit: int = 8192) -> Optional[str]:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit]


def _log_error(
    errors_log: Optional[Path],
    root_path: Path,
    directory_path: Path,
    file_path: Optional[Path],
    rel_path: Optional[str],
    operation: str,
    exc: Exception,
    *,
    file_type: str = "other",
    ext: str = "",
    exiftool_exit_code: Optional[int] = None,
    exiftool_stderr: Optional[str] = None,
    exiftool_stdout: Optional[str] = None,
) -> None:
    if not errors_log:
        return
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "root": str(root_path),
        "directory": str(directory_path),
        "file_path": str(file_path) if file_path else None,
        "rel_path": rel_path,
        "file_type": file_type,
        "ext": ext,
        "operation": operation,
        "exception_class": exc.__class__.__name__,
        "exception_message": str(exc),
        "exception_traceback": traceback.format_exc(),
        "exiftool_exit_code": exiftool_exit_code,
        "exiftool_stderr": _truncate(exiftool_stderr),
        "exiftool_stdout": _truncate(exiftool_stdout),
    }
    try:
        errors_log.parent.mkdir(parents=True, exist_ok=True)
        with errors_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


@dataclass(frozen=True)
class DirectoryJob:
    path: Path
    include_files: bool


def _build_jobs(selections: list[DirectorySelection]) -> list[DirectoryJob]:
    jobs: list[DirectoryJob] = []
    for selection in selections:
        if selection.recursive:
            for dirpath, dirnames, _filenames in os.walk(selection.path):
                dir_path = Path(dirpath)
                if _is_hidden(dir_path):
                    dirnames[:] = []
                    continue
                jobs.append(DirectoryJob(path=dir_path, include_files=True))
        else:
            jobs.append(DirectoryJob(path=selection.path, include_files=selection.include_root_files))
    return jobs


def _collect_files(directory: Path, include_files: bool) -> list[Path]:
    if not include_files:
        return []
    files = []
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        if _is_hidden(entry):
            continue
        if entry.suffix.lower() in {".xmp", ".aae"}:
            continue
        files.append(entry)
    return files


def _filter_changed_files(db: Database, files: list[Path], hash_mode: str) -> list[Path]:
    by_path = db.get_files_by_paths([str(p) for p in files])
    changed: list[Path] = []
    for path in files:
        row = by_path.get(str(path))
        if row is None:
            changed.append(path)
            continue
        try:
            stat = path.stat()
        except OSError:
            changed.append(path)
            continue
        if int(row["mtime"]) != int(stat.st_mtime) or int(row["size"]) != int(stat.st_size):
            changed.append(path)
            continue
        if hash_mode != "none":
            # If hash is missing, we need to reprocess to populate it.
            if not row["hash"]:
                changed.append(path)
        # Unchanged otherwise.
    return changed
