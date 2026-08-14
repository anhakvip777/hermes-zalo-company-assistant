from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from follow_up import FollowUpService, classify_response
from history_store import HistoryStore


@dataclass(frozen=True)
class FakeSendResult:
    success: bool
    message_id: str | None = None
    raw_response: dict[str, object] | None = None


def _fixed_now() -> datetime:
    return datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)


def _service(
    tmp_path: Path,
    *,
    allowed_users: set[str] | None = None,
    send_dm=None,
) -> tuple[FollowUpService, HistoryStore, list[tuple[str, str]]]:
    store = HistoryStore(tmp_path / "history.sqlite3")
    sent: list[tuple[str, str]] = []

    async def default_send(target_id: str, text: str) -> FakeSendResult:
        sent.append((target_id, text))
        return FakeSendResult(success=True, message_id=f"provider-{target_id}")

    service = FollowUpService(
        store=store,
        allowed_users=lambda: set(allowed_users or {"u-1"}),
        send_dm=send_dm or default_send,
        now=_fixed_now,
    )
    return service, store, sent


@pytest.mark.asyncio
async def test_create_rejects_non_allowlisted_target_before_persist_or_send(
    tmp_path: Path,
) -> None:
    service, store, sent = _service(tmp_path)

    with pytest.raises(ValueError, match="allowlist"):
        await service.create(
            owner_id="admin",
            title="Họp",
            question="Có họp không?",
            targets=[{"zalo_id": "outside"}],
            due_at="2026-08-15T10:00:00+00:00",
        )

    assert sent == []
    assert store.connection.execute("SELECT count(*) FROM follow_ups").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_create_persists_all_targets_before_sending_and_records_outcome(
    tmp_path: Path,
) -> None:
    observed_counts: list[int] = []
    service, store, sent = _service(tmp_path)

    async def send_after_persist(target_id: str, text: str) -> FakeSendResult:
        observed_counts.append(
            store.connection.execute("SELECT count(*) FROM follow_up_targets").fetchone()[0]
        )
        sent.append((target_id, text))
        return FakeSendResult(success=True, message_id=f"provider-{target_id}")

    service.send_dm = send_after_persist
    result = await service.create(
        owner_id="admin",
        title="Họp",
        question="Có họp không?",
        targets=[{"zalo_id": "u-1", "name": "Lan"}],
        due_at="2026-08-15T10:00:00+00:00",
    )

    assert result["targets"][0]["state"] == "awaiting_response"
    assert observed_counts == [1]
    assert sent == [("u-1", "Có họp không?")]


def test_response_matching_requires_exact_dm_and_timestamp_and_is_idempotent(
    tmp_path: Path,
) -> None:
    service, store, _sent = _service(tmp_path)
    follow_up_id = store.create_follow_up(
        owner_id="admin",
        title="Họp",
        question_text="Có họp không?",
        due_at="2026-08-15T10:00:00+00:00",
        targets=[{"target_id": "u-1", "target_name": "Lan"}],
        created_at="2026-08-14T08:00:00+00:00",
    )
    assert store.claim_initial_target(follow_up_id, "u-1") is not None
    assert store.complete_initial_target(
        follow_up_id,
        "u-1",
        state="awaiting_response",
        provider_message_id="initial-1",
        sent_at="2026-08-14T09:00:00+00:00",
    ) is not None

    assert service.record_inbound_response(
        stored_message_id=10,
        sender_id="u-1",
        thread_type="group",
        thread_id="group-1",
        sent_at="2026-08-14T11:00:00+00:00",
        text="Có",
    ) == []
    assert service.record_inbound_response(
        stored_message_id=11,
        sender_id="u-1",
        thread_type="dm",
        thread_id="u-1",
        sent_at="2026-08-14T09:00:00+00:00",
        text="Có",
    ) == []

    response_message = store.store_message(
        thread_type="dm",
        thread_id="u-1",
        sender_id="u-1",
        text="Có, mình tham gia",
        provider_message_id="response-1",
        sent_at="2026-08-14T11:00:00+00:00",
    )
    matched = service.record_inbound_response(
        stored_message_id=response_message.message_id,
        sender_id="u-1",
        thread_type="dm",
        thread_id="u-1",
        sent_at="2026-08-14T11:00:00+00:00",
        text="Có, mình tham gia",
    )
    assert matched == [
        {"follow_up_id": follow_up_id, "target_id": "u-1", "response_kind": "yes"}
    ]
    assert service.record_inbound_response(
        stored_message_id=response_message.message_id,
        sender_id="u-1",
        thread_type="dm",
        thread_id="u-1",
        sent_at="2026-08-14T11:00:00+00:00",
        text="Có, mình tham gia",
    ) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Có", "yes"), ("không tham gia", "no"), ("ko được", "no"), ("để xem", "other")],
)
def test_classify_response_is_deterministic(text: str, expected: str) -> None:
    assert classify_response(text) == expected


