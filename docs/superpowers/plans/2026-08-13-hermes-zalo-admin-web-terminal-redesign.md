# Kế hoạch triển khai Hermes Zalo Admin Web phong cách terminal

> **Cho agent thực thi:** BẮT BUỘC dùng `superpowers:subagent-driven-development` (khuyên dùng) hoặc `superpowers:executing-plans` để triển khai từng task. Các bước dùng checkbox (`- [ ]`) để theo dõi.

**Mục tiêu:** Thay toàn bộ giao diện Admin Web bằng app shell phong cách terminal đã duyệt, tách HTML/CSS/JavaScript thuần, giữ nguyên business API, database, migration và phân quyền.

**Kiến trúc:** `AdminWebApp` tiếp tục sở hữu session, CSRF và toàn bộ `/admin/api/*`; nó chỉ phục vụ thêm ba asset cố định cùng origin từ `hermes-plugin/admin_web/`. `app.js` dùng DOM API và state trong memory để render bốn màn hình; `admin.css` sở hữu dark/light theme, sidebar responsive và terminal component mà không cần framework hoặc build step.

**Công nghệ:** Python 3.11+, aiohttp, HTML5 semantic, CSS custom properties/media queries, JavaScript ES2022 thuần, Node test runner, pytest, fake DOM harness hiện có.

---

## Checkpoint phiên làm việc

- Spec chuẩn: `docs/superpowers/specs/2026-08-13-hermes-zalo-admin-web-terminal-redesign-design.md` tại commit `bf60ca1`.
- Baseline source: official release `v1.1.4`; business API và database sáu bảng đã ổn định.
- Migration bất biến: `hermes-plugin/migrations/001_initial.sql` với SHA-256
  `1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a`.
- Static acceptance trước kế hoạch: `ok: true`; working tree chỉ chứa tài liệu kế hoạch/manifest trong lượt này.
- Task 1–12 hoàn tất trong working tree chưa commit: Admin Web tách thành ba asset cùng origin (`index.html`, `admin.css`, `app.js`); backend chỉ phục vụ hai asset cố định, asset lạ trả `404`, CSP không có `unsafe-inline`; không thay API, database, phân quyền hay migration.
- UI terminal đã có login/theme, sidebar desktop/tablet/mobile, dashboard, danh bạ/allowlist draft guard, history split view + tìm kiếm message + nút quay lại mobile, QR/log/activity/danger-zone dạng MiniTerminal, loading/error/401/409, modal focus-safe và cleanup state nhạy cảm. Kiểm chứng browser fake runtime: 1280×720, 768×900, 390×844; không tràn ngang document; mobile có bottom navigation. Runtime thử nghiệm `localhost:8879` đang phục vụ asset mới.
- Hardening cuối đã thêm guard cho phản hồi hội thoại/nhóm đến muộn, vô hiệu hóa response sau session expiry, luồng lỗi QR tiếng Việt qua `runAction`, export Blob cleanup trễ, nút Đăng xuất mobile có accessible name và asset CSS/JS `no-cache` để browser revalidate sau deploy. Các thay đổi chỉ nằm ở asset UI/test/header asset đã đăng ký trong manifest; không đổi API, database, migration hoặc permission.
- Verification mới nhất ngày 2026-08-13: Node `67/67 PASS`; Python toàn bộ gồm integration `227 passed`; Admin Web `88 passed`; full/static acceptance `ok: true`; `npm audit --omit=dev` 0 vulnerabilities; `python -m pip check` sạch; `npm pack --dry-run --json` có đủ 3 asset; `git diff --check` exit 0. Migration vẫn giữ SHA-256 khóa `1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a`.
- Browser fake runtime `localhost:8879` đã được khởi động lại với Hermes venv và xác nhận server trả asset CSS mới `Cache-Control: no-cache`; browser-control timeout lặp lại tại reload nên không được ghi thành PASS trực quan mới cho 1280×720, 768×900, 390×844. CSS/test responsive hiện có vẫn bao phủ ba viewport; cần kiểm tra trực quan lại ba viewport trước khi phát hành chính thức nếu runtime browser khả dụng.
- Việc tiếp theo: review diff cuối cùng, kiểm tra browser QA ba viewport khi kết nối browser ổn định, rồi commit thay đổi UI trên branch `company-assistant-v1`; sau đó người dùng chọn phát hành/push. Nếu compact, đọc lại `AGENTS.md`, ba tài liệu kiến trúc, manifest này và checkpoint trước khi làm tiếp; không sửa API/database/migration.

## Bản đồ file

| File | Hành động | Trách nhiệm sau triển khai |
|---|---|---|
| `hermes-plugin/admin_web/index.html` | Tạo | HTML semantic cố định cho login, app shell, navigation, modal và vùng render |
| `hermes-plugin/admin_web/admin.css` | Tạo | Design token, dark/light theme, terminal component, responsive và accessibility |
| `hermes-plugin/admin_web/app.js` | Tạo | API client, preference, navigation, render và mutation flow |
| `hermes-plugin/admin.py` | Sửa | Đọc/validate asset, phục vụ ba route cố định và CSP; giữ nguyên API nghiệp vụ |
| `tests/python/test_tooling.py` | Sửa | Asset/CSP contract và fake-DOM regression cho JavaScript tách riêng |
| `test/config.test.js` | Sửa | Contract package phải chứa đủ `admin_web/` |
| `package.json` | Sửa | Whitelist `hermes-plugin/admin_web/` trong runtime package |
| `README.md` | Sửa | Ghi giao diện mới, theme và browser support bằng tiếng Anh |
| `README.vi.md` | Sửa | Ghi hướng dẫn giao diện mới bằng tiếng Việt |
| `docs/operations/acceptance-checklist.md` | Sửa | Thêm checklist browser QA desktop/tablet/mobile |
| `docs/superpowers/plans/2026-08-10-hermes-zalo-admin-web-ui.md` | Sửa | Ghi checkpoint kết quả cuối và việc tiếp theo |

## Bất biến thực thi

- Không sửa `hermes-plugin/migrations/001_initial.sql`.
- Không thêm route dưới `/admin/api/` và không đổi payload hiện có.
- Asset route chỉ nhận đúng `admin.css` và `app.js`; không dùng path parameter.
- Không dùng `innerHTML`, inline event handler, CDN, external font, framework hoặc frontend build.
- `localStorage` chỉ lưu `hz-admin-theme-v1` và `hz-admin-sidebar-v1`.
- Mọi task kết thúc bằng targeted test; mỗi checkpoint lớn chạy static acceptance và `git diff --check`.

---

### Task 1: Khóa asset runtime trong package bằng TDD

**Files:**
- Modify: `test/config.test.js:14-21`
- Modify: `package.json:21-43`
- Modify: `docs/architecture/file-manifest.md`
- Create: `hermes-plugin/admin_web/index.html`
- Create: `hermes-plugin/admin_web/admin.css`
- Create: `hermes-plugin/admin_web/app.js`

- [x] **Bước 1: Viết test Node RED cho runtime package**

Mở rộng test đầu trong `test/config.test.js`:

```javascript
assert.ok(packageJson.files.includes("hermes-plugin/admin_web/"));
```

