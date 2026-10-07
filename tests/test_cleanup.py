from datetime import datetime, timezone
import os
from unittest.mock import Mock

import pytest
from redis.exceptions import ConnectionError
from rq.exceptions import NoSuchJobError

import cleanup

NOW = 2_000_000_000


def upload(root, name="a", days=8, marker="consent.json"):
    directory = root / (name * 64)
    directory.mkdir()
    for filename in (marker, "form.pdf"):
        (directory / filename).write_text("synthetic")
        os.utime(directory / filename, (NOW - days * 86400,) * 2)
    os.utime(directory, (NOW - days * 86400,) * 2)
    return directory


def test_expired_upload_removed_with_expired_job_record(tmp_path, monkeypatch):
    directory = upload(tmp_path)
    monkeypatch.setattr(cleanup.Job, "fetch", Mock(side_effect=NoSuchJobError))
    assert cleanup.cleanup(tmp_path, Mock(), now=NOW) == 1
    assert not directory.exists()


@pytest.mark.parametrize("status", ["queued", "started", "deferred", "scheduled", None])
def test_active_or_unknown_job_is_preserved(tmp_path, monkeypatch, status):
    directory = upload(tmp_path)
    monkeypatch.setattr(cleanup.Job, "fetch", Mock(return_value=Mock(get_status=Mock(return_value=status))))
    assert cleanup.cleanup(tmp_path, Mock(), now=NOW) == 0
    assert directory.exists()


def test_recent_files_dry_run_and_legacy_results(tmp_path, monkeypatch):
    recent = upload(tmp_path, "a", days=7)
    legacy = upload(tmp_path, "b", marker="stats.json")
    unknown = upload(tmp_path, "c", marker="unrelated.txt")
    modified = upload(tmp_path, "d")
    os.utime(modified / "form.pdf", (NOW,) * 2)
    monkeypatch.setattr(cleanup.Job, "fetch", Mock(side_effect=NoSuchJobError))
    assert cleanup.cleanup(tmp_path, Mock(), dry_run=True, now=NOW) == 1
    assert legacy.exists()
    assert cleanup.cleanup(tmp_path, Mock(), now=NOW) == 1
    assert all(d.exists() for d in (recent, unknown, modified))
    assert not legacy.exists()


def test_redis_outage_preserves_files(tmp_path):
    directory = upload(tmp_path)
    with pytest.raises(ConnectionError):
        cleanup.cleanup(tmp_path, Mock(ping=Mock(side_effect=ConnectionError)), now=NOW)
    assert directory.exists()


def test_symlinks_not_followed(tmp_path, monkeypatch):
    directory = upload(tmp_path)
    (tmp_path / ("b" * 64)).symlink_to(directory, target_is_directory=True)
    (directory / "linked.pdf").symlink_to(directory / "form.pdf")
    os.utime(directory, (NOW - 8 * 86400,) * 2)
    monkeypatch.setattr(cleanup.Job, "fetch", Mock(side_effect=NoSuchJobError))
    assert cleanup.cleanup(tmp_path, Mock(), now=NOW) == 0
    assert directory.exists()


def test_failed_legacy_upload_with_known_job_removed(tmp_path, monkeypatch):
    directory = upload(tmp_path, marker="legacy.docx")
    monkeypatch.setattr(cleanup.Job, "fetch", Mock(return_value=Mock(get_status=Mock(return_value="failed"))))
    assert cleanup.cleanup(tmp_path, Mock(), now=NOW) == 1
    assert not directory.exists()


def test_next_weekly_run():
    before = datetime(2026, 10, 11, 2, 59, tzinfo=timezone.utc)
    at = datetime(2026, 10, 11, 3, tzinfo=timezone.utc)
    assert cleanup.next_run(before) == at
    assert cleanup.next_run(at) == datetime(2026, 10, 18, 3, tzinfo=timezone.utc)
