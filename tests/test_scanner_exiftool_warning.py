from __future__ import annotations

import json
from pathlib import Path

from app.core.config import default_config
from app.core.db import Database
from app.core.models import DirectorySelection
from app.core.scanner import scan


def test_scan_rc1_warning_no_errors(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    file_path = root / "image.jpg"
    file_path.write_bytes(b"data")

    def fake_run(_path, files):
        return ([{"SourceFile": str(files[0])}], "17 image files read")

    monkeypatch.setattr("app.core.scanner.run_exiftool", fake_run)

    db_path = tmp_path / "test.db"
    db = Database(db_path)
    result = scan(
        db,
        default_config(),
        root,
        selections=[
            DirectorySelection(path=root, recursive=True, include_root_files=True)
        ],
        errors_log_path=tmp_path / "errors.jsonl",
        db_path=db_path,
    )
    db.close()

    assert result.stats.errors == 0
    assert result.stats.warnings == 1
    assert result.stats.images == 1