- [x] **Bước 2: Chạy test và xác nhận RED đúng nguyên nhân**

Run:

Run: `node --test test/config.test.js`

Expected:

- Node FAIL vì `package.json.files` chưa chứa `hermes-plugin/admin_web/`.

- [x] **Bước 3: Đăng ký ba asset trong file manifest**

Thêm ba dòng sau vào bảng **File tạo mới** của
`docs/architecture/file-manifest.md` trước khi tạo file:

```markdown
| `hermes-plugin/admin_web/index.html` | App shell, login, sidebar, topbar và vùng render của Admin Web |
| `hermes-plugin/admin_web/admin.css` | Theme terminal, component, responsive và accessibility |
| `hermes-plugin/admin_web/app.js` | API client, UI state, navigation và renderer bốn màn hình |
```

- [x] **Bước 4: Tạo ba asset tối thiểu để thiết lập seam**

Tạo `hermes-plugin/admin_web/index.html`:

```html
<!doctype html>
<html lang="vi" data-theme="system">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark light">
  <title>Hermes Zalo Admin</title>
  <link rel="stylesheet" href="/admin/assets/admin.css">
  <script src="/admin/assets/app.js" defer></script>
</head>
<body>
  <main id="admin-root" aria-live="polite"></main>
</body>
</html>
```

Tạo `hermes-plugin/admin_web/admin.css`:

```css
:root { color-scheme: dark light; font-family: system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; }
```

Tạo `hermes-plugin/admin_web/app.js`:

```javascript
"use strict";
const root = document.querySelector("#admin-root");
if (!root) throw new Error("Admin Web root is missing");
root.textContent = "Đang tải Admin Web…";
```

Thêm vào `package.json.files`:

```json
"hermes-plugin/admin_web/"
```

- [x] **Bước 5: Chạy Node packaging test để xác nhận GREEN**

Run: `node --test test/config.test.js`

Expected: PASS toàn file.

- [x] **Bước 6: Chạy static acceptance rồi commit seam asset**

Run: `python scripts/acceptance.py --static --json`

Expected: `ok: true`, manifest không còn path bị thiếu.

```powershell
git add docs/architecture/file-manifest.md hermes-plugin/admin_web package.json test/config.test.js
git commit -m "test: define admin web asset boundary"
```

---

### Task 2: Phục vụ asset cố định và CSP fail-closed

**Files:**
- Modify: `hermes-plugin/admin.py:676-904,1065-1144`
- Test: `tests/python/test_tooling.py`

- [x] **Bước 1: Viết test RED cho ba asset và CSP cùng origin**

Thêm test sau vào `tests/python/test_tooling.py`:

```python
@pytest.mark.asyncio
async def test_admin_web_serves_fixed_same_origin_assets_with_strict_csp(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    client, _cookie, _csrf = await authenticated_web_client(
        tmp_path,
        admin=AdminService(store=store),
        store=store,
        bridge=FakeBridge(),
    )
    try:
        page = await client.get("/admin/")
        css = await client.get("/admin/assets/admin.css")
        script = await client.get("/admin/assets/app.js")
        unknown = await client.get("/admin/assets/anything.js")
        assert page.status == css.status == script.status == 200
        assert unknown.status == 404
        assert page.content_type == "text/html"
        assert css.content_type == "text/css"
        assert script.content_type == "application/javascript"
        html = await page.text()
        assert 'href="/admin/assets/admin.css"' in html
        assert 'src="/admin/assets/app.js"' in html
        assert "<style" not in html
        assert "<script>" not in html
        assert page.headers["Cache-Control"] == "no-store"
        assert css.headers["Cache-Control"] == "public, max-age=3600"
        assert script.headers["X-Content-Type-Options"] == "nosniff"
        csp = page.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self'" in csp
        assert "img-src 'self' blob:" in csp
        assert "unsafe-inline" not in csp
    finally:
        await client.close()
```

Run:

```powershell
python -m pytest -q tests/python/test_tooling.py::test_admin_web_serves_fixed_same_origin_assets_with_strict_csp
```

Expected: FAIL vì asset route chưa tồn tại và trang vẫn chứa inline style/script.

- [x] **Bước 2: Chuyển script inline nguyên trạng sang `app.js` và đổi helper test**

Dùng block chính xác trong `hermes-plugin/admin.py` tại commit `bf60ca1`, từ
dòng bắt đầu `const state=` đến ngay trước `</script>`, làm nguồn cho `app.js`.
Đặt comment `// BOOTSTRAP` ngay trước bốn đoạn đăng ký event/session cuối. Không
đổi endpoint, query key, request body, retry delay, pagination limit hoặc text
error trong bước chuyển cơ học này.

Thay import `ADMIN_HTML` và phần trích script trong `tests/python/test_tooling.py` bằng:

```python
from admin import ADMIN_APP_JS, AdminService, AdminSessionSigner, AdminWebApp

def run_admin_javascript(body: str) -> subprocess.CompletedProcess[bytes]:
    definitions = ADMIN_APP_JS.split("// BOOTSTRAP", 1)[0]
    # Giữ nguyên FakeNode harness hiện có.
    source = f"{harness}\n{definitions}\nawait (async()=>{{\n{body}\n}})();\n"
    return subprocess.run(
        ["node", "--input-type=module", "-"],
        input=source.encode("utf-8"),
        capture_output=True,
        check=False,
    )
```

- [x] **Bước 3: Thay `ADMIN_HTML` inline bằng loader asset cố định**

Trong `hermes-plugin/admin.py`, thêm gần `_AdminSession`:

```python
ADMIN_WEB_ROOT = Path(__file__).resolve().parent / "admin_web"

def _read_admin_asset(name: str) -> str:
    if name not in {"index.html", "admin.css", "app.js"}:
        raise RuntimeError(f"unknown Admin Web asset: {name}")
    path = ADMIN_WEB_ROOT / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"required Admin Web asset is missing: {name}") from exc

ADMIN_HTML = _read_admin_asset("index.html")
ADMIN_CSS = _read_admin_asset("admin.css")
ADMIN_APP_JS = _read_admin_asset("app.js")
```

Trước khi xóa chuỗi inline, thay `index.html` tối thiểu của Task 1 bằng HTML cũ
từ `<body>` đến trước `<script>`, thêm `<link>`/`<script defer>` đã có trong
`<head>`, rồi xóa `<style>` và `<script>` inline. Như vậy app live vẫn có đủ
`#layout`, `#nav`, `#login`, `#password`, `#login-error` và `#app` trong commit
trung gian. Sau đó xóa chuỗi HTML/CSS/JS inline cũ khỏi `admin.py`.

- [x] **Bước 4: Thêm đúng hai route public cố định**

Trong middleware auth và `create_application()`:

```python
public = {
    ("GET", "/admin/"),
    ("GET", "/admin/assets/admin.css"),
    ("GET", "/admin/assets/app.js"),
    ("POST", "/admin/api/login"),
}

app.router.add_get("/admin/", self._page)
app.router.add_get("/admin/assets/admin.css", self._admin_css)
app.router.add_get("/admin/assets/app.js", self._admin_js)
```

Thêm handler:

