# Kế hoạch triển khai đồng bộ allowlist Admin Web vào `.env`

> **Cho agent thực thi:** BẮT BUỘC dùng `superpowers:subagent-driven-development` (khuyên dùng) hoặc `superpowers:executing-plans` để triển khai từng task. Các bước dùng checkbox (`- [ ]`) để theo dõi.

**Mục tiêu:** Khi admin bấm **Lưu và áp dụng**, ba tập ID access được ghi đồng nhất vào `config.yaml`, `.env` và runtime, rồi vẫn giữ nguyên sau gateway restart.

**Kiến trúc:** Mở rộng `CompanyConfigFile` thành ranh giới persistence duy nhất cho access config. YAML vẫn là dữ liệu Admin Web hiển thị; ba biến `.env` là bản sao dùng lúc startup. Mỗi apply giữ snapshot hai file, ghi có giới hạn và rollback cả hai nếu ghi hoặc runtime apply thất bại.

**Công nghệ:** Python 3.11+, PyYAML, filesystem atomic replace, pytest/pytest-asyncio, aiohttp Admin Web integration, systemd user services trên VPS.

---

## Checkpoint phiên làm việc

- Spec chuẩn đã duyệt: `docs/superpowers/specs/2026-08-18-admin-web-env-sync-design.md`, commit `e339356` trên branch `company-assistant-v1`.
- Root cause đã tái hiện trên VPS: YAML chứa admin, Tiny và Tí Nị; `.env` chỉ chứa admin trong `ZALO_ALLOWED_USERS`; `CompanyConfig.from_platform_extra(..., env=env_file)` loại Tiny khi startup.
- Kiến trúc bất biến: không đổi API Admin Web, schema SQLite, migration, hai process Node/Python, trusted-team policy hay mention gate.
- File được phép sửa: `hermes-plugin/company_config.py`, `tests/python/test_company_config.py`, `tests/python/test_tooling.py`, `tests/integration/test_company_assistant_flow.py`, `docs/operations/configuration.md`, `docs/operations/acceptance-checklist.md`, manifest và kế hoạch này.
- Baseline trước code: HEAD `e339356`; trước khi triển khai phải xác nhận working tree sạch và static acceptance `ok: true`.
- Việc tiếp theo: Task 1, viết regression test startup override và xem test đỏ trước khi sửa production code.

## Bản đồ file

| File | Hành động | Trách nhiệm |
|---|---|---|
| `hermes-plugin/company_config.py` | Sửa | Đồng bộ ba biến access vào `.env`, atomic write và rollback hai file |
| `tests/python/test_company_config.py` | Sửa | Regression startup, bảo toàn secret/comment, mode và lỗi ghi file |
| `tests/python/test_tooling.py` | Sửa | Rollback YAML + `.env` khi runtime apply lỗi |
| `tests/integration/test_company_assistant_flow.py` | Sửa | Admin Web apply chỉ thành công sau khi YAML/env/runtime đồng nhất |
| `docs/operations/configuration.md` | Sửa | Ghi nguồn cấu hình và hành vi Web sync |
| `docs/operations/acceptance-checklist.md` | Sửa | Thêm kiểm tra restart giữ allowlist |
| `docs/architecture/file-manifest.md` | Sửa | Đăng ký spec/kế hoạch và phạm vi file |
| `docs/superpowers/plans/2026-08-18-admin-web-env-sync.md` | Tạo/sửa | Checkpoint, bằng chứng test và deploy |

---

### Task 1: Regression startup override và render `.env` có giới hạn

**Files:**
- Modify: `tests/python/test_company_config.py`
- Modify: `hermes-plugin/company_config.py`

- [ ] **Bước 1: Viết helper test đọc `.env` và regression đỏ**

Thêm vào `tests/python/test_company_config.py`:

```python
def _dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def test_access_apply_syncs_env_and_survives_startup_override(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_file = _config_file(config_path)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENAI_API_KEY=keep-secret\n"
        "ZALO_ALLOWED_USERS=u-1\n"
        "ZALO_ADMIN_USERS=u-1\n"
        "ZALO_ALLOWED_GROUPS=g-1\n",
        encoding="utf-8",
    )
    config_file = CompanyConfigFile(config_path, env_path=env_path)
    before = config_file.read_access_config()

    applied = config_file.apply_access_config(
        allowed_users=["u-1", "tiny"],
        admin_users=["u-1"],
        allowed_groups=["g-1"],
        expected_fingerprint=before.fingerprint,
    )

    startup = CompanyConfig.from_platform_extra(
        applied.config.to_mapping(),
        env=_dotenv(env_path),
    )
    assert startup.allowed_users == frozenset({"u-1", "tiny"})
    assert _dotenv(env_path)["OPENAI_API_KEY"] == "keep-secret"
```

