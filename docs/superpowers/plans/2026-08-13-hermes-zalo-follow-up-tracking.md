# Kế hoạch triển khai theo dõi phản hồi Zalo nhiều ngày

> **Cho agent thực thi:** BẮT BUỘC dùng superpowers:subagent-driven-development (khuyên dùng) hoặc superpowers:executing-plans để triển khai từng task. Các bước dùng checkbox (- [ ]) để theo dõi.

**Mục tiêu:** Admin gửi một câu hỏi DM đến nhiều thành viên allowlist, theo dõi phản hồi bền vững nhiều ngày, nhắc tự động đúng một lần khi quá hạn, rồi báo cáo riêng cho admin sở hữu yêu cầu và chờ chỉ đạo.

**Kiến trúc:** SQLite Conversation Store là nguồn sự thật duy nhất. Migration 002 thêm state theo dõi; FollowUpService giữ state machine và claim nguyên tử; ZaloAdapter chỉ là điểm nối gửi/nhận và chạy một ticker asyncio cùng process hiện có. zalo_admin là bề mặt duy nhất để admin tạo, xem, gia hạn, nhắc thủ công hoặc đóng follow-up.

**Công nghệ:** Python 3.11+, SQLite/WAL, asyncio, Hermes Agent 0.19.0 tại eb52760564dbba2e5971fa54bd67384e281cd3b8, pytest và fake bridge hiện hữu.

---

## Checkpoint phiên làm việc

- Spec chuẩn: docs/superpowers/specs/2026-08-13-hermes-zalo-follow-up-tracking-design.md, được duyệt triển khai; source hiện tại ở commit 45c48d59 trên branch company-assistant-v1.
- Kiến trúc bất biến: Node bridge và Python adapter là hai process duy nhất; ticker nằm trong ZaloAdapter, không tạo cron/service/process mới. SQLite là nguồn sự thật, không dùng Hermes cron, terminal, prompt hay file JSON làm state follow-up.
- Migration bất biến: hermes-plugin/migrations/001_initial.sql SHA-256 1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a; mọi schema mới chỉ nằm trong 002_follow_up_tracking.sql.
- Policy khóa: chỉ DM của đúng target_id sau initial_sent_at mới hoàn thành target; group không bao giờ hoàn thành follow-up DM. Reminder tự động đúng một lần; report chỉ gửi DM của owner_id; sau report trạng thái là awaiting_admin.
- Baseline trước triển khai: `git status --short` sạch; `python scripts/acceptance.py --static --json` trả `ok: true` ngày 2026-08-14. Sau Task 1, working tree giữ nguyên các thay đổi tài liệu đã có và thêm đúng migration/store/test trong phạm vi task.
- File manifest hiện đã đăng ký toàn bộ path mới và path sửa; không sửa Node bridge, Admin Web API, systemd hay `001_initial.sql`.
- Task 1 evidence: test migration/claim/recovery đỏ trước production code; sau đó `tests/python/test_history_store.py` đạt `31 passed`, gồm purge response giữ outcome. Migration `002` và API persistence dùng transaction/claim có điều kiện.
- Task 2–5 evidence: FollowUpService, one-time reminder/report, recovery, adapter ticker/store-first, `zalo_admin` admin boundary và integration DM/group đều đã triển khai; targeted Python/integration suite đạt `208 passed`, sau regression cuối toàn bộ Python đạt `250 passed`.
- Verification mới nhất: Node `67/67 PASS`; Python `250 passed`; full acceptance `ok: true`; `npm audit --omit=dev` báo `0 vulnerabilities`; `python -m pip check` sạch; checksum `001_initial.sql` đúng `1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a`; `npm pack --dry-run --json` có `hermes-plugin/follow_up.py` và migration `002`; `git diff --check` exit `0`.
- Việc tiếp theo: đánh dấu các bước kế hoạch đã hoàn tất, chạy lại verification sau checkpoint, rồi commit thay đổi. Chưa push/tag nếu người dùng chưa yêu cầu.

## Bản đồ file

