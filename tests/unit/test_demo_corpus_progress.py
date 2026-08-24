"""Progress payload and stale-heartbeat checks for corpus ingestion."""

from collections import Counter
from datetime import UTC, datetime, timedelta

from legal_chatbot.demo_corpus.cli import _progress_payload
from legal_chatbot.demo_corpus.status_cli import _is_stale


def test_progress_payload_is_bounded_and_reports_eta() -> None:
    payload = _progress_payload(
        processed=2,
        total=10,
        entry=None,
        outcome="indexed",
        outcomes=Counter(indexed=2),
        started_at=0.0,
    )

    assert payload["processed"] == 2
    assert payload["total"] == 10
    assert payload["counts"] == {"indexed": 2}
    assert payload["eta_seconds"] is not None
    assert "title" not in payload
    assert "file_url" not in payload


def test_status_marks_only_old_running_heartbeats_stale() -> None:
    recent = datetime.now(UTC).isoformat()
    old = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()

    assert not _is_stale(
        {"status": "RUNNING", "summary": {"updated_at": recent}}, 300
    )
    assert _is_stale({"status": "RUNNING", "summary": {"updated_at": old}}, 300)
    assert not _is_stale({"status": "COMPLETED", "summary": {"updated_at": old}}, 300)
