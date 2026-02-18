# Changelog

## 1.1.0 - 2026-02-18

### Added
- CLI option `--images-only yes|no` (default `yes`) to limit scans to image files.
- GUI `Images only` checkbox (default checked) to match CLI behavior.
- Tests for CLI parsing and scanner default image-only filtering.

## 1.0.1 - 2026-02-09

### Added
- Warnings counter and non-fatal handling for ExifTool exit code 1.
- JSONL error logging for per-file failures with configurable path.

### Fixed
- Treat ExifTool warnings as non-fatal when JSON parses successfully.

## 1.0.0 - 2026-02-09

### Added
- PyQt GUI for DB selection, scan root discovery, tri-state directory selection, progress, and reports.
- Headless CLI mode with interactive prompts, JSON/text reports, and cancellation handling.
- SQLite schema with migrations, indexing, and scan status tracking.
- ExifTool integration with JSON capture and normalized tag extraction.
- taken_ts derivation with provenance tracking and taken_src distribution reporting.
- Configurable hashing and MIME detection.
- Scan reports with export to JSON/CSV and taken_src distribution.

### Changed
- Unified scan engine for GUI and CLI with dry-run support.
- Per-directory transactional scanning with cancel-safe rollback.

### Fixed
- Robust tag normalization and rescan synchronization for file_tags.
