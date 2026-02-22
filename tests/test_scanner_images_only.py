from __future__ import annotations

from pathlib import Path

from app.core.config import default_config
from app.core.db import Database
from app.core.models import DirectorySelection
from app.core.scanner import scan


def test_scan_defaults_to_images_only(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    image = root / "image.jpg"
    doc = root / "doc.pdf"
    audio = root / "track.flac"
    image.write_bytes(b"img")
    doc.write_bytes(b"pdf")
    audio.write_bytes(b"audio")

    called_with: list[str] = []

    def fake_run(_path, files):
        called_with.extend(str(path) for path in files)
        return ([{"SourceFile": str(path)} for path in files], None)

    monkeypatch.setattr("app.core.scanner.run_exiftool", fake_run)

    db_path = tmp_path / "test.db"
    db = Database(db_path)
    result = scan(
        db,
        default_config(),
        root,
        selections=[DirectorySelection(path=root, recursive=True, include_root_files=True)],
        images_only=True,
        errors_log_path=tmp_path / "errors.jsonl",
        db_path=db_path,
    )

    rows = db.conn.execute("SELECT rel_path, type FROM files ORDER BY rel_path").fetchall()
    db.close()

    assert result.stats.images == 1
    assert result.stats.videos == 0
    assert called_with == [str(image)]
    assert [(row["rel_path"], row["type"]) for row in rows] == [("image.jpg", "image")]
