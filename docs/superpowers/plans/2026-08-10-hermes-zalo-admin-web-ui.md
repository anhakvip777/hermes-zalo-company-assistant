# Kế hoạch triển khai Admin Web UI Hermes Zalo

> **Dành cho agent thực thi:** BẮT BUỘC dùng `superpowers:subagent-driven-development` (khuyến nghị) hoặc `superpowers:executing-plans` để thực hiện kế hoạch theo từng task. Mọi bước dùng checkbox `- [ ]` để theo dõi.

**Mục tiêu:** Thêm Admin Web UI tiếng Việt vào chính Hermes Zalo plugin để quản lý thông tin bot, danh bạ, nhóm, allowlist, lịch sử và vận hành mà không thêm process, schema, migration hoặc file runtime mới.

**Kiến trúc:** `AdminWebApp` nằm trong `hermes-plugin/admin.py`, chạy bằng `aiohttp.web` trên cùng event loop với `ZaloAdapter` và chỉ bind loopback. UI gọi `AdminService`, `HistoryStore`, `CompanyConfigFile` và bridge wrapper hiện có; browser không nhận bridge token, cookie Zalo hoặc provider credential.

**Công nghệ:** Python 3.11+, `aiohttp` 3.14, SQLite hiện có, PyYAML, HTML/CSS/JavaScript thuần, pytest/pytest-asyncio, fake bridge hiện có.

---

## Checkpoint phiên làm việc

- Tag `v1.1.3` ngày 2026-08-13: compatibility matrix PASS cả Ubuntu, macOS và
  Windows nhưng job `release-artifacts` fail tại builder. Root cause là fallback
  tự suy ra `npm-cli.js` cạnh binary Node chỉ đúng trên máy Windows local, không
  đúng với layout `actions/setup-node` trên Ubuntu. Giữ tag `v1.1.3` bất biến
  làm evidence run lỗi. Bản sửa `1.1.4` resolve npm từ PATH khi thiếu
  `npm_execpath`, có regression test và build pre-release thực tế PASS trên
  Windows với nhánh fallback. Số Node test mới là `66`. Việc tiếp theo: full
  verification, commit/push, tạo tag `v1.1.4`, chờ CI tag PASS và xác minh ba
  artifact/checksum do run CI upload.
- Cập nhật release `v1.1.3` ngày 2026-08-13: repo sạch ban đầu tại commit
  `89e3d17787d1562f98835495f427c3d542a162e8`; phát hiện manifest khai sai số
  Node test kỳ vọng `66` trong khi thực tế là `65`, đồng thời metadata npm còn
  trỏ về upstream. Đã thêm regression test, sửa số liệu manifest thành `65` và
  trỏ repository/bugs/homepage về
  `anhakvip777/hermes-zalo-company-assistant`. Verification trước commit: Node
  `65/65`, Python gồm integration `202/202`, full acceptance `ok: true`,
  `npm audit --omit=dev` có 0 vulnerability, `pip check` sạch, `git diff
  --check` exit `0`; migration giữ checksum khóa
  `1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a`.
  Việc tiếp theo: chạy lại full verification sau cập nhật checkpoint, commit và
  push, tạo/push tag `v1.1.3`, rồi xác minh CI tag và artifact provenance.
- Cập nhật 2026-08-13 sau tag `v1.1.0`: compatibility matrix Windows/Ubuntu/
  macOS đều pass nhưng job artifact thất bại trong bước builder trên Ubuntu;
  workflow npm cũ của upstream cũng tự chạy và fail trước publish. Không di
  chuyển tag bất biến `v1.1.0`. Bản sửa là `1.1.1`: source audit dùng
  `git archive HEAD` để đóng đúng committed tree xuyên nền tảng; npm publish
  chuyển sang `workflow_dispatch` thủ công để tag nội bộ không publish nhầm.
  Việc tiếp theo: full verification, commit/push, chờ CI branch pass, tag
  `v1.1.1` và xác minh artifact/manifest từ tag CI.
- Cập nhật release-hardening ngày 2026-08-13: policy trusted-team cho phép mọi
  `allowed_users` đọc history của mọi `allowed_groups` đã được ghi rõ; họ vẫn
  không thể đọc DM người khác, export/xóa history, đổi retention hoặc dùng
  quyền admin. Release manifest pin Hermes Agent `0.19.0` tại commit
  `eb52760564dbba2e5971fa54bd67384e281cd3b8` cùng hai contract
  `PlatformEntry.env_enablement_fn` và `MessageEvent.channel_context`.
  Release builder báo fail rõ khi source archive thiếu Git provenance và chỉ
  cho official build khi HEAD có tag đúng `v<package.version>`. CI checkout
  exact Hermes commit, chạy compatibility/full suite, chạy trên tag `v*`, ghi
  CI run ID/URL vào manifest và upload artifact.
- Kiểm thử fresh sau hardening: Node `62/62`, toàn bộ Python `202/202`,
  integration `17/17`, full acceptance `ok: true`, `npm audit --omit=dev` có
  0 vulnerability, `pip check` sạch và `git diff --check` exit `0`. Contract
  test chạy bằng Python venv của chính Hermes commit mục tiêu đạt `2/2`.
  Pre-release artifact mới không có path runtime/state bị cấm; quét secret chỉ
  bắt Bearer giả trong regression test. Migration vẫn có SHA-256 khóa
  `1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a`.
  Release commit cục bộ đầu tiên là `e3558503476c8cc1fdd023594fe5b0abaed89ba6`;
  sau commit đã bổ sung regression để mọi build dùng `--allow-dirty` luôn mang
  nhãn pre-release, kể cả checkout sạch. Việc tiếp theo: commit regression cuối,
  tạo/push tag `v1.1.0`, chờ CI tag pass rồi dùng artifact/checksum do CI upload
  làm official release. Không dùng pre-release làm artifact chính thức.
- Cập nhật: 2026-08-13, hardening production cho mô hình trusted-team đã được
  chủ dự án và tester chấp nhận có điều kiện. Method credential/session/QR được
  chặn không phân biệt hoa thường; live/unknown method chưa có trong bảng phân
  loại fail-closed. Installer/uninstaller có `--dry-run`, bắt buộc `--yes`,
  `--force` mới ghi đè, backup config/plugin và restore-backup đã test. Retention
  mặc định 90 ngày (`30/90/365/forever`) purge khi startup. systemd dùng profile
  `/var/lib/hermes-zalo/profile`, user `hermes-zalo`, `ProtectHome=true` và
  `ProtectSystem=strict`. npm/plugin cùng version `1.1.0`; runtime có
  `npm-shrinkwrap.json`, Python runtime dependencies được pin riêng.
- Kiểm thử mới nhất: Node `56/56`, toàn bộ Python `201/201`, integration `16/16`,
  `npm audit --omit=dev` có 0 vulnerability và `pip check` không có dependency
  hỏng. Full acceptance trả `ok: true`, static acceptance giữ đúng checksum
  migration, `npm audit --omit=dev` có 0 vulnerability và `pip check` sạch.
  GitNexus hậu kiểm trước đó không có import cycle; workspace hiện không có
  `.codegraph/` nên không chạy lại index. Việc tiếp theo: tạo và kiểm tra runtime
  + source/audit pre-release bundle có manifest checksum, quét secret trên source
  và artifact. Commit/tag/CI chính thức chưa được tuyên bố khi working tree còn
  dirty.
- Đóng gói pre-release audit ngày 2026-08-13: runtime package và source/audit
  bundle được tạo bằng `scripts/build-release.mjs --allow-dirty`; manifest ghi
  đúng `pre-release-dirty`, commit nền, phiên bản runtime và số test kỳ vọng.
  Source bundle có test/CI/lockfile, không chứa `.env`, database, cookie,
  session, media, log hoặc `node_modules`. Quét mẫu secret độ tin cậy cao chỉ
  bắt một Bearer giả trong regression test redaction; không phát hiện secret
  thật. Runtime package cài thử vào prefix sạch, giữ `zca-js@2.1.2` và checksum
  migration bất biến. Việc tiếp theo: tester đối chiếu manifest/checksum và CI
  chính thức sau khi source được commit/tag; nghiệm thu live Admin Web/Zalo chỉ
  thực hiện khi người dùng yêu cầu thao tác trên runtime.
- Cập nhật: 2026-08-13, đã sửa hai blocker hậu kiểm trước khi đóng gói VPS:
  phản hồi workflow kết bạn đi qua `ZaloAdapter.send()` để chỉ lưu outbound sau
  provider message ID, và package npm chứa `requirements-test.txt` cùng
  `pyproject.toml` đúng như hướng dẫn cài đặt. Test RED đã tái hiện cả hai lỗi
  trước khi sửa.
- Kiểm thử mới nhất: `npm test` đạt `42/42`; toàn bộ Python đạt `192/192`;
  integration đạt `15/15`; `npm audit --omit=dev` không có vulnerability.
  GitNexus đã lập lại index, xác nhận workflow đi qua `send`/`_store_outbound`
  và không có import cycle. Việc tiếp theo: chạy full acceptance, kiểm tra nội
  dung artifact mới và chỉ đồng bộ runtime khi có yêu cầu vận hành.
- Cập nhật: 2026-08-12, sau khi kiểm tra lại redaction Authorization và bộ test,
  ghi nhận quyết định chấp nhận rủi ro session group.
  hardening lỗi Web/log và đồng bộ runtime production đã kiểm thử.
- Kiến trúc vẫn giữ nguyên: Admin UI nằm trong Hermes plugin; Node bridge là
  process duy nhất sở hữu `zca-js`; không có Admin service riêng.
- Database vẫn giữ nguyên sáu bảng và migration
  `hermes-plugin/migrations/001_initial.sql`; checksum khóa vẫn là
  `1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a` và
  không có migration mới.
- `docs/architecture/file-manifest.md` vẫn là danh sách file chuẩn duy nhất;
  static acceptance xác nhận không thiếu file trong manifest.
- Đã triển khai trong working tree: access fingerprint/batch rollback, history
  pagination, runtime transaction, Web auth/session/CSRF, toàn bộ route
  overview/access/history/system, adapter lifecycle, fake bridge/integration,
  tài liệu vận hành và checklist secret. CSP đã cho phép `blob:` để QR do UI
  tải bằng Blob URL hiển thị đúng.
- Kiểm thử mới nhất sau hardening redaction: `npm test` đạt `41/41`; toàn bộ Python đạt `173/173`;
  integration đạt `15/15`; `python scripts/acceptance.py --static --json` trả `ok: true`;
  `git diff --check` exit `0` (chỉ có cảnh báo LF/CRLF của Git).
- Browser QA fake đã đạt ở desktop `1280x720` và mobile `390x844`: đăng nhập,
  Tổng quan, tên/ID bot, bạn bè, `Group AI`, thành viên kèm ID, bản nháp
  **Lưu và áp dụng**, history/activity/system và QR PNG `220x220`; không có
  tràn ngang toàn trang. Cookie `Secure` hoạt động qua hostname `localhost`.
- Cơ chế continuity: `AGENTS.md` + ba tài liệu kiến trúc + checkpoint này +
  static acceptance.
- Trạng thái runtime sống khi checkpoint: `adapter.py`, `admin.py` và
  `history_store.py` đã được sao lưu ngoài repo rồi đồng bộ từ working tree;
  các file plugin production đều khớp bản đã kiểm thử. Gateway đã restart sạch
  và `GET http://localhost:8790/admin/` trả `200`. Bridge đã có fallback
  `getUserInfo` khi `getGroupMembersInfo` không trả tên và không cần restart lại.
  Bản plugin cũ vẫn được giữ để rollback nhưng manifest discovery của bản
  backup đã đổi tên thành `plugin.yaml.disabled`, tránh ghi đè factory của bản
  `plugins/zalo`.
- Nghiệm thu live `Group AI` đã có bằng chứng trong log và SQLite: hai lượt
  @mention từ admin được lưu với `mentioned_bot=1` và có phản hồi Hermes; một
  tin kế tiếp không mention được lưu với `mentioned_bot=0` nhưng không tạo
  phản hồi. Group và admin đều khớp allowlist runtime, `group_mode=mention`.
- Admin Web production đã bật bằng credential do người dùng nhập cục bộ; không
  ghi password/hash/session secret vào tài liệu. Factory runtime trỏ đúng
  `HERMES_HOME/plugins/zalo/adapter.py`, cổng `127.0.0.1:8790` đang lắng nghe.
  Route bridge live của `Group AI` trả đúng bốn mục `Tên Zalo (ID)` gồm Việt Anh
  Nguyên Quảng, Tiny, Nhà Chung Nam và Tí Nị; tab mở trước khi bridge cập nhật có
  thể giữ danh sách ID cũ cho đến khi tải lại. Sau lần restart Gateway mới nhất,
  browser đang ở màn hình đăng nhập; việc tiếp theo là đăng nhập lại và xác nhận
  trực quan danh sách `Group AI`. Các thao tác mutation (Lưu/QR/restart từ UI)
  chỉ chạy khi người dùng yêu cầu.
- Working tree có nhiều thay đổi chưa commit từ toàn bộ
  `company-assistant-v1`; không reset, checkout hoặc gom commit ngoài phạm vi.

### Quyết định phát hành đã chấp nhận

- Giữ session hội thoại chung của group.
- Chấp nhận rủi ro lượt xử lý sau kế thừa nhầm quyền admin của lượt trước khi
  group session đang bận; rủi ro này không còn là blocker phát hành.
- Không sửa Hermes core và không tách session theo từng thành viên.
- Khuyến nghị admin thực hiện thao tác memory đặc quyền trong chat riêng.

### Việc còn lại trước khi chốt hoàn thành