@pytest.mark.asyncio
async def test_initial_send_exception_is_recorded_as_unknown(tmp_path: Path) -> None:
    async def broken_send(_target_id: str, _text: str) -> FakeSendResult:
        raise TimeoutError("provider timeout")

    service, store, _sent = _service(tmp_path, send_dm=broken_send)
    result = await service.create(
        owner_id="admin",
        title="Họp",
        question="Có họp không?",
        targets=[{"zalo_id": "u-1"}],
        due_at="2026-08-15T10:00:00+00:00",
    )
    assert result["targets"][0]["state"] == "initial_unknown"
    assert store.follow_up_targets(result["follow_up_id"])[0]["state"] == "initial_unknown"


@pytest.mark.asyncio
async def test_tick_sends_one_reminder_then_one_report_to_owner(tmp_path: Path) -> None:
    service, store, sent = _service(tmp_path)
    result = await service.create(
        owner_id="admin-a",
        title="Xác nhận họp",
        question="Bạn có tham gia họp không?",
        targets=[{"zalo_id": "u-1", "name": "Lan"}],
        due_at="2026-08-15T10:00:00+00:00",
    )
    service.now = lambda: datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)

    first = await service.tick()
    second = await service.tick()

    assert first["reminders"] == 1
    assert first["reports"] == 1
    assert second == {"reminders": 0, "reports": 0}
    assert [recipient for recipient, _ in sent] == ["u-1", "u-1", "admin-a"]
    assert "Chưa phản hồi" in sent[-1][1]
    status = await service.status(follow_up_id=result["follow_up_id"])
    assert status["state"] == "awaiting_admin"
    assert status["targets"][0]["state"] == "reminded"
    assert store.connection.execute(
        "SELECT report_state FROM follow_ups WHERE id=?",
        (result["follow_up_id"],),
    ).fetchone()[0] == "sent"


@pytest.mark.asyncio
async def test_late_response_after_report_updates_target_without_second_report(
    tmp_path: Path,
) -> None:
    service, store, sent = _service(tmp_path)
    result = await service.create(
        owner_id="admin-a",
        title="Xác nhận họp",
        question="Bạn có tham gia họp không?",
        targets=[{"zalo_id": "u-1"}],
        due_at="2026-08-15T10:00:00+00:00",
    )
    service.now = lambda: datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
    await service.tick()
    before = len(sent)
    response = store.store_message(
        thread_type="dm",
        thread_id="u-1",
        sender_id="u-1",
        text="Có",
        provider_message_id="late-1",
        sent_at="2026-08-15T12:00:00+00:00",
    )
    matched = service.record_inbound_response(
        stored_message_id=response.message_id,
        sender_id="u-1",
        thread_type="dm",
        thread_id="u-1",
        sent_at="2026-08-15T12:00:00+00:00",
        text="Có",
    )
    assert matched[0]["response_kind"] == "yes"
    assert (await service.tick()) == {"reminders": 0, "reports": 0}
    assert len(sent) == before
    assert (await service.status(follow_up_id=result["follow_up_id"]))["targets"][0]["state"] == "responded"


