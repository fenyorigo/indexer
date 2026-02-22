from __future__ import annotations

from pathlib import Path

from app.core.config import default_config
from app.core.db import Database
from app.core.models import DirectorySelection
from app.core.scanner import scan


def test_scan_stores_db_media_path_separately(tmp_path: Path, monkeypatch) -> None:
    media_root = tmp_path / "source-media"
    media_root.mkdir()
    sub = media_root / "2020"
    sub.mkdir()
    file_path = sub / "photo.jpg"
    file_path.write_bytes(b"data")

    def fake_run(_path, files):
        return ([{"SourceFile": str(files[0])}], None)

    monkeypatch.setattr("app.core.scanner.run_exiftool", fake_run)

    db_root = Path("/data/photos")
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    result = scan(
        db,
        default_config(),
        media_root,
        selections=[DirectorySelection(path=media_root, recursive=True, include_root_files=True)],
        db_media_root=db_root,
        errors_log_path=tmp_path / "errors.jsonl",
        db_path=db_path,
    )

    root_row = db.conn.execute("SELECT path FROM roots ORDER BY id DESC LIMIT 1").fetchone()
    dir_rows = db.conn.execute("SELECT path, rel_path FROM directories ORDER BY rel_path").fetchall()
    file_row = db.conn.execute("SELECT path, rel_path FROM files LIMIT 1").fetchone()
    db.close()

    assert result.stats.images == 1
    assert root_row["path"] == "/data/photos"
    assert [(row["path"], row["rel_path"]) for row in dir_rows] == [
        ("/data/photos", ""),
        ("/data/photos/2020", "2020"),
    ]
    assert (file_row["path"], file_row["rel_path"]) == ("/data/photos/2020/photo.jpg", "2020/photo.jpg")