- [x] Che credential sau `Authorization: Basic ...` và `Authorization: Bearer ...`.
- [x] Chạy Node, Python, integration, static acceptance và `git diff --check`.
- [ ] Kiểm tra lại Admin Web và luồng Zalo–Hermes thực tế sau thay đổi redaction.

  Kiểm tra live hiện tại: listener `127.0.0.1:8790` đang chạy và
  `GET http://localhost:8790/admin/` trả `200`; luồng chat Group AI cần
  đăng nhập/thao tác Zalo thực tế để xác nhận lại.

Các checkbox bên dưới là công thức thực thi gốc. Trạng thái phiên hiện tại phải
đọc từ checkpoint này: code/test của Task 0-10 và verification tự động Task 11
đã hoàn tất; các bước `Commit` chưa chạy vì working tree chung chưa được người
dùng yêu cầu gom commit; nghiệm thu đăng nhập production vẫn đang thực hiện.

---

## Điều kiện tiên quyết

Working tree hiện có nhiều thay đổi backend `company-assistant-v1` chưa commit.
Không được để chúng vô tình lọt vào commit Admin Web UI.

- Chạy Task 0 và lưu trạng thái baseline trước khi sửa runtime.
- Không tạo worktree từ `HEAD` cho tới khi backend hiện tại được checkpoint bằng
  một quy trình riêng; các file untracked sẽ không xuất hiện trong worktree mới.
- Nếu triển khai inline, trước mỗi commit phải dùng `git add --` với danh sách
  file chính xác và kiểm tra `git diff --cached --name-only`.
- Không tạo file runtime hoặc test mới, không sửa
  `hermes-plugin/migrations/001_initial.sql`.
- Không ghi password, session secret, bridge token, cookie Zalo hoặc provider
  key vào YAML, SQLite, response, HTML, JavaScript, audit hay log.

Baseline đọc-only ngày 2026-08-10:

```powershell
python -m pytest tests/python/test_tooling.py tests/python/test_company_config.py tests/python/test_history_store.py -q -p no:cacheprovider
# 50 passed
```

## Bản đồ file

| File | Trách nhiệm |
|---|---|
| `hermes-plugin/admin.py` | Settings, scrypt, session, CSRF, throttle, `AdminService`, `AdminWebApp`, route và HTML/CSS/JS |
| `hermes-plugin/company_config.py` | Access snapshot/fingerprint, batch apply, rollback và group mutation |
| `hermes-plugin/history_store.py` | Conversation/message/activity pagination bằng schema hiện có |
| `hermes-plugin/tooling.py` | Đồng bộ action access của `zalo_admin` |
| `hermes-plugin/adapter.py` | Vòng đời Web UI, bridge/status/QR/service callback |
| `hermes-plugin/plugin.yaml` | Tên biến môi trường Web UI, không chứa giá trị secret |
| `tests/python/test_company_config.py` | TDD persistence access |
| `tests/python/test_history_store.py` | TDD history/activity pagination |
| `tests/python/test_tooling.py` | TDD AdminService, auth, route, CSRF và UI contract |
| `tests/python/test_adapter.py` | TDD lifecycle và service target |
| `tests/integration/fake_bridge.py` | Fake profile/friends/groups/member/health/QR |
| `tests/integration/test_company_assistant_flow.py` | Luồng Web UI tích hợp |
| `docs/operations/configuration.md` | Cấu hình, reverse proxy và fallback CLI |
| `docs/operations/acceptance-checklist.md` | Checklist nghiệm thu |
| `README.vi.md` | Hướng dẫn admin ngắn |

## Interface đã khóa cho các task

```python
CompanyConfigFile.read_access_config() -> AccessConfigSnapshot
CompanyConfigFile.apply_access_config(*, allowed_users, admin_users,
    allowed_groups, expected_fingerprint) -> AccessConfigSnapshot
CompanyConfigFile.rollback_access_config(snapshot,
    *, expected_fingerprint) -> AccessConfigSnapshot
HistoryStore.list_conversations(*, thread_type=None, query=None,
    limit=50, offset=0) -> dict[str, Any]
HistoryStore.get_conversation(conversation_id) -> dict[str, Any] | None
HistoryStore.page_messages(conversation_id, *, sender_id=None, since=None,
    until=None, query=None, limit=100, offset=0) -> dict[str, Any]
HistoryStore.page_tool_activity(*, requester_id=None, tool_name=None,
    status=None, thread_type=None, thread_id=None, since=None, until=None,
    limit=100, offset=0) -> dict[str, Any]
AdminService.get_access_config(*, requester) -> dict[str, Any]
AdminService.apply_access_config(*, allowed_users, admin_users,
    allowed_groups, expected_fingerprint, requester) -> dict[str, Any]
AdminWebSettings.from_env(env=None) -> AdminWebSettings
AdminWebApp.create_application() -> aiohttp.web.Application
AdminWebApp.start() -> bool
AdminWebApp.stop() -> None
```

Pagination trả contract chung:

```python
{"items": [], "limit": 50, "offset": 0, "next_offset": None}
```

---

### Task 0: Khóa baseline

**Files:** Không sửa file.

- [ ] **Bước 1: Ghi trạng thái và staging**

```powershell
git status --short
git rev-parse --short HEAD
git diff --cached --name-only
```

Kỳ vọng: không có file staged; lưu danh sách file dirty để đối chiếu Task 11.

- [ ] **Bước 2: Chạy baseline Node**

```powershell
npm test
```

Kỳ vọng: exit `0`.

- [ ] **Bước 3: Chạy baseline Python**

```powershell
python -m pytest -q -p no:cacheprovider
```

Kỳ vọng: exit `0`. Nếu đỏ, dừng và chẩn đoán baseline riêng; không sửa test cũ
để che lỗi.

- [ ] **Bước 4: Chụp danh sách file hiện có**

```powershell
rg --files | Sort-Object
```

Kỳ vọng: snapshot này được dùng để chứng minh không có file runtime/test mới.

---

### Task 1: Access snapshot, fingerprint, batch apply và rollback

**Files:**

- Modify: `hermes-plugin/company_config.py:19-344`
- Test: `tests/python/test_company_config.py`

- [ ] **Bước 1: Viết test RED cho fingerprint canonical và apply**

Thêm vào `tests/python/test_company_config.py`:

```python
from company_config import CompanyConfigConflict


def _config_file(path: Path) -> CompanyConfigFile:
    path.write_text(
        yaml.safe_dump(
            {
                "gateway": {"platforms": {"zalo": {"extra": valid_extra()}}},
                "unrelated": {"keep": True},
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return CompanyConfigFile(path)


def test_access_fingerprint_apply_conflict_and_unrelated_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    config_file = _config_file(path)
    before = config_file.read_access_config()
    applied = config_file.apply_access_config(
        allowed_users=["u-2", "u-1", "u-2"],
        admin_users=["u-1"],
        allowed_groups=["g-2", "g-1", "g-2"],
        expected_fingerprint=before.fingerprint,
    )
    assert applied.config.allowed_users == frozenset({"u-1", "u-2"})
    assert applied.config.allowed_groups == frozenset({"g-1", "g-2"})
    assert applied.fingerprint != before.fingerprint
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["unrelated"] == {"keep": True}

    bytes_after = path.read_bytes()
    with pytest.raises(CompanyConfigConflict, match="changed"):
        config_file.apply_access_config(
            allowed_users=["u-1", "u-2"],
            admin_users=["u-1"],
            allowed_groups=["g-1"],
            expected_fingerprint=before.fingerprint,
        )
    assert path.read_bytes() == bytes_after
```

- [ ] **Bước 2: Viết test RED cho rollback và group mutation**

```python
def test_access_rollback_and_group_mutation_protect_last_group(tmp_path: Path) -> None:
    config_file = _config_file(tmp_path / "config.yaml")
    before = config_file.read_access_config()
    applied = config_file.apply_access_config(
        allowed_users=["u-1", "u-2"],
        admin_users=["u-1"],
        allowed_groups=["g-1", "g-2"],
        expected_fingerprint=before.fingerprint,
    )
    rolled_back = config_file.rollback_access_config(
        before, expected_fingerprint=applied.fingerprint
    )
    assert rolled_back.config.allowed_groups == frozenset({"g-1"})
    assert "g-2" in config_file.mutate("add_group", "g-2").allowed_groups
    assert "g-2" not in config_file.mutate("remove_group", "g-2").allowed_groups
    with pytest.raises(CompanyConfigError, match="last allowed group"):
        config_file.mutate("remove_group", "g-1")
```

- [ ] **Bước 3: Chạy RED**

```powershell
python -m pytest tests/python/test_company_config.py::test_access_fingerprint_apply_conflict_and_unrelated_yaml tests/python/test_company_config.py::test_access_rollback_and_group_mutation_protect_last_group -q -p no:cacheprovider
```

Kỳ vọng: FAIL vì thiếu snapshot/conflict API.

- [ ] **Bước 4: Cài đặt snapshot và fingerprint chỉ trên ba access set**

Thêm imports `hashlib`, `hmac`, `json`, `threading` và:

```python
class CompanyConfigConflict(CompanyConfigError):
    pass


@dataclass(frozen=True, slots=True)
class AccessConfigSnapshot:
    config: CompanyConfig
    fingerprint: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "allowed_users": sorted(self.config.allowed_users),
            "admin_users": sorted(self.config.admin_users),
            "allowed_groups": sorted(self.config.allowed_groups),
            "fingerprint": self.fingerprint,
        }


def _access_fingerprint(config: CompanyConfig) -> str:
    payload = {
        "allowed_users": sorted(config.allowed_users),
        "admin_users": sorted(config.admin_users),
        "allowed_groups": sorted(config.allowed_groups),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

Trong `CompanyConfigFile.__init__`, thêm `self._lock = threading.RLock()`. Thêm:

```python
    def read_access_config(self) -> AccessConfigSnapshot:
        with self._lock:
            config = self.load(env={})
            return AccessConfigSnapshot(config, _access_fingerprint(config))

    def apply_access_config(
        self, *, allowed_users: Any, admin_users: Any, allowed_groups: Any,
        expected_fingerprint: str,
    ) -> AccessConfigSnapshot:
        with self._lock:
            current = self.read_access_config()
            if not hmac.compare_digest(current.fingerprint, str(expected_fingerprint)):
                raise CompanyConfigConflict("company access config changed; reload")
            updated = self.update_atomic(
                {
                    "allowed_users": sorted(_ids(allowed_users)),
                    "admin_users": sorted(_ids(admin_users)),
                    "allowed_groups": sorted(_ids(allowed_groups)),
                }
            )
            return AccessConfigSnapshot(updated, _access_fingerprint(updated))

    def rollback_access_config(
        self, snapshot: AccessConfigSnapshot, *, expected_fingerprint: str,
    ) -> AccessConfigSnapshot:
        with self._lock:
            current = self.read_access_config()
            if not hmac.compare_digest(current.fingerprint, str(expected_fingerprint)):
                raise CompanyConfigConflict("company access config changed after apply")
            return self.apply_access_config(
                allowed_users=snapshot.config.allowed_users,
                admin_users=snapshot.config.admin_users,
                allowed_groups=snapshot.config.allowed_groups,
                expected_fingerprint=current.fingerprint,
            )
