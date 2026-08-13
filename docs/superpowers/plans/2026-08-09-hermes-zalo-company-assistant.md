# Trợ lý công ty Hermes trên Zalo - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (khuyến nghị) hoặc `superpowers:executing-plans` để thực hiện kế hoạch theo từng nhiệm vụ. Mỗi bước dùng checkbox `- [ ]`.

**Goal:** Biến fork `cuongdev/hermes-zalo-plugin@1.0.9` thành cầu nối một tài khoản Zalo công ty với Hermes Agent `0.19.0`, lưu đầy đủ hội thoại/media và cho thành viên allowlist dùng Hermes cùng toàn bộ method vận hành của `zca-js@2.1.2` ngay lập tức; admin có quyền quản trị cao hơn.

**Architecture:** Giữ Node `ZaloClient` làm lớp sở hữu phiên `zca-js` và bridge loopback token-authenticated. Python adapter ghi event vào SQLite trước mention gate, tạo DM/session routing, đăng ký `zalo`, `zalo_history`, `zalo_admin`, và dùng `ContextVar` + `pre_tool_call` để bảo vệ memory. Không có approval broker hay transport tối thiểu.

**Tech Stack:** Node.js 22, Express 4, `zca-js@2.1.2`, `node:test`, Python 3.11, Hermes Agent 0.19.0, `aiohttp`, SQLite, `pytest`, systemd.

---

## Tài liệu đã khóa trước code

- `docs/architecture/system-overview.md`
- `docs/architecture/database-schema.md`
- `docs/architecture/file-manifest.md`

Không đổi ba tài liệu trên để mở lại approval-heavy design, thu gọn zca-js hoặc đổi schema. Nếu phát hiện yêu cầu cần đổi kiến trúc/schema, dừng tại checkpoint và xin duyệt lại.

## Nhiệm vụ 1: Test harness và migration schema

**Files:**

- Tạo: `hermes-plugin/migrations/001_initial.sql`
- Tạo: `tests/python/conftest.py`, `tests/python/test_history_store.py`
- Tạo: `pyproject.toml`, `requirements-test.txt`
- Sửa: `package.json`, `package-lock.json`, `.gitignore`, `.npmignore`

- [ ] Viết test RED kiểm tra sáu bảng, foreign keys, unique dedupe và migration checksum.
- [ ] Chạy `python -m pytest tests/python/test_history_store.py -q`; xác nhận fail vì migration/module chưa tồn tại.
- [ ] Viết `001_initial.sql` đúng bảng/constraint trong `database-schema.md`, gồm trigger chặn UPDATE/DELETE trên `tool_activity` nếu cần append-only metadata.
- [ ] Cài `HistoryStore.apply_migrations()` chạy script theo version, SHA-256 checksum và transaction.
- [ ] Thêm script Node `test` dùng `node --test \"test/**/*.test.js\"`; thêm script Python trong `pyproject.toml`.
- [ ] Chạy lại test migration và `git diff --check`; commit checkpoint C1.

## Nhiệm vụ 2: Bridge config, auth, SSE và catalog

**Files:**

- Tạo: `bridge/config.js`, `bridge/auth.js`, `bridge/redaction.js`, `bridge/event-buffer.js`, `bridge/method-catalog.js`, `bridge/app.js`
- Tạo: `test/config.test.js`, `test/auth.test.js`, `test/event-buffer.test.js`, `test/method-catalog.test.js`, `test/app.test.js`, `test/helpers/fake-zalo-client.js`
- Sửa: `server.js`, `zaloClient.js`, `permissions.js`, `paths.js`

- [ ] Viết test RED: config thiếu token/host ngoài loopback bị từ chối; mọi route thiếu Bearer trả 401; SSE replay theo `Last-Event-ID`; catalog có `sendMessage`, `createPoll` và ẩn `getCookie/getContext`.
- [ ] Chạy từng test bằng `node --test test/config.test.js` và xác nhận fail vì module/app factory chưa có.
- [ ] Cài `loadConfig(env)` với token tối thiểu 32 ký tự, host cố định `127.0.0.1`, port hợp lệ và path state.
- [ ] Cài `requireBridgeAuth` so sánh constant-time, nhận `Authorization: Bearer`; không đọc query token. Áp dụng trước route `/health`, `/events`, `/qr`, lifecycle và API.
- [ ] Cài `EventBuffer` ring 200 record, heartbeat, replay từ cursor và bỏ cursor quá cũ theo chuẩn SSE.
- [ ] Cài `MethodCatalog` đọc `node_modules/zca-js/dist/apis/*.d.ts` + signature runtime, gắn nhóm từ `permissions.js`, schema chung positional và schema tên cho method phổ biến. `list/describe` không trả raw source/credential.
- [ ] Cài `redactSecrets(value)` đệ quy theo key/value (`cookie`, `token`, `password`, `apiKey`, `secret`, `imei`, `authorization`) trước JSON response và log.
- [ ] Chuyển route hiện có vào `createBridgeApp({client, config})`; giữ route tiện dụng và `POST /api/:method`, thêm `GET /api/methods`/`:method`. `callRaw` chỉ gọi method tồn tại, chuyển `\"user\"`/`\"group\"` thành `ThreadType`, chặn method secret.
- [ ] Sửa `server.js` chỉ khởi động khi được chạy trực tiếp, đăng ký event qua `EventBuffer`, không log nội dung/credential thô.
- [ ] Chạy toàn bộ Node tests, `node --check` và `npm pack --dry-run`; commit C2.

