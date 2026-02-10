from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


@dataclass(frozen=True)
class AppConfig:
    exiftool_path: str
    image_extensions: tuple[str, ...]
    video_extensions: tuple[str, ...]
    hash_mode: str
    mime_mode: str
    errors_log_path: str

    def is_image(self, path: Path) -> bool:
        return path.suffix.lower() in self.image_extensions

    def is_video(self, path: Path) -> bool:
        return path.suffix.lower() in self.video_extensions


DEFAULT_IMAGE_EXTS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".heic",
    ".webp",
)
DEFAULT_VIDEO_EXTS = (
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
)


def _tupleize(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(s.lower() for s in items)


def default_config() -> AppConfig:
    return AppConfig(
        exiftool_path="",
        image_extensions=DEFAULT_IMAGE_EXTS,
        video_extensions=DEFAULT_VIDEO_EXTS,
        hash_mode="none",
        mime_mode="ext",
        errors_log_path="",
    )


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        return default_config()

    data = yaml.safe_load(path.read_text()) or {}
    hash_mode = str(data.get("hash_mode", "none")).lower()
    mime_mode = str(data.get("mime_mode", "ext")).lower()
    if "hash_sha1" in data and data.get("hash_sha1"):
        hash_mode = "sha256"
    if "store_mime" in data and data.get("store_mime"):
        mime_mode = "ext"
    return AppConfig(
        exiftool_path=str(data.get("exiftool_path", "")),
        image_extensions=_tupleize(data.get("image_extensions", DEFAULT_IMAGE_EXTS)),
        video_extensions=_tupleize(data.get("video_extensions", DEFAULT_VIDEO_EXTS)),
        hash_mode=hash_mode,
        mime_mode=mime_mode,
        errors_log_path=str(data.get("errors_log_path", "")),
    )