```python
async def _admin_css(self, _request: Any):
    from aiohttp import web
    return web.Response(
        text=ADMIN_CSS,
        content_type="text/css",
        charset="utf-8",
        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )

async def _admin_js(self, _request: Any):
    from aiohttp import web
    return web.Response(
        text=ADMIN_APP_JS,
        content_type="application/javascript",
        charset="utf-8",
        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
```

- [x] **Bước 5: Siết CSP trang**

Đổi header `_page()` thành:

```python
"Content-Security-Policy": (
    "default-src 'self'; base-uri 'none'; object-src 'none'; "
    "frame-ancestors 'none'; form-action 'self'; "
    "style-src 'self'; script-src 'self'; img-src 'self' blob:"
),
```

Giữ `Cache-Control: no-store` và `X-Content-Type-Options: nosniff`.

- [x] **Bước 6: Chạy asset/CSP và JavaScript legacy tests**

Run:

```powershell
python -m pytest -q tests/python/test_tooling.py -k "admin_web or access_conflict or overview_shows or system_shows"
node --check hermes-plugin/admin_web/app.js
```

Expected: asset/CSP PASS và toàn bộ regression JavaScript cũ PASS. Không commit
Task 2 nếu bất kỳ renderer/helper nào chưa được chuyển đủ sang `app.js`.

- [x] **Bước 7: Commit asset server**

```powershell
git add hermes-plugin/admin.py hermes-plugin/admin_web tests/python/test_tooling.py
git commit -m "feat: serve isolated admin web assets"
```

---

### Task 3: Chuyển API client và renderer hiện tại sang `app.js` mà không đổi hành vi

**Files:**
- Modify: `hermes-plugin/admin_web/app.js`
- Modify: `hermes-plugin/admin_web/index.html`
- Test: `tests/python/test_tooling.py`

- [x] **Bước 1: Viết HTML semantic đầy đủ nhưng chưa styling**

Thay body `index.html` bằng khung cố định sau:

```html
<body>
  <div id="login-screen" class="login-screen">
    <form id="login" class="login-terminal" novalidate>
      <p class="terminal-title">HERMES ZALO · ADMIN LOGIN</p>
      <label for="password">Mật khẩu quản trị</label>
      <input id="password" type="password" autocomplete="current-password" required>
      <button type="submit">Đăng nhập</button>
      <p id="login-error" class="error-panel" aria-live="assertive"></p>
    </form>
  </div>
  <div id="app-shell" class="app-shell hidden">
    <aside id="sidebar" class="sidebar">
      <button id="sidebar-toggle" type="button" aria-label="Thu gọn thanh điều hướng"></button>
      <nav id="nav" aria-label="Điều hướng quản trị">
        <button data-view="overview" type="button">Tổng quan</button>
        <button data-view="access" type="button">Danh bạ &amp; Allowlist</button>
        <button data-view="history" type="button">Hội thoại</button>
        <button data-view="system" type="button">Hệ thống &amp; Hoạt động</button>
      </nav>
      <button id="logout" type="button">Đăng xuất</button>
    </aside>
    <section class="workspace">
      <header class="topbar">
        <span id="route-label"></span>
        <button id="theme-toggle" type="button" aria-label="Đổi giao diện màu"></button>
      </header>
      <main id="app" aria-live="polite"></main>
    </section>
  </div>
  <div id="modal-root"></div>
  <div id="toast-root" aria-live="polite"></div>
</body>
```

Giữ `<link>` và `<script defer>` trong `<head>`.

- [x] **Bước 2: Chuyển nguyên API/renderer definitions cũ sang `app.js`**

Di chuyển và giữ nguyên signature các hàm đang được regression test:

```javascript
const VIEW_TITLES={overview:"Tổng quan",access:"Danh bạ & Allowlist",history:"Hội thoại",system:"Hệ thống & Hoạt động"};
const state={csrf:null,view:"overview",draft:null,savedAccess:null,renderVersion:0,qrUrl:null,pendingOperation:null};
async function api(path,options={}) {
  const method=options.method||"GET";
  const headers={...(options.headers||{})};
  if(options.body&&!headers["Content-Type"])headers["Content-Type"]="application/json";
  if(state.csrf&&!['GET','HEAD'].includes(method))headers["X-CSRF-Token"]=state.csrf;
  const response=await fetch(path,{credentials:"same-origin",...options,method,headers});
  const data=await response.json().catch(()=>({code:"invalid_response",message:"Phản hồi không hợp lệ"}));
  if(!response.ok)throw Object.assign(new Error(data.message||"Yêu cầu thất bại"),{status:response.status,data});
  return data;
}
function el(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=String(text);if(className)node.className=className;return node;}
function clearApp(title){const app=document.querySelector("#app");app.replaceChildren(el("h1",title));const route=document.querySelector("#route-label");if(route)route.textContent=`~/admin/${state.view}`;return app;}
function card(title){const root=el("section",undefined,"card");if(title)root.append(el("h2",title));return root;}
function row(label,value){const p=el("p");p.append(el("strong",`${label}: `),document.createTextNode(value===undefined||value===null||value===""?"—":String(value)));return p;}
function button(label,action,tone=""){const item=el("button",label,tone?`button button-${tone}`:"button");item.type="button";item.addEventListener("click",action);return item;}
function entityId(item){return String(item?.id??item?.userId??item?.uid??item?.groupId??item?.threadId??"");}
function entityName(item){return String(item?.name??item?.displayName??item?.zaloName??item?.groupName??entityId(item));}
function friendStatus(item){const explicit=item?.friendStatus;if(explicit!==undefined&&explicit!==null&&explicit!=="")return String(explicit);const isFriend=item?.isFr;if(isFriend===true||isFriend===1||isFriend==="1")return "Bạn bè";if(isFriend===false||isFriend===0||isFriend==="0")return "Chưa kết bạn";const account=item?.accountStatus;return account===undefined||account===null||account===""?"":String(account);}
function setMember(values,id,enabled){const set=new Set((values||[]).map(String));enabled?set.add(String(id)):set.delete(String(id));return [...set].sort();}
function checkbox(label,checked,onChange){const wrap=el("label");const input=document.createElement("input");input.type="checkbox";input.checked=checked;input.addEventListener("change",()=>onChange(input.checked));wrap.append(input,document.createTextNode(` ${label} `));return wrap;}
```

Di chuyển không đổi endpoint/hành vi các hàm:

```javascript
renderOverviewEnhanced
renderAccessEnhanced
renderHistoryEnhanced
renderConversationEnhanced
renderSystemEnhanced
loadQrWithRetry
pollAfterRestart
historyQuery
historyFilters
renderCurrent
navigate
```

Nguồn chính xác của body các renderer là `hermes-plugin/admin.py` tại commit
`bf60ca1`, từ `renderOverviewEnhanced` đến `renderCurrent`. Đây là phép chuyển
file cơ học: không đổi chuỗi endpoint, query key, request body, retry delay,
pagination limit hoặc nội dung error trong task này.

- [x] **Bước 3: Tạo bootstrap sau marker**

Cuối `app.js`:

```javascript
// BOOTSTRAP
document.querySelector("#login").addEventListener("submit", handleLogin);
document.querySelector("#logout").addEventListener("click", handleLogout);
for (const item of document.querySelectorAll("[data-view]")) {
  item.addEventListener("click", () => navigate(item.dataset.view));
}
api("/admin/api/session")
  .then(data => { state.csrf=data.csrf; showApp(); return renderCurrent(); })
  .catch(() => showLogin());
```