- [ ] **Bước 2: Chạy test để xác nhận đỏ đúng nguyên nhân**

Run:

```powershell
python -m pytest -q tests/python/test_company_config.py::test_access_apply_syncs_env_and_survives_startup_override
```

Expected: FAIL vì `CompanyConfigFile.__init__` chưa nhận `env_path` hoặc `.env` chưa được đồng bộ.

- [ ] **Bước 3: Thêm mapping access env và constructor tối thiểu**

Trong `hermes-plugin/company_config.py`, thêm:

```python
ACCESS_ENV_KEYS = {
    "allowed_users": "ZALO_ALLOWED_USERS",
    "admin_users": "ZALO_ADMIN_USERS",
    "allowed_groups": "ZALO_ALLOWED_GROUPS",
}


class CompanyConfigFile:
    def __init__(self, path: str | Path, *, env_path: str | Path | None = None):
        self.path = Path(path)
        self.env_path = Path(env_path) if env_path is not None else self.path.parent / ".env"
        self._lock = threading.RLock()
```

Thêm renderer thuần, chỉ thay ba key và loại dòng trùng của chính ba key:

```python
def _render_access_env(text: str, config: CompanyConfig) -> str:
    replacements = {
        env_key: ",".join(sorted(getattr(config, field)))
        for field, env_key in ACCESS_ENV_KEYS.items()
    }
    output: list[str] = []
    written: set[str] = set()
    for line in text.splitlines(keepends=True):
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=", line)
        key = match.group(1) if match else ""
        if key not in replacements:
            output.append(line)
            continue
        if key not in written:
            newline = "\r\n" if line.endswith("\r\n") else "\n"
            output.append(f"{key}={replacements[key]}{newline}")
            written.add(key)
    if output and not output[-1].endswith(("\n", "\r")):
        output[-1] += "\n"
    for key in ACCESS_ENV_KEYS.values():
        if key not in written:
            output.append(f"{key}={replacements[key]}\n")
    return "".join(output)
```

Thêm `import re`; không log `text` hoặc `replacements`.

- [ ] **Bước 4: Thêm atomic writer `.env` và gọi sau validation**

Thêm method:

```python
def _write_access_env(self, config: CompanyConfig) -> None:
    try:
        current = self.env_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    rendered = _render_access_env(current, config)
    self.env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{self.env_path.name}.",
        suffix=".tmp",
        dir=self.env_path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, self.env_path)
        try:
            os.chmod(self.env_path, 0o600)
        except OSError:
            pass
    finally:
        Path(tmp_name).unlink(missing_ok=True)
```

Trong `apply_access_config`, sau khi candidate được validate và YAML được cập nhật, gọi `self._write_access_env(updated)` trước khi tạo và trả `AccessConfigSnapshot`.

- [ ] **Bước 5: Chạy targeted test xanh và config suite**

Run:

```powershell
python -m pytest -q tests/python/test_company_config.py::test_access_apply_syncs_env_and_survives_startup_override
python -m pytest -q tests/python/test_company_config.py
```

Expected: regression PASS; toàn bộ config suite PASS.

- [ ] **Bước 6: Commit Task 1**

```powershell
git add hermes-plugin/company_config.py tests/python/test_company_config.py
git commit -m "fix: sync web allowlist to profile env"
```

---

### Task 2: Atomic rollback và bảo toàn secret/comment/mode

**Files:**
- Modify: `tests/python/test_company_config.py`
- Modify: `hermes-plugin/company_config.py`

- [ ] **Bước 1: Viết test đỏ bảo toàn nội dung không liên quan và mode**