| File | Hành động | Trách nhiệm sau triển khai |
|---|---|---|
| docs/architecture/file-manifest.md | Sửa | Đăng ký tất cả file follow-up trước code |
| docs/architecture/system-overview.md | Sửa | Ghi ticker nội bộ và ranh giới follow-up |
| docs/architecture/database-schema.md | Sửa | Ghi bảng/state/index migration 002 |
| docs/operations/acceptance-checklist.md | Sửa | Checklist vận hành, recovery và retention |
| hermes-plugin/migrations/002_follow_up_tracking.sql | Tạo | Bảng/index/check state bền vững |
| hermes-plugin/history_store.py | Sửa | Persistence có transaction và claim có điều kiện |
| hermes-plugin/follow_up.py | Tạo | Quy tắc nghiệp vụ, outcome, report, orchestration |
| hermes-plugin/adapter.py | Sửa | Gửi DM, match inbound store-first và ticker nội bộ |
| hermes-plugin/admin.py | Sửa | Route năm action admin-only đến service |
| hermes-plugin/tooling.py | Sửa | Schema zalo_admin cho payload follow-up |
| tests/python/test_history_store.py | Sửa | Migration/foreign-key/claim persistence |
| tests/python/test_follow_up.py | Tạo | State machine và recovery độc lập Hermes |
| tests/python/test_adapter.py | Sửa | Inbound DM-only và ticker outbound |
| tests/python/test_tooling.py | Sửa | Admin boundary và allowlist validation |
| tests/integration/test_company_assistant_flow.py | Sửa | Luồng DM/group/report owner end-to-end |
| tests/integration/test_restart.py | Sửa nếu cần | Reopen DB sau claim dở dang không gửi lại |

## Hợp đồng nghiệp vụ khóa

| Public method | Dữ liệu vào bắt buộc | Kết quả khóa |
|---|---|---|
| `create` | `owner_id`, `title`, `question`, `targets`, `due_at` | Tạo toàn bộ target trước outbound và trả outcome từng target |
| `record_inbound_response` | Stored message, sender, thread, timestamp, text | Chỉ update target DM hợp lệ và trả các target được ghép |
| `tick` | Không có | Claim reminder/report đến hạn, không tự retry outcome unknown |
| `status` | optional `follow_up_id` | Admin xem được mọi follow-up; member không thể vào tool |
| `extend`, `remind`, `close` | `actor_id`, follow-up ID và input tương ứng | Mọi admin có thể vận hành; report tự động vẫn chỉ về owner |

### Quy ước fixture trong các test của kế hoạch

- `make_service(tmp_path, send_dm=None, now=None)` tạo `HistoryStore` tạm và
  `FollowUpService`; callback mặc định trả `{success: True, message_id: "provider-1"}`
  và ghi danh sách recipient/text để assertion.
- `create_waiting_target(service, owner_id, target_id, due_at)` gọi create,
  claim initial và complete initial với `awaiting_response`; helper trả ID
  follow-up.
- `create_waiting_target_in_store(store, due_at)` tạo cùng state trực tiếp để
  kiểm tra recovery mà không gọi network.
- Các test tooling dùng fixture đã có trong tests/python/test_tooling.py:
  `config`, `requester`, `bind_requester`, `FakeBridge`, `HistoryStore` và
  `ZaloTooling`; helper `make_tooling_with_follow_up_service` chỉ thêm
  `FollowUpService` với callback gửi giả và trả `(tooling, sent)`.
- Test integration dùng `company_config`, `ZaloAdapter`, `MediaPolicy` và
  `HistoryStore` như test real adapter hiện có; thay `adapter.send` bằng callback
  ghi recipient để không gọi bridge thật. Helper tên
  `make_real_adapter_with_fake_send` trả `(adapter, sent)`; `create_follow_up_as`
  gọi tool dưới requester admin. `group_message` là dict có `threadType=group`,
  `threadId`, `senderId`, `text`, `mentions` và `ts`.

- follow_ups.state: active, awaiting_admin, closed.
- follow_ups.report_state: pending, sending, sent, unknown.
- follow_up_targets.state: initial_sending, awaiting_response, initial_failed, initial_unknown, reminder_sending, reminded, reminder_failed, reminder_unknown, responded.
- Mọi claim ghi trạng thái *_sending trước I/O. Recovery đổi mọi claim dở dang thành *_unknown; không có retry tự động.
- Một DM hợp lệ cập nhật tối đa một lần cho từng target phù hợp; event duplicate không cập nhật lại. Khi messages bị retention/delete, response_message_id thành NULL nhưng outcome đã ghi vẫn còn.

---

### Task 1: Migration 002 và persistence atomic của HistoryStore