`handleLogin` và `handleLogout` giữ request cũ; `showApp/showLogin` đổi selector
từ HTML cũ sang `#login-screen` và `#app-shell`.

Mở rộng `testNodes` trong fake DOM harness để các selector mới có node thật:

```javascript
"#app-shell":new FakeNode("div"),
"#login-screen":new FakeNode("div"),
"#route-label":new FakeNode("span"),
"#theme-toggle":new FakeNode("button"),
"#sidebar-toggle":new FakeNode("button"),
"#modal-root":new FakeNode("div"),
"#toast-root":new FakeNode("div"),
```

- [x] **Bước 4: Chạy toàn bộ regression JavaScript hiện có**

Run:

```powershell
python -m pytest -q tests/python/test_tooling.py -k "restart_poll or access_ or overview_ or system_ or history_ or enhanced_render or pages_show"
node --check hermes-plugin/admin_web/app.js
```

Expected: PASS. Endpoint calls và assertion text cũ không đổi.

- [x] **Bước 5: Chạy toàn bộ test Admin Web backend**

Run: `python -m pytest -q tests/python/test_tooling.py -k admin_web`

Expected: PASS.

- [x] **Bước 6: Commit hành vi parity**

```powershell
git add hermes-plugin/admin_web tests/python/test_tooling.py
git commit -m "refactor: move admin web client into static assets"
```

---

### Task 4: Theme system/dark/light và sidebar persistence

**Files:**
- Modify: `hermes-plugin/admin_web/app.js`
- Modify: `hermes-plugin/admin_web/admin.css`
- Test: `tests/python/test_tooling.py`

- [x] **Bước 1: Mở rộng fake DOM harness cho preference tests**

Thêm vào harness `run_admin_javascript`:

```javascript
const storage=new Map();
globalThis.localStorage={
  getItem:key=>storage.has(key)?storage.get(key):null,
  setItem:(key,value)=>storage.set(key,String(value)),
  removeItem:key=>storage.delete(key),
};
window.matchMedia=query=>({matches:query.includes("dark"),addEventListener(){},removeEventListener(){}});
document.documentElement=new FakeNode("html");
document.documentElement.dataset={};
```

- [x] **Bước 2: Viết test RED cho preference allowlist**

```python
def test_admin_web_theme_and_sidebar_preferences_are_versioned_and_isolated() -> None:
    assert_admin_javascript(r'''
storage.clear();
applyInitialPreferences();
assert.equal(document.documentElement.dataset.theme,"system");
setTheme("dark");
setSidebar("collapsed");
assert.equal(storage.get("hz-admin-theme-v1"),"dark");
assert.equal(storage.get("hz-admin-sidebar-v1"),"collapsed");
assert.equal(storage.size,2);
assert.equal(state.csrf,null);
assert.equal(storage.has("csrf"),false);
''')
```

Run targeted test.

Expected: FAIL vì preference functions chưa có.

- [x] **Bước 3: Implement preference functions**

Trong `app.js` trước marker bootstrap:

```javascript
const THEME_KEY="hz-admin-theme-v1";
const SIDEBAR_KEY="hz-admin-sidebar-v1";
const THEMES=new Set(["system","dark","light"]);
const SIDEBARS=new Set(["expanded","collapsed"]);

function storedChoice(key, allowed, fallback) {
  const value=localStorage.getItem(key);
  return allowed.has(value)?value:fallback;
}
function setTheme(value) {
  const theme=THEMES.has(value)?value:"system";
  document.documentElement.dataset.theme=theme;
  localStorage.setItem(THEME_KEY,theme);
  updateThemeLabel(theme);
}
function setSidebar(value) {
  const sidebar=SIDEBARS.has(value)?value:"expanded";
  document.documentElement.dataset.sidebar=sidebar;
  localStorage.setItem(SIDEBAR_KEY,sidebar);
  updateSidebarLabel(sidebar);
}
function applyInitialPreferences() {
  document.documentElement.dataset.theme=storedChoice(THEME_KEY,THEMES,"system");
  document.documentElement.dataset.sidebar=storedChoice(SIDEBAR_KEY,SIDEBARS,"expanded");
}
function updateThemeLabel(theme) {
  const control=document.querySelector("#theme-toggle");
  if(control)control.setAttribute("aria-label",`Giao diện hiện tại: ${theme}`);
}
function updateSidebarLabel(sidebar) {
  const control=document.querySelector("#sidebar-toggle");
  if(control)control.setAttribute("aria-label",sidebar==="collapsed"?"Mở rộng thanh điều hướng":"Thu gọn thanh điều hướng");
}
```

Theme button luân phiên `system -> dark -> light -> system`; sidebar button luân
phiên `expanded <-> collapsed`.

- [x] **Bước 4: Thêm design token và responsive shell CSS**

Trong `admin.css`, định nghĩa đầy đủ các nhóm selector:

```css
:root,[data-theme="dark"] { --page:#07101c;--surface:#0c1422;--panel:#101a2a;--line:#263650;--text:#e8eef8;--muted:#8d9ab0;--accent:#34c5ef;--focus:#69d7ff; }
[data-theme="light"] { --page:#eef4fa;--surface:#f8fbff;--panel:#fff;--line:#c8d6e7;--text:#102033;--muted:#5f7085;--accent:#087ec2;--focus:#006cae; }
@media (prefers-color-scheme:light) { [data-theme="system"] { --page:#eef4fa;--surface:#f8fbff;--panel:#fff;--line:#c8d6e7;--text:#102033;--muted:#5f7085;--accent:#087ec2;--focus:#006cae; } }
.app-shell { min-height:100vh;display:grid;grid-template-columns:236px minmax(0,1fr); }
[data-sidebar="collapsed"] .app-shell { grid-template-columns:82px minmax(0,1fr); }
@media (max-width:900px) { .app-shell { grid-template-columns:82px minmax(0,1fr); } }
@media (max-width:620px) { .app-shell { display:block; }.sidebar { position:fixed;inset:auto 0 0;height:66px;z-index:10; } }
@media (prefers-reduced-motion:reduce) { *,*::before,*::after { animation-duration:.01ms!important;transition-duration:.01ms!important; } }
```

Bổ sung focus ring `:focus-visible`, `.hidden`, login shell, sidebar, topbar và
bottom navigation theo token; không hard-code màu nghiệp vụ ngoài token.

- [x] **Bước 5: Chạy preference test và syntax check**

Run:

```powershell
python -m pytest -q tests/python/test_tooling.py -k "theme_and_sidebar or admin_web_html"
node --check hermes-plugin/admin_web/app.js
```

Expected: PASS.

- [x] **Bước 6: Commit shell/theme**

```powershell
git add hermes-plugin/admin_web tests/python/test_tooling.py
git commit -m "feat: add persistent admin theme and sidebar"
```

---

### Task 5: Terminal component và màn hình Tổng quan

**Files:**
- Modify: `hermes-plugin/admin_web/admin.css`
- Modify: `hermes-plugin/admin_web/app.js`
- Test: `tests/python/test_tooling.py`