```

Mở rộng `mutate()` với `groups = set(current.allowed_groups)`, action
`add_group`/`remove_group`, chặn xóa group cuối, rồi ghi cả ba tập trong một
`update_atomic()`.

- [ ] **Bước 5: Chạy GREEN và toàn bộ config suite**

```powershell
python -m pytest tests/python/test_company_config.py -q -p no:cacheprovider
```

Kỳ vọng: PASS; invalid batch không ghi file, unrelated YAML và bridge-token rule
được giữ nguyên.

- [ ] **Bước 6: Commit**

```powershell
git add -- hermes-plugin/company_config.py tests/python/test_company_config.py
git diff --cached --check
git diff --cached --name-only
git commit -m "feat: add atomic access config snapshots"
```

Kỳ vọng: staged list chỉ có hai file trên.

---

### Task 2: Phân trang conversation, message và activity

**Files:**

- Modify: `hermes-plugin/history_store.py:538-965`
- Test: `tests/python/test_history_store.py`

- [ ] **Bước 1: Viết test RED cho ba page API**

```python
def test_admin_history_pages_filter_order_and_decode_metadata(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    for index in range(3):
        store.store_message(
            thread_type="group",
            thread_id="g-1",
            sender_id=f"u-{index}",
            text=f"báo giá {index}",
            provider_message_id=f"m-{index}",
            sent_at=f"2026-08-10T0{index}:00:00Z",
            attachments=[{"kind": "file", "filename": f"f-{index}.txt", "download_status": "pending"}],
        )
    store.store_message(
        thread_type="dm", thread_id="u-1", sender_id="u-1", text="riêng",
        provider_message_id="dm-1", sent_at="2026-08-10T04:00:00Z",
    )
    for index in range(3):
        store.log_tool_activity(
            requester_id="web-admin" if index < 2 else "u-1",
            thread_type="system" if index < 2 else "dm",
            thread_id="admin-web" if index < 2 else "u-1",
            tool_name=f"admin_web.action_{index}", status="success",
            metadata={"index": index}, occurred_at=f"2026-08-10T05:00:0{index}Z",
        )

    conversations = store.list_conversations(limit=1, offset=0)
    assert len(conversations["items"]) == 1
    assert conversations["next_offset"] == 1
    group = next(
        item for item in store.list_conversations(limit=10)["items"]
        if item["thread_id"] == "g-1"
    )
    messages = store.page_messages(group["id"], query="báo giá", limit=2, offset=0)
    assert [item["text"] for item in messages["items"]] == ["báo giá 1", "báo giá 2"]
    assert messages["items"][0]["attachments"][0]["filename"] == "f-1.txt"
    assert messages["next_offset"] == 2
    activity = store.page_tool_activity(requester_id="web-admin", limit=10)
    assert len(activity["items"]) == 2
    assert activity["items"][0]["metadata"]["index"] == 1
```

- [ ] **Bước 2: Chạy RED**

```powershell
python -m pytest tests/python/test_history_store.py::test_admin_history_pages_filter_order_and_decode_metadata -q -p no:cacheprovider
```

Kỳ vọng: FAIL vì thiếu page API.

- [ ] **Bước 3: Cài đặt list conversation**

```python
    @staticmethod
    def _page(limit: int, offset: int, *, maximum: int) -> tuple[int, int]:
        normalized_limit = max(1, min(int(limit), maximum))
        normalized_offset = int(offset)
        if normalized_offset < 0:
            raise ValueError("offset must not be negative")
        return normalized_limit, normalized_offset

    def list_conversations(
        self, *, thread_type: str | None = None, query: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        capped, start = self._page(limit, offset, maximum=100)
        clauses = ["c.account_id=?"]
        params: list[Any] = [self.account_id]
        if thread_type:
            clauses.append("c.thread_type=?")
            params.append(self._thread_type(thread_type))
        if query:
            clauses.append("(c.title LIKE ? OR c.thread_id LIKE ?)")
            needle = f"%{str(query)}%"
            params.extend([needle, needle])
        rows = self.connection.execute(
            "SELECT c.*, COUNT(m.id) AS message_count "
            "FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id "
            f"WHERE {' AND '.join(clauses)} GROUP BY c.id "
            "ORDER BY c.last_message_at DESC, c.id DESC LIMIT ? OFFSET ?",
            [*params, capped + 1, start],
        ).fetchall()
        items = [dict(row) for row in rows[:capped]]
        return {"items": items, "limit": capped, "offset": start,
                "next_offset": start + capped if len(rows) > capped else None}
```

- [ ] **Bước 4: Cài đặt message/activity page**

```python
    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM conversations WHERE id=? AND account_id=?",
            (int(conversation_id), self.account_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def page_messages(
        self, conversation_id: int, *, sender_id: str | None = None,
        since: str | None = None, until: str | None = None,
        query: str | None = None, limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        if self.get_conversation(conversation_id) is None:
            raise ValueError("conversation does not exist for this account")
        capped, start = self._page(limit, offset, maximum=100)
        clauses = ["m.conversation_id=?"]
        params: list[Any] = [int(conversation_id)]
        if sender_id is not None:
            clauses.append("m.sender_id=?")
            params.append(str(sender_id))
        if since is not None:
            clauses.append("m.sent_at>=?")
            params.append(str(since))
        if until is not None:
            clauses.append("m.sent_at<=?")
            params.append(str(until))
        if query is not None:
            clauses.append("m.text LIKE ?")
            params.append(f"%{str(query)}%")
        rows = self.connection.execute(
            "SELECT m.*, c.thread_type, c.thread_id, c.title "
            "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY m.sent_at DESC, m.id DESC LIMIT ? OFFSET ?",
            [*params, capped + 1, start],
        ).fetchall()
        selected = rows[:capped]
        message_ids = [int(row["id"]) for row in selected]
        attachments: dict[int, list[dict[str, Any]]] = {key: [] for key in message_ids}
        if message_ids:
            placeholders = ",".join("?" for _ in message_ids)
            attachment_rows = self.connection.execute(
                "SELECT * FROM attachments "
                f"WHERE message_id IN ({placeholders}) ORDER BY message_id, attachment_index",
                message_ids,
            ).fetchall()
            for attachment in attachment_rows:
                attachments[int(attachment["message_id"])].append(dict(attachment))
        items = []
        for row in reversed(selected):
            item = self._row(row)
            item["attachments"] = attachments[int(row["id"])]
            items.append(item)
        return {
            "items": items,
            "limit": capped,
            "offset": start,
            "next_offset": start + capped if len(rows) > capped else None,
        }

    def page_tool_activity(
        self, *, requester_id: str | None = None, tool_name: str | None = None,
        status: str | None = None, thread_type: str | None = None,
        thread_id: str | None = None, since: str | None = None,
        until: str | None = None, limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        capped, start = self._page(limit, offset, maximum=100)
        clauses = ["1=1"]
        params: list[Any] = []
        for column, value in (
            ("requester_id", requester_id),
            ("tool_name", tool_name),
            ("status", status),
            ("thread_type", thread_type),
            ("thread_id", thread_id),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(str(value))
        if since is not None:
            clauses.append("occurred_at>=?")
            params.append(str(since))
        if until is not None:
            clauses.append("occurred_at<=?")
            params.append(str(until))
        rows = self.connection.execute(
            f"SELECT * FROM tool_activity WHERE {' AND '.join(clauses)} "
            "ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, capped + 1, start],
        ).fetchall()
        items = []
        for row in rows[:capped]:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            items.append(item)
        return {
            "items": items,
            "limit": capped,
            "offset": start,
            "next_offset": start + capped if len(rows) > capped else None,
        }
```

- [ ] **Bước 5: Chạy GREEN và schema regression**

```powershell
python -m pytest tests/python/test_history_store.py -q -p no:cacheprovider
```

Kỳ vọng: PASS, `EXPECTED_TABLES` không đổi và migration checksum test vẫn PASS.

- [ ] **Bước 6: Commit**

```powershell
git add -- hermes-plugin/history_store.py tests/python/test_history_store.py
git diff --cached --check
git commit -m "feat: add admin history pagination"
```

---

### Task 3: Transaction runtime cho access config và group action

**Files:**

- Modify: `hermes-plugin/admin.py:46-191`
- Modify: `hermes-plugin/tooling.py:262-298,423-439`
- Test: `tests/python/test_tooling.py`

- [ ] **Bước 1: Viết test RED cho apply một lần và rollback file/runtime**

```python
@pytest.mark.asyncio
async def test_admin_access_transaction_applies_once_and_rolls_back(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {"gateway": {"platforms": {"zalo": {"extra": config().to_mapping()}}}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config_file = CompanyConfigFile(path)
    runtime = [config()]
    applied: list[CompanyConfig] = []

    def runtime_provider() -> CompanyConfig:
        return runtime[-1]

    def runtime_applier(value: CompanyConfig) -> None:
        runtime.append(value)
        applied.append(value)

    admin = AdminService(
        config_file=config_file, store=HistoryStore(tmp_path / "h.sqlite"),
        runtime_config_provider=runtime_provider,
        runtime_config_applier=runtime_applier,
    )
    snapshot = admin.get_access_config(requester=requester("admin", admin=True))
    result = await admin.apply_access_config(
        allowed_users=["admin", "u-1", "u-2"], admin_users=["admin"],
        allowed_groups=["g-1", "g-2"],
        expected_fingerprint=snapshot["fingerprint"],
        requester=requester("admin", admin=True),
    )
    assert result["config"]["allowed_groups"] == ["g-1", "g-2"]
    assert len(applied) == 1
    assert applied[0].bridge_token == config().bridge_token

    before = config_file.read_access_config()
    calls: list[CompanyConfig] = []

    def fail_then_restore(value: CompanyConfig) -> None:
        calls.append(value)
        if len(calls) == 1:
            raise RuntimeError("runtime apply failed")

    failing = AdminService(
        config_file=config_file, store=HistoryStore(tmp_path / "failure.sqlite"),
        runtime_config_provider=lambda: runtime[-1],
        runtime_config_applier=fail_then_restore,
    )
    with pytest.raises(RuntimeError, match="runtime apply failed"):
        await failing.apply_access_config(
            allowed_users=["admin", "u-1"], admin_users=["admin"],
            allowed_groups=["g-1"], expected_fingerprint=before.fingerprint,
            requester=requester("admin", admin=True),
        )
    assert config_file.read_access_config().fingerprint == before.fingerprint
    assert len(calls) == 2
```

- [ ] **Bước 2: Chạy RED**

```powershell
python -m pytest tests/python/test_tooling.py::test_admin_access_transaction_applies_once_and_rolls_back -q -p no:cacheprovider
```

Kỳ vọng: FAIL vì `AdminService` chưa có transaction API.

- [ ] **Bước 3: Mở rộng AdminService**

Thêm `runtime_config_provider`, `runtime_config_applier` vào constructor và
`self._config_lock = asyncio.Lock()`. Thêm:

```python
    def get_access_config(self, *, requester: Requester) -> dict[str, Any]:
        self.require(requester)
        if self.config_file is None:
            raise CompanyConfigError("company config file is not configured")
        return self.config_file.read_access_config().to_mapping()

    async def apply_access_config(
        self, *, allowed_users: Any, admin_users: Any, allowed_groups: Any,
        expected_fingerprint: str, requester: Requester,
    ) -> dict[str, Any]:
        self.require(requester)
        if self.config_file is None or self.runtime_config_provider is None:
            raise CompanyConfigError("company config runtime is not configured")
        async with self._config_lock:
            persisted_before = self.config_file.read_access_config()
            runtime_before = self.runtime_config_provider()
            persisted_after = self.config_file.apply_access_config(
                allowed_users=allowed_users, admin_users=admin_users,
                allowed_groups=allowed_groups,
                expected_fingerprint=expected_fingerprint,
            )
            runtime_after = replace(
                persisted_after.config, bridge_token=runtime_before.bridge_token
            )
            try:
                if self.runtime_config_applier is not None:
                    await _maybe_call(self.runtime_config_applier, runtime_after)
            except Exception:
                self.config_file.rollback_access_config(
                    persisted_before,
                    expected_fingerprint=persisted_after.fingerprint,
                )
                if self.runtime_config_applier is not None:
                    await _maybe_call(self.runtime_config_applier, runtime_before)
                raise
            return {
                "success": True,
                "config": persisted_after.config.to_mapping(),
                "fingerprint": persisted_after.fingerprint,
            }
```

Import `asyncio` và `replace` trong `admin.py`.

- [ ] **Bước 4: Chuyển config_mutate sang cùng transaction**

Đổi method và nhánh trong `action()` thành code sau:

```python
    async def config_mutate(
        self, action: str, zalo_id: str, *, requester: Requester,
    ) -> dict[str, Any]:
        self.require(requester)
        value = str(zalo_id or "").strip()
        if not value:
            raise CompanyConfigError("Zalo ID is required")
        snapshot = self.config_file.read_access_config()
        users = set(snapshot.config.allowed_users)
        admins = set(snapshot.config.admin_users)
        groups = set(snapshot.config.allowed_groups)
        if action == "add_user":
            users.add(value)
        elif action == "remove_user":
            if value in admins:
                raise CompanyConfigError("remove admin role before removing user")
            users.discard(value)
        elif action == "add_admin":
            if value not in users:
                raise CompanyConfigError("admin must already be an allowed user")
            admins.add(value)
        elif action == "remove_admin":
            if value in admins and len(admins) == 1:
                raise CompanyConfigError("cannot remove the last admin")
            admins.discard(value)
        elif action == "add_group":
            groups.add(value)
        elif action == "remove_group":
            if value in groups and len(groups) == 1:
                raise CompanyConfigError("cannot remove the last allowed group")
            groups.discard(value)
        else:
            raise CompanyConfigError(f"unknown config mutation: {action}")
        result = await self.apply_access_config(
            allowed_users=users, admin_users=admins, allowed_groups=groups,
            expected_fingerprint=snapshot.fingerprint, requester=requester,
        )
        return {**result, "action": action}

    async def action(self, action: str, *, requester: Requester, **args: Any) -> Any:
        self.require(requester)
        action = str(action or "").strip().lower()
        config_actions = {
            "add_user", "remove_user", "add_admin", "remove_admin",
            "add_group", "remove_group",
        }
        if action in config_actions:
            return await self.config_mutate(
                action, str(args.get("zalo_id") or args.get("user_id") or ""),
                requester=requester,
            )
        return await self._action_without_config(action, requester=requester, **args)
```

Thêm helper chứa nguyên contract cũ:

```python
    async def _action_without_config(
        self, action: str, *, requester: Requester, **args: Any,
    ) -> Any:
        if action == "status":
            result = await _maybe_call(self.status_provider)
            return result if result is not None else {"success": True}
        if action == "memory_add":
            return self.memory_add(str(args.get("text") or ""), requester=requester)
        if action == "memory_update":
            return self.memory_update(
                str(args.get("old") or ""), str(args.get("new") or ""),
                requester=requester,
            )
        if action == "memory_delete":
            return self.memory_delete(str(args.get("text") or ""), requester=requester)
        if action == "history_export":
            return self.history_export(
                str(args.get("destination") or "history.jsonl"),
                requester=requester, **_history_filters(args),
            )
        if action == "history_delete":
            return self.history_delete(requester=requester, **_history_filters(args))
        if action in {"login_qr", "reconnect", "start", "stop", "restart"}:
            return await _maybe_call(self.lifecycle.get(action), args)
        if action == "show_logs":
            lines = int(args.get("lines") or 100)
            if self.log_provider is not None:
                return await _maybe_call(self.log_provider, lines)
            return self.show_logs(lines, requester=requester)
        raise ValueError(f"unknown admin action: {action}")
```

Trong `ZaloTooling.zalo_admin()`, dùng block sau thay callback config cũ:

```python
config_actions = {
    "add_user", "remove_user", "add_admin", "remove_admin",
    "add_group", "remove_group",
}
result = await self.admin.action(action, requester=requester, **admin_args)
if action in config_actions and isinstance(result, Mapping):
    rendered = result.get("config")
    if isinstance(rendered, Mapping):
        refreshed = CompanyConfig.from_mapping(rendered)
        self.config = replace(
            refreshed, bridge_token=getattr(self.config, "bridge_token", "")
        )
```

Không gọi `on_config_change` lần thứ hai vì `AdminService` đã thực hiện runtime
transaction.

Thêm vào `ZALO_ADMIN_SCHEMA`:

```python
"allowed_users": {"type": "array", "items": {"type": "string"}},
"admin_users": {"type": "array", "items": {"type": "string"}},
"allowed_groups": {"type": "array", "items": {"type": "string"}},
"fingerprint": {"type": "string"},
```

- [ ] **Bước 5: Chạy tooling regression**

```powershell
python -m pytest tests/python/test_tooling.py -q -p no:cacheprovider
```

Kỳ vọng: PASS; non-admin vẫn bị chặn, memory/history/lifecycle cũ không đổi.

- [ ] **Bước 6: Commit**

```powershell
git add -- hermes-plugin/admin.py hermes-plugin/tooling.py tests/python/test_tooling.py
git diff --cached --check
git commit -m "feat: apply access config as one transaction"
```

---

### Task 4: Web settings, scrypt, cookie signer và login throttle

**Files:**

- Modify: `hermes-plugin/admin.py:1-45`
- Test: `tests/python/test_tooling.py`

- [ ] **Bước 1: Viết test RED cho settings và password hash**

```python
from admin import (
    AdminSessionSigner,
    AdminWebSettings,
    AdminWebSettingsError,
    LoginThrottle,
    hash_admin_password,
    verify_admin_password,
)


def test_admin_web_settings_hash_signer_and_throttle() -> None:
    encoded = hash_admin_password("mat-khau", salt=b"0123456789abcdef")
    env = {
        "ZALO_ADMIN_WEB_ENABLED": "true",
        "ZALO_ADMIN_WEB_HOST": "127.0.0.1",
        "ZALO_ADMIN_WEB_PORT": "8790",
        "ZALO_ADMIN_WEB_PASSWORD_HASH": encoded,
        "ZALO_ADMIN_WEB_SESSION_SECRET": "s" * 32,
        "ZALO_ADMIN_WEB_SESSION_TTL_SECONDS": "86400",
    }
    settings = AdminWebSettings.from_env(env)
    assert settings.enabled is True
    assert settings.port == 8790
    assert verify_admin_password("mat-khau", encoded) is True
    assert verify_admin_password("sai", encoded) is False

    with pytest.raises(AdminWebSettingsError, match="127.0.0.1"):
        AdminWebSettings.from_env({**env, "ZALO_ADMIN_WEB_HOST": "0.0.0.0"})
    with pytest.raises(AdminWebSettingsError, match="PASSWORD_HASH"):
        AdminWebSettings.from_env({**env, "ZALO_ADMIN_WEB_PASSWORD_HASH": ""})

    signer = AdminSessionSigner(b"k" * 32)
    cookie = signer.sign("session-id")
    assert signer.verify(cookie) == "session-id"
    with pytest.raises(ValueError, match="signature"):
        signer.verify(cookie + "x")

    now = [1000.0]
    throttle = LoginThrottle(clock=lambda: now[0])
    for _ in range(4):
        assert throttle.record_failure() == 0
    assert throttle.record_failure() == 300
    assert throttle.retry_after() == 300
    now[0] += 301
    assert throttle.retry_after() == 0
```

- [ ] **Bước 2: Chạy RED**

```powershell
python -m pytest tests/python/test_tooling.py::test_admin_web_settings_hash_signer_and_throttle -q -p no:cacheprovider
```

Kỳ vọng: FAIL vì các symbol chưa tồn tại.

- [ ] **Bước 3: Cài đặt primitives bằng standard library**

Thêm imports `base64`, `hashlib`, `hmac`, `os`, `time`, `dataclass` và:

```python
class AdminWebSettingsError(ValueError):
    pass


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class AdminWebSettings:
    enabled: bool
    host: str = "127.0.0.1"
    port: int = 8790
    password_hash: str = ""
    session_secret: bytes = b""
    session_ttl_seconds: int = 86400

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AdminWebSettings":
        source = os.environ if env is None else env
        enabled = _enabled(source.get("ZALO_ADMIN_WEB_ENABLED"))
        host = str(source.get("ZALO_ADMIN_WEB_HOST") or "127.0.0.1").strip()
        if host != "127.0.0.1":
            raise AdminWebSettingsError("ZALO_ADMIN_WEB_HOST must be 127.0.0.1")
        try:
            port = int(source.get("ZALO_ADMIN_WEB_PORT") or 8790)
            ttl = int(source.get("ZALO_ADMIN_WEB_SESSION_TTL_SECONDS") or 86400)
        except (TypeError, ValueError) as exc:
            raise AdminWebSettingsError("admin web port and TTL must be integers") from exc
        password_hash = str(source.get("ZALO_ADMIN_WEB_PASSWORD_HASH") or "")
        session_secret = str(source.get("ZALO_ADMIN_WEB_SESSION_SECRET") or "").encode("utf-8")
        if not 1 <= port <= 65535:
            raise AdminWebSettingsError("ZALO_ADMIN_WEB_PORT is invalid")
        if not 300 <= ttl <= 604800:
            raise AdminWebSettingsError("session TTL must be between 300 and 604800")
        if enabled and not password_hash:
            raise AdminWebSettingsError("ZALO_ADMIN_WEB_PASSWORD_HASH is required")
        if enabled and len(session_secret) < 32:
            raise AdminWebSettingsError("ZALO_ADMIN_WEB_SESSION_SECRET must be at least 32 bytes")
        return cls(enabled, host, port, password_hash, session_secret, ttl)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_admin_password(password: str, *, salt: bytes | None = None) -> str:
    raw = str(password).encode("utf-8")
    if not raw:
        raise ValueError("password is required")
    actual_salt = salt or os.urandom(16)
    digest = hashlib.scrypt(raw, salt=actual_salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${_b64(actual_salt)}${_b64(digest)}"


def verify_admin_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = str(encoded_hash).split("$", 5)
        expected_bytes = _unb64(expected)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            str(password).encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r),
            p=int(p), dklen=len(expected_bytes),
        )
        return hmac.compare_digest(actual, expected_bytes)
    except (TypeError, ValueError):
        return False


class AdminSessionSigner:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("session secret must be at least 32 bytes")
        self.secret = secret

    def sign(self, session_id: str) -> str:
        signature = hmac.new(
            self.secret, session_id.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return f"{session_id}.{signature}"

    def verify(self, cookie: str) -> str:
        try:
            session_id, supplied = str(cookie).rsplit(".", 1)
        except ValueError as exc:
            raise ValueError("invalid session signature") from exc
        expected = hmac.new(
            self.secret, session_id.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise ValueError("invalid session signature")
        return session_id


class LoginThrottle:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.failures: list[float] = []
        self.locked_until = 0.0

    def retry_after(self) -> int:
        return max(0, int(self.locked_until - self.clock() + 0.999))

    def record_failure(self) -> int:
        now = self.clock()
        self.failures = [stamp for stamp in self.failures if now - stamp <= 300]
        self.failures.append(now)
        if len(self.failures) >= 5:
            self.locked_until = now + 300
        return self.retry_after()

    def reset(self) -> None:
        self.failures.clear()
        self.locked_until = 0.0
```

- [ ] **Bước 4: Chạy GREEN và tooling regression**

```powershell
python -m pytest tests/python/test_tooling.py -q -p no:cacheprovider
```

Kỳ vọng: PASS.

- [ ] **Bước 5: Commit**

```powershell
git add -- hermes-plugin/admin.py tests/python/test_tooling.py
git diff --cached --check
git commit -m "feat: add admin web authentication primitives"
```

---

### Task 5: AdminWebApp, session RAM, CSRF và HTML shell

**Files:**

- Modify: `hermes-plugin/admin.py`
- Test: `tests/python/test_tooling.py`

- [ ] **Bước 1: Viết test RED cho login/session/logout**

```python
from aiohttp.test_utils import TestClient, TestServer
from admin import AdminWebApp


@pytest.mark.asyncio
async def test_admin_web_login_cookie_csrf_expiry_logout_and_audit(tmp_path: Path) -> None:
    settings = AdminWebSettings(
        enabled=True, host="127.0.0.1", port=8790,
        password_hash=hash_admin_password("mat-khau", salt=b"0123456789abcdef"),
        session_secret=b"k" * 32, session_ttl_seconds=3600,
    )
    store = HistoryStore(tmp_path / "h.sqlite")
    web_app = AdminWebApp(
        settings=settings, admin=AdminService(store=store), store=store,
        bridge=None, export_root=tmp_path / "exports",
    )
    client = TestClient(TestServer(web_app.create_application()))
    await client.start_server()
    try:
        denied = await client.get("/admin/api/overview")
        assert denied.status == 401
        login = await client.post("/admin/api/login", json={"password": "mat-khau"})
        assert login.status == 200
        body = await login.json()
        set_cookie = login.headers["Set-Cookie"]
        assert "HttpOnly" in set_cookie and "Secure" in set_cookie
        assert "SameSite=Strict" in set_cookie
        cookie = set_cookie.split(";", 1)[0]

        session = await client.get("/admin/api/session", headers={"Cookie": cookie})
        assert (await session.json())["csrf"] == body["csrf"]
        rejected = await client.post("/admin/api/logout", headers={"Cookie": cookie})
        assert rejected.status == 403
        logout = await client.post(
            "/admin/api/logout",
            headers={"Cookie": cookie, "X-CSRF-Token": body["csrf"]},
        )
        assert logout.status == 200
        tools = [row[0] for row in store.connection.execute(
            "SELECT tool_name FROM tool_activity ORDER BY id"
        )]
        assert tools == ["admin_web.login", "admin_web.logout"]
    finally:
        await client.close()
```

- [ ] **Bước 2: Chạy RED**

```powershell
python -m pytest tests/python/test_tooling.py::test_admin_web_login_cookie_csrf_expiry_logout_and_audit -q -p no:cacheprovider
```

Kỳ vọng: FAIL vì thiếu `AdminWebApp`.

- [ ] **Bước 3: Tạo session model và requester cố định**

```python
import secrets


WEB_ADMIN_REQUESTER = Requester(
    requester_id="web-admin", thread_type="system", thread_id="admin-web",
    is_admin=True, session_key="zalo:system:admin-web",
)


@dataclass(slots=True)
class _AdminSession:
    csrf: str
    expires_at: float
```

Thêm shell hoàn chỉnh; Task sau chỉ bổ sung hàm render, không đổi auth flow:

```python
ADMIN_HTML = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hermes Zalo Admin</title>
<style>
body{margin:0;font-family:system-ui,sans-serif;background:#f4f6f8;color:#17202a}
header{padding:14px 20px;background:#075e54;color:white}#layout{min-height:calc(100vh - 50px)}
nav{display:flex;gap:8px;padding:12px;background:white}button,input{font:inherit;padding:8px}
main{padding:16px}.hidden{display:none}.error{color:#b42318}.card{background:white;padding:14px;border-radius:10px;margin-bottom:10px}
@media(min-width:760px){#layout{display:grid;grid-template-columns:230px 1fr}nav{flex-direction:column}}
</style></head><body><header>Hermes Zalo Admin</header><div id="layout">
<nav id="nav" class="hidden"><button data-view="overview">Tổng quan</button>
<button data-view="access">Danh bạ &amp; Allowlist</button>
<button data-view="history">Hội thoại</button>
<button data-view="system">Hệ thống &amp; Hoạt động</button>
<button id="logout">Đăng xuất</button></nav>
<main><form id="login" class="card"><h1>Đăng nhập</h1>
<label>Mật khẩu <input id="password" type="password" autocomplete="current-password" required></label>
<button type="submit">Đăng nhập</button><p id="login-error" class="error"></p></form>
<section id="app" class="hidden" aria-live="polite"></section></main></div>
<script>
const state={csrf:null,view:"overview",draft:null};
async function api(path,options={}){const headers={"Content-Type":"application/json",...(options.headers||{})};if(state.csrf&&options.method&&options.method!=="GET")headers["X-CSRF-Token"]=state.csrf;const response=await fetch(path,{credentials:"same-origin",...options,headers});const data=await response.json().catch(()=>({code:"invalid_response",message:"Phản hồi không hợp lệ"}));if(!response.ok)throw Object.assign(new Error(data.message||"Yêu cầu thất bại"),{status:response.status,data});return data;}
function clearApp(title){const app=document.querySelector("#app");app.replaceChildren();const heading=document.createElement("h1");heading.textContent=title;app.append(heading);return app;}
function showApp(){document.querySelector("#login").classList.add("hidden");document.querySelector("#nav").classList.remove("hidden");document.querySelector("#app").classList.remove("hidden");}
async function renderCurrent(){clearApp({overview:"Tổng quan",access:"Danh bạ & Allowlist",history:"Hội thoại",system:"Hệ thống & Hoạt động"}[state.view]);}
document.querySelector("#login").addEventListener("submit",async event=>{event.preventDefault();try{const data=await api("/admin/api/login",{method:"POST",body:JSON.stringify({password:document.querySelector("#password").value})});state.csrf=data.csrf;showApp();await renderCurrent();}catch(error){document.querySelector("#login-error").textContent=error.message;}});
document.querySelector("#logout").addEventListener("click",async()=>{await api("/admin/api/logout",{method:"POST",body:"{}"});location.reload();});
for(const button of document.querySelectorAll("[data-view]")){button.addEventListener("click",async()=>{state.view=button.dataset.view;await renderCurrent();});}
</script></body></html>"""
```

- [ ] **Bước 4: Cài đặt AdminWebApp auth shell**

```python
class AdminWebApp:
    COOKIE_NAME = "hermes_zalo_admin"

    def __init__(
        self, *, settings: AdminWebSettings, admin: AdminService,
        store: HistoryStore, bridge: Any, export_root: str | Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.admin = admin
        self.store = store
        self.bridge = bridge
        self.export_root = Path(export_root)
        self.clock = clock
        self.signer = AdminSessionSigner(settings.session_secret)
        self.throttle = LoginThrottle(clock=clock)
        self.sessions: dict[str, _AdminSession] = {}
        self._runner = None
        self._site = None

    def _audit(self, action: str, *, status: str = "success",
               error_text: str | None = None, target_id: str | int | None = None,
               count: int | None = None) -> int:
        metadata = {}
        if target_id is not None:
            metadata["target_id"] = str(target_id)
        if count is not None:
            metadata["count"] = int(count)
        return self.store.log_tool_activity(
            requester_id="web-admin", thread_type="system", thread_id="admin-web",
            tool_name=f"admin_web.{action}", status=status,
            error_text=error_text, metadata=metadata,
        )

    def _error(self, status: int, code: str, message: str, *, retryable=False):
        from aiohttp import web
        return web.json_response(
            {"code": code, "message": message, "retryable": bool(retryable)},
            status=status,
        )

    def _require_session(self, request):
        cookie = request.cookies.get(self.COOKIE_NAME, "")
        session_id = self.signer.verify(cookie)
        session = self.sessions.get(session_id)
        if session is None or session.expires_at < self.clock():
            self.sessions.pop(session_id, None)
            raise ValueError("session expired")
        return session_id, session

    def create_application(self):
        from aiohttp import web

        @web.middleware
        async def auth(request, handler):
            public = {("GET", "/admin/"), ("POST", "/admin/api/login")}
            if (request.method, request.path) not in public:
                try:
                    session_id, session = self._require_session(request)
                except ValueError:
                    return self._error(401, "unauthorized", "Phiên đăng nhập không hợp lệ")
                request["admin_session_id"] = session_id
                request["admin_session"] = session
                if request.method not in {"GET", "HEAD"}:
                    supplied = request.headers.get("X-CSRF-Token", "")
                    if not hmac.compare_digest(supplied, session.csrf):
                        return self._error(403, "csrf", "CSRF token không hợp lệ")
            return await handler(request)

        app = web.Application(middlewares=[auth])
        app.router.add_get("/admin/", self._page)
        app.router.add_post("/admin/api/login", self._login)
        app.router.add_get("/admin/api/session", self._session_route)
        app.router.add_post("/admin/api/logout", self._logout)
        app.router.add_get("/admin/api/overview", self._overview)
        return app

    async def _page(self, _request):
        from aiohttp import web
        return web.Response(text=ADMIN_HTML, content_type="text/html")

    async def _login(self, request):
        from aiohttp import web
        retry = self.throttle.retry_after()
        if retry:
            return self._error(429, "login_throttled", "Đăng nhập đang tạm khóa", retryable=True)
        body = await request.json()
        if not verify_admin_password(str(body.get("password") or ""), self.settings.password_hash):
            self.throttle.record_failure()
            return self._error(401, "bad_credentials", "Mật khẩu không đúng")
        self.throttle.reset()
        session_id = secrets.token_urlsafe(32)
        session = _AdminSession(
            csrf=secrets.token_urlsafe(24),
            expires_at=self.clock() + self.settings.session_ttl_seconds,
        )
        self.sessions[session_id] = session
        response = web.json_response({"success": True, "csrf": session.csrf})
        response.set_cookie(
            self.COOKIE_NAME, self.signer.sign(session_id), httponly=True,
            secure=True, samesite="Strict", path="/admin",
            max_age=self.settings.session_ttl_seconds,
        )
        self._audit("login")
        return response

    async def _session_route(self, request):
        from aiohttp import web
        return web.json_response({"csrf": request["admin_session"].csrf})

    async def _logout(self, request):
        from aiohttp import web
        self.sessions.pop(request["admin_session_id"], None)
        response = web.json_response({"success": True})
        response.del_cookie(self.COOKIE_NAME, path="/admin")
        self._audit("logout")
        return response

    async def _overview(self, _request):
        from aiohttp import web
        result = await self.admin.action("status", requester=WEB_ADMIN_REQUESTER)
        return web.json_response(redact_value(result))

    async def start(self) -> bool:
        if not self.settings.enabled or self._runner is not None:
            return False
        from aiohttp import web
        runner = web.AppRunner(self.create_application())
        try:
            await runner.setup()
            site = web.TCPSite(runner, self.settings.host, self.settings.port)
            await site.start()
        except BaseException:
            await runner.cleanup()
            raise
        self._runner, self._site = runner, site
        return True

    async def stop(self) -> None:
        self.sessions.clear()
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._site = None
```

Import `redact_value` từ `history_store` ở cả relative và top-level import.

- [ ] **Bước 5: Chạy GREEN và tamper/expiry tests**

```powershell
python -m pytest tests/python/test_tooling.py::test_admin_web_login_cookie_csrf_expiry_logout_and_audit tests/python/test_tooling.py::test_admin_web_settings_hash_signer_and_throttle -q -p no:cacheprovider
```

Kỳ vọng: PASS. Thêm assertion riêng rằng cookie tampered và clock vượt TTL đều
trả `401`; `stop()` làm `sessions == {}`.

- [ ] **Bước 6: Commit**

```powershell
git add -- hermes-plugin/admin.py tests/python/test_tooling.py
git diff --cached --check
git commit -m "feat: serve authenticated admin web shell"
```

---

### Task 6: Tổng quan, danh bạ, nhóm và Lưu và áp dụng

**Files:**

- Modify: `hermes-plugin/admin.py`
- Test: `tests/python/test_tooling.py`

- [ ] **Bước 1: Mở rộng FakeBridge và viết test RED**

Trong `FakeBridge.request()` của test, thêm response cho `/health`, `/policy`,
`/friends`, `/groups`, `/chat-info`. Thêm:

```python
@pytest.mark.asyncio
async def test_admin_web_access_apply_maps_conflict_and_audits(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {"gateway": {"platforms": {"zalo": {"extra": config().to_mapping()}}}},
            sort_keys=False,
        ), encoding="utf-8",
    )
    store = HistoryStore(tmp_path / "h.sqlite")
    runtime = [config()]
    admin = AdminService(
        config_file=CompanyConfigFile(path), store=store,
        status_provider=lambda: {"success": True, "connected": True,
                                 "bot": {"id": "bot", "name": "Trợ lý"}},
        runtime_config_provider=lambda: runtime[-1],
        runtime_config_applier=runtime.append,
    )
    client, cookie, csrf = await authenticated_web_client(
        tmp_path, admin=admin, store=store, bridge=FakeBridge()
    )
    try:
        access = await client.get("/admin/api/access", headers={"Cookie": cookie})
        snapshot = await access.json()
        applied = await client.post(
            "/admin/api/access/apply",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={
                "allowed_users": ["admin", "u-1", "u-2"],
                "admin_users": ["admin"],
                "allowed_groups": ["g-1", "g-2"],
                "fingerprint": snapshot["fingerprint"],
            },
        )
        assert applied.status == 200
        assert runtime[-1].allowed_groups == frozenset({"g-1", "g-2"})
        conflict = await client.post(
            "/admin/api/access/apply",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={**snapshot, "allowed_groups": ["g-1"]},
        )
        assert conflict.status == 409
        audit = store.connection.execute(
            "SELECT requester_id, thread_type, thread_id, tool_name FROM tool_activity "
            "WHERE tool_name='admin_web.apply_access_config' ORDER BY id LIMIT 1"
        ).fetchone()
        assert tuple(audit) == ("web-admin", "system", "admin-web", "admin_web.apply_access_config")
    finally:
        await client.close()
```

`authenticated_web_client()` là async helper đầy đủ trong cùng test file: tạo
settings/hash, `AdminWebApp`, `TestClient`, login, tách cookie pair và trả
`(client, cookie_pair, csrf)`.

- [ ] **Bước 2: Chạy RED**

```powershell
python -m pytest tests/python/test_tooling.py::test_admin_web_access_apply_maps_conflict_and_audits -q -p no:cacheprovider
```

Kỳ vọng: FAIL vì route chưa có.

- [ ] **Bước 3: Đăng ký route và bridge JSON helper**

```python
app.router.add_get("/admin/api/access", self._access)
app.router.add_get("/admin/api/friends", self._friends)
app.router.add_get("/admin/api/groups", self._groups)
app.router.add_get("/admin/api/groups/{group_id}/members", self._group_members)
app.router.add_post("/admin/api/access/apply", self._apply_access)
```

```python
    async def _bridge_json(self, method: str, path: str, *, payload=None, params=None):
        if self.bridge is None:
            return {"error": "bridge is unavailable"}
        result = self.bridge.request(method, path, payload=payload, params=params)
        if inspect.isawaitable(result):
            result = await result
        return redact_value(result)

    async def _access(self, _request):
        from aiohttp import web
        return web.json_response(self.admin.get_access_config(requester=WEB_ADMIN_REQUESTER))

    async def _friends(self, _request):
        from aiohttp import web
        return web.json_response(await self._bridge_json("GET", "/friends"))

    async def _groups(self, _request):
        from aiohttp import web
        return web.json_response(await self._bridge_json("GET", "/groups"))

    async def _group_members(self, request):
        from aiohttp import web
        result = await self._bridge_json(
            "GET", "/chat-info",
            params={"threadId": request.match_info["group_id"], "threadType": "group"},
        )
        return web.json_response(result)
```

- [ ] **Bước 4: Cài handler apply và error contract**

```python
    async def _apply_access(self, request):
        from aiohttp import web
        body = await request.json()
        try:
            result = await self.admin.apply_access_config(
                allowed_users=body.get("allowed_users"),
                admin_users=body.get("admin_users"),
                allowed_groups=body.get("allowed_groups"),
                expected_fingerprint=str(body.get("fingerprint") or ""),
                requester=WEB_ADMIN_REQUESTER,
            )
        except CompanyConfigConflict:
            self._audit("apply_access_config", status="failed", error_text="config conflict")
            return self._error(409, "config_conflict", "Cấu hình đã thay đổi; hãy tải lại")
        except (CompanyConfigError, TypeError, ValueError) as exc:
            message = redact_text(str(exc)) or "Cấu hình không hợp lệ"
            self._audit("apply_access_config", status="failed", error_text=message)
            return self._error(400, "invalid_config", message)
        except Exception as exc:
            message = redact_text(str(exc)) or "Không thể áp dụng cấu hình"
            self._audit("apply_access_config", status="failed", error_text=message)
            return self._error(500, "apply_failed", message)
        count = sum(len(result["config"][key]) for key in (
            "allowed_users", "admin_users", "allowed_groups"
        ))
        self._audit("apply_access_config", count=count)
        return web.json_response(redact_value(result))
```

Không đưa ba array ID vào audit metadata.

- [ ] **Bước 5: Hoàn thiện HTML/JS Tổng quan và Access**

JavaScript phải tạo node bằng `document.createElement` và gán dữ liệu bằng
`textContent`; không dùng `innerHTML`. `renderAccess()` tải access/friends/groups,
giữ draft trong `state.draft`, render checkbox member/admin/group, cho nhập ID,
và chỉ POST khi bấm **Lưu và áp dụng**. Response `409` giữ draft và hiện nút
**Tải lại cấu hình**.

Giữ hàm `api()` đã có và thêm các hàm render hoàn chỉnh:

```javascript
function line(label,value){const p=document.createElement("p");const strong=document.createElement("strong");strong.textContent=label+": ";p.append(strong,document.createTextNode(String(value??"—")));return p;}
function values(result,key){const raw=result?.items??result?.[key]??result?.result??[];return Array.isArray(raw)?raw:[];}
function setMembership(list,id,checked){const set=new Set(list);if(checked)set.add(String(id));else set.delete(String(id));return [...set].sort();}
function checkbox(label,checked,onChange){const wrapper=document.createElement("label");const input=document.createElement("input");input.type="checkbox";input.checked=checked;input.addEventListener("change",()=>onChange(input.checked));wrapper.append(input,document.createTextNode(" "+label));return wrapper;}
async function renderOverview(){const app=clearApp("Tổng quan");const data=await api("/admin/api/overview");app.append(line("Zalo ID",data.bot?.id),line("Tên",data.bot?.name),line("Kết nối",data.connected?"Đã kết nối":"Mất kết nối"),line("Hội thoại",data.history?.conversations),line("Tin nhắn",data.history?.messages),line("Provider",data.provider??"unknown"),line("Model",data.model??"unknown"));}
async function renderAccess(){
  const app=clearApp("Danh bạ & Allowlist");
  const [access,friendsResult,groupsResult]=await Promise.all([api("/admin/api/access"),api("/admin/api/friends"),api("/admin/api/groups")]);
  state.draft={allowed_users:[...access.allowed_users],admin_users:[...access.admin_users],allowed_groups:[...access.allowed_groups],fingerprint:access.fingerprint};
  const people=document.createElement("div");people.className="card";const peopleTitle=document.createElement("h2");peopleTitle.textContent="Cá nhân";people.append(peopleTitle);
  for(const person of values(friendsResult,"friends")){const row=document.createElement("p");row.append(document.createTextNode(`${person.name??person.id} (${person.id}) `),checkbox("Thành viên",state.draft.allowed_users.includes(String(person.id)),checked=>{state.draft.allowed_users=setMembership(state.draft.allowed_users,person.id,checked);if(!checked)state.draft.admin_users=setMembership(state.draft.admin_users,person.id,false);}),checkbox("Admin",state.draft.admin_users.includes(String(person.id)),checked=>{state.draft.admin_users=setMembership(state.draft.admin_users,person.id,checked);if(checked)state.draft.allowed_users=setMembership(state.draft.allowed_users,person.id,true);}));people.append(row);}
  const userInput=document.createElement("input");userInput.placeholder="Nhập Zalo ID";const addUser=document.createElement("button");addUser.type="button";addUser.textContent="Thêm thành viên";addUser.onclick=()=>{if(userInput.value.trim())state.draft.allowed_users=setMembership(state.draft.allowed_users,userInput.value.trim(),true);};people.append(userInput,addUser);
  const groups=document.createElement("div");groups.className="card";const groupsTitle=document.createElement("h2");groupsTitle.textContent="Nhóm";groups.append(groupsTitle);
  for(const group of values(groupsResult,"groups")){const row=document.createElement("p");const members=document.createElement("button");members.type="button";members.textContent="Xem thành viên";members.onclick=async()=>{const data=await api(`/admin/api/groups/${encodeURIComponent(group.id)}/members`);const pre=document.createElement("pre");pre.textContent=JSON.stringify(data.result?.members??data.members??[],null,2);row.append(pre);};row.append(document.createTextNode(`${group.name??group.id} (${group.id}) `),checkbox("Allowlist",state.draft.allowed_groups.includes(String(group.id)),checked=>{state.draft.allowed_groups=setMembership(state.draft.allowed_groups,group.id,checked);}),members);groups.append(row);}
  const groupInput=document.createElement("input");groupInput.placeholder="Nhập group ID";const addGroup=document.createElement("button");addGroup.type="button";addGroup.textContent="Thêm nhóm";addGroup.onclick=()=>{if(groupInput.value.trim())state.draft.allowed_groups=setMembership(state.draft.allowed_groups,groupInput.value.trim(),true);};groups.append(groupInput,addGroup);
  const save=document.createElement("button");save.textContent="Lưu và áp dụng";save.onclick=async()=>{const result=await api("/admin/api/access/apply",{method:"POST",body:JSON.stringify(state.draft)});state.draft={...result.config,fingerprint:result.fingerprint};await renderAccess();};app.append(people,groups,save);
}
async function renderCurrent(){try{if(state.view==="overview")await renderOverview();else if(state.view==="access")await renderAccess();else clearApp(state.view==="history"?"Hội thoại":"Hệ thống & Hoạt động");}catch(error){const app=clearApp("Có lỗi");app.append(line("Chi tiết",error.message));if(error.status===409){const reload=document.createElement("button");reload.textContent="Tải lại cấu hình";reload.onclick=renderAccess;app.append(reload);}}}
```

- [ ] **Bước 6: Chạy GREEN và regression**

```powershell
python -m pytest tests/python/test_tooling.py::test_admin_web_access_apply_maps_conflict_and_audits tests/python/test_company_config.py -q -p no:cacheprovider
```

Kỳ vọng: PASS.

- [ ] **Bước 7: Commit**

```powershell
git add -- hermes-plugin/admin.py tests/python/test_tooling.py
git diff --cached --check
git commit -m "feat: manage Zalo access from admin web"
```

---

### Task 7: Hội thoại, export/delete và attachment download

**Files:**

- Modify: `hermes-plugin/admin.py`
- Modify: `hermes-plugin/history_store.py`
- Test: `tests/python/test_tooling.py`
- Test: `tests/python/test_history_store.py`

- [ ] **Bước 1: Viết test RED cho history route và media containment**

```python
@pytest.mark.asyncio
async def test_admin_web_history_export_delete_and_attachment_scope(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    store = HistoryStore(tmp_path / "h.sqlite", media_root=media_root)
    media = media_root / "group" / "g-1" / "file.txt"
    media.parent.mkdir(parents=True)
    media.write_text("safe", encoding="utf-8")
    stored = store.store_message(
        thread_type="group", thread_id="g-1", sender_id="u-1",
        text="báo giá", provider_message_id="m-1",
        attachments=[{
            "kind": "file", "filename": "file.txt", "local_path": str(media),
            "download_status": "downloaded",
        }],
    )
    admin = AdminService(store=store, export_root=tmp_path / "exports")
    client, cookie, csrf = await authenticated_web_client(
        tmp_path, admin=admin, store=store, bridge=FakeBridge()
    )
    try:
        conversations = await client.get("/admin/api/conversations", headers={"Cookie": cookie})
        conversation = (await conversations.json())["items"][0]
        messages = await client.get(
            f"/admin/api/conversations/{conversation['id']}", headers={"Cookie": cookie}
        )
        assert (await messages.json())["items"][0]["text"] == "báo giá"
        attachment = await client.get(
            f"/admin/api/attachments/{stored.attachment_ids[0]}",
            headers={"Cookie": cookie},
        )
        assert attachment.status == 200
        assert await attachment.text() == "safe"
        deleted = await client.post(
            "/admin/api/history/delete",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={"thread_type": "group", "thread_id": "g-1", "confirm": True},
        )
        assert deleted.status == 200
        audit_names = [row[0] for row in store.connection.execute(
            "SELECT tool_name FROM tool_activity ORDER BY id"
        )]
        assert "admin_web.attachment_download" in audit_names
        assert "admin_web.history_delete" in audit_names
    finally:
        await client.close()
```

- [ ] **Bước 2: Chạy RED**

```powershell
python -m pytest tests/python/test_tooling.py::test_admin_web_history_export_delete_and_attachment_scope -q -p no:cacheprovider
```

Kỳ vọng: FAIL vì route và `export_root` chưa tồn tại.

- [ ] **Bước 3: Thêm export root do server kiểm soát**

Mở rộng `AdminService.__init__` với
`export_root: str | Path | None = None`. Thêm:

```python
    def web_history_export(
        self, *, requester: Requester, thread_type: str | None = None,
        thread_id: str | None = None, since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        self.require(requester)
        if self.store is None or self.export_root is None:
            raise CompanyConfigError("history export is not configured")
        self.export_root.mkdir(parents=True, exist_ok=True)
        destination = self.export_root / (
            f"history-{int(time.time())}-{secrets.token_hex(4)}.jsonl"
        )
        result = self.store.export_history(
            destination, thread_type=thread_type, thread_id=thread_id,
            since=since, until=until,
        )
        return {**result, "path": str(destination)}
```

- [ ] **Bước 4: Đăng ký và cài route history**

Đăng ký:

```python
app.router.add_get("/admin/api/conversations", self._conversations)
app.router.add_get("/admin/api/conversations/{conversation_id}", self._conversation)
app.router.add_get("/admin/api/history/search", self._history_search)
app.router.add_post("/admin/api/history/export", self._history_export)
app.router.add_post("/admin/api/history/delete", self._history_delete)
app.router.add_get("/admin/api/attachments/{attachment_id}", self._attachment)
```

Handler list/detail:

```python
    async def _conversations(self, request):
        from aiohttp import web
        try:
            result = self.store.list_conversations(
                thread_type=request.query.get("thread_type"),
                query=request.query.get("query"),
                limit=int(request.query.get("limit", 50)),
                offset=int(request.query.get("offset", 0)),
            )
        except (TypeError, ValueError) as exc:
            return self._error(400, "invalid_page", redact_text(str(exc)) or "Bộ lọc không hợp lệ")
        return web.json_response(redact_value(result))

    async def _conversation(self, request):
        from aiohttp import web
        conversation_id = int(request.match_info["conversation_id"])
        if self.store.get_conversation(conversation_id) is None:
            return self._error(404, "conversation_not_found", "Không tìm thấy hội thoại")
        result = self.store.page_messages(
            conversation_id,
            sender_id=request.query.get("sender_id"),
            since=request.query.get("since"), until=request.query.get("until"),
            query=request.query.get("query"),
            limit=int(request.query.get("limit", 100)),
            offset=int(request.query.get("offset", 0)),
        )
        return web.json_response(redact_value(result))
```

Handler attachment phải hoàn chỉnh như sau:

```python
    async def _attachment(self, request):
        from aiohttp import web
        item = self.store.get_attachment(
            int(request.match_info["attachment_id"]), requester_id="web-admin",
            is_admin=True, allowed_groups=set(),
        )
        if not item or not item.get("local_path"):
            return self._error(404, "attachment_not_found", "Không tìm thấy file")
        target = Path(item["local_path"]).resolve()
        root = self.store.media_root.resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return self._error(404, "attachment_not_found", "Không tìm thấy file")
        if not target.is_file():
            return self._error(404, "attachment_not_found", "Không tìm thấy file")
        self._audit("attachment_download", target_id=item["id"])
        return web.FileResponse(target)
```

- [ ] **Bước 5: Cài export/delete/search với confirm rõ ràng**

```python
    @staticmethod
    def _history_filters(data: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: data[key] for key in ("thread_type", "thread_id", "since", "until")
            if data.get(key) is not None
        }

    async def _history_search(self, request):
        from aiohttp import web
        result = self.store.search_messages(
            request.query.get("query", ""), requester_id="web-admin", is_admin=True,
            allowed_groups=set(), thread_type=request.query.get("thread_type"),
            thread_id=request.query.get("thread_id"),
            limit=int(request.query.get("limit", 50)),
        )
        return web.json_response(redact_value({"items": result}))

    async def _history_export(self, request):
        from aiohttp import web
        try:
            result = self.admin.web_history_export(
                requester=WEB_ADMIN_REQUESTER, **self._history_filters(await request.json())
            )
            path = Path(result["path"]).resolve()
            root = self.export_root.resolve()
            path.relative_to(root)
            self._audit("history_export", count=int(result.get("messages", 0)))
            return web.FileResponse(path)
        except (CompanyConfigError, ValueError) as exc:
            message = redact_text(str(exc)) or "Không thể xuất lịch sử"
            self._audit("history_export", status="failed", error_text=message)
            return self._error(400, "history_export_failed", message)

    async def _history_delete(self, request):
        body = await request.json()
        if body.get("confirm") is not True:
            return self._error(400, "confirmation_required", "Cần xác nhận thao tác xóa")
        try:
            result = self.admin.history_delete(
                requester=WEB_ADMIN_REQUESTER, **self._history_filters(body)
            )
        except (CompanyConfigError, ValueError) as exc:
            message = redact_text(str(exc)) or "Không thể xóa lịch sử"
            self._audit("history_delete", status="failed", error_text=message)
            return self._error(400, "history_delete_failed", message)
        self._audit("history_delete", count=int(result.get("messages", 0)))
        from aiohttp import web
        return web.json_response(redact_value(result))
```

- [ ] **Bước 6: Hoàn thiện render Hội thoại**

Thêm code JS sau, giữ dữ liệu hiển thị qua `textContent`:

```javascript
async function renderHistory(){
  const app=clearApp("Hội thoại");
  const list=await api("/admin/api/conversations?limit=50&offset=0");
  for(const conversation of list.items){
    const card=document.createElement("div");card.className="card";
    const open=document.createElement("button");open.textContent=`${conversation.title??conversation.thread_id} (${conversation.thread_id})`;
    open.onclick=async()=>{const page=await api(`/admin/api/conversations/${conversation.id}?limit=100&offset=0`);card.replaceChildren(open);for(const message of page.items){const p=document.createElement("p");p.textContent=`${message.sender_name??message.sender_id}: ${message.text}`;card.append(p);}};
    card.append(open);app.append(card);
  }
  const exportButton=document.createElement("button");exportButton.textContent="Xuất lịch sử";exportButton.onclick=async()=>{const response=await fetch("/admin/api/history/export",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:"{}"});if(!response.ok){throw new Error("Không thể xuất lịch sử");}const blob=await response.blob();const link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download="history.jsonl";link.click();URL.revokeObjectURL(link.href);};
  const deleteButton=document.createElement("button");deleteButton.textContent="Xóa phạm vi thử nghiệm";deleteButton.onclick=async()=>{if(window.confirm("Xóa lịch sử đã chọn?")){await api("/admin/api/history/delete",{method:"POST",body:JSON.stringify({confirm:true})});await renderHistory();}};
  app.append(exportButton,deleteButton);
}
```

Đổi `renderCurrent()` dispatch để gọi `renderHistory()` khi `state.view` là
`history`. Timeout/`unknown` chỉ được hiển thị, không gọi lại.

- [ ] **Bước 7: Chạy GREEN và history regression**

```powershell
python -m pytest tests/python/test_history_store.py tests/python/test_tooling.py::test_admin_web_history_export_delete_and_attachment_scope -q -p no:cacheprovider
```

Kỳ vọng: PASS; media ngoài root không được phục vụ/xóa, migration không đổi.

- [ ] **Bước 8: Commit**

```powershell
git add -- hermes-plugin/admin.py hermes-plugin/history_store.py tests/python/test_tooling.py tests/python/test_history_store.py
git diff --cached --check
git commit -m "feat: browse and manage Zalo history"
```

---

### Task 8: Hệ thống, activity, QR và restart accepted-once

**Files:**

- Modify: `hermes-plugin/admin.py`
- Modify: `hermes-plugin/adapter.py:74-81,325-387`
- Test: `tests/python/test_tooling.py`
- Test: `tests/python/test_adapter.py`

- [ ] **Bước 1: Viết test RED cho system/activity/restart**

```python
@pytest.mark.asyncio
async def test_admin_web_system_activity_restart_is_accepted_once(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    calls: list[tuple[str, str]] = []

    async def restart(args=None):
        calls.append(("restart", str((args or {}).get("target") or "")))
        return {"success": True}

    admin = AdminService(
        store=store,
        status_provider=lambda: {"success": True, "connected": True,
                                 "provider": "unknown", "model": "unknown"},
        lifecycle={"restart": restart, "login_qr": lambda _args=None: {"success": True}},
        log_provider=lambda lines: {"success": True, "lines": [f"last-{lines}"]},
    )
    client, cookie, csrf = await authenticated_web_client(
        tmp_path, admin=admin, store=store, bridge=FakeBridge()
    )
    try:
        bad = await client.post(
            "/admin/api/system/restart",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={"target": "database"},
        )
        assert bad.status == 400
        accepted = await client.post(
            "/admin/api/system/restart",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={"target": "bridge"},
        )
        assert accepted.status == 202
        await asyncio.sleep(0.3)
        assert calls == [("restart", "bridge")]
        activity = await client.get("/admin/api/activity", headers={"Cookie": cookie})
        assert any(
            item["tool_name"] == "admin_web.restart"
            for item in (await activity.json())["items"]
        )
    finally:
        await client.close()
```

- [ ] **Bước 2: Chạy RED**

```powershell
python -m pytest tests/python/test_tooling.py::test_admin_web_system_activity_restart_is_accepted_once -q -p no:cacheprovider
```

Kỳ vọng: FAIL vì route chưa có.

- [ ] **Bước 3: Thêm BridgePort bytes và QR provider**

Mở rộng `_AdapterBridge`:

```python
    async def request_bytes(self, path: str, params=None) -> tuple[bytes, str]:
        return await self.adapter._get_bytes(path, params=params)
```

Thêm `_get_bytes()` trong adapter: dùng shared `ClientSession`, bridge auth
headers, timeout 10 giây, chỉ chấp nhận status `200`, đọc tối đa 2 MiB và trả
`(bytes, content_type)`. Nếu lớn hơn cap hoặc content type không phải
`image/png`, raise lỗi an toàn.

Mở rộng `AdminWebApp.__init__` nhận bridge object có `request()` và
`request_bytes()`. Cài `_get_bytes()` trong adapter bằng code đầy đủ:

```python
    async def _get_bytes(self, path: str, params: Optional[Dict[str, Any]] = None) -> tuple[bytes, str]:
        import aiohttp
        if not self._session or self._session.closed:
            raise RuntimeError("bridge session is not connected")
        try:
            async with self._session.get(
                f"{self.bridge_url}{path}", params=params or {},
                headers=self._headers(), timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"bridge bytes request failed with HTTP {response.status}")
                content_type = str(response.headers.get("Content-Type") or "")
                if not content_type.lower().startswith("image/png"):
                    raise RuntimeError("bridge returned a non-PNG QR response")
                length = int(response.headers.get("Content-Length") or 0)
                if length > 2 * 1024 * 1024:
                    raise RuntimeError("QR response exceeds the 2 MiB cap")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > 2 * 1024 * 1024:
                        raise RuntimeError("QR response exceeds the 2 MiB cap")
                    chunks.append(chunk)
                return b"".join(chunks), content_type
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise RuntimeError(redact_text(str(exc)) or "bridge bytes request failed") from exc
```

- [ ] **Bước 4: Đăng ký system/activity route**

```python
app.router.add_get("/admin/api/activity", self._activity)
app.router.add_get("/admin/api/system", self._system)
app.router.add_post("/admin/api/system/qr", self._qr)
app.router.add_get("/admin/api/system/qr.png", self._qr_png)
app.router.add_post("/admin/api/system/reconnect", self._reconnect)
app.router.add_post("/admin/api/system/restart", self._restart)
app.router.add_get("/admin/api/system/logs", self._logs)
```

Thêm handlers cụ thể:

```python
    async def _activity(self, request):
        from aiohttp import web
        result = self.store.page_tool_activity(
            requester_id=request.query.get("requester_id"),
            tool_name=request.query.get("tool_name"), status=request.query.get("status"),
            thread_type=request.query.get("thread_type"), thread_id=request.query.get("thread_id"),
            since=request.query.get("since"), until=request.query.get("until"),
            limit=int(request.query.get("limit", 100)), offset=int(request.query.get("offset", 0)),
        )
        return web.json_response(redact_value(result))

    async def _system(self, _request):
        from aiohttp import web
        status = await self.admin.action("status", requester=WEB_ADMIN_REQUESTER)
        health = await self._bridge_json("GET", "/health")
        policy = await self._bridge_json("GET", "/policy")
        qr = await self._bridge_json("GET", "/qr")
        return web.json_response(redact_value({
            **(status if isinstance(status, Mapping) else {"status": status}),
            "bridge": health, "policy": policy, "qr": qr,
            "provider": (status or {}).get("provider", "unknown") if isinstance(status, Mapping) else "unknown",
            "model": (status or {}).get("model", "unknown") if isinstance(status, Mapping) else "unknown",
        }))

    async def _qr(self, _request):
        from aiohttp import web
        result = await self.admin.action("login_qr", requester=WEB_ADMIN_REQUESTER)
        self._audit("qr", status="success" if not (isinstance(result, Mapping) and result.get("error")) else "failed")
        return web.json_response(redact_value(result))

    async def _qr_png(self, _request):
        from aiohttp import web
        try:
            payload, content_type = await self.bridge.request_bytes("/qr.png")
        except Exception as exc:
            message = redact_text(str(exc)) or "QR chưa sẵn sàng"
            return self._error(404, "qr_unavailable", message, retryable=True)
        self._audit("qr_image")
        return web.Response(body=payload, content_type=content_type.split(";", 1)[0])

    async def _reconnect(self, _request):
        from aiohttp import web
        result = await self.admin.action("reconnect", requester=WEB_ADMIN_REQUESTER)
        self._audit("reconnect", status="success" if not (isinstance(result, Mapping) and result.get("error")) else "failed")
        return web.json_response(redact_value(result))

    async def _logs(self, request):
        from aiohttp import web
        lines = max(1, min(int(request.query.get("lines", 100)), 500))
        result = await self.admin.action("show_logs", requester=WEB_ADMIN_REQUESTER, lines=lines)
        self._audit("show_logs", count=lines)
        return web.json_response(redact_value(result))
```

- [ ] **Bước 5: Cài restart trả 202 trước side effect**

```python
    async def _restart(self, request):
        from aiohttp import web
        body = await request.json()
        target = str(body.get("target") or "")
        if target not in {"gateway", "bridge"}:
            return self._error(400, "invalid_target", "Target phải là gateway hoặc bridge")
        self._audit("restart", status="unknown", target_id=target)
        loop = asyncio.get_running_loop()
        loop.call_later(
            0.2,
            lambda: asyncio.create_task(
                self.admin.action("restart", requester=WEB_ADMIN_REQUESTER, target=target)
            ),
        )
        return web.json_response({"accepted": True, "target": target}, status=202)
```

`_qr` gọi `login_qr` đúng một lần. `_qr_png` gọi
`bridge.request_bytes("/qr.png")` và trả PNG. `_reconnect` gọi lifecycle callback
khác `login_qr` với `forceQR:false`. `_logs` giới hạn 1–500 dòng, redact rồi audit
`show_logs`.

- [ ] **Bước 6: Mở rộng adapter service target**

Đổi `_admin_service_action(action, args=None)`, lấy `target` từ mapping và map:

```python
units = {
    "bridge": os.getenv("ZALO_BRIDGE_SYSTEMD_UNIT", "hermes-zalo-company-bridge.service"),
    "gateway": os.getenv("HERMES_GATEWAY_SYSTEMD_UNIT", "hermes-gateway.service"),
}
target = str((args or {}).get("target") or "bridge")
if target not in units:
    return {"success": False, "error": "invalid service target", "target": target}
unit = units[target]
```

Giữ `create_subprocess_exec` không qua shell. Windows/dev trả lỗi đã redact,
không stack trace.

- [ ] **Bước 7: Hoàn thiện render System & Activity**

Thêm render code:

```javascript
async function renderSystem(){
  const app=clearApp("Hệ thống & Hoạt động");
  const data=await api("/admin/api/system");
  app.append(line("Bridge",data.bridge?.loggedIn?"Đã đăng nhập":"Chưa đăng nhập"),line("Provider",data.provider),line("Model",data.model),line("QR",data.qr?.status));
  const qr=document.createElement("img");qr.alt="QR đăng nhập Zalo";qr.src="/admin/api/system/qr.png";qr.width=220;app.append(qr);
  const reconnect=document.createElement("button");reconnect.textContent="Reconnect Zalo";reconnect.onclick=()=>api("/admin/api/system/reconnect",{method:"POST",body:"{}"});app.append(reconnect);
  for(const target of ["bridge","gateway"]){const button=document.createElement("button");button.textContent=`Restart ${target}`;button.onclick=async()=>{if(window.confirm(`Restart ${target}?`)){await api("/admin/api/system/restart",{method:"POST",body:JSON.stringify({target})});await pollAfterRestart();}};app.append(button);}
  const activity=await api("/admin/api/activity?limit=50&offset=0");for(const item of activity.items){const p=document.createElement("p");p.textContent=`${item.occurred_at} ${item.tool_name} ${item.status}`;app.append(p);}
}
async function pollAfterRestart(){for(const delay of [1000,2000,4000,8000,15000]){await new Promise(resolve=>setTimeout(resolve,delay));try{await api("/admin/api/session");await renderSystem();return;}catch(error){if(error.status!==401)throw error;}}const p=document.createElement("p");p.textContent="Gateway chưa trở lại. Dùng systemctl restart hermes-gateway.";document.querySelector("#app").append(p);}
```

Đổi `renderCurrent()` dispatch `system` sang `renderSystem()`; không lặp POST
restart khi poll thất bại.

- [ ] **Bước 8: Chạy GREEN và timeout regression**

```powershell
python -m pytest tests/python/test_tooling.py::test_admin_web_system_activity_restart_is_accepted_once tests/python/test_adapter.py::test_transport_error_is_ambiguous_and_never_marked_safe_to_retry -q -p no:cacheprovider
```

Kỳ vọng: PASS, mutation không retry.

- [ ] **Bước 9: Commit**

```powershell
git add -- hermes-plugin/admin.py hermes-plugin/adapter.py tests/python/test_tooling.py tests/python/test_adapter.py
git diff --cached --check
git commit -m "feat: add admin system operations"
```

---

### Task 9: Gắn Web UI vào vòng đời adapter và giữ QR recovery

**Files:**

- Modify: `hermes-plugin/adapter.py:213-315,403-498,633-677`
- Modify: `hermes-plugin/plugin.yaml:22-74`
- Test: `tests/python/test_adapter.py`

- [ ] **Bước 1: Viết test RED cho lifecycle fail-soft**

```python
@pytest.mark.asyncio
async def test_admin_web_lifecycle_is_fail_soft_and_idempotent(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    class FakeAdminWeb:
        is_running = False

        async def start(self):
            calls.append("start")
            self.is_running = True
            return True

        async def stop(self):
            calls.append("stop")
            self.is_running = False

    adapter = _adapter(tmp_path)
    fake = FakeAdminWeb()
    adapter.admin_web = fake
    adapter._mark_connected()
    await adapter._start_admin_web()
    await adapter._start_admin_web()
    assert calls == ["start"]
    await adapter.disconnect()
    assert calls == ["start", "stop"]
```

Thêm test thứ hai: `AdminWebApp.start()` raise `OSError("port busy")` nhưng adapter
vẫn giữ trạng thái connected/chat; log không chứa session secret.

- [ ] **Bước 2: Viết test RED cho session_dead QR recovery**

```python
@pytest.mark.asyncio
async def test_session_dead_keeps_running_admin_web_for_qr_recovery(tmp_path) -> None:
    adapter = _adapter(tmp_path)
    notified: list[str] = []
    adapter._notify_fatal_error = lambda: notified.append("fatal")
    adapter.admin_web = SimpleNamespace(is_running=True)
    await adapter._on_session_dead({"reason": "expired"})
    assert notified == []
    assert adapter.get_last_error() is not None
```

Tên getter fatal phải dùng đúng API `BasePlatformAdapter` hiện có; nếu không có
public getter, assert field mà test adapter hiện dùng.

- [ ] **Bước 3: Chạy RED**

```powershell
python -m pytest tests/python/test_adapter.py::test_admin_web_lifecycle_is_fail_soft_and_idempotent tests/python/test_adapter.py::test_session_dead_keeps_running_admin_web_for_qr_recovery -q -p no:cacheprovider
```

Kỳ vọng: FAIL vì adapter chưa sở hữu Web UI.

- [ ] **Bước 4: Khởi tạo một bridge/admin/web instance dùng chung**

Trong `__init__`:

- Lưu `self.admin_service` thay vì biến local.
- Tạo một `_AdapterBridge(self)` và dùng cho cả `ZaloTooling`/`AdminWebApp`.
- Truyền `runtime_config_provider=lambda: self.company_config` và
  `runtime_config_applier=self._apply_company_config` vào `AdminService`.
- `export_root` là `HERMES_HOME/zalo-company/exports`.
- Parse `AdminWebSettings.from_env()`; invalid settings chỉ log đã redact và tạo
  settings disabled.
- Cho phép inject `admin_web_app` qua kwargs để test.

Khởi tạo production:

```python
self.admin_web = kwargs.pop("admin_web_app", None) or AdminWebApp(
    settings=admin_web_settings,
    admin=self.admin_service,
    store=self.history_store,
    bridge=bridge,
    export_root=hermes_home / "zalo-company" / "exports",
)
```

- [ ] **Bước 5: Cài lifecycle idempotent**

Sau `_mark_connected()` của successful `connect()`, gọi `_start_admin_web()` và
bắt/redact mọi lỗi, không đổi kết quả connect. `disconnect()` gọi
`_stop_admin_web()` trước khi đóng shared `ClientSession`. `AdminWebApp` có
property:

```python
@property
def is_running(self) -> bool:
    return self._runner is not None
```

SSE bridge mất sau khi connect không gọi `disconnect()`, nên UI vẫn mở. Nếu
`session_dead` và `admin_web.is_running`, chỉ set fatal/status để UI tạo QR,
không gọi Hermes fatal handler tháo adapter. Khi nhận SSE status connected sau
relogin, gọi `_mark_connected()` lại. Nếu UI không chạy, giữ hành vi fatal/retry
cũ của Hermes 0.19.

- [ ] **Bước 6: Khai báo optional env**

Thêm sáu biến từ spec vào `optional_env`; `PASSWORD_HASH` và `SESSION_SECRET`
có `password: true`. Không thêm chúng vào `requires_env` của platform vì Hermes
0.19 bỏ qua `optional_env` nhưng dùng `requires_env` để quyết định enable plugin.

- [ ] **Bước 7: Chạy adapter/plugin contract**

```powershell
python -m pytest tests/python/test_adapter.py tests/integration/test_company_assistant_flow.py::test_plugin_loads_with_hermes_directory_package_semantics -q -p no:cacheprovider
```

Kỳ vọng: PASS; vẫn đúng ba tool, ba hook, hai required env.

- [ ] **Bước 8: Commit**

```powershell
git add -- hermes-plugin/adapter.py hermes-plugin/plugin.yaml tests/python/test_adapter.py
git diff --cached --check
git commit -m "feat: run admin web with Zalo adapter"
```

---

### Task 10: Integration fake bridge và tài liệu vận hành

**Files:**

- Modify: `tests/integration/fake_bridge.py`
- Modify: `tests/integration/test_company_assistant_flow.py`
- Modify: `docs/operations/configuration.md`
- Modify: `docs/operations/acceptance-checklist.md`
- Modify: `README.vi.md`

- [ ] **Bước 1: Mở rộng fake bridge mà vẫn giữ contract cũ**

Trong `FakeCompanyBridge.__init__` thêm:

```python
self.profile = {"id": "bot-id", "name": "Trợ lý công ty"}
self.friends = [
    {"id": "u-1", "name": "Lan"},
    {"id": "admin", "name": "Việt Anh"},
]
self.groups = [{"id": "g-1", "name": "Group AI", "memberCount": 2}]
self.members = {"g-1": self.friends}
self.logged_in = True
self.available = True
self.qr_png = b"\x89PNG\r\n\x1a\n" + b"fake-qr"
```

Đầu `request()`:

```python
if not self.available:
    return {"error": "bridge unavailable", "outcome": "failed"}
if path == "/health":
    return {"ok": True, "loggedIn": self.logged_in, "ownId": self.profile["id"], "qr": "authenticated"}
if path == "/policy":
    return {"mode": "all_operational_methods", "allowedActionCount": len(self.methods)}
if path == "/friends":
    return {"success": True, "items": self.friends}
if path == "/groups":
    return {"success": True, "items": self.groups}
if path == "/chat-info":
    thread_id = str((params or {}).get("threadId") or "")
    if str((params or {}).get("threadType")) == "group":
        return {"success": True, "result": {"id": thread_id, "members": self.members.get(thread_id, [])}}
    return {"success": True, "result": self.profile}
if path == "/qr":
    return {"status": "pending" if not self.logged_in else "authenticated"}
if path == "/relogin":
    self.logged_in = False
    return {"success": True, "status": "pending"}
```

Thêm:

```python
async def request_bytes(self, path: str, params=None) -> tuple[bytes, str]:
    self.calls.append({"http_method": "GET", "path": path, "payload": {}, "params": dict(params or {})})
    if not self.available or path != "/qr.png":
        raise RuntimeError("QR image unavailable")
    return self.qr_png, "image/png"
```

- [ ] **Bước 2: Viết integration RED cho luồng chính**

Thêm helper Web client độc lập trong integration file và test:

```python
@pytest.mark.asyncio
async def test_admin_web_login_overview_apply_history_and_bridge_down(tmp_path: Path) -> None:
    bridge = FakeCompanyBridge()
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.store_message(
        thread_type="group", thread_id="g-1", sender_id="u-1",
        text="mai họp 9 giờ", provider_message_id="seed-1",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {"gateway": {"platforms": {"zalo": {"extra": company_config().to_mapping()}}}},
            sort_keys=False,
        ), encoding="utf-8",
    )
    runtime = [company_config()]
    admin = AdminService(
        config_file=CompanyConfigFile(config_path), store=store,
        status_provider=lambda: {"success": True, "connected": bridge.available,
                                 "bot": bridge.profile, "provider": "unknown", "model": "unknown"},
        runtime_config_provider=lambda: runtime[-1],
        runtime_config_applier=runtime.append,
        export_root=tmp_path / "exports",
    )
    client, cookie, csrf = await integration_web_client(
        tmp_path, admin=admin, store=store, bridge=bridge
    )
    try:
        overview = await client.get("/admin/api/overview", headers={"Cookie": cookie})
        assert (await overview.json())["bot"]["id"] == "bot-id"
        friends = await client.get("/admin/api/friends", headers={"Cookie": cookie})
        assert (await friends.json())["items"][0]["id"] == "u-1"
        access = await (await client.get("/admin/api/access", headers={"Cookie": cookie})).json()
        applied = await client.post(
            "/admin/api/access/apply",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={**access, "allowed_groups": ["g-1"]},
        )
        assert applied.status == 200
        conversations = await (await client.get(
            "/admin/api/conversations", headers={"Cookie": cookie}
        )).json()
        assert conversations["items"][0]["thread_id"] == "g-1"

        bridge.available = False
        system = await client.get("/admin/api/system", headers={"Cookie": cookie})
        assert system.status == 200
        assert (await system.json())["bridge"]["error"] == "bridge unavailable"
    finally:
        await client.close()
```

- [ ] **Bước 3: Viết test manifest Hermes 0.19-safe**

```python
def test_plugin_manifest_keeps_admin_web_env_optional_for_hermes_019() -> None:
    manifest = yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8"))
    required = {item["name"] for item in manifest["requires_env"]}
    optional = {item["name"] for item in manifest["optional_env"]}
    admin_names = {
        "ZALO_ADMIN_WEB_ENABLED", "ZALO_ADMIN_WEB_HOST", "ZALO_ADMIN_WEB_PORT",
        "ZALO_ADMIN_WEB_PASSWORD_HASH", "ZALO_ADMIN_WEB_SESSION_SECRET",
        "ZALO_ADMIN_WEB_SESSION_TTL_SECONDS",
    }
    assert admin_names <= optional
    assert admin_names.isdisjoint(required)
```

- [ ] **Bước 4: Chạy integration GREEN**

```powershell
python -m pytest tests/integration/test_company_assistant_flow.py::test_admin_web_login_overview_apply_history_and_bridge_down tests/integration/test_company_assistant_flow.py::test_plugin_manifest_keeps_admin_web_env_optional_for_hermes_019 -q -p no:cacheprovider
```

Kỳ vọng: PASS; bridge down không làm UI route mất.

- [ ] **Bước 5: Cập nhật configuration.md bằng lệnh tạo hash an toàn**

Thêm biến env, loopback `127.0.0.1:8790`, reverse proxy HTTPS, session 24 giờ,
fallback CLI/SSH và lệnh PowerShell:

```powershell
$secure = Read-Host "Mật khẩu Admin Web" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
$env:ADMIN_WEB_PASSWORD = $plain
$pluginPath = Join-Path $env:LOCALAPPDATA "hermes\plugins\zalo"
python -c "import os,sys; sys.path.insert(0,sys.argv[1]); from admin import hash_admin_password; print(hash_admin_password(os.environ['ADMIN_WEB_PASSWORD']))" $pluginPath
Remove-Item Env:ADMIN_WEB_PASSWORD
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
Remove-Variable plain -ErrorAction SilentlyContinue
```

Nêu rõ: Web UI không sửa provider secret, UI chết cùng Gateway, cold-start khi
Gateway chết cần `systemctl restart hermes-gateway`.

- [ ] **Bước 6: Cập nhật README.vi.md và acceptance checklist**

Checklist phải có đúng các mục: login, bot info, friend/group/member IDs, access
apply, group store/mention, history search/export/delete, QR/reconnect,
activity/log/restart và secret scan. Không sửa `README.md` hoặc systemd env
template vì hai file đó không nằm trong danh sách triển khai của spec này.

- [ ] **Bước 7: Chạy integration/docs checks**

```powershell
python -m pytest tests/integration -q -p no:cacheprovider
git diff --check
rg -n "ZALO_ADMIN_WEB_PASSWORD_HASH|ZALO_ADMIN_WEB_SESSION_SECRET|127.0.0.1:8790" docs/operations/configuration.md README.vi.md hermes-plugin/plugin.yaml
```

Kỳ vọng: PASS; chỉ có tên biến/giá trị ví dụ, không có secret thật.

- [ ] **Bước 8: Commit**

```powershell
git add -- tests/integration/fake_bridge.py tests/integration/test_company_assistant_flow.py docs/operations/configuration.md docs/operations/acceptance-checklist.md README.vi.md
git diff --cached --check
git commit -m "docs: add admin web operations and acceptance"
```

---

### Task 11: Full verification và nghiệm thu Group AI

**Files:** Không tạo file. Nếu phát hiện lỗi, quay lại task sở hữu file, sửa bằng
một vòng RED/GREEN và commit tại task đó.

- [ ] **Bước 1: Kiểm tra manifest và whitespace**

```powershell
git diff --check
git status --short
git diff --name-only HEAD~8..HEAD
```

Kỳ vọng: mọi path thuộc manifest; không có file runtime/test mới; migration không
đổi. So với snapshot Task 0 để bảo toàn thay đổi có sẵn của người dùng.

- [ ] **Bước 2: Chạy Node suite**

```powershell
npm test
```

Kỳ vọng: exit `0`, 27 test hiện tại và mọi test mới đều PASS.

- [ ] **Bước 3: Chạy toàn bộ Python**

```powershell
python -m pytest -q -p no:cacheprovider
```

Kỳ vọng: exit `0`, không skip test quan trọng của Admin Web UI.

- [ ] **Bước 4: Chạy acceptance tự động**

```powershell
python scripts/acceptance.py --json
```

Kỳ vọng: exit `0`. Nếu runner hiện không nhận `--json`, chạy
`python scripts/acceptance.py` và cập nhật tài liệu theo output thật; không sửa
runner ngoài phạm vi.

- [ ] **Bước 5: Quét secret có chủ đích**

```powershell
rg -n -i "authorization: bearer|x-bridge-token|api[_-]?key|password|session_secret|set-cookie" hermes-plugin tests docs README.vi.md
```

Đọc từng match. Chỉ tên field, fake secret trong test và `[REDACTED]` được phép;
không có credential thật trong diff, HTML, fixture response hoặc audit.

- [ ] **Bước 6: Nghiệm thu thật với Group AI**

1. Mở UI qua HTTPS và đăng nhập.
2. Xác nhận tên/ID bot, bạn bè, `Group AI`, thành viên và ID.
3. Thêm rồi bỏ một test user/group bằng **Lưu và áp dụng**.
4. Xác nhận bridge không restart và Zalo vẫn connected.
5. Gửi tin không mention: tin được lưu, bot không trả lời.
6. Allowed user mention: Hermes trả lời và history có cả hai tin.
7. Tìm kiếm, export và xóa một phạm vi thử nghiệm.
8. Mở QR/reconnect, xem activity/log và restart bridge.
9. Restart Gateway từ UI; xác nhận UI mất rồi trở lại, không có POST lặp.

- [ ] **Bước 7: Chạy lại verification sau mọi sửa nghiệm thu**

```powershell
git diff --check
npm test
python -m pytest -q -p no:cacheprovider
python scripts/acceptance.py
```

Kỳ vọng: tất cả exit `0` trước khi báo hoàn thành.

- [ ] **Bước 8: Xác nhận không có staging sót**

```powershell
git diff --cached --name-only
git status --short
```

Kỳ vọng: không có file staged. Các dirty path có từ Task 0 vẫn được báo riêng,
không tuyên bố worktree sạch nếu chúng còn tồn tại.
### Runtime incident handled

- Hermes core raised `TypeError: unhashable type: 'slice'` because zca-js can
  return object-valued `quote.content` while `MessageEvent.reply_to_text` must
  be text.
- Added `_quote_text()` at the adapter boundary and a quote-object regression
  test; Hermes core and group-session behavior remain unchanged.
- Verified after fix: Node `41/41`, Python `174/174`, integration `15/15`,
  static acceptance `ok: true`, and `git diff --check` exit `0`.
- Backed up the runtime adapter, synchronized the fixed file, and restarted
  Hermes Gateway successfully; no new `TypeError`/`unhashable` log appeared.

### Checkpoint đóng gói VPS từ rollback-friend-workflow (2026-08-13)

- Đã xác định Git tree đầy đủ
  `2ecc50b5be2657aaaeefbe11c0bab2b07c710650` chứa đúng hai blob của snapshot
  `rollback-friend-workflow-20260812-234605`. Repo và runtime đã được khôi phục
  từ tree này; `adapter.py` và `history_store.py` khớp byte-for-byte với snapshot.
- Backup đầy đủ trước khôi phục nằm tại
  `HERMES_HOME/zalo-company/runtime-backups/before-restore-tree-2ecc50b5-20260813-093610`
  với 115 file repo và 25 file runtime. Không thay đổi database, cấu hình,
  allowlist, cookie hoặc credential.
- Artifact VPS:
  `E:/plugin-release/hermes-zalo-company-rollback-20260812-234605.tgz`, SHA-256
  `7905400c2b64dcbf43386dbf9af2e6a25a7afb4b23ae03d69dacd9ac8c3a8cb2`.
  Tarball có 34 entry theo whitelist, không chứa `.env`, credential, database,
  session, media, log, test, tài liệu nội bộ hoặc `node_modules`; quét secret sạch.
- Kiểm thử trên bản dựng tạm và sau triển khai: Node `41/41`, toàn bộ Python
  `192/192`, integration `15/15`, static acceptance `ok: true` và
  `git diff --check` exit `0`. Migration giữ SHA-256 bất biến
  `1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a`.
- Đã cài thử tarball bằng `npm install --ignore-scripts` trong prefix sạch;
  dependency `zca-js` là `2.1.2` và hai file rollback sau cài vẫn khớp snapshot.
  Gateway máy hiện tại chạy PID `2000`; plugin Zalo kết nối bridge thành công lúc
  `2026-08-13 09:36:48`.
- Cài VPS: chép tarball lên VPS, dùng Node >=22 chạy
  `npm install -g ./hermes-zalo-company-rollback-20260812-234605.tgz`, sau đó
  `hermes-zalo-plugin setup`, `hermes gateway restart` và
  `hermes gateway status`. Không chép state/credential từ máy phát triển vào gói.
