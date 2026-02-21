from __future__ import annotations

from pathlib import Path

from app.core.config import default_config
from app.core.db import Database
from app.core.models import DirectorySelection
from app.core.scanner import scan


def test_scan_classifies_docs_and_audio_when_images_only_disabled(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()

    (root / "photo.jpg").write_bytes(b"img")
    (root / "movie.mp4").write_bytes(b"vid")
    (root / "legacy.doc").write_bytes(b"doc")
    (root / "sheet.xls").write_bytes(b"xls")
    (root / "slides.ppt").write_bytes(b"ppt")
    (root / "notes.txt").write_bytes(b"txt")
    (root / "paper.pdf").write_bytes(b"pdf")
    (root / "track.flac").write_bytes(b"aud")

    def fake_run(_path, files):
        return ([{"SourceFile": str(path)} for path in files], None)

    monkeypatch.setattr("app.core.scanner.run_exiftool", fake_run)

    db_path = tmp_path / "test.db"
    db = Database(db_path)
    scan(
        db,
        default_config(),
        root,
        selections=[DirectorySelection(path=root, recursive=True, include_root_files=True)],
        images_only=False,
        errors_log_path=tmp_path / "errors.jsonl",
        db_path=db_path,
    )

    rows = db.conn.execute("SELECT rel_path, type FROM files ORDER BY rel_path").fetchall()
    db.close()

    assert [(row["rel_path"], row["type"]) for row in rows] == [
        ("legacy.doc", "doc"),
        ("movie.mp4", "video"),
        ("notes.txt", "doc"),
        ("paper.pdf", "doc"),
        ("photo.jpg", "image"),
        ("sheet.xls", "doc"),
        ("slides.ppt", "doc"),
        ("track.flac", "audio"),
    ]