## Nhiệm vụ 3: History Store và media policy

**Files:**

- Tạo: `hermes-plugin/media_policy.py`, `tests/python/test_media_policy.py`
- Sửa: `hermes-plugin/history_store.py` (tạo ở Nhiệm vụ 1 nếu chưa có), `paths.js`

- [ ] Viết RED cho insert trùng, group message không mention, context 100, search/recent/get_message/get_attachment và export/delete.
- [ ] Chạy pytest để quan sát đúng failure.
- [ ] Cài `upsert_conversation`, `insert_message`, `insert_event`, `insert_attachment`, `recent_messages`, `search_messages`, `export_history`, `delete_history`, `stats` với transaction và dedupe no-op.
- [ ] Cài `MediaPolicy` nhận normalized attachment; filename chỉ giữ chữ/số/`._-`, path theo `history/media/<type>/<id>/<date>`; size đã biết >20 MiB là metadata-only.
- [ ] Với size chưa biết, đọc stream từng chunk, dừng ngay khi tổng vượt cap; lỗi download cập nhật `failed` nhưng không rollback message.
- [ ] Hash SHA-256 và unique `(message_id, attachment_index)` để duplicate không tải lại.
- [ ] Chạy test media/history, kiểm tra file permissions và restart store trên cùng DB.

## Nhiệm vụ 4: Company config, requester context và adapter routing

**Files:**

- Tạo: `hermes-plugin/company_config.py`, `hermes-plugin/request_context.py`, `tests/python/test_company_config.py`, `tests/python/test_request_context.py`, `tests/python/test_adapter.py`
- Sửa: `hermes-plugin/adapter.py`, `hermes-plugin/plugin.yaml`, `hermes-plugin/__init__.py`

- [ ] Viết RED cho config fail-closed, admin subset, group mode mention, group lưu trước gate, DM tách session, group dùng session chung và người ngoài allowlist.
- [ ] Chạy pytest và ghi nhận failure trước implementation.
- [ ] Cài `CompanyConfig.from_platform_extra()` với `allowed_users`, `admin_users`, `allowed_groups`, `group_mode=mention`, cap/context/retention; env override không được tạo allow-all ngoài ý muốn.
- [ ] Cài `request_context` bằng `ContextVar[Requester]`, context manager `bind_requester()` và `current_requester()` fail-closed khi không có context.
- [ ] Trong `_on_inbound_message`, phân loại event; group thuộc allowlist luôn gọi `store_message`/media metadata trước mention check. DM ngoài allowlist không lưu và không gọi Hermes.
- [ ] Sau store thành công, group chỉ gọi Hermes khi sender allowlist + mention; DM allowlist gọi Hermes. Dedupe trả về trước khi tạo `MessageEvent`.
- [ ] Tạo session source DM/group đúng và định dạng context 100 message gần nhất trong `MessageEvent.text` hoặc hook pre-dispatch; không nhúng binary.
- [ ] Bind `Requester` bằng context manager bao quanh `handle_message(event)`; ghi inbound/outbound message và tool activity.
- [ ] Gửi media qua route buffer an toàn, timeout trả `unknown` và không retry; ghi outbound message sau provider response.
- [ ] Đặt `group_sessions_per_user: false` trong tài liệu/config migration; chạy adapter tests.

## Nhiệm vụ 5: Tool surface, admin guard và memory

**Files:**

- Tạo: `hermes-plugin/tooling.py`, `hermes-plugin/admin.py`, `tests/python/test_tooling.py`
- Sửa: `hermes-plugin/adapter.py`, `hermes-plugin/plugin.yaml`, `hermes-plugin/__init__.py`