```python
def test_access_env_sync_preserves_secrets_comments_and_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _config_file(config_path)
    env_path = tmp_path / ".env"
    untouched = (
        "# private profile\n"
        "OPENAI_API_KEY=secret-value\n"
        "ZALO_PLUGIN_TOKEN=" + "t" * 32 + "\n"
        "CUSTOM_VALUE=keep me\n"
    )
    env_path.write_text(untouched + "ZALO_ALLOWED_USERS=old\n", encoding="utf-8")
    config_file = CompanyConfigFile(config_path, env_path=env_path)
    before = config_file.read_access_config()

    config_file.apply_access_config(
        allowed_users=["u-1", "u-2"],
        admin_users=["u-1"],
        allowed_groups=["g-1"],
        expected_fingerprint=before.fingerprint,
    )

    after = env_path.read_text(encoding="utf-8")
    assert untouched in after
    assert "ZALO_ALLOWED_USERS=u-1,u-2\n" in after
    if os.name == "posix":
        assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
```

Thêm `import stat` vào test.

- [ ] **Bước 2: Chạy test và xác nhận đỏ nếu writer chưa giữ mode/nội dung**

Run: `python -m pytest -q tests/python/test_company_config.py::test_access_env_sync_preserves_secrets_comments_and_mode`

Expected: FAIL trước khi atomic writer hoàn chỉnh; PASS sau khi Task 1 writer đáp ứng contract.

- [ ] **Bước 3: Viết test đỏ rollback YAML khi env write lỗi**

```python
def test_access_apply_restores_yaml_when_env_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    _config_file(config_path)
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=keep\n", encoding="utf-8")
    config_file = CompanyConfigFile(config_path, env_path=env_path)
    before = config_file.read_access_config()
    yaml_before = config_path.read_bytes()
    env_before = env_path.read_bytes()

    def fail(_config: CompanyConfig) -> None:
        raise OSError("env replace failed")

    monkeypatch.setattr(config_file, "_write_access_env", fail)
    with pytest.raises(OSError, match="env replace failed"):
        config_file.apply_access_config(
            allowed_users=["u-1", "tiny"],
            admin_users=["u-1"],
            allowed_groups=["g-1"],
            expected_fingerprint=before.fingerprint,
        )

    assert config_path.read_bytes() == yaml_before
    assert env_path.read_bytes() == env_before
```

- [ ] **Bước 4: Chạy test để xác nhận đỏ**

Run: `python -m pytest -q tests/python/test_company_config.py::test_access_apply_restores_yaml_when_env_write_fails`

Expected: FAIL vì YAML hiện đã đổi trước khi `_write_access_env` ném lỗi.

- [ ] **Bước 5: Implement snapshot/restore hai file tối thiểu**

Trong `apply_access_config`, giữ bytes trước thay đổi và phục hồi khi exception:

```python
yaml_before = self.path.read_bytes()
env_existed = self.env_path.exists()
env_before = self.env_path.read_bytes() if env_existed else b""
try:
    updated = self.update_atomic(
        {
            "allowed_users": sorted(_ids(allowed_users)),
            "admin_users": sorted(_ids(admin_users)),
            "allowed_groups": sorted(_ids(allowed_groups)),
        }
    )
    self._write_access_env(updated)
except Exception:
    self._replace_bytes(self.path, yaml_before)
    if env_existed:
        self._replace_bytes(self.env_path, env_before, mode=0o600)
    else:
        self.env_path.unlink(missing_ok=True)
    raise
```

Thêm helper đầy đủ; không dùng shell:

```python
@staticmethod
def _replace_bytes(path: Path, content: bytes, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
        if mode is not None:
            try:
                os.chmod(path, mode)
            except OSError:
                pass
    finally:
        Path(tmp_name).unlink(missing_ok=True)
```

Vì lock là `RLock`, `update_atomic` tiếp tục dùng được trong transaction hiện tại.

- [ ] **Bước 6: Chạy config suite xanh**

Run: `python -m pytest -q tests/python/test_company_config.py`

Expected: tất cả PASS, gồm conflict không đổi file và rollback env failure.

- [ ] **Bước 7: Commit Task 2**

```powershell
git add hermes-plugin/company_config.py tests/python/test_company_config.py
git commit -m "fix: rollback access config and env atomically"
```

---

### Task 3: Rollback runtime và Admin Web integration

**Files:**
- Modify: `tests/python/test_tooling.py`
- Modify: `tests/integration/test_company_assistant_flow.py`

- [ ] **Bước 1: Mở rộng test runtime rollback để kiểm tra `.env`**

Trong `test_admin_access_transaction_applies_once_and_rolls_back`, tạo `env_path`, truyền vào `CompanyConfigFile`, rồi thêm assertion:

```python
env_path = tmp_path / ".env"
env_path.write_text(
    "OPENAI_API_KEY=keep\n"
    "ZALO_ALLOWED_USERS=admin,u-1,u-2\n"
    "ZALO_ADMIN_USERS=admin\n"
    "ZALO_ALLOWED_GROUPS=g-1,g-2\n",
    encoding="utf-8",
)
config_file = CompanyConfigFile(path, env_path=env_path)
env_before_failure = env_path.read_bytes()

# Sau runtime_applier ném lỗi và AdminService rollback:
assert config_file.read_access_config().fingerprint == before.fingerprint
assert env_path.read_bytes() == env_before_failure
assert len(calls) == 2
```

- [ ] **Bước 2: Chạy test targeted**

Run: `python -m pytest -q tests/python/test_tooling.py::test_admin_access_transaction_applies_once_and_rolls_back`

Expected: PASS vì `rollback_access_config` gọi lại `apply_access_config`, nên YAML và `.env` cùng trở về snapshot trước lỗi.

- [ ] **Bước 3: Thêm integration test Web apply đồng nhất ba nguồn**

Trong fixture Admin Web integration, tạo `.env` cạnh `config.yaml`, sau POST `/admin/api/access/apply` assert:

```python
env_values = _dotenv(config_path.parent / ".env")
assert env_values["ZALO_ALLOWED_USERS"] == "admin,u-1,u-2"
assert env_values["ZALO_ADMIN_USERS"] == "admin"
assert env_values["ZALO_ALLOWED_GROUPS"] == "g-1,g-2"
assert runtime[-1].allowed_users == frozenset({"admin", "u-1", "u-2"})

document = yaml.safe_load(config_path.read_text(encoding="utf-8"))
extra = document["gateway"]["platforms"]["zalo"]["extra"]
reloaded = CompanyConfig.from_platform_extra(extra, env=env_values)
assert reloaded.allowed_users == runtime[-1].allowed_users
```

- [ ] **Bước 4: Chạy integration targeted rồi suite quyền**

Run:

```powershell
python -m pytest -q tests/integration/test_company_assistant_flow.py -k "access"
python -m pytest -q tests/python/test_tooling.py tests/integration/test_company_assistant_flow.py
```

Expected: Web apply, stale fingerprint, runtime rollback và env restart parity đều PASS.

- [ ] **Bước 5: Commit Task 3**

```powershell
git add tests/python/test_tooling.py tests/integration/test_company_assistant_flow.py
git commit -m "test: cover admin web env synchronization"
```

---

### Task 4: Tài liệu, full verification và checkpoint release

**Files:**
- Modify: `docs/operations/configuration.md`
- Modify: `docs/operations/acceptance-checklist.md`
- Modify: `docs/superpowers/plans/2026-08-18-admin-web-env-sync.md`

- [ ] **Bước 1: Cập nhật tài liệu vận hành**

Ghi rõ trong `docs/operations/configuration.md`:

```markdown
Admin Web là bề mặt quản lý access. Mỗi lần **Lưu và áp dụng**, plugin cập nhật
đồng thời `gateway.platforms.zalo.extra` trong `config.yaml`, ba biến
`ZALO_ALLOWED_USERS`, `ZALO_ADMIN_USERS`, `ZALO_ALLOWED_GROUPS` trong `.env` và
runtime adapter. Không sửa thủ công một trong hai nguồn vì lần apply tiếp theo
sẽ đồng bộ lại cả hai.
```

Thêm checklist:

```markdown
- [ ] Web apply làm YAML, `.env` và runtime có cùng member/admin/group.
- [ ] Restart gateway xong Tiny và Tí Nị vẫn nằm trong effective allowlist.
- [ ] Secret/comment trong `.env` không đổi và mode file là `0600`.
- [ ] Runtime apply lỗi rollback YAML và `.env` về fingerprint cũ.
```

- [ ] **Bước 2: Chạy toàn bộ kiểm chứng**

Run:

```powershell
npm test
python -m pytest -q -p no:cacheprovider
python scripts/acceptance.py --json
npm audit --omit=dev
python -m pip check
(Get-FileHash hermes-plugin/migrations/001_initial.sql -Algorithm SHA256).Hash.ToLower()
git diff --check
```

Expected: Node và Python không fail; acceptance `ok: true`; audit 0; pip check sạch; checksum `001` là `1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a`; diff check exit 0.

- [ ] **Bước 3: Cập nhật checkpoint bằng số liệu thật**