- [x] **Bước 1: Viết test RED cho component semantic và safe DOM**

```python
def test_overview_uses_terminal_status_components_without_dynamic_html() -> None:
    assert_admin_javascript(r'''
globalThis.fetch=async()=>({ok:true,status:200,json:async()=>({
  bot:{id:"bot-1",name:"Trợ lý"},bridge:{ok:true,loggedIn:true},
  gateway:{status:"Hoạt động"},provider:"custom",model:"gpt-5.6-terra",
  counts:{allowed_users:5,allowed_groups:2},history:{conversations:24,messages:1248},
  recent_activity:[],
})});
await renderOverviewEnhanced();
assert.ok(findNodes(testNodes["#app"],n=>n.className?.includes("terminal-frame")).length===1);
assert.ok(findNodes(testNodes["#app"],n=>n.className?.includes("status-card")).length>=4);
assert.match(nodeText(testNodes["#app"]),/bot-1/);
assert.equal(APP_USES_INNER_HTML,false);
''')
```

Trong definitions đặt constant:

```javascript
const APP_USES_INNER_HTML=false;
```

Run targeted test; expected FAIL vì class component chưa có.

- [x] **Bước 2: Tạo helper component bằng DOM API**

Trong `app.js`:

```javascript
function terminalFrame(title) {
  const frame=el("section",undefined,"terminal-frame");
  const head=el("header",undefined,"terminal-head");
  for (const color of ["red","amber","green"]) head.append(el("i",undefined,`terminal-dot ${color}`));
  head.append(el("span",title,"terminal-title"));
  const body=el("div",undefined,"terminal-body");
  frame.append(head,body);
  return {frame,body};
}
function statusCard(label,value,detail,tone="neutral") {
  const root=el("article",undefined,`status-card tone-${tone}`);
  root.append(el("span",label,"status-label"),el("strong",value,"status-value"),el("small",detail,"status-detail"));
  return root;
}
function badge(text,tone="neutral") { return el("span",text,`badge badge-${tone}`); }
```

- [x] **Bước 3: Render Tổng quan theo mockup đã duyệt**

`renderOverviewEnhanced` phải tạo đúng thứ tự:

```javascript
const {frame,body}=terminalFrame("TỔNG QUAN · LIVE STATUS");
const stats=el("div",undefined,"status-grid");
stats.append(
  statusCard("ZALO",zaloState,data.bridge?.loggedIn?"Đã đăng nhập":"Cần đăng nhập",zaloTone),
  statusCard("HERMES GATEWAY",gatewayState,"Adapter Hermes",gatewayTone),
  statusCard("HỘI THOẠI",data.history?.conversations??0,`${data.history?.messages??0} tin nhắn`),
  statusCard("ALLOWLIST",`${data.counts?.allowed_users??0} / ${data.counts?.allowed_groups??0}`,"Thành viên / nhóm")
);
body.append(stats,botPanel,activityPanel,quickActionsPanel);
app.append(frame);
```

Quick action chỉ gọi `navigate`; nút QR không gọi POST như regression hiện tại.

- [x] **Bước 4: Thêm CSS terminal/dashboard**

Tạo selector `.terminal-frame`, `.terminal-head`, `.terminal-dot`,
`.terminal-body`, `.status-grid`, `.status-card`, `.dashboard-grid`,
`.quick-actions`, `.badge-*` theo token. Border terminal dùng:

```css
.terminal-frame { border:1px solid transparent;border-radius:18px;background:linear-gradient(var(--surface),var(--surface)) padding-box,linear-gradient(135deg,var(--accent),#568cff88,#e7a63399,#98496288) border-box;box-shadow:var(--shadow-terminal);overflow:hidden; }
```

- [x] **Bước 5: Chạy overview regression**

Run:

```powershell
python -m pytest -q tests/python/test_tooling.py -k "overview or enhanced_render"
```

Expected: PASS.

- [x] **Bước 6: Commit dashboard**

```powershell
git add hermes-plugin/admin_web tests/python/test_tooling.py
git commit -m "feat: redesign admin overview dashboard"
```

---

### Task 6: Danh bạ, bảng responsive và draft guard

**Files:**
- Modify: `hermes-plugin/admin_web/admin.css`
- Modify: `hermes-plugin/admin_web/app.js`
- Test: `tests/python/test_tooling.py`

- [x] **Bước 1: Viết test RED cho draft dirty, beforeunload và stale badge**

```python
def test_access_draft_guard_and_stale_snapshot_are_explicit() -> None:
    assert_admin_javascript(r'''
state.draft={allowed_users:["u-1"],admin_users:[],allowed_groups:["g-1"],fingerprint:"fp"};
state.savedAccess={allowed_users:[],admin_users:[],allowed_groups:["g-1"],fingerprint:"fp"};
assert.equal(hasUnsavedAccessChanges(),true);
const event={preventDefault(){this.prevented=true;},returnValue:undefined};
handleBeforeUnload(event);
assert.equal(event.prevented,true);
assert.equal(event.returnValue,"");
const stale=staleNotice({stale:true,error:"bridge unavailable"});
assert.match(nodeText(stale),/Dữ liệu cũ/);
''')
```

Run targeted test; expected FAIL vì functions chưa có.

- [x] **Bước 2: Implement normalized draft comparison và unload guard**

```javascript
function accessShape(value) {
  return {
    allowed_users:[...(value?.allowed_users||[])].map(String).sort(),
    admin_users:[...(value?.admin_users||[])].map(String).sort(),
    allowed_groups:[...(value?.allowed_groups||[])].map(String).sort(),
  };
}
function hasUnsavedAccessChanges() {
  return JSON.stringify(accessShape(state.draft))!==JSON.stringify(accessShape(state.savedAccess));
}
function handleBeforeUnload(event) {
  if (!hasUnsavedAccessChanges()) return;
  event.preventDefault();
  event.returnValue="";
}
function staleNotice(data) {
  if (!data?.stale) return null;
  const root=el("div",undefined,"stale-notice");
  root.append(badge("Dữ liệu cũ","warning"),el("span",data.error||"Bridge không sẵn sàng"));
  return root;
}
```

Bootstrap gắn `window.addEventListener("beforeunload",handleBeforeUnload)`.

- [x] **Bước 3: Render bảng người và nhóm theo DataTable**

Mỗi cell có `data-label` để CSS mobile hiển thị label:

```javascript
function tableCell(label,nodeOrText) {
  const cell=el("td");
  cell.dataset.label=label;
  if(nodeOrText&&typeof nodeOrText==="object"&&"tagName" in nodeOrText)cell.append(nodeOrText);
  else cell.append(document.createTextNode(String(nodeOrText??"—")));
  return cell;
}
```

Giữ các toggle bằng input checkbox thật với label; không dùng div giả switch.
Group member detail dùng `replaceChildren` để lần mở sau không nhân đôi danh sách.

- [x] **Bước 4: Tạo DraftBar và navigation guard**

```javascript
function draftBar(onSave,onReload) {
  const bar=el("aside",undefined,"draft-bar");
  bar.append(el("span","Có thay đổi chưa áp dụng"),button("Tải lại",onReload),button("Lưu và áp dụng",onSave,"primary"));
  return bar;
}
async function guardedNavigate(view) {
  if (state.view==="access"&&view!=="access"&&hasUnsavedAccessChanges()&&!window.confirm("Bỏ các thay đổi allowlist chưa lưu?")) return false;
  return navigate(view);
}
```