- [ ] Viết RED: member gọi `zalo(list|describe|call)` được; `zalo_history` chỉ thấy DM của mình/group allowlist; non-admin `zalo_admin` bị từ chối; admin mutation chạy ngay; non-admin memory qua `memory`, `write_file`, `patch`, `terminal`, `execute_code` bị block.
- [ ] Chạy pytest để xác nhận RED.
- [ ] Đăng ký tool qua `ctx.register_tool(name, toolset, schema, handler, is_async=True)`; handler không nhận `requester_id` tin từ model, chỉ dùng `current_requester()`.
- [ ] `zalo` gọi `/api/methods`, `/api/methods/:method`, `/api/:method`; `params` chuyển theo catalog, `args` là fallback; mọi response chạy redaction và `HistoryStore.log_tool_activity`.
- [ ] `zalo_history` triển khai `recent`, `search`, `get_message`, `get_attachment`; member scope là session DM cá nhân hoặc group allowlist, admin scope toàn công ty.
- [ ] `zalo_admin` triển khai `status`, allowlist/admin, memory add/update/delete, history export/delete, login_qr, start/stop/restart, show_logs; mọi action kiểm tra `is_admin`, cấm xóa admin cuối.
- [ ] Hook `pre_gateway_dispatch` lưu/bind context; hook `pre_tool_call` phân tích args/path/code để chặn non-admin đụng `MEMORY.md`, `USER.md` hoặc thư mục memory. Hook `post_tool_call` log trạng thái đã redact.
- [ ] Cấu hình `approvals.mode: off` chỉ là migration vận hành đã được người dùng chốt; plugin không tạo approval code/broker.
- [ ] Chạy test tooling/adapter và kiểm tra tool schemas với Hermes Agent 0.19.0.

## Nhiệm vụ 6: Đóng gói và vận hành

**Files:**

- Tạo: `systemd/hermes-zalo-company-bridge.service`, `systemd/hermes-gateway.service`, `systemd/hermes-zalo-company.env.example`, `scripts/migrate-v1.0.9-config.mjs`, `tests/integration/fake_bridge.py`, `tests/integration/test_company_assistant_flow.py`, `tests/integration/test_restart.py`
- Sửa: `package.json`, `package-lock.json`, `install.mjs`, `install.sh`, `uninstall.mjs`, `login.mjs`, `bin/cli.mjs`, `README.md`, `README.vi.md`, `.github/workflows/ci.yml`, `.gitignore`, `.npmignore`

- [ ] Viết integration RED cho DM/group/tool/restart trên fake bridge.
- [ ] Cài migration config 1.0.9 idempotent: map env cũ sang `gateway.platforms.zalo.extra`, không copy secret vào YAML.
- [ ] Cập nhật install/CLI/systemd dùng data dir `0700`, env file `0600`, Node 22/Python 3.11; service bridge chạy trước gateway.
- [ ] Cập nhật README tiếng Việt với allowlist, group lưu không mention, memory admin-only, QR và rủi ro unofficial API.
- [ ] Chạy integration và kiểm tra package bằng `npm pack --dry-run`.

## Nhiệm vụ 7: Nghiệm thu và review

- [ ] Chạy `npm test` và đọc đủ output; không dùng exit code cuối của chuỗi lệnh để che failure.
- [ ] Chạy `python -m pytest -q`, integration, restart, `npm audit --omit=dev --json`, `npm pack --dry-run`, `git diff --check`.
- [ ] Chạy `python scripts/acceptance.py --json` và đối chiếu `docs/operations/acceptance-checklist.md` từng dòng.
- [ ] Dùng GitNexus `status`, `context` cho `ZaloClient`, `ZaloAdapter`, `createBridgeApp` và `HistoryStore` để kiểm tra call path sau thay đổi.
- [ ] Kiểm tra `git status --short`; mọi file thay đổi phải có trong `docs/architecture/file-manifest.md`.
- [ ] Nếu một test fail, viết regression test trước khi sửa; chỉ báo hoàn tất sau khi có output mới với exit code 0 và checklist đủ.

## Điều kiện dừng

Dừng và xin duyệt lại nếu cần đổi `system-overview.md`, `database-schema.md`, `file-manifest.md`, thêm approval broker, thu gọn bề mặt `zca-js`, hoặc tạo file ngoài manifest. Các lỗi dependency/test có thể sửa trong phạm vi file đã khóa; không tự mở rộng kiến trúc.

## Quyết định phát hành bổ sung