Thay `Việc tiếp theo` ở đầu kế hoạch bằng số test pass/fail, commit code, kết quả acceptance và bước deploy. Không ghi ID cá nhân đầy đủ, token, cookie hoặc secret.

- [ ] **Bước 4: Commit tài liệu/checkpoint**

```powershell
git add docs/operations/configuration.md docs/operations/acceptance-checklist.md docs/superpowers/plans/2026-08-18-admin-web-env-sync.md
git commit -m "docs: record admin web env sync verification"
git push origin company-assistant-v1
```

---

### Task 5: Deploy VPS, reconcile `.env` và kiểm tra restart

**Files trên VPS:**
- Source: `/home/anhakvip777/ai-agents/hermes-zalo-company-assistant`
- Profile: `/home/anhakvip777/.hermes/profiles/zalo-company`
- Plugin: `/home/anhakvip777/.hermes/profiles/zalo-company/plugins/zalo`
- Backup: `/home/anhakvip777/.hermes/profiles/zalo-company/runtime-backups/`

- [ ] **Bước 1: Backup trước deploy**

Tạo thư mục timestamp mode `0700`; copy plugin, `config.yaml`, `.env`, credential runtime và SQLite bằng `sqlite3.Connection.backup`. Chạy `PRAGMA integrity_check` trên bản backup và chỉ tiếp tục khi kết quả `ok`.

- [ ] **Bước 2: Fast-forward source và cài plugin**

```bash
git -C "$HOME/ai-agents/hermes-zalo-company-assistant" fetch origin company-assistant-v1
git -C "$HOME/ai-agents/hermes-zalo-company-assistant" merge --ff-only FETCH_HEAD
cd "$HOME/ai-agents/hermes-zalo-company-assistant"
npm ci --omit=dev --ignore-scripts --no-audit --no-fund
node install.mjs --yes --service-only --force \
  --hermes-home "$HOME/.hermes/profiles/zalo-company"
```

Truyền `ZALO_PLUGIN_TOKEN`, `ZALO_DATA_DIR` và `ZALO_RUNTIME_ENV_FILE` từ profile hiện hữu mà không in giá trị.

- [ ] **Bước 3: Reconcile allowlist YAML hiện tại vào `.env`**

Dùng Python của Hermes profile gọi `CompanyConfigFile` mới:

```python
config_file = CompanyConfigFile(profile / "config.yaml", env_path=profile / ".env")
snapshot = config_file.read_access_config()
config_file.apply_access_config(
    allowed_users=snapshot.config.allowed_users,
    admin_users=snapshot.config.admin_users,
    allowed_groups=snapshot.config.allowed_groups,
    expected_fingerprint=snapshot.fingerprint,
)
```

Không hiển thị nội dung `.env`; chỉ báo ba tập YAML/env có bằng nhau hay không.

- [ ] **Bước 4: Restart và kiểm tra runtime startup**

```bash
systemctl --user restart com.hermes.zaloplugin.service
systemctl --user restart hermes-gateway-zalo-company.service
```

Poll tối đa 30 giây cho bridge health và Admin Web. Xác nhận:

- bridge `ok=true`, `loggedIn=true`;
- gateway/bridge/cloudflared `active` + `enabled`;
- TCP SSE tới `127.0.0.1:8787` ở trạng thái `ESTAB`;
- `/admin/`, CSS và JS trả HTTP 200;
- load `CompanyConfig.from_platform_extra(extra, env=.env)` chứa đúng toàn bộ ID đã lưu trên Web;
- `.env` mode `0600`, secret key vẫn có mặt nhưng không in giá trị.

- [ ] **Bước 5: Kiểm tra Tiny thật và checkpoint deploy**

Yêu cầu Tiny gửi một DM mới. Bridge phải nhận inbound, conversation store phải có message mới của đúng sender và gateway không gửi thông báo từ chối. Sau đó cập nhật checkpoint với commit, backup path và kết quả thực tế; không ghi nội dung DM hoặc ID đầy đủ.

## Tiêu chí hoàn thành

- Web apply đồng bộ YAML, `.env` và runtime trong một transaction có rollback.
- Startup env không còn loại thành viên đã lưu trên Web.
- Secret/comment/biến lạ trong `.env` được giữ nguyên; mode POSIX là `0600`.
- Chat admin và Admin Web dùng chung đường persistence.
- Full Node/Python/integration/acceptance sạch; migration `001` không đổi.
- VPS restart vẫn cho Tiny/Tí Nị hoạt động và có backup rollback được.