Cập nhật nav bootstrap dùng `guardedNavigate`.

- [x] **Bước 5: Thêm CSS table/card mobile và DraftBar**

Desktop dùng table semantic. Ở `max-width:620px`, ẩn `thead`, mỗi `tr` thành card
và `td::before { content:attr(data-label) }`. DraftBar sticky trên desktop và
đứng trên bottom navigation ở mobile.

- [x] **Bước 6: Chạy access regression**

Run:

```powershell
python -m pytest -q tests/python/test_tooling.py -k "access or group_members"
```

Expected: PASS, gồm conflict, lock khi save, unlisted ID và zca friend status.

- [x] **Bước 7: Commit access UI**

```powershell
git add hermes-plugin/admin_web tests/python/test_tooling.py
git commit -m "feat: redesign admin access management"
```

---

### Task 7: Hội thoại split view, filter và modal delete/export

**Files:**
- Modify: `hermes-plugin/admin_web/admin.css`
- Modify: `hermes-plugin/admin_web/app.js`
- Test: `tests/python/test_tooling.py`

- [x] **Bước 1: Viết test RED cho confirm modal không side-effect sớm**

```python
def test_history_delete_requires_explicit_modal_confirmation() -> None:
    assert_admin_javascript(r'''
let deletes=0;
globalThis.fetch=async(path,options={})=>{
  if(path==="/admin/api/history/delete"){deletes+=1;return {ok:true,status:200,json:async()=>({success:true})};}
  throw new Error(path);
};
const modal=confirmModal({title:"Xóa hội thoại",message:"Không thể hoàn tác",confirmLabel:"Xóa",tone:"danger"});
assert.equal(deletes,0);
modal.cancel();
assert.equal(deletes,0);
const confirmed=confirmModal({title:"Xóa hội thoại",message:"Không thể hoàn tác",confirmLabel:"Xóa",tone:"danger",onConfirm:()=>api("/admin/api/history/delete",{method:"POST",body:"{}"})});
await confirmed.confirm();
assert.equal(deletes,1);
''')
```

Run targeted test; expected FAIL vì modal chưa có.

- [x] **Bước 2: Implement modal focus-safe**

```javascript
function confirmModal({title,message,confirmLabel,tone="neutral",onConfirm=async()=>{}}) {
  const previous=document.activeElement;
  const dialog=el("section",undefined,`modal modal-${tone}`);
  dialog.setAttribute("role","dialog");dialog.setAttribute("aria-modal","true");
  const cancelButton=button("Hủy",cancel);
  const confirmButton=button(confirmLabel,confirm,tone==="danger"?"danger":"primary");
  dialog.append(el("h2",title),el("p",message),cancelButton,confirmButton);
  const root=document.querySelector("#modal-root");root.replaceChildren(dialog);
  function close(){root.replaceChildren();previous?.focus?.();}
  function cancel(){close();}
  async function confirm(){confirmButton.disabled=true;try{await onConfirm();close();}finally{confirmButton.disabled=false;}}
  return {dialog,cancel,confirm};
}
```

Bootstrap gắn Escape handler chỉ đóng modal hiện tại, không phát mutation.

- [x] **Bước 3: Render split view hội thoại**

`renderHistoryEnhanced` tạo `.conversation-layout` với:

- `.conversation-list`: conversation button semantic, pagination.
- `.conversation-detail`: empty prompt hoặc message timeline.
- `.history-toolbar`: filter hiện tại, không đổi query key.

`renderConversationEnhanced` giữ endpoint, pagination, attachment link và
thread activity; thêm badge bot/mention/recalled/status bằng helper `badge`.

- [x] **Bước 4: Nối delete/export vào modal và toast**

Delete body giữ nguyên filter/confirm contract hiện tại. Export giữ fetch Blob
và revoke URL; sau success gọi `showToast("Đã tạo file xuất lịch sử","success")`.
Không retry hai thao tác.

- [x] **Bước 5: Thêm CSS split/mobile**

Desktop `grid-template-columns:300px minmax(0,1fr)`. Mobile xếp dọc, có nút
`Quay lại danh sách`; message bubble tối đa 78% desktop và 92% mobile, metadata
luôn nằm ngoài nội dung text.

- [x] **Bước 6: Chạy history regression**

Run:

```powershell
python -m pytest -q tests/python/test_tooling.py -k "history or conversation or attachment"
```

Expected: PASS.

- [x] **Bước 7: Commit history UI**

```powershell
git add hermes-plugin/admin_web tests/python/test_tooling.py
git commit -m "feat: redesign admin conversation history"
```

---

### Task 8: Hệ thống, QR, log, activity và danger zone

**Files:**
- Modify: `hermes-plugin/admin_web/admin.css`
- Modify: `hermes-plugin/admin_web/app.js`
- Test: `tests/python/test_tooling.py`

- [x] **Bước 1: Viết test RED cho restart modal và unknown state**

```python
def test_system_restart_waits_for_confirmation_and_shows_pending_state() -> None:
    assert_admin_javascript(r'''
let restartCalls=0;
globalThis.fetch=async(path)=>{
  if(path==="/admin/api/system/restart"){restartCalls+=1;return {ok:true,status:202,json:async()=>({accepted:true})};}
  throw new Error(path);
};
const flow=restartConfirmation("gateway");
assert.equal(restartCalls,0);
flow.cancel();
assert.equal(restartCalls,0);
const accepted=restartConfirmation("gateway");
await accepted.confirm();
assert.equal(restartCalls,1);
assert.equal(state.pendingOperation,"restart:gateway");
''')
```

Run targeted test; expected FAIL.

- [x] **Bước 2: Implement restart confirmation một lần**

```javascript
function restartConfirmation(target) {
  const modal=confirmModal({
    title:`Restart ${target}`,
    message:`Kết nối ${target} sẽ tạm gián đoạn. Hệ thống không tự gửi lại lệnh.`,
    confirmLabel:`Restart ${target}`,
    tone:"danger",
    onConfirm:async()=>{
      state.pendingOperation=`restart:${target}`;
      await api("/admin/api/system/restart",{method:"POST",body:JSON.stringify({target})});
      await pollAfterRestart(target);
    },
  });
  return {
    cancel:modal.cancel,
    confirm:modal.confirm,
  };
}
```

- [x] **Bước 3: Render MiniTerminal cho System**

Tạo helper:

```javascript
function miniTerminal(title,tone="neutral") {
  const root=el("section",undefined,`mini-terminal mini-${tone}`);
  const body=el("div",undefined,"mini-body");
  root.append(el("header",title,"mini-title"),body);
  return {root,body};
}
```

`renderSystemEnhanced` render đúng nhóm Runtime, QR, Live Log, Activity và Danger
Zone. Giữ các filter/query/pagination hiện tại. Log dùng `textContent`; copy chỉ
dùng `lastError` đã redact như regression.

- [x] **Bước 4: QR lifecycle và cleanup Blob URL**

