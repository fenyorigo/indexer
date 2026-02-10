from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.exiftool import ExiftoolError, ExiftoolParseError, run_exiftool


def _fake_run(returncode: int, stdout: str, stderr: str = ""):
    def _runner(*_args, **_kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return _runner


def test_run_exiftool_rc1_valid_json(monkeypatch):
    stdout = json.dumps([{"SourceFile": "/tmp/a.jpg"}])
    monkeypatch.setattr("subprocess.run", _fake_run(1, stdout, "17 image files read"))
    records, warning = run_exiftool("exiftool", ["/tmp/a.jpg"])
    assert len(records) == 1
    assert warning == "17 image files read"


def test_run_exiftool_rc2_fatal(monkeypatch):
    monkeypatch.setattr("subprocess.run", _fake_run(2, "", "fatal"))
    with pytest.raises(ExiftoolError):
        run_exiftool("exiftool", ["/tmp/a.jpg"])


def test_run_exiftool_invalid_json(monkeypatch):
    monkeypatch.setattr("subprocess.run", _fake_run(1, "not json", "warn"))
    with pytest.raises(ExiftoolParseError):
        run_exiftool("exiftool", ["/tmp/a.jpg"])
