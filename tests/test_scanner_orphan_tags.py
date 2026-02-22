from __future__ import annotations

from pathlib import Path

from app.core.config import default_config
from app.core.db import Database
from app.core.models import DirectorySelection
from app.core.scanner import scan


def test_scan_prunes_orphan_tags_after_index(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    image = root / "image.jpg"
    image.write_bytes(b"img")

    def fake_run(_path, files):
        return ([{"SourceFile": str(path)} for path in files], None)

    monkeypatch.setattr("app.core.scanner.run_exiftool", fake_run)

    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.conn.execute(
        "INSERT INTO tags (tag, kind, source) VALUES (?, ?, ?)",
        ("Algéria 1972", "subject", "xmp-dc"),
    )
    db.commit()

    before = db.conn.execute("SELECT COUNT(*) AS c FROM tags").fetchone()
    assert before is not None and int(before["c"]) == 1

    scan(
        db,
        default_config(),
        root,
        selections=[DirectorySelection(path=root, recursive=True, include_root_files=True)],
        include_videos=False,
        include_docs=False,
        include_audio=False,
        video_tags=False,
        errors_log_path=tmp_path / "errors.jsonl",
        db_path=db_path,
    )

    after = db.conn.execute("SELECT COUNT(*) AS c FROM tags").fetchone()
    db.close()

    assert after is not None and int(after["c"]) == 0