def test_response_after_reminder_failure_is_still_matched(tmp_path: Path) -> None:
    service, store, _sent = _service(tmp_path)
    follow_up_id = store.create_follow_up(
        owner_id="admin",
        title="Họp",
        question_text="Có họp không?",
        due_at="2026-08-15T10:00:00Z",
        targets=[{"target_id": "u-1"}],
        created_at="2026-08-14T08:00:00Z",
    )
    assert store.claim_initial_target(follow_up_id, "u-1") is not None
    assert store.complete_initial_target(
        follow_up_id,
        "u-1",
        state="awaiting_response",
        provider_message_id="initial-1",
        sent_at="2026-08-14T09:00:00Z",
    ) is not None
    claims = store.claim_due_reminder_targets(now="2026-08-15T10:00:00Z")
    assert len(claims) == 1
    assert store.complete_reminder_target(
        claims[0]["id"], state="reminder_failed"
    ) is not None
    response = store.store_message(
        thread_type="dm",
        thread_id="u-1",
        sender_id="u-1",
        text="Có",
        provider_message_id="response-failed-reminder",
        sent_at="2026-08-15T11:00:00Z",
    )
    assert service.record_inbound_response(
        stored_message_id=response.message_id,
        sender_id="u-1",
        thread_type="dm",
        thread_id="u-1",
        sent_at="2026-08-15T11:00:00Z",
        text="Có",
    )[0]["response_kind"] == "yes"


@pytest.mark.asyncio
async def test_closed_follow_up_does_not_match_later_dm(tmp_path: Path) -> None:
    service, store, _sent = _service(tmp_path)
    follow_up_id = store.create_follow_up(
        owner_id="admin",
        title="Họp",
        question_text="Có họp không?",
        due_at="2026-08-15T10:00:00+00:00",
        targets=[{"target_id": "u-1"}],
        created_at="2026-08-14T08:00:00+00:00",
    )
    assert store.claim_initial_target(follow_up_id, "u-1") is not None
    assert store.complete_initial_target(
        follow_up_id,
        "u-1",
        state="awaiting_response",
        provider_message_id="initial-1",
        sent_at="2026-08-14T09:00:00+00:00",
    ) is not None
    assert service.close(actor_id="admin", follow_up_id=follow_up_id)["state"] == "closed"
    with pytest.raises(ValueError, match="closed"):
        await service.remind(actor_id="admin", follow_up_id=follow_up_id)
    response = store.store_message(
        thread_type="dm",
        thread_id="u-1",
        sender_id="u-1",
        text="Có",
        provider_message_id="late-closed",
        sent_at="2026-08-15T12:00:00+00:00",
    )
    assert service.record_inbound_response(
        stored_message_id=response.message_id,
        sender_id="u-1",
        thread_type="dm",
        thread_id="u-1",
        sent_at="2026-08-15T12:00:00+00:00",
        text="Có",
    ) == []


@pytest.mark.asyncio
async def test_restart_after_reminder_claim_records_unknown_without_resending(
    tmp_path: Path,
) -> None:
    service, store, sent = _service(tmp_path)
    result = await service.create(
        owner_id="admin-a",
        title="Xác nhận họp",
        question="Bạn có tham gia họp không?",
        targets=[{"zalo_id": "u-1"}],
        due_at="2026-08-15T10:00:00+00:00",
    )
    service.now = lambda: datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
    claims = store.claim_due_reminder_targets(now="2026-08-15T10:00:00+00:00")
    assert len(claims) == 1
    store.close()

    reopened = HistoryStore(tmp_path / "history.sqlite3")
    service.store = reopened
    await service.tick()

    assert [recipient for recipient, _ in sent] == ["u-1", "admin-a"]
    target = reopened.follow_up_targets(result["follow_up_id"])[0]
    assert target["state"] == "reminder_unknown"


@pytest.mark.asyncio
async def test_admin_extend_and_manual_remind_are_explicit_and_non_repeating(
    tmp_path: Path,
) -> None:
    service, _store, sent = _service(tmp_path)
    result = await service.create(
        owner_id="admin-a",
        title="Xác nhận họp",
        question="Bạn có tham gia họp không?",
        targets=[{"zalo_id": "u-1"}],
        due_at="2026-08-15T10:00:00+00:00",
    )
    service.now = lambda: datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
    await service.tick()

    extended = await service.extend(
        actor_id="admin-b",
        follow_up_id=result["follow_up_id"],
        due_at="2026-08-16T10:00:00+00:00",
    )
    assert extended["state"] == "active"
    assert extended["targets"][0]["state"] == "awaiting_response"

    manual = await service.remind(
        actor_id="admin-b",
        follow_up_id=result["follow_up_id"],
        target_ids=["u-1"],
    )
    assert manual == {"success": True, "follow_up_id": result["follow_up_id"], "reminded": 1}
    assert [recipient for recipient, _ in sent] == ["u-1", "u-1", "admin-a", "u-1"]
    assert (await service.status(follow_up_id=result["follow_up_id"]))["targets"][0]["state"] == "reminded"
