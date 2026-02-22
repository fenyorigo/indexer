from __future__ import annotations

from pathlib import Path

from app.core.config import default_config
from app.core.db import Database
from app.core.models import DirectorySelection
from app.core.scanner import scan


def test_video_present_but_no_file_tags_when_video_tags_disabled(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    video = root / "clip.mp4"
    video.write_bytes(b"video")

    def fake_run(_path, files):
        return (
            [
                {
                    "SourceFile": str(files[0]),
                    "UserData:Keywords": ["Holiday 1972", "Phone App"],
                    "XMP-dc:Subject": ["Algéria 1972"],
                }
            ],
            None,
        )

    monkeypatch.setattr("app.core.scanner.run_exiftool", fake_run)

    db_path = tmp_path / "test.db"
    db = Database(db_path)
    result = scan(
        db,
        default_config(),
        root,
        selections=[DirectorySelection(path=root, recursive=True, include_root_files=True)],
        include_videos=True,
        include_docs=False,
        include_audio=False,
        video_tags=False,
        errors_log_path=tmp_path / "errors.jsonl",
        db_path=db_path,
    )

    file_row = db.conn.execute("SELECT id, type FROM files WHERE rel_path = 'clip.mp4'").fetchone()
    tag_rows = db.conn.execute("SELECT COUNT(*) AS c FROM file_tags").fetchone()
    db.close()

    assert result.stats.videos == 1
    assert file_row is not None
    assert file_row["type"] == "video"
    assert int(tag_rows["c"]) == 0


def test_docs_and_audio_excluded_by_default(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "image.jpg").write_bytes(b"img")
    (root / "movie.mp4").write_bytes(b"vid")
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
        errors_log_path=tmp_path / "errors.jsonl",
        db_path=db_path,
    )
    rows = db.conn.execute("SELECT rel_path, type FROM files ORDER BY rel_path").fetchall()
    db.close()

    assert [(row["rel_path"], row["type"]) for row in rows] == [
        ("image.jpg", "image"),
        ("movie.mp4", "video"),
    ]