- Chấp nhận rủi ro kế thừa nhầm quyền admin trong group session khi có lượt xử
  lý đồng thời; lỗi này không còn là blocker phát hành.
- Giữ nguyên session hội thoại chung của group; không sửa Hermes core và không
  tách session theo từng thành viên.
- Khuyến nghị admin thực hiện thao tác memory đặc quyền trong chat riêng.

---

# Workflow kết bạn bằng danh thiếp - Kế hoạch triển khai bổ sung

> **Dành cho agent thực thi:** BẮT BUỘC dùng `superpowers:executing-plans` để
> triển khai lần lượt. Mỗi thay đổi nghiệp vụ phải đi theo RED → GREEN. Không
> dùng subagent vì người dùng không yêu cầu giao việc cho agent khác.

**Mục tiêu:** Cho admin gửi lệnh kết bạn sau một hoặc nhiều danh thiếp trong
cùng DM/group; bot chọn đúng danh thiếp theo quy tắc đã duyệt, gọi
`sendFriendRequest` tuần tự và không tự thêm allowlist.

**Kiến trúc:** Giữ nguyên hai process. Node bridge tiếp tục chuẩn hóa
`chat.recommended` và cung cấp route `/friend/request`; Python adapter lưu contact
vào `messages.extra_json`, nhận diện lệnh đặc quyền sau khi message đã được lưu và
dùng một truy vấn HistoryStore mới chỉ đọc các message trước lệnh trong cùng
conversation. Không sửa `store_message`, `recent_messages`, bridge route, schema
hoặc migration.

**Công nghệ:** Node.js 22, `zca-js@2.1.2`, Python 3.11, SQLite hiện có,
`pytest`, `node:test`, GitNexus.

## Phạm vi file đã khóa bằng GitNexus

**Sửa:**

- `hermes-plugin/history_store.py` — thêm truy vấn chỉ đọc
  `contact_cards_before`; không đổi API lưu message.
- `hermes-plugin/adapter.py` — chuẩn hóa contact metadata, nhận diện lệnh,
  kiểm tra quyền, gọi friend request và gửi báo cáo.
- `tests/python/test_history_store.py` — test truy vấn số ít/số nhiều và scope
  conversation/account.
- `tests/python/test_adapter.py` — test DM/group/admin/member, batch, lỗi và
  không dispatch Hermes.
- `docs/superpowers/plans/2026-08-09-hermes-zalo-company-assistant.md` — cập
  nhật checkpoint sau triển khai.

**Chỉ chạy test, không sửa nếu test không phát hiện regression:**

- `test/app.test.js`
- `tests/integration/test_company_assistant_flow.py`
- `tests/integration/test_restart.py`

**Không sửa:**

- `hermes-plugin/migrations/001_initial.sql` và toàn bộ schema/checksum.
- `bridge/app.js`, `zaloClient.js`, `server.js`, `permissions.js`.
- Hermes core, Admin Web UI và cấu hình allowlist.

GitNexus trước triển khai xác nhận `HistoryStore.store_message` có 36 dependants
và `_on_inbound_message` có 25 dependants, nên implementation không thay đổi
contract của hai symbol này. `friend_request` hiện có blast radius upstream bằng
0 và được tái sử dụng nguyên trạng.

## Interface triển khai đã khóa

Trong `HistoryStore` thêm đúng interface:

```python
def contact_cards_before(
    self,
    *,
    message_id: int,
    thread_type: str,
    thread_id: str,
    multiple: bool,
) -> list[dict[str, Any]]:
    """Trả contact trước message trong cùng account/conversation.

    multiple=False: bỏ qua message thường và trả contact gần nhất.
    multiple=True: chỉ trả cụm contact liên tiếp ngay trước message; gặp message
    thường thì dừng. Kết quả luôn theo thứ tự cũ đến mới.
    """
```

Contact được lưu trong `extra_json` theo cấu trúc:

```json
{
  "msg_type": "chat.recommended",
  "contact": {
    "name": "Nguyễn Văn A",
    "phone": "0900000000",
    "gUid": "zalo-user-id"
  },
  "attachments": []
}
```

Các helper thuần trong `adapter.py`:

```python
def _contact_payload(message: Mapping[str, Any]) -> dict[str, str] | None:
    raise NotImplementedError

def _friend_request_command(text: str) -> str | None:  # "single"|"multiple"
    raise NotImplementedError

def _friend_request_bucket(response: Mapping[str, Any]) -> str:
    raise NotImplementedError
```

Adapter thêm method nội bộ:

```python
async def _handle_contact_friend_request(
    self,
    *,
    stored: StoredMessage,
    requester_id: str,
    thread_type: str,
    thread_id: str,
    command_text: str,
) -> bool:
    """Trả True nếu message là lệnh workflow và đã được xử lý hoàn toàn."""
    raise NotImplementedError
```

## Task 1: Truy vấn danh thiếp trong đúng conversation

**Files:**

- Modify: `hermes-plugin/history_store.py:727`
- Test: `tests/python/test_history_store.py`

- [ ] **Bước 1: Viết test RED cho lệnh số ít**

Thêm test lưu contact, một message thường và command trong cùng group; contact
gần nhất phải được trả dù có message thường nằm giữa:

```python
def test_contact_cards_before_single_returns_nearest_contact_in_same_conversation(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    first = store.store_message(
        thread_type="group", thread_id="g-1", sender_id="u-1",
        text="[contact: Lan]", provider_message_id="card-1",
        extra={"contact": {"name": "Lan", "phone": "0901", "gUid": "uid-lan"}},
    )
    store.store_message(
        thread_type="group", thread_id="g-1", sender_id="u-2",
        text="tin xen giữa", provider_message_id="normal-1",
    )
    command = store.store_message(
        thread_type="group", thread_id="g-1", sender_id="admin",
        text="kết bạn người này", provider_message_id="command-1",
    )

    cards = store.contact_cards_before(
        message_id=command.message_id, thread_type="group", thread_id="g-1",
        multiple=False,
    )

    assert cards == [{
        "message_id": first.message_id,
        "sender_id": "u-1",
        "name": "Lan",
        "phone": "0901",
        "gUid": "uid-lan",
    }]
```

- [ ] **Bước 2: Viết test RED cho cụm số nhiều và ranh giới**

Test phải có contact cũ, message thường, hai contact liền nhau, command, một
contact ở conversation khác và một store khác cùng file DB nhưng account khác.
Kỳ vọng chỉ hai contact liền trước command của đúng account/conversation được trả
theo thứ tự cũ → mới:

```python
cards = store.contact_cards_before(
    message_id=command.message_id,
    thread_type="group",
    thread_id="g-1",
    multiple=True,
)
assert [item["gUid"] for item in cards] == ["uid-minh", "uid-hung"]
```

Thêm case immediate previous message là message thường:

```python
assert store.contact_cards_before(
    message_id=command_after_text.message_id,
    thread_type="group",
    thread_id="g-1",
    multiple=True,
) == []
```

- [ ] **Bước 3: Chạy RED và xác nhận đúng nguyên nhân**

```powershell
python -m pytest tests/python/test_history_store.py -k "contact_cards_before" -q -p no:cacheprovider
```

Kỳ vọng: FAIL bằng `AttributeError: 'HistoryStore' object has no attribute
'contact_cards_before'`; không chấp nhận lỗi fixture, migration hoặc encoding.

- [ ] **Bước 4: Cài implementation tối thiểu**

Thêm method mới sau `recent_messages`; không sửa `recent_messages`:

```python
def contact_cards_before(
    self,
    *,
    message_id: int,
    thread_type: str,
    thread_id: str,
    multiple: bool,
) -> list[dict[str, Any]]:
    rows = self.connection.execute(
        "SELECT m.id, m.sender_id, m.extra_json "
        "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
        "WHERE c.account_id=? AND c.thread_type=? AND c.thread_id=? "
        "AND m.id<? ORDER BY m.id DESC",
        (
            self.account_id,
            self._thread_type(thread_type),
            str(thread_id),
            int(message_id),
        ),
    )
    selected: list[dict[str, Any]] = []
    for row in rows:
        try:
            extra = json.loads(row["extra_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            extra = {}
        contact = extra.get("contact") if isinstance(extra, dict) else None
        if not isinstance(contact, dict):
            if multiple:
                break
            continue
        selected.append({
            "message_id": int(row["id"]),
            "sender_id": str(row["sender_id"]),
            "name": str(contact.get("name") or ""),
            "phone": str(contact.get("phone") or ""),
            "gUid": str(contact.get("gUid") or ""),
        })
        if not multiple:
            break
    return list(reversed(selected))
```

Không dùng `json_extract`, không load toàn bộ rows bằng `fetchall`, không cập nhật
DB và không thay đổi khóa dedupe.

- [ ] **Bước 5: Chạy GREEN và regression HistoryStore**

```powershell
python -m pytest tests/python/test_history_store.py -q -p no:cacheprovider
```

Kỳ vọng: toàn bộ file PASS; sáu bảng và checksum migration giữ nguyên.

- [ ] **Bước 6: Kiểm tra diff phạm vi Task 1**

