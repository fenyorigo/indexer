from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.core.models import TagItem


class ExiftoolError(RuntimeError):
    def __init__(self, message: str, exit_code: int, stderr: str | None, stdout: str | None) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr
        self.stdout = stdout


class ExiftoolParseError(RuntimeError):
    def __init__(self, message: str, stdout: str | None) -> None:
        super().__init__(message)
        self.stdout = stdout


def find_exiftool(explicit_path: str | None = None) -> str | None:
    if explicit_path:
        return explicit_path
    return shutil.which("exiftool")


def run_exiftool(exiftool_path: str, files: Iterable[Path]) -> tuple[list[dict], str | None]:
    file_args = [str(p) for p in files]
    if not file_args:
        return [], None

    cmd = [exiftool_path, "-json", "-n"] + file_args
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode >= 2:
        raise ExiftoolError(
            proc.stderr.strip() or "ExifTool failed",
            proc.returncode,
            proc.stderr,
            proc.stdout,
        )
    try:
        records = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ExiftoolParseError(f"Invalid ExifTool JSON: {exc}", proc.stdout) from exc
    if not records:
        raise ExiftoolParseError("Empty ExifTool JSON", proc.stdout)
    warning = proc.stderr.strip() if proc.returncode == 1 and proc.stderr else None
    return records, warning


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]

_SPACE_RE = re.compile(r"\s+")


def normalize_tag(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip())


def parse_tags(record: dict) -> list[TagItem]:
    tags: list[TagItem] = []

    def add(kind: str, source: str, values: list[str]) -> None:
        for item in values:
            cleaned = normalize_tag(item)
            if cleaned:
                tags.append(TagItem(tag=cleaned, kind=kind, source=source))

    def get_any(keys: list[str]) -> list[str]:
        for key in keys:
            if key in record:
                return _as_list(record.get(key))
            lower_key = key.lower()
            for actual in record.keys():
                if actual.lower() == lower_key:
                    return _as_list(record.get(actual))
        return []

    keyword_values = get_any(["IPTC:Keywords", "Keywords", "IPTC:Keyword"])
    subject_values = get_any(["XMP-dc:Subject", "XMP:Subject", "Subject"])
    hierarchical_values = _split_hierarchical(
        get_any(
            [
                "XMP-lr:HierarchicalSubject",
                "HierarchicalSubject",
                "XMP:HierarchicalSubject",
            ]
        )
    )

    add("keyword", "iptc", keyword_values)
    add("subject", "xmp-dc", subject_values)

    for value in hierarchical_values:
        add("hierarchical", "xmp-lr", [value])
        category, person = _split_category_person(value)
        if category:
            add("category", "xmp-lr", [category])
        if person:
            add("person", "xmp-lr", [person])

    return tags


def _split_hierarchical(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if "," not in value:
            result.append(value)
            continue
        result.extend(_split_commas_outside_parens(value))
    return result


def _split_commas_outside_parens(value: str) -> list[str]:
    items: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                items.append(part)
            buf = []
            continue
        buf.append(ch)
    part = "".join(buf).strip()
    if part:
        items.append(part)
    return items


def _split_category_person(value: str) -> tuple[str | None, str | None]:
    if "|" not in value:
        return None, None
    category, remainder = value.split("|", 1)
    category = normalize_tag(category)
    remainder = normalize_tag(remainder)
    return (category or None, remainder or None)


def parse_dimensions(record: dict) -> tuple[int | None, int | None]:
    width = _first_int(
        record,
        ["ImageWidth", "EXIF:ImageWidth", "XMP:ImageWidth", "File:ImageWidth"],
    )
    height = _first_int(
        record,
        ["ImageHeight", "EXIF:ImageHeight", "XMP:ImageHeight", "File:ImageHeight"],
    )
    return width, height


def parse_gps(record: dict) -> tuple[float | None, float | None]:
    lat = _first_float(record, ["GPSLatitude", "Composite:GPSLatitude", "XMP:GPSLatitude"])
    lon = _first_float(record, ["GPSLongitude", "Composite:GPSLongitude", "XMP:GPSLongitude"])
    return lat, lon


def parse_make_model(record: dict) -> tuple[str | None, str | None]:
    make = record.get("Make")
    model = record.get("Model")
    return (str(make).strip() if make else None, str(model).strip() if model else None)


def parse_taken_ts(record: dict, stat_mtime: int) -> tuple[int, str]:
    priority = [
        ("SubSecDateTimeOriginal", "SubSecDateTimeOriginal"),
        ("DateTimeOriginal", "DateTimeOriginal"),
        ("CreateDate", "CreateDate"),
        ("XMP:CreateDate", "XMP_CreateDate"),
        ("XMP:DateCreated", "XMP_DateCreated"),
    ]
    for key, label in priority:
        value = _get_any(record, key)
        if value:
            ts = _parse_exif_datetime(value)
            if ts is not None:
                return ts, label
    return stat_mtime, "mtime_fallback"


def _first_int(record: dict, keys: list[str]) -> int | None:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None


def _first_float(record: dict, keys: list[str]) -> float | None:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _get_any(record: dict, key: str):
    if key in record:
        return record.get(key)
    lower_key = key.lower()
    for actual in record.keys():
        if actual.lower() == lower_key:
            return record.get(actual)
    return None


def _parse_exif_datetime(value) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, list):
        for item in value:
            ts = _parse_exif_datetime(item)
            if ts is not None:
                return ts
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    candidates = [
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y:%m:%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y:%m:%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y:%m:%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S.%f%z",
    ]
    for fmt in candidates:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue

    try:
        dt = datetime.fromisoformat(text.replace(":", "-", 2))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None