**Files:**
- Create: hermes-plugin/migrations/002_follow_up_tracking.sql
- Modify: hermes-plugin/history_store.py
- Modify: tests/python/test_history_store.py

- [x] **Bước 1: Viết test migration đỏ**

Thêm test này vào tests/python/test_history_store.py:

~~~python
def test_follow_up_migration_creates_state_tables(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    tables = {
        row["name"]
        for row in store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"follow_ups", "follow_up_targets"} <= tables
    foreign_keys = store.connection.execute(
        "PRAGMA foreign_key_list(follow_up_targets)"
    ).fetchall()
    assert any(
        row["table"] == "follow_ups" and row["on_delete"] == "CASCADE"
        for row in foreign_keys
    )
    assert any(
        row["table"] == "messages" and row["on_delete"] == "SET NULL"
        for row in foreign_keys
    )
~~~

- [x] **Bước 2: Chạy test đỏ**

Run: python -m pytest -q tests/python/test_history_store.py::test_follow_up_migration_creates_state_tables

Expected: FAIL vì table follow_ups chưa tồn tại.

- [x] **Bước 3: Thêm migration chỉ bổ sung schema**

Tạo 002_follow_up_tracking.sql, không sửa byte nào của 001_initial.sql:

~~~sql
CREATE TABLE follow_ups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id TEXT NOT NULL,
    title TEXT NOT NULL,
    question_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    due_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'awaiting_admin', 'closed')),
    report_state TEXT NOT NULL CHECK (report_state IN ('pending', 'sending', 'sent', 'unknown')),
    report_claimed_at TEXT,
    report_sent_at TEXT,
    closed_at TEXT
);

CREATE TABLE follow_up_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    follow_up_id INTEGER NOT NULL REFERENCES follow_ups(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL,
    target_name TEXT,
    state TEXT NOT NULL CHECK (state IN (
        'initial_sending', 'awaiting_response', 'initial_failed', 'initial_unknown',
        'reminder_sending', 'reminded', 'reminder_failed', 'reminder_unknown', 'responded'
    )),
    initial_claimed_at TEXT,
    initial_provider_message_id TEXT,
    initial_sent_at TEXT,
    response_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    response_at TEXT,
    response_kind TEXT CHECK (response_kind IN ('yes', 'no', 'other')),
    reminder_provider_message_id TEXT,
    reminder_claimed_at TEXT,
    reminder_sent_at TEXT,
    UNIQUE (follow_up_id, target_id)
);

CREATE INDEX follow_up_targets_pending_due_idx ON follow_up_targets(state, follow_up_id);
CREATE INDEX follow_up_targets_target_response_idx ON follow_up_targets(target_id, state, initial_sent_at);
CREATE INDEX follow_ups_state_due_idx ON follow_ups(state, due_at);
~~~

- [x] **Bước 4: Chạy migration xanh và regression checksum**

Run:

~~~powershell
python -m pytest -q tests/python/test_history_store.py::test_follow_up_migration_creates_state_tables
(Get-FileHash hermes-plugin/migrations/001_initial.sql -Algorithm SHA256).Hash.ToLower()
~~~

Expected: test PASS; checksum exactly 1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a.

- [x] **Bước 5: Viết test đỏ cho claim/recovery**

