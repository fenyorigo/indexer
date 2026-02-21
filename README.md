# Photo Indexer

Cross-platform (macOS + Fedora) photo/video indexer that scans a directory tree and stores metadata in a single SQLite database. The GUI is built with PyQt6.

## Requirements
- Python 3.11+
- ExifTool (external binary)

### macOS
- Install ExifTool: `brew install exiftool`

### Fedora
- Install ExifTool: `sudo dnf install exiftool`

## Setup
```bash
python3 -m pip install -r requirements.txt
```

## Run
```bash
python3 -m app
```

## CLI
Run headless scans with `--cli`:
```bash
source .venv/bin/activate
python3 -m app --cli --db /path/to/photos.db --root /path/to/photos
```

Important:
- `--images-only` defaults to `yes`.
- With default settings, videos/documents/audio are skipped.
- To include all supported file types, run with `--images-only no`.
- Non-image classification uses: `video` (`.mp4/.mov/.m4v/.avi`), `doc` (`.pdf/.txt/.doc/.docx/.xls/.xlsx/.ppt/.pptx`), `audio` (`.mp3/.m4a/.flac`).

Common options:
```bash
python3 -m app --cli --db /path/to/photos.db --root /path/to/photos --dry-run
python3 -m app --cli --db /path/to/photos.db --root /path/to/photos --changed-only
python3 -m app --cli --db /path/to/photos.db --root /path/to/photos --images-only no
python3 -m app --cli --db /path/to/photos.db --root /path/to/photos --include-root-files
python3 -m app --cli --db /path/to/photos.db --root /path/to/photos --json --report scan_report.json
python3 -m app --cli --db /path/to/photos.db --root /path/to/photos --errors-log /path/to/errors.jsonl
```

Fedora example:
```bash
python3 -m app --cli --db /home/user/photos.db --root /home/user/Pictures
```

macOS example:
```bash
python3 -m app --cli --db /Users/you/photos.db --root /Users/you/Pictures
```

## Migration
To migrate a v1 DB to v2:
```bash
python3 scripts/migrate_v1_to_v2.py /path/to/db.sqlite
```

## Config
Copy `config.sample.yaml` to `config.yaml` and edit as needed.
Key options:
- `hash_mode`: `none`, `quick`, `sha256`
- `mime_mode`: `ext`, `magic`, `filecmd`

## UI Tips
- `Only changed files` skips unchanged files (mtime/size check; also fills missing hashes if enabled).
- `Images only` is checked by default. Uncheck it to include videos, documents, audio, and other non-image files in scans.
- `Scan Report` exports the last scan summary (JSON/CSV).
- Use the status filter to view directory scan states.

## Schema
The current SQLite schema (v1) is in `schema.sql`.

## Notes
- SQLite DB schema is versioned via `PRAGMA user_version`.
- ExifTool integration is implemented in `app/core/exiftool.py`.
