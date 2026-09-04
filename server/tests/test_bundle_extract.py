"""APK bundle extraction must not evaluate a caller-controlled path in a shell."""
import sys
from pathlib import Path

import pytest

_CLI = Path(__file__).resolve().parent.parent / "cli"
if str(_CLI) not in sys.path:
    sys.path.insert(0, str(_CLI))

import bundle_extract


def test_extract_uses_literal_subprocess_arguments(tmp_path, monkeypatch):
    apk = tmp_path / "client; touch SHOULD_NOT_RUN.apk"
    apk.touch()
    destination = tmp_path / "bundles; not a command"
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(bundle_extract.subprocess, "run", fake_run)
    bundle_extract.extract_android_bundles(apk, destination)

    assert destination.is_dir()
    assert calls == [
        (["unzip", "-j", "-o", str(apk), "assets/aa/Android/*", "-d", str(destination)],
         {"check": True})
    ]


def test_extract_rejects_missing_apk_before_running_unzip(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle_extract.subprocess, "run", lambda *_a, **_k: pytest.fail("unzip ran"))
    with pytest.raises(FileNotFoundError):
        bundle_extract.extract_android_bundles(tmp_path / "missing.apk", tmp_path / "bundles")