```powershell
git diff --check -- hermes-plugin/history_store.py tests/python/test_history_store.py
git diff -- hermes-plugin/history_store.py tests/python/test_history_store.py
```

Không commit trong working tree đang chứa thay đổi trước phiên; chỉ commit nếu
người dùng yêu cầu rõ và staged diff đã được tách an toàn.

## Task 2: Chuẩn hóa contact và nhận diện lệnh

**Files:**

- Modify: `hermes-plugin/adapter.py:236-270,958-1050`
- Test: `tests/python/test_adapter.py`

- [ ] **Bước 1: Viết test RED cho contact metadata**

Mở rộng helper `_message` trong test bằng `attachment` tùy chọn, sau đó gửi một
`chat.recommended` và kiểm tra `extra.contact` sau khi lưu:

```python
message = _message(
    message_id="card-lan", sender_id="member-1", mentions=[]
)
message.update({
    "msgType": "chat.recommended",
    "text": "[contact: Lan 0901]",
    "attachment": {
        "type": "chat.recommended",
        "contact": {"name": "Lan", "phone": "0901", "gUid": "uid-lan"},
    },
})
await adapter._on_inbound_message(message)
row = adapter.history_store.recent_messages("group", "company-group")[0]
assert row["extra"]["contact"] == {
    "name": "Lan", "phone": "0901", "gUid": "uid-lan"
}
```

- [ ] **Bước 2: Viết test RED cho parser lệnh có dấu/không dấu**

```python
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("kết bạn người này", "single"),
        ("Kết bạn với người này!", "single"),
        ("gửi lời mời kết bạn", "single"),
        ("add người này", "single"),
        ("ket ban nguoi nay", "single"),
        ("kết bạn những người này", "multiple"),
        ("kết bạn tất cả", "multiple"),
        ("hãy tóm tắt cuộc họp", None),
    ],
)
def test_friend_request_command_is_explicit(text: str, expected: str | None) -> None:
    assert adapter_module._friend_request_command(text) == expected
```

- [ ] **Bước 3: Chạy RED**

```powershell
python -m pytest tests/python/test_adapter.py -k "contact_metadata or friend_request_command" -q -p no:cacheprovider
```

Kỳ vọng: FAIL do thiếu `_friend_request_command` và `extra.contact`.

- [ ] **Bước 4: Cài helper thuần tối thiểu**

Thêm import `Mapping` từ `collections.abc` và chuẩn hóa Unicode bằng
`unicodedata.normalize("NFD", ...)`, bỏ combining marks, lowercase, thay dấu câu
bằng khoảng trắng, gộp whitespace. Chỉ trả `single`/`multiple` khi toàn bộ câu sau
khi bỏ prefix lịch sự (`hãy`, `vui lòng`, `giúp`) khớp một phrase đã khóa; không
dùng substring mơ hồ như mọi câu có hai từ `kết bạn`.

```python
_FRIEND_SINGLE = {
    "ket ban nguoi nay",
    "ket ban voi nguoi nay",
    "gui loi moi ket ban",
    "add nguoi nay",
}
_FRIEND_MULTIPLE = {
    "ket ban nhung nguoi nay",
    "ket ban tat ca",
    "gui loi moi ket ban cho nhung nguoi nay",
}
```

`_contact_payload` chỉ tin object `attachment.contact`, convert ba field sang
string và trả `None` nếu message không phải `chat.recommended`/contact. Không tìm
`gUid` từ text, tên hoặc số điện thoại.

- [ ] **Bước 5: Lưu contact trong `extra_json` hiện có**

Trước `store_message`, tính:

```python
contact = _contact_payload(m)
extra = {
    "msg_type": str(m.get("msgType") or ""),
    "attachments": attachment_summaries,
}
if contact is not None:
    extra["contact"] = contact
```

Truyền `extra=extra`; không đổi `attachments` table và không đưa `gUid` vào
`messages.text` hoặc log.

- [ ] **Bước 6: Chạy GREEN và adapter routing regression**

```powershell
python -m pytest tests/python/test_adapter.py -k "contact_metadata or friend_request_command or allowed_group_is_stored_before_mention_gate or dm_only_stores" -q -p no:cacheprovider
```

Kỳ vọng: PASS; contact group không mention vẫn chỉ được lưu và chưa gọi Hermes.

## Task 3: Workflow admin trong DM và group

**Files:**

- Modify: `hermes-plugin/adapter.py:958-1123,1427-1468,1653-1655`
- Test: `tests/python/test_adapter.py`

- [ ] **Bước 1: Viết RED cho DM admin số ít**

