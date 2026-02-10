from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import default_config
from app.core.db import Database
from app.core.exiftool import ExiftoolError
from app.core.models import DirectorySelection
from app.core.scanner import scan


def test_scan_exiftool_fatal_writes_error_log(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    file_path = root / "image.jpg"
    file_path.write_bytes(b"data")

    def fake_run(_path, _files):
        raise ExiftoolError("fatal", 2, "stderr", "stdout")

    monkeypatch.setattr("app.core.scanner.run_exiftool", fake_run)

    db_path = tmp_path / "test.db"
    errors_log = tmp_path / "errors.jsonl"
    db = Database(db_path)
    result = scan(
        db,
        default_config(),
        root,
        selections=[DirectorySelection(path=root, recursive=True, include_root_files=True)],
        errors_log_path=errors_log,
        db_path=db_path,
    )
    db.close()

    assert result.stats.errors == 1
    assert errors_log.exists()
    first_line = errors_log.read_text().splitlines()[0]
    payload = json.loads(first_line)
    assert payload["operation"] == "exiftool"
    assert payload["exiftool_exit_code"] == 2
