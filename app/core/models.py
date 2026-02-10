from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RootRecord:
    id: int
    path: str
    added_at: str
    last_scan_at: Optional[str]


@dataclass(frozen=True)
class DirectorySelection:
    path: Path
    recursive: bool
    include_root_files: bool


@dataclass(frozen=True)
class ScanStats:
    directories: int
    images: int
    videos: int
    warnings: int
    errors: int
    tags_added: int
    file_tag_links_added: int
    category_tags_added: int
    value_tags_added: int


@dataclass(frozen=True)
class ScanResult:
    stats: ScanStats
    cancelled: bool


@dataclass(frozen=True)
class TagItem:
    tag: str
    kind: str
    source: str