Giữ `loadQrWithRetry`; bổ sung `releaseQrUrl()` khi logout, session `401`, thay QR
và `pagehide`:

```javascript
function releaseQrUrl(){if(state.qrUrl){URL.revokeObjectURL(state.qrUrl);state.qrUrl=null;}}
```

- [x] **Bước 5: Thêm CSS MiniTerminal/log/danger**

Log có `overflow:auto`, `white-space:pre-wrap`, `overflow-wrap:anywhere`.
Danger dùng token danger và text hậu quả; button không chỉ dựa vào màu để truyền
trạng thái.

- [x] **Bước 6: Chạy system/restart/QR regression**

Run:

```powershell
python -m pytest -q tests/python/test_tooling.py -k "system or restart or qr or reconnect or activity"
```

Expected: PASS.

- [x] **Bước 7: Commit System UI**

```powershell
git add hermes-plugin/admin_web tests/python/test_tooling.py
git commit -m "feat: redesign admin system controls"
```

---

### Task 9: Loading, empty, stale, error, 401 và 409 hoàn chỉnh

**Files:**
- Modify: `hermes-plugin/admin_web/admin.css`
- Modify: `hermes-plugin/admin_web/app.js`
- Test: `tests/python/test_tooling.py`

- [x] **Bước 1: Viết test RED cho skeleton và error shell**

```python
def test_admin_web_keeps_shell_for_loading_and_redacted_errors() -> None:
    assert_admin_javascript(r'''
showLoading("overview");
assert.ok(findNodes(testNodes["#app"],n=>n.className?.includes("skeleton")).length>=1);
const error=Object.assign(new Error("Không thể tải dữ liệu"),{status:500,data:{retryable:false}});
showViewError(error,()=>{});
assert.match(nodeText(testNodes["#app"]),/Không thể tải dữ liệu/);
assert.ok(findNodes(testNodes["#app"],n=>n.tagName==="BUTTON"&&/Thử lại/.test(n.textContent)).length===1);
assert.equal(testNodes["#app-shell"].classList.contains?.("hidden")??false,false);
''')
```

Mở rộng fake nodes/classList để có `contains`.

- [x] **Bước 2: Implement state component**

```javascript
function skeleton(count=4){const root=el("div",undefined,"skeleton-grid");for(let i=0;i<count;i++)root.append(el("span",undefined,"skeleton"));return root;}
function emptyState(title,message,action){const root=el("section",undefined,"empty-state");root.append(el("h2",title),el("p",message));if(action)root.append(action);return root;}
function showViewError(error,retry){const app=clearApp("Có lỗi");const panel=el("section",undefined,"error-panel");panel.append(el("h2","Không thể tải dữ liệu"),el("p",error.message||"Yêu cầu thất bại"),button("Thử lại",retry));app.append(panel);}
function showLoading(view){const app=clearApp(VIEW_TITLES[view]||"Đang tải");app.append(skeleton(view==="overview"?4:6));}
function showToast(message,tone="neutral"){const root=document.querySelector("#toast-root");const toast=el("div",message,`toast toast-${tone}`);root.replaceChildren(toast);window.setTimeout(()=>{if(root.children?.[0]===toast)root.replaceChildren();},4000);}
```

- [x] **Bước 3: Chuẩn hóa `renderCurrent` error branch**

`401` phải gọi `releaseQrUrl`, đặt `state.csrf=null`, không ghi storage và gọi
`showLogin`. `409` hiển thị action **Tải lại cấu hình** nhưng giữ `state.draft`.
Các lỗi khác dùng `showViewError(error,renderCurrent)`.

- [x] **Bước 4: Thêm CSS skeleton/state/toast**

Skeleton pulse tắt dưới reduced motion. Error/stale/empty đều có icon + text,
không chỉ màu. Toast không che bottom nav mobile.

- [x] **Bước 5: Chạy state regression**

Run:

```powershell
python -m pytest -q tests/python/test_tooling.py -k "pages_show or stale or conflict or expired or unhandled_errors"
```

Expected: PASS.

- [x] **Bước 6: Commit state UX**

```powershell
git add hermes-plugin/admin_web tests/python/test_tooling.py
git commit -m "feat: add resilient admin web states"
```

---

### Task 10: Accessibility và browser acceptance

**Files:**
- Modify: `hermes-plugin/admin_web/index.html`
- Modify: `hermes-plugin/admin_web/admin.css`
- Modify: `hermes-plugin/admin_web/app.js`
- Modify: `docs/operations/acceptance-checklist.md`
- Test: `tests/python/test_tooling.py`

- [x] **Bước 1: Viết static accessibility contract RED**

```python
def test_admin_web_assets_include_accessibility_and_responsive_contracts() -> None:
    html = (Path(__file__).parents[2] / "hermes-plugin/admin_web/index.html").read_text("utf-8")
    css = (Path(__file__).parents[2] / "hermes-plugin/admin_web/admin.css").read_text("utf-8")
    js = (Path(__file__).parents[2] / "hermes-plugin/admin_web/app.js").read_text("utf-8")
    assert 'aria-label="Điều hướng quản trị"' in html
    assert 'aria-live="assertive"' in html
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "max-width:620px" in css.replace(" ", "")
    assert "innerHTML" not in js
    assert "unsafe-eval" not in js
```

Run targeted test; expected FAIL cho marker còn thiếu.

- [x] **Bước 2: Hoàn thiện label/focus/modal keyboard**

- Mọi icon-only button có `aria-label` và cập nhật khi state đổi.
- Modal đặt focus vào nút Hủy, Escape đóng, đóng xong trả focus.
- Nav item có `aria-current="page"` cho view hiện tại.
- Theme button label gồm state hiện tại và state tiếp theo.
- Loading/error/mutation dùng đúng vùng live trong HTML.

- [x] **Bước 3: Hoàn thiện CSS viewport**

Xác nhận không selector nào tạo `min-width` lớn hơn viewport; ID và log dùng
`overflow-wrap:anywhere`; bảng mobile thành card; history/terminal/status grid
đều hạ về một cột khi cần.

- [x] **Bước 4: Bổ sung checklist QA thủ công**

Trong `docs/operations/acceptance-checklist.md`, thêm checklist exact:

```markdown
### Admin Web terminal UI

- [x] 1280×720 dark/light: sidebar mở, thu gọn và reload vẫn giữ state.
- [x] 768 px: sidebar icon-only; không tràn ngang toàn trang.
- [x] 390×844: bottom navigation; table thành card; modal và toast không bị che.
- [x] Login sai/đúng, session hết hạn và CSRF lỗi hiển thị thông báo tiếng Việt.
- [x] Overview loading/empty/error; Access stale/draft/409; History filter/page/export/delete.
- [x] System QR/log/activity/restart; không tự retry mutation.
- [x] Tab/Shift+Tab, Enter, Space, Escape và focus ring hoạt động.
- [x] `prefers-reduced-motion` tắt skeleton/transition không cần thiết.
```

- [x] **Bước 5: Chạy targeted accessibility test**

Run: `python -m pytest -q tests/python/test_tooling.py -k accessibility`

Expected: PASS.

- [x] **Bước 6: Browser QA bằng fake runtime hiện có**