Test gửi card trong DM admin, message thường, rồi command. Stub `_post` phải ghi
lại thứ tự call. Kỳ vọng một `/friend/request` với `uid-lan`, sau đó một `/send`
báo kết quả; `handle_message` không được gọi và allowlist không đổi:

```python
assert posts[0] == (
    "/friend/request",
    {"userId": "uid-lan", "msg": "Xin chào, tôi là trợ lý công ty."},
)
assert posts[1][0] == "/send"
assert dispatches == []
assert adapter.company_config.allowed_users == before_allowed_users
```

- [ ] **Bước 2: Viết RED cho group admin và mention gate**

Ba case độc lập:

1. Card do `member-1` gửi; admin mention bot và ra lệnh → một friend request.
2. Admin ra lệnh đúng nhưng không mention → không friend request, không reply,
   message vẫn được lưu.
3. Allowed member mention bot và ra lệnh → không friend request; bot gửi
   “Thao tác kết bạn bằng danh thiếp cần quản trị viên thực hiện.” và không gọi
   Hermes.

- [ ] **Bước 3: Viết RED cho batch và ranh giới message thường**

Gửi card cũ, message thường, card Minh, card Hùng, rồi admin mention:
`kết bạn những người này`. Kỳ vọng hai call `/friend/request` theo Minh → Hùng,
không gọi card cũ và chỉ gửi một báo cáo cuối.

- [ ] **Bước 4: Viết RED cho lỗi/unknown/thiếu gUid**

Stub response tuần tự:

```python
responses = iter([
    {"success": True, "result": ""},
    {"error": "Zalo error 225: already friends", "outcome": "failed"},
    {"error": "Zalo provider timeout", "outcome": "unknown"},
])
```

Cụm còn có một contact thiếu `gUid`. Kỳ vọng mỗi contact có ID chỉ gọi đúng một
lần, không retry unknown; báo cáo có đủ `thành công`, `đã là bạn/đã có lời mời`,
`không rõ kết quả`, `thiếu Zalo ID` và tên từng mục.

- [ ] **Bước 5: Chạy RED**

```powershell
python -m pytest tests/python/test_adapter.py -k "contact_friend_request_workflow" -q -p no:cacheprovider
```

Kỳ vọng: FAIL do workflow chưa tồn tại; test lưu contact của Task 2 vẫn PASS.

- [ ] **Bước 6: Cài `_friend_request_bucket`**

Quy tắc bucket:

```python
if response.get("outcome") == "unknown":
    return "unknown"
if not response.get("error"):
    return "success"
error = str(response.get("error") or "").casefold()
if re.search(r"(?:^|\D)(?:222|225)(?:\D|$)", error):
    return "existing"
return "failed"
```

Không coi timeout/connection reset là failure có thể retry.

- [ ] **Bước 7: Cài handler workflow**

Handler thực hiện đúng thứ tự:

1. Parse command; không phải command → `False`.
2. Nếu requester không thuộc `allowed_users` → `False` để giữ gate hiện tại.
3. Nếu requester không thuộc `admin_users` → gửi notice một lần, trả `True`.
4. Query `contact_cards_before` với `multiple` theo command.
5. Không có card → gửi yêu cầu gửi lại danh thiếp, trả `True`.
6. Với từng card theo thứ tự, thiếu `gUid` thì ghi bucket nhưng không gọi bridge;
   có `gUid` thì `await self.friend_request(...)` đúng một lần.
7. Tổng hợp một message và `await self.send(thread_id, report,
   metadata={"thread_type": thread_type})`.
8. Trả `True`; không gọi Hermes cho command đã xử lý.

Không tạo task nền và không chạy friend request song song để giữ thứ tự, tránh
rate burst và cho phép báo cáo tương ứng từng contact.

- [ ] **Bước 8: Nối một điểm rẽ hẹp vào `_on_inbound_message`**

Sau `stored.inserted`, `_persist_attachments` và trước gate dispatch Hermes:

```python
command_text = addressed_text if chat_type == "group" else original_text
if command_text is not None and await self._handle_contact_friend_request(
    stored=stored,
    requester_id=sender_id,
    thread_type=chat_type,
    thread_id=conversation_id,
    command_text=command_text,
):
    return
```

Trong group không mention thì `addressed_text is None`, vì vậy workflow không thể
chạy. Contact message không khớp command nên tiếp tục qua flow lưu/gate hiện có.

- [ ] **Bước 9: Chạy GREEN cho workflow và các gate lân cận**