~~~python
def test_follow_up_claim_is_atomic_and_recovery_marks_unknown(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    follow_up_id = store.create_follow_up(
        owner_id="admin",
        title="Họp",
        question_text="Có họp không?",
        due_at="2026-08-15T10:00:00+00:00",
        targets=[{"target_id": "u-1", "target_name": "Lan"}],
    )
    target = store.claim_initial_target(follow_up_id, "u-1")
    assert target["state"] == "initial_sending"
    assert store.claim_initial_target(follow_up_id, "u-1") is None
    assert store.recover_follow_up_claims() == {
        "initial_unknown": 1, "reminder_unknown": 0, "report_unknown": 0,
    }
    assert store.follow_up_targets(follow_up_id)[0]["state"] == "initial_unknown"
~~~

- [x] **Bước 6: Chạy test đỏ**

Run: python -m pytest -q tests/python/test_history_store.py::test_follow_up_claim_is_atomic_and_recovery_marks_unknown

Expected: FAIL vì API persistence chưa tồn tại.

- [x] **Bước 7: Thêm API store nhỏ, transaction-safe**

Thêm vào HistoryStore các phương thức `create_follow_up`, `follow_up_targets`,
`claim_initial_target`, `complete_initial_target`,
`claim_due_reminder_targets`, `complete_reminder_target`, `claim_due_reports`,
`complete_follow_up_report` và `recover_follow_up_claims`. Tất cả dùng
`self._lock`, nhận kiểu dữ liệu đúng như các test ở Bước 5 và trả dict/list
đã qua `_row` thay vì `sqlite3.Row`.

Claim phải có dạng `UPDATE follow_up_targets SET state=? WHERE id=? AND state=?` trong cùng transaction và chỉ trả row khi `cursor.rowcount == 1`; không query rồi update ngoài lock.

- [x] **Bước 8: Chạy targeted store tests xanh**

Run: python -m pytest -q tests/python/test_history_store.py

Expected: PASS, gồm test migration mới và recovery claim.

- [ ] **Bước 9: Commit checkpoint persistence**

~~~powershell
git add hermes-plugin/migrations/002_follow_up_tracking.sql hermes-plugin/history_store.py tests/python/test_history_store.py
git commit -m "feat: add persistent follow-up tracking state"
~~~

---

### Task 2: FollowUpService tạo DM, ghép phản hồi và state machine

**Files:**
- Create: hermes-plugin/follow_up.py
- Create: tests/python/test_follow_up.py

- [x] **Bước 1: Viết test đỏ target allowlist và store trước outbound**

~~~python
@pytest.mark.asyncio
async def test_create_persists_before_sending_and_rejects_non_allowed_target(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    async def send_dm(target_id: str, text: str) -> SendResult:
        calls.append((target_id, text))
        return SendResult(success=True, message_id=f"m-{target_id}")

    service = FollowUpService(
        store=HistoryStore(tmp_path / "history.sqlite3"),
        allowed_users=lambda: {"u-1"},
        send_dm=send_dm,
    )
    with pytest.raises(ValueError, match="allowlist"):
        await service.create(
            owner_id="admin", title="Họp", question="Có họp không?",
            targets=[{"zalo_id": "outside"}],
            due_at="2026-08-15T10:00:00+00:00",
        )
    assert calls == []
~~~

- [x] **Bước 2: Chạy test đỏ**

Run: python -m pytest -q tests/python/test_follow_up.py::test_create_persists_before_sending_and_rejects_non_allowed_target

Expected: FAIL vì module/service chưa có.

- [x] **Bước 3: Implement create tối thiểu**

FollowUpService.create phải parse due_at thành UTC future, chuẩn hóa target và gọi store.create_follow_up trước await send_dm. Với từng target, claim initial_sending, gửi câu hỏi, rồi complete bằng awaiting_response, initial_failed hoặc initial_unknown:

~~~python
def _send_outcome(result: SendResult, *, phase: str) -> tuple[str, str | None]:
    raw = result.raw_response if isinstance(result.raw_response, Mapping) else {}
    if result.success:
        return ("awaiting_response" if phase == "initial" else "reminded",
                str(result.message_id or "") or None)
    if str(raw.get("outcome") or "").lower() == "unknown":
        return (f"{phase}_unknown", None)
    return (f"{phase}_failed", None)
~~~

- [x] **Bước 4: Chạy test xanh**

Run: python -m pytest -q tests/python/test_follow_up.py::test_create_persists_before_sending_and_rejects_non_allowed_target

Expected: PASS.

- [x] **Bước 5: Viết test đỏ DM-only, timestamp và classification**

~~~python
def test_record_inbound_response_only_matches_target_dm_after_initial_send(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    follow_up_id = create_waiting_target(
        service, target_id="u-1", sent_at="2026-08-14T09:00:00+00:00"
    )
    assert service.record_inbound_response(
        stored_message_id=10, sender_id="u-1", thread_type="group",
        thread_id="g-1", sent_at="2026-08-14T11:00:00+00:00", text="Có",
    ) == []
    assert service.record_inbound_response(
        stored_message_id=11, sender_id="u-1", thread_type="dm",
        thread_id="u-1", sent_at="2026-08-14T08:59:59+00:00", text="Có",
    ) == []
    assert service.record_inbound_response(
        stored_message_id=12, sender_id="u-1", thread_type="dm",
        thread_id="u-1", sent_at="2026-08-14T11:00:00+00:00",
        text="Có, mình tham gia",
    ) == [{"follow_up_id": follow_up_id, "target_id": "u-1", "response_kind": "yes"}]
~~~

- [x] **Bước 6: Chạy test đỏ**

Run: python -m pytest -q tests/python/test_follow_up.py::test_record_inbound_response_only_matches_target_dm_after_initial_send

Expected: FAIL vì matching/state update chưa có.

- [x] **Bước 7: Implement classification và update có điều kiện**

~~~python
def classify_response(text: str) -> str:
    normalized = str(text or "").strip().casefold()
    if normalized.startswith("có"):
        return "yes"
    if normalized.startswith("không") or normalized.startswith("ko"):
        return "no"
    return "other"
~~~

record_inbound_response chỉ cho thread_type == "dm", thread_id == sender_id và sent_at > initial_sent_at. Store update dùng WHERE state IN ('awaiting_response', 'reminded') AND response_message_id IS NULL.

- [x] **Bước 8: Chạy service suite xanh**

Run: python -m pytest -q tests/python/test_follow_up.py

Expected: PASS cho allowed target, DM/group, before/after send và response yes/no/other.

- [ ] **Bước 9: Commit state machine**

~~~powershell
git add hermes-plugin/follow_up.py tests/python/test_follow_up.py
git commit -m "feat: add follow-up workflow service"
~~~

---

### Task 3: Reminder một lần, report owner và recovery

**Files:**
- Modify: hermes-plugin/follow_up.py
- Modify: hermes-plugin/history_store.py
- Modify: tests/python/test_follow_up.py
- Modify: tests/integration/test_restart.py

- [x] **Bước 1: Viết test đỏ reminder/report**

~~~python
@pytest.mark.asyncio
async def test_tick_sends_one_reminder_then_one_report_to_owner(tmp_path: Path) -> None:
    sent: list[tuple[str, str]] = []

    async def send_dm(target_id: str, text: str) -> SendResult:
        sent.append((target_id, text))
        return SendResult(success=True, message_id=f"m-{len(sent)}")

    service = make_service(
        tmp_path, send_dm=send_dm, now="2026-08-15T10:00:00+00:00"
    )
    follow_up_id = create_waiting_target(
        service, owner_id="admin-a", target_id="u-1",
        due_at="2026-08-15T09:00:00+00:00",
    )
    await service.tick()
    await service.tick()
    assert [recipient for recipient, _ in sent] == ["u-1", "admin-a"]
    status = await service.status(follow_up_id=follow_up_id)
    assert status["state"] == "awaiting_admin"
    assert status["targets"][0]["state"] == "reminded"
~~~

- [x] **Bước 2: Chạy test đỏ**

Run: python -m pytest -q tests/python/test_follow_up.py::test_tick_sends_one_reminder_then_one_report_to_owner

Expected: FAIL vì tick chưa claim/send/report.

- [x] **Bước 3: Implement tick, recovery và report render**

tick gọi store.recover_follow_up_claims khi service khởi động; claim reminder khi due_at <= now. Với mỗi target gửi text cố định:

~~~python
REMINDER_TEMPLATE = "Nhắc bạn phản hồi yêu cầu: {title}. Vui lòng trả lời khi có thể."
~~~

Khi tất cả target quá hạn có outcome, claim report_state='sending', render report từ SQLite và gửi duy nhất owner_id. Label report phải gồm Có, Không, Đã phản hồi khác, Chưa phản hồi, gửi lỗi hoặc không rõ kết quả. Dù report success hay unknown, complete_follow_up_report chuyển state follow_up sang awaiting_admin; unknown không retry.

- [x] **Bước 4: Chạy test xanh**

Run: python -m pytest -q tests/python/test_follow_up.py::test_tick_sends_one_reminder_then_one_report_to_owner

Expected: PASS; tick lần hai không có DM mới.

- [x] **Bước 5: Viết và chạy test recovery crash**

~~~python
def test_reopen_after_reminder_claim_marks_unknown_without_duplicate_send(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    follow_up_id = create_waiting_target_in_store(
        store, due_at="2026-08-14T09:00:00+00:00"
    )
    assert store.claim_due_reminder_targets(now="2026-08-14T10:00:00+00:00")
    store.close()

    reopened = HistoryStore(tmp_path / "history.sqlite3")
    assert reopened.recover_follow_up_claims()["reminder_unknown"] == 1
    assert reopened.claim_due_reminder_targets(now="2026-08-14T10:01:00+00:00") == []
    assert reopened.follow_up_targets(follow_up_id)[0]["state"] == "reminder_unknown"
~~~

Run: python -m pytest -q tests/python/test_follow_up.py::test_reopen_after_reminder_claim_marks_unknown_without_duplicate_send

Expected: FAIL trước recovery, PASS sau logic recovery; không duplicate outbound.

- [x] **Bước 6: Implement quyết định admin sau report**

extend chỉ re-open target chưa trả lời sang awaiting_response, reset report_state='pending' và không đổi responded. remind chỉ claim/send target admin chọn, không bật loop repeat. Tất cả admin đều được thực hiện action này qua AdminService; owner_id chỉ là đích của báo cáo tự động. close nhận actor_id để audit nhưng không owner-filtered:

~~~python
def close(self, *, actor_id: str, follow_up_id: int) -> dict[str, Any]:
    updated = self.store.close_follow_up(follow_up_id=follow_up_id)
    if not updated:
        raise ValueError("follow-up was not found")
    return {"success": True, "follow_up_id": follow_up_id, "state": "closed"}
~~~

- [x] **Bước 7: Chạy service/restart suite xanh**

Run: python -m pytest -q tests/python/test_follow_up.py tests/integration/test_restart.py

Expected: PASS, gồm response late, manual extend/remind, close, timeout và recovery.

- [ ] **Bước 8: Commit reminder/report/recovery**

~~~powershell
git add hermes-plugin/follow_up.py hermes-plugin/history_store.py tests/python/test_follow_up.py tests/integration/test_restart.py
git commit -m "feat: add one-time follow-up reminder and report"
~~~

---

### Task 4: Adapter store-first và ticker nội bộ

**Files:**
- Modify: hermes-plugin/adapter.py
- Modify: tests/python/test_adapter.py

- [x] **Bước 1: Viết test đỏ inbound order**

~~~python
@pytest.mark.asyncio
async def test_inbound_dm_records_follow_up_before_hermes_dispatch(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    observed: list[str] = []
    adapter.follow_ups.record_inbound_response = (
        lambda **kwargs: observed.append("follow-up") or []
    )
    adapter._message_handler = _capture_dispatch(observed)

    await adapter._on_inbound_message(
        _message("u-1", "Có", thread_type="user")
    )

    assert observed == ["follow-up", "hermes"]
~~~

- [x] **Bước 2: Chạy test đỏ**

Run: python -m pytest -q tests/python/test_adapter.py::test_inbound_dm_records_follow_up_before_hermes_dispatch

Expected: FAIL vì adapter chưa có service/call site.

- [x] **Bước 3: Wire service và inbound call**

Trong ZaloAdapter.__init__, tạo FollowUpService sau history_store; callback phải gọi self.send(target_id, text, metadata={"thread_type": "dm"}). Ngay sau if not stored.inserted: return, trước persist attachments/friend workflow/Hermes dispatch, thêm:

~~~python
if chat_type == "dm":
    self.follow_ups.record_inbound_response(
        stored_message_id=stored.message_id,
        sender_id=sender_id,
        thread_type="dm",
        thread_id=conversation_id,
        sent_at=sent_at,
        text=original_text,
    )
~~~

Không gọi cho group, non-allowlisted DM hoặc event trùng.

- [x] **Bước 4: Chạy test xanh**

Run: python -m pytest -q tests/python/test_adapter.py::test_inbound_dm_records_follow_up_before_hermes_dispatch

Expected: PASS.

- [x] **Bước 5: Viết test đỏ ticker lifecycle**

~~~python
@pytest.mark.asyncio
async def test_connect_starts_one_follow_up_ticker_and_disconnect_cancels_it(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    adapter._post = AsyncMock(
        return_value={"ok": True, "loggedIn": True, "ownId": "bot"}
    )
    await adapter.connect()
    first = adapter._follow_up_task
    await adapter.connect(is_reconnect=True)
    assert adapter._follow_up_task is first
    await adapter.disconnect()
    assert first.cancelled() or first.done()
~~~

- [x] **Bước 6: Chạy test đỏ**

Run: python -m pytest -q tests/python/test_adapter.py::test_connect_starts_one_follow_up_ticker_and_disconnect_cancels_it

Expected: FAIL vì ticker field/lifecycle chưa có.

- [x] **Bước 7: Implement ticker bridge-aware**

Thêm _follow_up_task, _ensure_follow_up_task và _follow_up_loop. Loop chỉ gọi await self.follow_ups.tick() khi self._bridge_available and self._zalo_logged_in; sleep 5 giây và log error đã redact. Start sau health/login hợp lệ; cancel/await task trong disconnect. Không tick khi bridge unavailable vì deadline vẫn bền vững trong SQLite.

- [x] **Bước 8: Chạy adapter suite xanh**

Run: python -m pytest -q tests/python/test_adapter.py

Expected: PASS cho DM/group gate, outbound store-first và ticker lifecycle.

- [ ] **Bước 9: Commit adapter integration**

~~~powershell
git add hermes-plugin/adapter.py tests/python/test_adapter.py
git commit -m "feat: integrate follow-up tracking with Zalo adapter"
~~~

---

### Task 5: Bề mặt zalo_admin, quyền và integration end-to-end

**Files:**
- Modify: hermes-plugin/admin.py
- Modify: hermes-plugin/tooling.py
- Modify: tests/python/test_tooling.py
- Modify: tests/integration/test_company_assistant_flow.py

- [x] **Bước 1: Viết test đỏ non-admin và target ngoài allowlist**

~~~python
@pytest.mark.asyncio
async def test_zalo_admin_follow_up_create_requires_admin_and_allowlisted_targets(
    tmp_path: Path,
) -> None:
    tooling, bridge = make_tooling_with_follow_up_service(
        tmp_path, allowed_users={"admin", "u-1"},
    )
    with bind_requester(requester("u-1", admin=False)):
        denied = json.loads(await tooling.zalo_admin({
            "action": "follow_up_create",
            "title": "Họp",
            "question": "Có?",
            "targets": [{"zalo_id": "u-1"}],
            "due_at": "2026-08-15T10:00:00Z",
        }))
    assert "error" in denied
    assert bridge.calls == []

    with bind_requester(requester("admin", admin=True)):
        rejected = json.loads(await tooling.zalo_admin({
            "action": "follow_up_create",
            "title": "Họp",
            "question": "Có?",
            "targets": [{"zalo_id": "outside"}],
            "due_at": "2026-08-15T10:00:00Z",
        }))
    assert "allowlist" in rejected["error"]
    assert bridge.calls == []
~~~

- [x] **Bước 2: Chạy test đỏ**

Run: python -m pytest -q tests/python/test_tooling.py::test_zalo_admin_follow_up_create_requires_admin_and_allowlisted_targets

Expected: FAIL vì admin action/service wiring chưa có.

- [x] **Bước 3: Wire service qua AdminService và schema**

AdminService.__init__ nhận follow_up_service. Giữ self.require(requester) đầu action() để toàn bộ năm action admin-only. Route create lấy owner_id từ requester, còn action mutate nhận actor_id để audit; không tin owner_id do model tự khai:

~~~python
if action == "follow_up_create":
    return await self.follow_up_service.create(
        owner_id=requester.requester_id,
        title=str(args.get("title") or ""),
        question=str(args.get("question") or ""),
        targets=args.get("targets") or [],
        due_at=str(args.get("due_at") or ""),
    )
if action == "follow_up_status":
    return await self.follow_up_service.status(
        follow_up_id=args.get("follow_up_id"),
    )
~~~

Thêm vào ZALO_ADMIN_SCHEMA các fields title, question, targets, due_at, follow_up_id và target_ids; không mở generic Zalo method.

- [x] **Bước 4: Chạy test xanh**

Run: python -m pytest -q tests/python/test_tooling.py::test_zalo_admin_follow_up_create_requires_admin_and_allowlisted_targets

Expected: PASS; tool_activity vẫn ghi blocked/failed phù hợp.

- [x] **Bước 5: Viết test integration DM/group/report owner**

~~~python
@pytest.mark.asyncio
async def test_follow_up_group_reply_never_completes_dm_target_and_report_goes_to_owner(
    tmp_path: Path,
) -> None:
    adapter, bridge = make_real_adapter_with_fake_send(
        tmp_path, admins={"admin-a", "admin-b"},
    )
    follow_up_id = await create_follow_up_as(
        adapter.tooling, owner_id="admin-a", targets=["u-1"],
    )
    await adapter._on_inbound_message(
        group_message("g-1", "u-1", text="Có")
    )
    await adapter.follow_ups.tick()

    recipients = [
        call["payload"]["threadId"]
        for call in bridge.calls
        if call["path"] == "/send"
    ]
    assert "admin-a" in recipients
    assert "admin-b" not in recipients
    status = await adapter.follow_ups.status(follow_up_id=follow_up_id)
    assert status["targets"][0]["response_kind"] is None
~~~

- [x] **Bước 6: Chạy integration đỏ rồi xanh**

Run:

~~~powershell
python -m pytest -q tests/integration/test_company_assistant_flow.py::test_follow_up_group_reply_never_completes_dm_target_and_report_goes_to_owner
python -m pytest -q tests/python/test_tooling.py tests/integration/test_company_assistant_flow.py
~~~

Expected: test đầu thất bại trước wiring, sau đó targeted suite PASS.

- [ ] **Bước 7: Commit quyền/integration**

~~~powershell
git add hermes-plugin/admin.py hermes-plugin/tooling.py tests/python/test_tooling.py tests/integration/test_company_assistant_flow.py
git commit -m "feat: expose admin follow-up workflow"
~~~

---

### Task 6: Documentation, acceptance và checkpoint release-ready

**Files:**
- Modify: docs/architecture/system-overview.md
- Modify: docs/architecture/database-schema.md
- Modify: docs/operations/acceptance-checklist.md
- Modify: docs/superpowers/plans/2026-08-13-hermes-zalo-follow-up-tracking.md

- [x] **Bước 1: Cập nhật tài liệu theo source thật**

Ghi rõ trong system-overview.md: ticker nội bộ chỉ chạy khi bridge/login sẵn sàng, state không ở Hermes cron. Trong database-schema.md: checksum 001 vẫn khóa, mô tả hai bảng 002, FK response_message_id ON DELETE SET NULL và không xóa follow-up đang mở khi purge message. Trong checklist thêm các case: DM đúng/người đúng/sau send; group rejected; một reminder; report owner-only; restart giữa claim; admin-only; bridge unavailable giữ pending.

- [x] **Bước 2: Chạy static acceptance sau docs**

Run: python scripts/acceptance.py --static --json

Expected: JSON ok: true, manifest không có path unexpected/missing.

- [x] **Bước 3: Chạy toàn bộ test và dependency checks**

Run:

~~~powershell
npm test
python -m pytest -q -p no:cacheprovider
python scripts/acceptance.py --json
npm audit --omit=dev
python -m pip check
(Get-FileHash hermes-plugin/migrations/001_initial.sql -Algorithm SHA256).Hash.ToLower()
git diff --check
~~~

Expected: Node/Python/integration PASS; full acceptance ok: true; audit 0 vulnerability; pip check sạch; checksum 001 đúng; diff check exit 0.

- [x] **Bước 4: Cập nhật checkpoint bằng bằng chứng thật**

Thay bullet Việc tiếp theo ở đầu plan này bằng số test pass/fail thực tế, kết quả exact của acceptance/audit/pip/checksum và next action. Không ghi token, cookie, QR, Zalo ID runtime hoặc output chứa secret.

- [ ] **Bước 5: Commit documentation/checkpoint**

~~~powershell
git add docs/architecture/system-overview.md docs/architecture/database-schema.md docs/operations/acceptance-checklist.md docs/architecture/file-manifest.md docs/superpowers/specs/2026-08-13-hermes-zalo-follow-up-tracking-design.md docs/superpowers/plans/2026-08-13-hermes-zalo-follow-up-tracking.md
git commit -m "docs: record follow-up workflow verification"
~~~

## Tiêu chí hoàn thành toàn kế hoạch

- State follow-up bền vững trong SQLite migration 002, 001 không đổi byte.
- DM/group/timestamp target matching fail-closed; event duplicate không hoàn thành lại.
- Mỗi target overdue chỉ có tối đa một automatic reminder; restart/timeout không auto-resend.
- Report duy nhất đến owner admin và follow-up vào awaiting_admin sau đó.
- Chỉ admin thực hiện toàn bộ năm action và có thể xem/vận hành mọi follow-up; target ngoài allowlist bị từ chối trước outbound. Báo cáo tự động vẫn chỉ gửi owner đã tạo.
- Bridge unavailable giữ pending; admin manual action mới có thể re-open/remind.
- Static/full acceptance, Node/Python/integration, audit, pip check, migration checksum và git diff --check đều có bằng chứng mới.