Khởi động Admin Web bằng fixture/fake bridge không chứa dữ liệu thật, mở bằng
browser tại 1280×720, 768×900 và 390×844. Kiểm tra đúng checklist Bước 4; lưu
kết quả pass/fail vào checkpoint, không lưu screenshot có ID/runtime thật.

- [x] **Bước 7: Commit accessibility/QA**

```powershell
git add hermes-plugin/admin_web tests/python/test_tooling.py docs/operations/acceptance-checklist.md
git commit -m "test: cover admin web responsive accessibility"
```

---

### Task 11: Packaging, installer parity và tài liệu vận hành

**Files:**
- Modify: `test/config.test.js`
- Modify: `README.md`
- Modify: `README.vi.md`
- Modify: `docs/superpowers/plans/2026-08-10-hermes-zalo-admin-web-ui.md`
- Test: `test/config.test.js`

- [x] **Bước 1: Viết packaging test RED cho đủ ba asset**

Mở rộng test `npm dry-run artifact`:

```javascript
for (const required of [
  "hermes-plugin/admin_web/index.html",
  "hermes-plugin/admin_web/admin.css",
  "hermes-plugin/admin_web/app.js",
]) assert.ok(paths.has(required),`missing ${required}`);
```

Thêm test installer source-tree:

```javascript
test("installer copies the complete admin web asset directory", () => {
  const source=fs.readFileSync(path.join(ROOT,"install.mjs"),"utf8");
  assert.match(source,/fs\.cpSync\(src, dest, \{ recursive: true, force: true \}\)/);
});
```

Run: `node --test test/config.test.js`

Expected: package test PASS nếu Task 1 đúng; nếu thiếu asset sẽ FAIL rõ path.

- [x] **Bước 2: Chạy pack và kiểm tra nội dung thực tế**

Run:

```powershell
npm pack --dry-run --json
```

Expected: metadata có đủ ba asset, không có `.env`, database, QR, media, log hoặc
mockup brainstorm.

- [x] **Bước 3: Cập nhật README tiếng Việt và tiếng Anh**

Thêm đoạn sau vào phần Admin Web của `README.vi.md`:

```markdown
Giao diện quản trị dùng phong cách terminal responsive, hỗ trợ chế độ theo hệ
điều hành/sáng/tối và sidebar có thể thu gọn. Trình duyệt chỉ lưu hai preference
giao diện đã version hóa; password, session, CSRF và dữ liệu công ty không được
lưu trong `localStorage`. Khuyên dùng bản Chrome, Edge, Firefox hoặc Safari còn
được nhà cung cấp cập nhật. Bản redesign không đổi API, database hoặc permission.
Nếu thiếu asset `admin_web`, plugin sẽ fail startup; hãy cài lại package đầy đủ.
```

Thêm bản tiếng Anh tương ứng vào `README.md`:

```markdown
The terminal-style Admin Web is responsive, supports system/light/dark themes,
and has a collapsible sidebar. The browser persists only two versioned UI
preferences; passwords, sessions, CSRF values, and company data are never stored
in `localStorage`. Use a currently supported Chrome, Edge, Firefox, or Safari.
The redesign does not change APIs, the database, or permissions. Missing
`admin_web` assets fail startup; reinstall the complete package.
```

- [x] **Bước 4: Cập nhật checkpoint kế hoạch Admin Web gốc**

Thêm vào đầu `Checkpoint phiên làm việc`, rồi thay các giá trị trong dấu `<...>`
bằng output thật của Task 12 trước commit cuối:

```markdown
- Terminal redesign hoàn tất tại `<commit-range>`: Node `<pass>/<total>`, Python
  `<pass>/<total>`, integration `<pass>/<total>`; browser QA 1280×720, 768×900
  và 390×844 `<PASS/FAIL>`; static/full acceptance `<kết quả>`. Việc tiếp theo:
  `<review hoặc phát hành patch>`.
```

Không commit khi còn dấu `<` hoặc `>` trong dòng checkpoint. Không ghi secret,
cookie hoặc ID runtime.

- [x] **Bước 5: Chạy packaging/security targeted**

Run:

```powershell
node --test test/config.test.js
npm audit --omit=dev
python scripts/acceptance.py --static --json
git diff --check
```

Expected: tất cả exit `0`, acceptance `ok: true`.

- [x] **Bước 6: Commit packaging/docs**

```powershell
git add test/config.test.js README.md README.vi.md docs/superpowers/plans/2026-08-10-hermes-zalo-admin-web-ui.md
git commit -m "docs: ship terminal admin web assets"
```

---

### Task 12: Full verification và release-ready checkpoint

**Files:**
- Modify: `docs/superpowers/plans/2026-08-10-hermes-zalo-admin-web-ui.md`
- Verify only: toàn repository

- [x] **Bước 1: Xác nhận working tree và manifest**

Run:

```powershell
git status --short
git diff --name-only HEAD~11..HEAD
python scripts/acceptance.py --static --json
```

Expected: mọi path nằm trong `file-manifest.md`; static acceptance `ok: true`.

- [x] **Bước 2: Chạy toàn bộ Node suite**

Run: `npm test`

Expected: tất cả test PASS, test count lớn hơn baseline `66`.

- [x] **Bước 3: Chạy toàn bộ Python và integration suite**

Run: `python -m pytest -q`

Expected: tất cả test PASS, không skip test mới.

- [x] **Bước 4: Chạy full acceptance và dependency audit**

Run:

```powershell
python scripts/acceptance.py --json
npm audit --omit=dev
python -m pip check
```

Expected: acceptance `ok: true`, `0 vulnerabilities`, không broken dependency.

- [x] **Bước 5: Kiểm tra migration và whitespace**

Run:

```powershell
(Get-FileHash hermes-plugin/migrations/001_initial.sql -Algorithm SHA256).Hash.ToLower()
git diff --check
```

Expected checksum:

```text
1bc42abea11f4480d7a513cb4ddd2ee9d6986d1449d5a939aed14e59c161e42a
```

Expected `git diff --check`: exit `0`.

- [x] **Bước 6: Cập nhật checkpoint bằng bằng chứng thật**

Ghi vào checkpoint kế hoạch Admin Web gốc:

- Commit range terminal redesign.
- Số Node/Python/integration pass thực tế.
- Kết quả browser QA ba viewport.
- Full/static acceptance, audit, pip check và migration checksum.
- Việc tiếp theo: review diff, chọn phát hành patch mới; không tự tag/push nếu
  người dùng chưa yêu cầu.

- [x] **Bước 7: Commit checkpoint cuối**

```powershell
git add docs/superpowers/plans/2026-08-10-hermes-zalo-admin-web-ui.md
git commit -m "docs: record terminal admin web verification"
```

## Tiêu chí hoàn thành toàn kế hoạch

- Login và bốn màn hình khớp style terminal đã duyệt.
- Theme system/dark/light và sidebar persistence pass test.
- Desktop/tablet/mobile không tràn ngang trang.
- Tất cả API, payload, database và permission giữ nguyên.
- Asset/CSP fail-closed và package/installer chứa đủ file.
- Loading, empty, stale, error, `401`, `409` và dangerous action có test.
- Node, Python, integration, full/static acceptance, audit, pip check và
  `git diff --check` đều PASS bằng bằng chứng mới.