```powershell
python -m pytest tests/python/test_adapter.py -k "contact_friend_request_workflow or allowed_group_is_stored_before_mention_gate or group_text_prefix_without_real_mention or group_sender_outside_allowlist or duplicate_inbound" -q -p no:cacheprovider
```

Kỳ vọng: PASS; duplicate command không gửi friend request lần hai vì dedupe return
trước workflow.

- [ ] **Bước 10: Chạy toàn bộ hai file sở hữu thay đổi**

```powershell
python -m pytest tests/python/test_history_store.py tests/python/test_adapter.py -q -p no:cacheprovider
```

Kỳ vọng: tất cả PASS, không warning/error mới.

## Task 4: Nghiệm thu toàn dự án và GitNexus hậu kiểm

**Files:** Không thêm file. Nếu test phát hiện lỗi, quay lại Task sở hữu behavior
và viết test RED riêng trước khi sửa.

- [ ] **Bước 1: Node contract**

```powershell
npm test
```

Kỳ vọng: toàn bộ Node PASS; route `/friend/request` và contact normalization cũ
không bị thay đổi.

- [ ] **Bước 2: Toàn bộ Python và integration**

```powershell
python -m pytest -q -p no:cacheprovider
python -m pytest tests/integration -q -p no:cacheprovider
```

Kỳ vọng: tất cả PASS; không bỏ qua test Admin Web, restart, dedupe hoặc media.

- [ ] **Bước 3: Acceptance, migration và whitespace**

```powershell
python scripts/acceptance.py --static --json
git diff --check
```

Kỳ vọng: `ok: true`; migration checksum vẫn là
`1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a`;
`git diff --check` exit `0`.

- [ ] **Bước 4: Làm mới và kiểm tra GitNexus**

```powershell
gitnexus analyze . --force --index-only --branch company-assistant-v1
gitnexus impact contact_cards_before --repo plugin --branch company-assistant-v1 --file hermes-plugin/history_store.py --direction upstream --depth 4 --include-tests
gitnexus impact _handle_contact_friend_request --repo plugin --branch company-assistant-v1 --file hermes-plugin/adapter.py --direction upstream --depth 4 --include-tests
gitnexus detect-changes --scope unstaged --repo plugin --branch company-assistant-v1 --limit 200
gitnexus check --cycles --json --repo plugin --branch company-assistant-v1
```

Kỳ vọng:

- Không có import cycle.
- `contact_cards_before` chỉ có workflow adapter và test làm caller.
- `_handle_contact_friend_request` chỉ được `_on_inbound_message` gọi trực tiếp.
- Không xuất hiện cạnh mới tới Admin Web, service lifecycle, provider config,
  media download hoặc migration.

- [ ] **Bước 5: Rà manifest và checkpoint**

```powershell
git status --short
git diff --name-only
```

Đối chiếu mọi path với `docs/architecture/file-manifest.md`. Cập nhật
**Checkpoint phiên làm việc** trong kế hoạch Admin Web hiện hoạt động bằng số
pass/fail thực tế, lệnh test mới nhất và `Việc tiếp theo`; không ghi secret.

- [ ] **Bước 6: Chỉ sau nghiệm thu local mới đồng bộ runtime**

Sao lưu file runtime hiện tại, đồng bộ đúng `adapter.py` và `history_store.py` đã
test sang `HERMES_HOME/plugins/zalo`, xác nhận hash nguồn/runtime khớp, restart
Gateway, kiểm tra status và gửi thử theo thứ tự:

1. DM admin: một card → “kết bạn người này”.
2. Group AI: member gửi card → admin `@bot kết bạn người này`.
3. Group AI: hai card liền nhau → admin `@bot kết bạn những người này`.
4. Allowed member thường ra lệnh → nhận thông báo liên hệ admin.

Không dùng contact thật ngoài phạm vi admin đã chủ động gửi để thử. Không tự thêm
ID vừa kết bạn vào allowlist.

## Điều kiện hoàn thành workflow

Chỉ báo hoàn thành khi có bằng chứng mới trong cùng lượt rằng:

1. Test RED đã fail đúng nguyên nhân trước implementation.
2. Node, toàn bộ Python và integration đều PASS.
3. Static acceptance `ok: true`, `git diff --check` exit `0`.
4. Migration/schema/checksum không thay đổi.
5. GitNexus hậu kiểm không có cycle hoặc cạnh ngoài phạm vi dự kiến.
6. Runtime đã đồng bộ, Gateway restart thành công và bốn luồng Zalo thực tế đã
   được kiểm tra hoặc được ghi rõ là còn chờ thao tác test của người dùng.
