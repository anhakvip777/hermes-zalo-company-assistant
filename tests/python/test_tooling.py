from __future__ import annotations

import json
import asyncio
import os
import subprocess
import threading
from pathlib import Path

import pytest
import yaml
from aiohttp.test_utils import TestClient, TestServer

from company_config import CompanyConfig, CompanyConfigError, CompanyConfigFile
from history_store import HistoryStore
from follow_up import FollowUpService
from request_context import Requester, bind_requester
from tooling import ZaloTooling, register_tooling
from admin import (
    ADMIN_APP_JS,
    ADMIN_HTML,
    AdminService,
    AdminSessionSigner,
    AdminWebApp,
    AdminWebSettings,
    AdminWebSettingsError,
    LoginThrottle,
    hash_admin_password,
    verify_admin_password,
)


def config() -> CompanyConfig:
    return CompanyConfig.from_mapping(
        {
            "bridge_url": "http://127.0.0.1:8787",
            "bridge_token": "t" * 32,
            "allowed_users": ["u-1", "admin"],
            "admin_users": ["admin"],
            "allowed_groups": ["g-1"],
            "group_mode": "mention",
        }
    )


def requester(user_id: str, *, admin: bool = False) -> Requester:
    return Requester(
        requester_id=user_id,
        thread_type="dm",
        thread_id=user_id,
        is_admin=admin,
        session_key=f"zalo:dm:{user_id}",
    )


class FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.profile = {"id": "bot", "name": "Trợ lý"}
        self.friends = [
            {"id": "u-1", "name": "Lan"},
            {"id": "admin", "name": "Việt Anh"},
        ]
        self.groups = [{"id": "g-1", "name": "Group AI", "memberCount": 2}]
        self.qr_png = b"\x89PNG\r\n\x1a\n" + b"fake-qr"
        self.available = True

    async def request(self, method: str, path: str, payload=None, params=None):
        self.calls.append((method, path, payload or {}))
        if not self.available:
            return {"error": "bridge unavailable", "outcome": "failed"}
        if path == "/api/methods":
            methods = [{"name": "sendMessage"}, {"name": "createPoll"}]
            if params and params.get("query"):
                methods = [item for item in methods if params["query"].lower() in item["name"].lower()]
            return {"methods": methods}
        if path == "/api/methods/createPoll":
            return {"method": {"name": "createPoll", "parameters": []}}
        if path == "/api/createPoll":
            return {"success": True, "result": {"pollId": "p-1", "token": "hide-me"}}
        if path == "/health":
            return {"ok": True, "loggedIn": True, "ownId": "bot"}
        if path == "/policy":
            return {"mode": "all_operational_methods"}
        if path == "/friends":
            return {"success": True, "result": self.friends}
        if path == "/groups":
            return {"success": True, "result": self.groups}
        if path == "/chat-info":
            if params and params.get("threadType") == "group":
                return {
                    "success": True,
                    "result": {
                        "id": params.get("threadId"),
                        "members": self.friends,
                    },
                }
            return {"success": True, "result": self.profile}
        if path == "/qr":
            return {"status": "authenticated"}
        if path == "/relogin":
            return {"success": True, "status": "pending"}
        return {"success": True}

    async def request_bytes(self, path: str, params=None):
        if path != "/qr.png":
            raise RuntimeError("not found")
        return self.qr_png, "image/png"


async def authenticated_web_client(
    tmp_path: Path,
    *,
    admin: AdminService,
    store: HistoryStore,
    bridge: object,
) -> tuple[TestClient, str, str]:
    settings = AdminWebSettings(
        enabled=True,
        host="127.0.0.1",
        port=8790,
        password_hash=hash_admin_password(
            "mat-khau",
            salt=b"0123456789abcdef",
        ),
        session_secret=b"k" * 32,  # type: ignore[arg-type]
        session_ttl_seconds=3600,
    )
    web_app = AdminWebApp(
        settings=settings,
        admin=admin,
        store=store,
        bridge=bridge,
        export_root=tmp_path / "exports",
    )
    application = web_app.create_application()

    async def cleanup(_application) -> None:
        try:
            await web_app.stop()
        finally:
            store.close()

    application.on_cleanup.append(cleanup)
    client = TestClient(TestServer(application))
    await client.start_server()
    login = await client.post(
        "/admin/api/login",
        json={"password": "mat-khau"},
    )
    assert login.status == 200
    body = await login.json()
    return client, login.headers["Set-Cookie"].split(";", 1)[0], body["csrf"]


def run_admin_javascript(body: str) -> subprocess.CompletedProcess[bytes]:
    definitions = ADMIN_APP_JS.split("// BOOTSTRAP", 1)[0]
    harness = r'''
import assert from "node:assert/strict";
class FakeNode {
  constructor(tag="div", value=undefined) {
    this.tagName=String(tag).toUpperCase();
    this.textContent=value===undefined?"":String(value);
    this.children=[];
    this.listeners={};
    this.attributes={};
    this.dataset={};
    this.classList={add(){},remove(){},contains(){return false;}};
    this.value="";
    this.checked=false;
  }
  append(...items) {
    for (const item of items) {
      const child=typeof item==="string"?new FakeNode("#text",item):item;
      child.parentNode=this;
      this.children.push(child);
    }
  }
  replaceChildren(...items) { this.children=[];this.textContent="";this.append(...items); }
  remove() { if(this.parentNode){this.parentNode.children=this.parentNode.children.filter(child=>child!==this);this.parentNode=null;} }
  addEventListener(name,callback) { (this.listeners[name]??=[]).push(callback); }
  async click() { for (const callback of this.listeners.click??[]) await callback({target:this}); }
  focus() { this.focused=true; }
  removeAttribute(name) { delete this.attributes[name];delete this[name]; }
  setAttribute(name,value) { this.attributes[name]=String(value);this[name]=String(value); }
}
const testNodes={
    "#app":new FakeNode("section"),
    "#login":new FakeNode("form"),
    "#login-screen":new FakeNode("div"),
    "#app-shell":new FakeNode("div"),
    "#nav":new FakeNode("nav"),
    "#login-error":new FakeNode("p"),
    "#route-label":new FakeNode("span"),
    "#theme-toggle":new FakeNode("button"),
    "#login-theme-toggle":new FakeNode("button"),
    "#sidebar-toggle":new FakeNode("button"),
    "#modal-root":new FakeNode("div"),
    "#toast-root":new FakeNode("div"),
};
const documentListeners={};
const storage=new Map();
globalThis.localStorage={
  getItem:key=>storage.has(key)?storage.get(key):null,
  setItem:(key,value)=>storage.set(key,String(value)),
  removeItem:key=>storage.delete(key),
};
globalThis.document={
  createElement:tag=>new FakeNode(tag),
  createTextNode:value=>new FakeNode("#text",value),
  querySelector:selector=>testNodes[selector]??null,
  querySelectorAll:()=>[],
  addEventListener:(name,callback)=>{(documentListeners[name]??=[]).push(callback);},
  removeEventListener:(name,callback)=>{documentListeners[name]=(documentListeners[name]??[]).filter(item=>item!==callback);},
};
document.body=new FakeNode("body");
document.documentElement=new FakeNode("html");
document.documentElement.dataset={};
globalThis.window=globalThis;
window.confirm=()=>true;
window.matchMedia=query=>({matches:query.includes("dark"),addEventListener(){},removeEventListener(){}});
globalThis.location={reload(){}};
URL.createObjectURL=()=>"blob:test";
URL.revokeObjectURL=()=>{};
function nodeText(node) { return (node?.textContent??"")+((node?.children??[]).map(nodeText).join("")); }
function findNodes(node,predicate) {
  const matches=predicate(node)?[node]:[];
  for (const child of node?.children??[]) matches.push(...findNodes(child,predicate));
  return matches;
}
'''
    source = f"{harness}\n{definitions}\nawait (async()=>{{\n{body}\n}})();\n"
    return subprocess.run(
        ["node", "--input-type=module", "-"],
        input=source.encode("utf-8"),
        capture_output=True,
        check=False,
    )


def assert_admin_javascript(body: str) -> None:
    checked = run_admin_javascript(body)
    assert checked.returncode == 0, checked.stderr.decode(
        "utf-8",
        errors="replace",
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


@pytest.mark.asyncio
async def test_admin_web_start_and_stop_serialize_during_site_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    site_starting = asyncio.Event()
    release_site = asyncio.Event()
    runners = []

    class FakeRunner:
        def __init__(self, _application, *, access_log=None):
            self.access_log = access_log
            self.cleaned_up = False
            self.site = None
            runners.append(self)

        async def setup(self):
            return None

        async def cleanup(self):
            self.cleaned_up = True
            if self.site is not None:
                self.site.listening = False

    class FakeSite:
        def __init__(self, runner, _host, _port):
            self.runner = runner
            self.listening = False
            runner.site = self

        async def start(self):
            self.listening = True
            site_starting.set()
            await release_site.wait()

    monkeypatch.setattr("aiohttp.web.AppRunner", FakeRunner)
    monkeypatch.setattr("aiohttp.web.TCPSite", FakeSite)
    store = HistoryStore(tmp_path / "h.sqlite")
    web_app = AdminWebApp(
        settings=AdminWebSettings(
            enabled=True,
            host="127.0.0.1",
            port=8790,
            password_hash=hash_admin_password(
                "mat-khau",
                salt=b"0123456789abcdef",
            ),
            session_secret=b"k" * 32,  # type: ignore[arg-type]
            session_ttl_seconds=3600,
        ),
        admin=AdminService(store=store),
        store=store,
        bridge=None,
        export_root=tmp_path / "exports",
    )
    start_task = asyncio.create_task(web_app.start())
    stop_task = None
    try:
        await asyncio.wait_for(site_starting.wait(), timeout=1)
        stop_task = asyncio.create_task(web_app.stop())
        await asyncio.sleep(0)
        release_site.set()

        assert await asyncio.wait_for(start_task, timeout=1) is True
        await asyncio.wait_for(stop_task, timeout=1)
        assert web_app.is_running is False
        assert runners[0].cleaned_up is True
        assert runners[0].site.listening is False
    finally:
        release_site.set()
        await asyncio.gather(start_task, return_exceptions=True)
        if stop_task is not None:
            await asyncio.gather(stop_task, return_exceptions=True)
        await web_app.stop()


@pytest.mark.asyncio
async def test_admin_login_rechecks_throttle_and_runs_scrypt_off_event_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    web_app = AdminWebApp(
        settings=AdminWebSettings(
            enabled=True,
            host="127.0.0.1",
            port=8790,
            password_hash=hash_admin_password(
                "mat-khau",
                salt=b"0123456789abcdef",
            ),
            session_secret=b"k" * 32,  # type: ignore[arg-type]
            session_ttl_seconds=3600,
        ),
        admin=AdminService(store=store),
        store=store,
        bridge=None,
        export_root=tmp_path / "exports",
    )
    released = asyncio.Event()
    arrivals = 0

    class SlowRequest:
        async def json(self):
            nonlocal arrivals
            arrivals += 1
            if arrivals == 10:
                released.set()
            await released.wait()
            return {"password": "sai"}

    main_thread = threading.get_ident()
    verifier_threads: list[int] = []

    def fake_verify(_password: str, _encoded: str) -> bool:
        verifier_threads.append(threading.get_ident())
        return False

    monkeypatch.setattr("admin.verify_admin_password", fake_verify)
    responses = await asyncio.gather(
        *(web_app._login(SlowRequest()) for _ in range(10))
    )

    assert len(verifier_threads) == 5
    assert all(thread_id != main_thread for thread_id in verifier_threads)
    assert [response.status for response in responses].count(401) == 4
    assert [response.status for response in responses].count(429) == 6


@pytest.mark.asyncio
async def test_admin_web_login_cookie_csrf_logout_and_audit(tmp_path: Path) -> None:
    settings = AdminWebSettings(
        enabled=True,
        host="127.0.0.1",
        port=8790,
        password_hash=hash_admin_password(
            "mat-khau",
            salt=b"0123456789abcdef",
        ),
        session_secret=b"k" * 32,  # type: ignore[arg-type]
        session_ttl_seconds=3600,
    )
    store = HistoryStore(tmp_path / "h.sqlite")
    web_app = AdminWebApp(
        settings=settings,
        admin=AdminService(store=store),
        store=store,
        bridge=None,
        export_root=tmp_path / "exports",
    )
    client = TestClient(TestServer(web_app.create_application()))
    await client.start_server()
    try:
        denied = await client.get("/admin/api/overview")
        assert denied.status == 401

        login = await client.post(
            "/admin/api/login",
            json={"password": "mat-khau"},
        )
        assert login.status == 200
        body = await login.json()
        set_cookie = login.headers["Set-Cookie"]
        assert "HttpOnly" in set_cookie and "Secure" in set_cookie
        assert "SameSite=Strict" in set_cookie
        cookie = set_cookie.split(";", 1)[0]

        session = await client.get(
            "/admin/api/session",
            headers={"Cookie": cookie},
        )
        assert session.status == 200
        assert (await session.json())["csrf"] == body["csrf"]

        rejected = await client.post(
            "/admin/api/logout",
            headers={"Cookie": cookie},
        )
        assert rejected.status == 403
        logout = await client.post(
            "/admin/api/logout",
            headers={"Cookie": cookie, "X-CSRF-Token": body["csrf"]},
        )
        assert logout.status == 200
        tools = [
            row[0]
            for row in store.connection.execute(
                "SELECT tool_name FROM tool_activity ORDER BY id"
            )
        ]
        assert tools == ["admin_web.login", "admin_web.logout"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_html_has_history_filters_and_recovery_polling(
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
        response = await client.get("/admin/")
        html = await response.text()
        assert response.status == 200
        for marker in (
            'href="/admin/assets/admin.css"',
            'src="/admin/assets/app.js"',
        ):
            assert marker in html
        assert "innerHTML" not in html
        script = ADMIN_APP_JS
        checked = subprocess.run(
            ["node", "--check", "-"],
            input=script.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        assert checked.returncode == 0, checked.stderr.decode(
            "utf-8",
            errors="replace",
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_csp_allows_blob_qr_images(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    client, _cookie, _csrf = await authenticated_web_client(
        tmp_path,
        admin=AdminService(store=store),
        store=store,
        bridge=FakeBridge(),
    )
    try:
        response = await client.get("/admin/")
        csp = response.headers["Content-Security-Policy"]
        assert "img-src 'self' blob:" in csp
    finally:
        await client.close()


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
        unknown_body = await unknown.json()
        assert unknown_body["code"] == "not_found"
        assert page.content_type == "text/html"
        assert css.content_type == "text/css"
        assert script.content_type == "application/javascript"
        html = await page.text()
        assert 'href="/admin/assets/admin.css"' in html
        assert 'src="/admin/assets/app.js"' in html
        assert "<style" not in html
        assert "<script>" not in html
        assert page.headers["Cache-Control"] == "no-store"
        assert css.headers["Cache-Control"] == "no-cache"
        assert script.headers["Cache-Control"] == "no-cache"
        assert script.headers["X-Content-Type-Options"] == "nosniff"
        csp = page.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self'" in csp
        assert "img-src 'self' blob:" in csp
        assert "unsafe-inline" not in csp
    finally:
        await client.close()


def test_restart_poll_ends_on_expired_session_but_retries_network_failures() -> None:
    assert_admin_javascript(
        r'''
globalThis.setTimeout=callback=>{callback();return 0;};
const originalDraft={allowed_users:["u-1"],fingerprint:"draft"};
state.csrf="old-csrf";
state.draft=originalDraft;
let attempts=0;
let renderCalls=0;
const loginMessages=[];
showLogin=message=>loginMessages.push(message);
renderSystemEnhanced=async()=>{renderCalls+=1;};
globalThis.fetch=async()=>{
  attempts+=1;
  return {ok:false,status:401,json:async()=>({})};
};

const expired=await pollAfterRestart();

assert.equal(expired,false);
assert.equal(attempts,1);
assert.equal(state.csrf,null);
    assert.equal(state.draft,null);
assert.equal(renderCalls,0);
assert.equal(loginMessages.length,1);
assert.match(loginMessages[0],/hết hạn|đăng nhập/i);
assert.doesNotMatch(nodeText(testNodes["#app"]),/systemctl/i);

attempts=0;
renderCalls=0;
loginMessages.length=0;
state.csrf="stale";
globalThis.fetch=async()=>{
  attempts+=1;
  if(attempts<3)throw new Error("gateway down");
  return {ok:true,status:200,json:async()=>({csrf:"fresh"})};
};

const recovered=await pollAfterRestart();

assert.equal(recovered,true);
assert.equal(attempts,3);
assert.equal(state.csrf,"fresh");
assert.equal(renderCalls,1);
assert.equal(loginMessages.length,0);
'''
    )


def test_admin_web_theme_and_sidebar_preferences_are_versioned_and_isolated() -> None:
    assert_admin_javascript(
        r'''
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
'''
    )


def test_overview_uses_terminal_status_components_without_dynamic_html() -> None:
    assert_admin_javascript(
        r'''
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
'''
    )


def test_access_draft_guard_and_stale_snapshot_are_explicit() -> None:
    assert_admin_javascript(
        r'''
state.draft={allowed_users:["u-1"],admin_users:[],allowed_groups:["g-1"],fingerprint:"fp"};
state.savedAccess={allowed_users:[],admin_users:[],allowed_groups:["g-1"],fingerprint:"fp"};
assert.equal(hasUnsavedAccessChanges(),true);
const event={preventDefault(){this.prevented=true;},returnValue:undefined};
handleBeforeUnload(event);
assert.equal(event.prevented,true);
assert.equal(event.returnValue,"");
const stale=staleNotice({stale:true,error:"bridge unavailable"});
assert.match(nodeText(stale),/Dữ liệu cũ/);
'''
    )


def test_draft_bar_is_rendered_only_after_access_changes() -> None:
    assert_admin_javascript(
        r'''
const host=el("div");
state.draft={allowed_users:["u-1"],admin_users:[],allowed_groups:["g-1"]};
state.savedAccess={allowed_users:["u-1"],admin_users:[],allowed_groups:["g-1"]};
renderDraftBar(host,()=>{},()=>{});
assert.doesNotMatch(nodeText(host),/Có thay đổi chưa áp dụng/);
state.draft.allowed_users.push("u-2");
renderDraftBar(host,()=>{},()=>{});
assert.match(nodeText(host),/Có thay đổi chưa áp dụng/);
'''
    )


def test_access_uses_responsive_tables_and_marks_draft_after_a_toggle() -> None:
    assert_admin_javascript(
        r'''
const response=data=>({ok:true,status:200,json:async()=>data});
globalThis.fetch=async path=>{
  if(path==="/admin/api/access")return response({
    allowed_users:["u-1"],admin_users:[],allowed_groups:["g-1"],fingerprint:"fp",
  });
  if(path==="/admin/api/friends")return response({items:[{id:"u-1",name:"Lan",isFr:true}]});
  if(path==="/admin/api/groups")return response({items:[{id:"g-1",name:"Nhóm AI",memberCount:1}]});
  throw new Error(path);
};
state.view="access";
await renderAccessEnhanced();
assert.ok(findNodes(testNodes["#app"],node=>node.className?.includes("data-table")).length>=2);
assert.doesNotMatch(nodeText(testNodes["#app"]),/Có thay đổi chưa áp dụng/);
const memberInput=findNodes(testNodes["#app"],node=>node.tagName==="INPUT"&&node.type==="checkbox")[0];
memberInput.checked=false;
for(const listener of memberInput.listeners.change||[])listener({target:memberInput});
assert.match(nodeText(testNodes["#app"]),/Có thay đổi chưa áp dụng/);
'''
    )


def test_history_delete_requires_explicit_modal_confirmation() -> None:
    assert_admin_javascript(
        r'''
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
'''
    )


def test_system_restart_waits_for_confirmation_and_shows_pending_state() -> None:
    assert_admin_javascript(
        r'''
let restartCalls=0;
globalThis.fetch=async(path)=>{
  if(path==="/admin/api/system/restart"){restartCalls+=1;return {ok:true,status:202,json:async()=>({accepted:true})};}
  if(path==="/admin/api/session")return {ok:true,status:200,json:async()=>({csrf:"fresh"})};
  throw new Error(path);
};
pollAfterRestart=async()=>true;
const flow=restartConfirmation("gateway");
assert.equal(restartCalls,0);
flow.cancel();
assert.equal(restartCalls,0);
const accepted=restartConfirmation("gateway");
await accepted.confirm();
assert.equal(restartCalls,1);
assert.equal(state.pendingOperation,"restart:gateway");
'''
    )


def test_admin_web_keeps_shell_for_loading_and_redacted_errors() -> None:
    assert_admin_javascript(
        r'''
showLoading("overview");
assert.ok(findNodes(testNodes["#app"],node=>node.className?.includes("skeleton")).length>=1);
const error=Object.assign(new Error("Không thể tải dữ liệu"),{status:500,data:{retryable:false}});
showViewError(error,()=>{});
assert.match(nodeText(testNodes["#app"]),/Không thể tải dữ liệu/);
assert.ok(findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&/Thử lại/.test(node.textContent)).length===1);
assert.equal(testNodes["#app-shell"].classList.contains?.("hidden")??false,false);
'''
    )


def test_expired_session_clears_in_memory_admin_web_state() -> None:
    assert_admin_javascript(
        r'''
state.csrf="csrf";
state.draft={allowed_users:["u-1"]};
state.accessSnapshot={friends:{items:["private"]}};
state.historyFilters={query:"private"};
state.activityFilters={tool_name:"private"};
state.pendingOperation="restart:gateway";
state.qrUrl="blob:secret";
let revoked="";
URL.revokeObjectURL=value=>{revoked=value;};
expireSession();
assert.equal(state.csrf,null);
assert.equal(state.draft,null);
assert.equal(state.accessSnapshot,null);
assert.equal(state.historyFilters,null);
assert.equal(state.activityFilters,null);
assert.equal(state.pendingOperation,null);
assert.equal(state.qrUrl,null);
assert.equal(revoked,"blob:secret");
'''
    )


def test_qr_401_uses_the_same_expired_session_cleanup_path() -> None:
    assert_admin_javascript(
        r'''
state.csrf="csrf";
state.draft={allowed_users:["u-1"]};
state.accessSnapshot={friends:{items:["private"]}};
state.historyFilters={query:"private"};
state.activityFilters={tool_name:"private"};
state.pendingOperation="restart:gateway";
state.qrUrl="blob:private";
let revoked="";
URL.revokeObjectURL=value=>{revoked=value;};
const image=el("img");
state.view="system";
const token=++state.renderVersion;
globalThis.fetch=async()=>({ok:false,status:401});
await loadQrWithRetry(image,[0],token);
assert.equal(state.csrf,null);
assert.equal(state.draft,null);
assert.equal(state.accessSnapshot,null);
assert.equal(state.historyFilters,null);
assert.equal(state.activityFilters,null);
assert.equal(state.pendingOperation,null);
assert.equal(state.qrUrl,null);
assert.equal(revoked,"blob:private");
'''
    )


def test_expired_session_clears_visible_sensitive_controls_and_modal() -> None:
    assert_admin_javascript(
        r'''
state.csrf="csrf";
state.view="access";
state.draft={allowed_users:["u-1"]};
testNodes["#password" ]=el("input");
testNodes["#password"].value="secret";
const modal=el("section");
testNodes["#modal-root"].append(modal);
testNodes["#toast-root"].append(el("div","private toast"));
expireSession();
assert.equal(testNodes["#password"].value,"");
assert.equal(testNodes["#modal-root"].children.length,0);
assert.equal(testNodes["#toast-root"].children.length,0);
assert.equal(state.renderVersion>0,true);
'''
    )


def test_history_export_uses_api_error_path_and_delayed_blob_cleanup() -> None:
    assert_admin_javascript(
        r'''
const response=data=>({ok:true,status:200,json:async()=>data,blob:async()=>({})});
globalThis.fetch=async(path,options)=>{if(path==="/admin/api/history/export")return response({});if(path.startsWith("/admin/api/conversations?"))return response({items:[],next_offset:null});throw new Error(path);};
const originalUrl=URL.createObjectURL;const originalRevoke=URL.revokeObjectURL;let revoked="";
URL.createObjectURL=()=>"blob:export";URL.revokeObjectURL=value=>{revoked=value;};
const originalSetTimeout=globalThis.setTimeout;const timers=[];
globalThis.setTimeout=(callback,delay)=>{timers.push({callback,delay});return timers.length;};
await renderHistoryEnhanced();
const exportButton=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Xuất theo bộ lọc")[0];
assert.ok(exportButton);
await exportButton.click();
const link=findNodes(document.body,node=>node.tagName==="A"&&node.download==="history.jsonl")[0];
assert.ok(link);
assert.equal(revoked,"");
assert.ok(document.body.children.includes(link));
const cleanup=timers.find(timer=>timer.delay>=100&&timer.delay<4000);
assert.ok(cleanup);
cleanup.callback();
assert.equal(revoked,"blob:export");
assert.equal(document.body.children.includes(link),false);
globalThis.setTimeout=originalSetTimeout;URL.createObjectURL=originalUrl;URL.revokeObjectURL=originalRevoke;
'''
    )


def test_run_action_reports_failures_and_expires_on_401() -> None:
    assert_admin_javascript(
        r'''
state.csrf="csrf";
let result=await runAction(async()=>{throw Object.assign(new Error("Phiên hết hạn"),{status:401});},"Không thể xuất");
assert.equal(result,false);
assert.equal(state.csrf,null);
result=await runAction(async()=>{throw new Error("Bridge tạm mất");},"Không thể xuất");
assert.equal(result,false);
assert.match(nodeText(testNodes["#toast-root"]),/Bridge tạm mất/);
'''
    )


def test_qr_mutations_use_vietnamese_error_path_and_expire_on_401() -> None:
    assert_admin_javascript(
        r'''
loadQrWithRetry=async()=>true;
const response=(status,data={})=>({ok:status>=200&&status<300,status,json:async()=>data});
let mutationStatus=500;const calls=[];
globalThis.fetch=async(path,options={})=>{
  calls.push({path,method:options.method||"GET",body:options.body});
  if(path==="/admin/api/system")return response(200,{bot:{},bridge:{},gateway:{},qr:{}});
  if(path==="/admin/api/system/logs?lines=50")return response(200,{lines:[]});
  if(path.startsWith("/admin/api/activity?"))return response(200,{items:[],next_offset:null});
  if(path==="/admin/api/system/qr"||path==="/admin/api/system/reconnect")return response(mutationStatus,{message:"service unavailable"});
  throw new Error(`unexpected fetch ${path}`);
};
state.view="system";state.renderVersion=40;
await renderSystemEnhanced(40);
const create=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Tạo QR mới")[0];
const reconnect=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Reconnect Zalo")[0];
await create.click();
assert.match(nodeText(testNodes["#toast-root"]),/Không thể tạo QR mới/);
testNodes["#toast-root"].replaceChildren();
await reconnect.click();
assert.match(nodeText(testNodes["#toast-root"]),/Không thể kết nối lại Zalo/);
state.csrf="csrf";mutationStatus=401;
await create.click();
assert.equal(state.csrf,null);
assert.deepEqual(calls.filter(call=>call.path==="/admin/api/system/qr"||call.path==="/admin/api/system/reconnect").map(call=>[call.path,call.method,call.body]),[
  ["/admin/api/system/qr","POST","{}"],
  ["/admin/api/system/reconnect","POST","{}"],
  ["/admin/api/system/qr","POST","{}"],
]);
'''
    )


def test_dynamic_admin_controls_have_accessible_names() -> None:
    source = ADMIN_APP_JS
    for marker in (
        'setAttribute("aria-label","Loại hội thoại")',
        'setAttribute("aria-label","Zalo ID người gửi")',
        'setAttribute("aria-label","Từ thời điểm")',
        'setAttribute("aria-label","Đến thời điểm")',
        'setAttribute("aria-label","Từ khóa lịch sử")',
        'setAttribute("aria-label","Thêm Zalo ID vào allowlist")',
        'setAttribute("aria-label","Thêm Group ID vào allowlist")',
    ):
        assert marker in source

    root = Path(__file__).parents[2] / "hermes-plugin" / "admin_web"
    html = (root / "index.html").read_text("utf-8")
    css = (root / "admin.css").read_text("utf-8")
    assert 'id="logout"' in html and 'aria-label="Đăng xuất"' in html
    assert ".sidebar #logout { display: none; }" not in css


def test_admin_web_assets_include_accessibility_and_responsive_contracts() -> None:
    root = Path(__file__).parents[2] / "hermes-plugin" / "admin_web"
    html = (root / "index.html").read_text("utf-8")
    css = (root / "admin.css").read_text("utf-8")
    js = (root / "app.js").read_text("utf-8")
    assert 'aria-label="Điều hướng quản trị"' in html
    assert 'aria-live="assertive"' in html
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "max-width: 620px" in css
    assert "innerHTML" not in js
    assert "unsafe-eval" not in js


def test_confirm_modal_traps_focus_and_restores_the_trigger() -> None:
    assert_admin_javascript(
        r'''
const trigger=el("button","Mở hộp thoại");
document.activeElement=trigger;
const modal=confirmModal({title:"Xóa",message:"Không thể hoàn tác",confirmLabel:"Xóa",tone:"danger"});
const [cancel,confirm]=findNodes(modal.dialog,node=>node.tagName==="BUTTON");
assert.equal(cancel.focused,true);
let prevented=false;
const shiftTab={key:"Tab",shiftKey:true,target:cancel,preventDefault(){prevented=true;}};
for(const listener of documentListeners.keydown||[])listener(shiftTab);
assert.equal(prevented,true);
assert.equal(confirm.focused,true);
prevented=false;
const tab={key:"Tab",shiftKey:false,target:confirm,preventDefault(){prevented=true;}};
for(const listener of documentListeners.keydown||[])listener(tab);
assert.equal(prevented,true);
assert.equal(cancel.focused,true);
modal.cancel();
assert.equal(trigger.focused,true);
'''
    )


def test_admin_web_uses_labeled_local_icons_for_navigation_and_theme() -> None:
    root = Path(__file__).parents[2] / "hermes-plugin" / "admin_web"
    html = (root / "index.html").read_text("utf-8")
    css = (root / "admin.css").read_text("utf-8")
    assert 'class="nav-icon" aria-hidden="true"' in html
    assert 'class="nav-label"' in html
    assert 'class="theme-icon" aria-hidden="true"' in html
    assert '.nav-icon' in css
    assert '.nav-label' in css
    assert '::first-letter' not in css


def test_history_messages_have_distinct_bubbles_and_recalled_badge() -> None:
    assert_admin_javascript(
        r'''
const response=data=>({ok:true,status:200,json:async()=>data});
globalThis.fetch=async path=>{
  if(path.startsWith("/admin/api/conversations/"))return response({items:[
    {sender_id:"u-1",sender_name:"Lan",text:"Xin chào",sent_at:"2026-01-01T00:00:00Z",is_bot:0,mentioned_bot:0,recalled_at:"2026-01-01T00:01:00Z",attachments:[]},
    {sender_id:"bot",sender_name:"Hermes",text:"Chào bạn",sent_at:"2026-01-01T00:02:00Z",is_bot:1,mentioned_bot:1,attachments:[]},
  ],next_offset:null});
  if(path.startsWith("/admin/api/activity"))return response({items:[]});
  throw new Error(path);
};
const host=el("section");
await renderConversationEnhanced(host,{id:1,thread_type:"dm",thread_id:"u-1"});
assert.equal(findNodes(host,node=>node.className?.includes("message-bubble")).length,2);
assert.equal(findNodes(host,node=>node.className?.includes("message-user")).length,1);
assert.equal(findNodes(host,node=>node.className?.includes("message-bot")).length,1);
assert.match(nodeText(host),/Đã thu hồi/);
assert.match(nodeText(host),/Mention bot/);
'''
    )


def test_history_keeps_message_search_and_mobile_back_action() -> None:
    assert_admin_javascript(
        r'''
const calls=[];
const response=data=>({ok:true,status:200,json:async()=>data});
globalThis.fetch=async path=>{
  calls.push(path);
  if(path.startsWith("/admin/api/conversations?"))return response({items:[{id:7,title:"Nhóm AI",thread_type:"group",thread_id:"g-1",message_count:1,last_message_at:"t"}],next_offset:null});
  if(path.startsWith("/admin/api/history/search?"))return response({items:[{sender_id:"u-1",sender_name:"Lan",text:"lịch họp"}]});
  if(path.startsWith("/admin/api/conversations/7?"))return response({items:[],next_offset:null});
  if(path.startsWith("/admin/api/activity?"))return response({items:[]});
  throw new Error(path);
};
await renderHistoryEnhanced();
const search=button("Tìm tin nhắn",async()=>{const result=await api(`/admin/api/history/search?query=${encodeURIComponent("lịch họp")}`);const output=card("Kết quả tin nhắn");for(const message of result.items||[])output.append(row(`${message.sender_name??message.sender_id} (${message.sender_id})`,message.text));testNodes["#app"].append(output);});
testNodes["#app"].append(search);
await search.click();
assert.ok(calls.some(path=>path.startsWith("/admin/api/history/search?query=")));
const open=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Mở hội thoại")[0];
await open.click();
assert.ok(findNodes(testNodes["#app"],node=>node.textContent==="Quay lại danh sách").length===1);
'''
    )


def test_system_uses_mini_terminal_sections() -> None:
    assert_admin_javascript(
        r'''
loadQrWithRetry=async()=>true;
const response=data=>({ok:true,status:200,json:async()=>data});
globalThis.fetch=async path=>{
  if(path==="/admin/api/system")return response({bot:{},bridge:{},gateway:{},qr:{}});
  if(path==="/admin/api/system/logs?lines=50")return response({lines:[]});
  if(path.startsWith("/admin/api/activity?"))return response({items:[],next_offset:null});
  throw new Error(path);
};
await renderSystemEnhanced();
assert.ok(findNodes(testNodes["#app"],node=>node.className?.includes("mini-terminal")).length>=3);
'''
    )


def test_admin_web_mobile_navigation_resets_desktop_sidebar_rules() -> None:
    css = (
        Path(__file__).parents[2]
        / "hermes-plugin"
        / "admin_web"
        / "admin.css"
    ).read_text("utf-8")
    mobile = css.split("@media (max-width: 620px)", 1)[1]
    assert "top: auto;" in mobile
    assert "color: var(--text) !important;" in mobile


def test_access_conflict_keeps_draft_until_reload_fetches_current_snapshot() -> None:
    assert_admin_javascript(
        r'''
const originalDraft={
  allowed_users:["u-1","draft-user"],
  admin_users:["u-1"],
  allowed_groups:["g-1"],
  fingerprint:"draft-fingerprint",
};
state.draft=originalDraft;
let accessReads=0;
let applyCalls=0;
const response=(status,data)=>({
  ok:status>=200&&status<300,
  status,
  json:async()=>data,
});
globalThis.fetch=async(path,options={})=>{
  if(path==="/admin/api/access"&&(!options.method||options.method==="GET")){
    accessReads+=1;
    const fingerprint=accessReads===1?"server-before":"server-fresh";
    return response(200,{
      allowed_users:["u-1"],admin_users:["u-1"],allowed_groups:["g-1"],fingerprint,
    });
  }
  if(path==="/admin/api/friends")return response(200,{items:[]});
  if(path==="/admin/api/groups")return response(200,{items:[]});
  if(path==="/admin/api/access/apply"){
    applyCalls+=1;
    return response(409,{message:"Cấu hình đã thay đổi trên máy chủ"});
  }
  throw new Error(`unexpected fetch ${path}`);
};

await renderAccessEnhanced();
const save=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Lưu và áp dụng")[0];
await save.click();

assert.equal(applyCalls,1);
assert.equal(accessReads,1);
assert.equal(state.draft,originalDraft);
assert.match(nodeText(testNodes["#app"]),/Cấu hình đã thay đổi/i);
const reload=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Tải lại cấu hình")[0];
assert.ok(reload);

await reload.click();

assert.equal(accessReads,2);
assert.notEqual(state.draft,originalDraft);
assert.equal(state.draft.fingerprint,"server-fresh");
assert.deepEqual(state.draft.allowed_users,["u-1"]);
'''
    )


def test_overview_shows_runtime_status_and_opens_qr_without_mutation() -> None:
    assert_admin_javascript(
        r'''
const calls=[];
const response=(data)=>({ok:true,status:200,json:async()=>data});
globalThis.fetch=async(path,options={})=>{
  calls.push({path,method:options.method||"GET"});
  if(path==="/admin/api/overview")return response({
    bot:{id:"bot-1",name:"Trợ lý công ty"},
    bridge:{ok:true,loggedIn:true},
    connected:true,
    adapter_active:true,
    provider:"openai-compatible",
    model:"gpt-5.6",
    counts:{},history:{},recent_activity:[],
  });
  throw new Error(`unexpected fetch ${path}`);
};
let systemRenders=0;
renderSystemEnhanced=async()=>{systemRenders+=1;};

await renderOverviewEnhanced();

const rendered=nodeText(testNodes["#app"]);
assert.match(rendered,/Bridge:/);
assert.match(rendered,/Hermes Gateway:/);
assert.match(rendered,/Provider: openai-compatible/);
assert.match(rendered,/Model: gpt-5\.6/);
const openQr=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Mở QR")[0];
assert.ok(openQr);
const openSystem=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Mở hệ thống")[0];
assert.ok(openSystem);

await openQr.click();

assert.equal(state.view,"system");
assert.equal(systemRenders,1);
assert.equal(calls.filter(call=>call.method==="POST").length,0);
assert.equal(calls.some(call=>/relogin|\/system\/qr$/.test(call.path)),false);
'''
    )


def test_system_shows_bot_filters_activity_and_copies_redacted_bridge_error() -> None:
    assert_admin_javascript(
        r'''
const calls=[];
const copied=[];
Object.defineProperty(globalThis,"navigator",{
  configurable:true,
  value:{clipboard:{writeText:async value=>{copied.push(value);}}},
});
loadQrWithRetry=async()=>true;
const response=data=>({ok:true,status:200,json:async()=>data});
globalThis.fetch=async(path,options={})=>{
  calls.push({path,method:options.method||"GET"});
  if(path==="/admin/api/system")return response({
    bot:{id:"bot-1",name:"Trợ lý công ty"},
    bridge:{ok:false,error:"bridge [REDACTED]",lastError:"raw-not-for-copy"},
    gateway:{status:"Hoạt động"},
    provider:"provider-a",model:"model-a",qr:{status:"pending"},
  });
  if(path==="/admin/api/system/logs?lines=50")return response({lines:[]});
  if(path.startsWith("/admin/api/activity?"))return response({items:[],next_offset:null});
  throw new Error(`unexpected fetch ${path}`);
};

await renderSystemEnhanced();

const rendered=nodeText(testNodes["#app"]);
assert.match(rendered,/Họ tên: Trợ lý công ty/);
assert.match(rendered,/Zalo ID: bot-1/);
assert.match(rendered,/Hermes Gateway: Hoạt động/);
const filterNames=["requester_id","tool_name","status","thread_type","thread_id","since","until"];
const values={
  requester_id:"web-admin",
  tool_name:"admin_web.restart",
  status:"failed",
  thread_type:"system",
  thread_id:"admin-web",
  since:"2026-08-10T00:00:00Z",
  until:"2026-08-11T00:00:00Z",
};
for(const name of filterNames){
  const input=findNodes(testNodes["#app"],node=>node.name===name)[0];
  assert.ok(input,`missing ${name}`);
  input.value=values[name];
}
const apply=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Lọc hoạt động")[0];
assert.ok(apply);
await apply.click();
const activityCalls=calls.filter(call=>call.path.startsWith("/admin/api/activity?"));
assert.equal(activityCalls.length,2);
const query=new URL(activityCalls.at(-1).path,"http://admin.local").searchParams;
for(const name of filterNames)assert.equal(query.get(name),values[name]);
assert.equal(query.get("limit"),"50");
assert.equal(query.get("offset"),"0");

const copy=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Sao chép lỗi")[0];
assert.ok(copy);
await copy.click();
assert.deepEqual(copied,["bridge [REDACTED]"]);
assert.equal(copied[0].includes("raw-not-for-copy"),false);
'''
    )


def test_system_activity_ignores_stale_filter_response() -> None:
    assert_admin_javascript(
        r'''
const response=data=>({ok:true,status:200,json:async()=>data});
loadQrWithRetry=async()=>true;
let activityCalls=0;
const gates=[];
globalThis.fetch=async path=>{
  if(path==="/admin/api/system")return response({
    bot:{id:"bot-1",name:"Hermes"},
    bridge:{ok:true,loggedIn:true},
    provider:"provider-a",model:"model-a",qr:{status:"pending"},
  });
  if(path==="/admin/api/system/logs?lines=50")return response({lines:[]});
  if(path.startsWith("/admin/api/activity?")){
    activityCalls+=1;
    return new Promise(resolve=>gates.push(resolve));
  }
  throw new Error(`unexpected fetch ${path}`);
};

const initialRender=renderSystemEnhanced();
while(activityCalls<1)await Promise.resolve();
const toolInput=findNodes(testNodes["#app"],node=>node.name==="tool_name")[0];
assert.ok(toolInput);
toolInput.value="new-filter";
const filter=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent.includes("ho"))[0];
assert.ok(filter);
const filteredRender=filter.click();
while(activityCalls<2)await Promise.resolve();
gates[1](response({items:[{occurred_at:"new",tool_name:"new-activity",status:"success"}],next_offset:null}));
await filteredRender;
assert.match(nodeText(testNodes["#app"]),/new-activity/);

gates[0](response({items:[{occurred_at:"old",tool_name:"old-activity",status:"success"}],next_offset:null}));
await initialRender;
const rendered=nodeText(testNodes["#app"]);
assert.match(rendered,/new-activity/);
assert.doesNotMatch(rendered,/old-activity/);
'''
    )


def test_admin_web_pages_show_loading_and_empty_states() -> None:
    assert_admin_javascript(
        r'''
const response=data=>({ok:true,status:200,json:async()=>data});
let releaseOverview;
globalThis.fetch=async path=>{
  if(path==="/admin/api/overview")return await new Promise(resolve=>{
    releaseOverview=()=>resolve(response({
      bot:{},bridge:{},counts:{},history:{},recent_activity:[],
    }));
  });
  throw new Error(`unexpected fetch ${path}`);
};

state.view="overview";
const pending=renderCurrent();
await Promise.resolve();
assert.match(nodeText(testNodes["#app"]),/Đang tải/);
releaseOverview();
await pending;
assert.match(nodeText(testNodes["#app"]),/Chưa có hoạt động gần đây/);

state.draft=null;
globalThis.fetch=async path=>{
  if(path==="/admin/api/access")return response({
    allowed_users:[],admin_users:[],allowed_groups:[],fingerprint:"fp",
  });
  if(path==="/admin/api/friends"||path==="/admin/api/groups")return response({items:[]});
  throw new Error(`unexpected fetch ${path}`);
};
await renderAccessEnhanced();
let rendered=nodeText(testNodes["#app"]);
assert.match(rendered,/Không có cá nhân nào/);
assert.match(rendered,/Không có nhóm nào/);

globalThis.fetch=async path=>{
  if(path.startsWith("/admin/api/conversations?"))return response({items:[],next_offset:null});
  throw new Error(`unexpected fetch ${path}`);
};
await renderHistoryEnhanced();
assert.match(nodeText(testNodes["#app"]),/Chưa có hội thoại phù hợp/);

loadQrWithRetry=async()=>true;
globalThis.fetch=async path=>{
  if(path==="/admin/api/system")return response({bot:{},bridge:{},gateway:{},qr:{}});
  if(path==="/admin/api/system/logs?lines=50")return response({lines:[]});
  if(path.startsWith("/admin/api/activity?"))return response({items:[],next_offset:null});
  throw new Error(`unexpected fetch ${path}`);
};
await renderSystemEnhanced();
rendered=nodeText(testNodes["#app"]);
assert.match(rendered,/Chưa có log/);
assert.match(rendered,/Chưa có hoạt động/);
'''
    )


def test_system_activity_pagination_uses_next_offset() -> None:
    assert_admin_javascript(
        r'''
loadQrWithRetry=async()=>true;
const response=data=>({ok:true,status:200,json:async()=>data});
const offsets=[];
globalThis.fetch=async path=>{
  if(path==="/admin/api/system")return response({bot:{},bridge:{},gateway:{},qr:{}});
  if(path==="/admin/api/system/logs?lines=50")return response({lines:[]});
  if(path.startsWith("/admin/api/activity?")){
    const offset=Number(new URL(path,"http://admin.local").searchParams.get("offset"));
    offsets.push(offset);
    return response(offset===0
      ?{items:[{occurred_at:"t1",tool_name:"tool-1",status:"success"}],next_offset:50}
      :{items:[{occurred_at:"t2",tool_name:"tool-2",status:"failed"}],next_offset:null});
  }
  throw new Error(`unexpected fetch ${path}`);
};

await renderSystemEnhanced();
const next=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Trang sau hoạt động")[0];
assert.ok(next);
await next.click();
assert.deepEqual(offsets,[0,50]);
assert.match(nodeText(testNodes["#app"]),/tool-2/);

const previous=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Trang trước hoạt động")[0];
assert.ok(previous);
await previous.click();
assert.deepEqual(offsets,[0,50,0]);
'''
    )


def test_system_copies_redacted_last_error_fallbacks() -> None:
    assert_admin_javascript(
        r'''
const copied=[];
Object.defineProperty(globalThis,"navigator",{
  configurable:true,
  value:{clipboard:{writeText:async value=>{copied.push(value);}}},
});
loadQrWithRetry=async()=>true;
const response=data=>({ok:true,status:200,json:async()=>data});
let systemData;
globalThis.fetch=async path=>{
  if(path==="/admin/api/system")return response(systemData);
  if(path==="/admin/api/system/logs?lines=50")return response({lines:[]});
  if(path.startsWith("/admin/api/activity?"))return response({items:[],next_offset:null});
  throw new Error(`unexpected fetch ${path}`);
};

for(const [data,expected] of [
  [{bridge:{ok:false,lastError:"nested [REDACTED]"}},"nested [REDACTED]"],
  [{bridge:{ok:false},bridge_error:"top-level [REDACTED]"},"top-level [REDACTED]"],
]){
  systemData=data;
  copied.length=0;
  await renderSystemEnhanced();
  assert.match(nodeText(testNodes["#app"]),new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")));
  const copy=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Sao chép lỗi")[0];
  assert.ok(copy);
  await copy.click();
  assert.deepEqual(copied,[expected]);
}
'''
    )


def test_access_displays_friend_status_from_supported_zca_shapes() -> None:
    assert_admin_javascript(
        r'''
const response=data=>({ok:true,status:200,json:async()=>data});
globalThis.fetch=async path=>{
  if(path==="/admin/api/access")return response({
    allowed_users:["u-1"],admin_users:["u-1"],allowed_groups:["g-1"],fingerprint:"fp",
  });
  if(path==="/admin/api/friends")return response({items:[
    {id:"u-1",name:"Lan",friendStatus:"Đã kết bạn"},
    {id:"u-2",name:"Minh",isFr:true},
    {id:"u-3",name:"An",accountStatus:"Tài khoản hạn chế"},
  ]});
  if(path==="/admin/api/groups")return response({items:[]});
  throw new Error(`unexpected fetch ${path}`);
};

await renderAccessEnhanced();

assert.equal(typeof friendStatus,"function");
const rendered=nodeText(testNodes["#app"]);
assert.match(rendered,/Lan \(u-1\).*Đã kết bạn/);
assert.match(rendered,/Minh \(u-2\).*Bạn bè/);
assert.match(rendered,/An \(u-3\).*Tài khoản hạn chế/);
'''
    )


def test_enhanced_render_ignores_stale_response_and_reports_unknown_gateway() -> None:
    assert_admin_javascript(
        r'''
let releaseOverview;
const response=data=>({ok:true,status:200,json:async()=>data});
globalThis.fetch=async path=>{
  if(path!=="/admin/api/overview")throw new Error(`unexpected fetch ${path}`);
  return await new Promise(resolve=>{releaseOverview=()=>resolve(response({
    bot:{id:"bot-stale",name:"Stale"},bridge:{},counts:{},history:{},recent_activity:[],
  }));});
};

state.view="overview";
const pending=renderOverviewEnhanced();
state.view="access";
state.renderVersion=(state.renderVersion||0)+1;
clearApp("Màn hình hiện tại");
releaseOverview();
await pending;
assert.equal(nodeText(testNodes["#app"]),"Màn hình hiện tại");

globalThis.fetch=async()=>response({
  bot:{id:"bot-1",name:"Trợ lý"},bridge:{},counts:{},history:{},recent_activity:[],
});
await renderOverviewEnhanced();
const rendered=nodeText(testNodes["#app"]);
assert.match(rendered,/Hermes Gateway: Không rõ/);
assert.doesNotMatch(rendered,/Hermes Gateway: Đang hoạt động/);
'''
    )


def test_restart_poll_is_target_aware_for_bridge() -> None:
    assert_admin_javascript(
        r'''
globalThis.setTimeout=callback=>{callback();return 0;};
const response=(status,data)=>({ok:status>=200&&status<300,status,json:async()=>data});
let systemCalls=0;
let sessionCalls=0;
let renders=0;
renderSystemEnhanced=async()=>{renders+=1;};
globalThis.fetch=async path=>{
  if(path==="/admin/api/session"){sessionCalls+=1;return response(200,{csrf:"wrong"});}
  if(path==="/admin/api/system"){
    systemCalls+=1;
    return response(200,{bridge:systemCalls<3?{ok:false,error:"down"}:{ok:true}});
  }
  throw new Error(`unexpected fetch ${path}`);
};

const recovered=await pollAfterRestart("bridge");
assert.equal(recovered,true);
assert.equal(systemCalls,3);
assert.equal(sessionCalls,0);
assert.equal(renders,1);
'''
    )


def test_access_keeps_unlisted_ids_visible_and_never_hides_401_with_cache() -> None:
    assert_admin_javascript(
        r'''
const response=(status,data)=>({ok:status>=200&&status<300,status,json:async()=>data});
let contactStatus=200;
globalThis.fetch=async path=>{
  if(path==="/admin/api/access")return response(200,{
    allowed_users:["u-hidden"],admin_users:["u-hidden"],
    allowed_groups:["g-hidden"],fingerprint:"fp",
  });
  if(path==="/admin/api/friends")return response(contactStatus,
    contactStatus===200?{items:[]}:{message:"Phiên hết hạn"});
  if(path==="/admin/api/groups")return response(200,{items:[]});
  throw new Error(`unexpected fetch ${path}`);
};

await renderAccessEnhanced();
const rendered=nodeText(testNodes["#app"]);
assert.match(rendered,/u-hidden/);
assert.match(rendered,/g-hidden/);

contactStatus=401;
let caught;
try{await renderAccessEnhanced();}catch(error){caught=error;}
assert.equal(caught?.status,401);
'''
    )


def test_group_members_replace_previous_list_and_remove_admin_with_member() -> None:
    assert_admin_javascript(
        r'''
const response=data=>({ok:true,status:200,json:async()=>data});
globalThis.fetch=async path=>{
  if(path==="/admin/api/access")return response({
    allowed_users:["u-1"],admin_users:["u-1"],allowed_groups:["g-1"],fingerprint:"fp",
  });
  if(path==="/admin/api/friends")return response({items:[]});
  if(path==="/admin/api/groups")return response({items:[{id:"g-1",name:"Group AI",memberCount:1}]});
  if(path==="/admin/api/groups/g-1/members")return response({items:[{id:"u-1",name:"Lan"}]});
  throw new Error(`unexpected fetch ${path}`);
};

await renderAccessEnhanced();
const show=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Xem thành viên")[0];
await show.click();
await show.click();
assert.equal(findNodes(testNodes["#app"],node=>node.tagName==="UL").length,1);
const allowedLabel=findNodes(testNodes["#app"],node=>node.tagName==="LABEL"&&/Được phép/.test(nodeText(node)))[0];
const input=findNodes(allowedLabel,node=>node.tagName==="INPUT")[0];
input.checked=false;
for(const callback of input.listeners.change||[])await callback({target:input});
assert.deepEqual(state.draft.allowed_users,[]);
assert.deepEqual(state.draft.admin_users,[]);
'''
    )


def test_access_save_locks_controls_while_request_is_in_flight() -> None:
    assert_admin_javascript(
        r'''
const response=(status,data)=>({ok:status>=200&&status<300,status,json:async()=>data});
let releaseApply;
globalThis.fetch=async path=>{
  if(path==="/admin/api/access")return response(200,{
    allowed_users:["u-1"],admin_users:["u-1"],allowed_groups:["g-1"],fingerprint:"fp",
  });
  if(path==="/admin/api/friends")return response(200,{items:[{id:"u-1",name:"Lan"}]});
  if(path==="/admin/api/groups")return response(200,{items:[{id:"g-1",name:"Group AI"}]});
  if(path==="/admin/api/access/apply")return await new Promise(resolve=>{
    releaseApply=()=>resolve(response(409,{message:"conflict"}));
  });
  throw new Error(`unexpected fetch ${path}`);
};

await renderAccessEnhanced();
const save=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Lưu và áp dụng")[0];
const pending=save.click();
await Promise.resolve();
assert.equal(save.disabled,true);
releaseApply();
await pending;
assert.equal(save.disabled,false);
'''
    )


def test_history_render_ignores_late_page_after_navigation() -> None:
    assert_admin_javascript(
        r'''
let releasePage;
const response=data=>({ok:true,status:200,json:async()=>data});
globalThis.fetch=async path=>{
  if(path.startsWith("/admin/api/conversations?"))return await new Promise(resolve=>{
    releasePage=()=>resolve(response({items:[{id:1,thread_id:"stale-group",thread_type:"group"}],next_offset:null}));
  });
  throw new Error(`unexpected fetch ${path}`);
};

state.view="history";
const pending=renderHistoryEnhanced();
state.view="overview";
state.renderVersion=(state.renderVersion||0)+1;
clearApp("Tổng quan mới");
releasePage();
await pending;
assert.equal(nodeText(testNodes["#app"]),"Tổng quan mới");
'''
    )


def test_conversation_detail_ignores_late_selection_and_expired_session() -> None:
    assert_admin_javascript(
        r'''
let releaseA,releaseB,releaseExpired;
const response=data=>({ok:true,status:200,json:async()=>data});
globalThis.fetch=async path=>{
  if(path.startsWith("/admin/api/conversations/a?"))return await new Promise(resolve=>{releaseA=()=>resolve(response({items:[{sender_id:"old",text:"stale-message"}],next_offset:null}));});
  if(path.startsWith("/admin/api/conversations/b?"))return await new Promise(resolve=>{releaseB=()=>resolve(response({items:[{sender_id:"new",text:"current-message"}],next_offset:null}));});
  if(path.startsWith("/admin/api/conversations/expired?"))return await new Promise(resolve=>{releaseExpired=()=>resolve(response({items:[{sender_id:"late",text:"expired-message"}],next_offset:null}));});
  if(path.startsWith("/admin/api/activity?"))return response({items:[]});
  throw new Error(`unexpected fetch ${path}`);
};
const detail=el("section");
state.view="history";state.renderVersion=60;
const first=renderConversationEnhanced(detail,{id:"a",thread_type:"group",thread_id:"g-a"},0,undefined,60);
await Promise.resolve();
const second=renderConversationEnhanced(detail,{id:"b",thread_type:"group",thread_id:"g-b"},0,undefined,60);
await Promise.resolve();
releaseB();await second;
assert.match(nodeText(detail),/current-message/);
releaseA();await first;
assert.match(nodeText(detail),/current-message/);
assert.doesNotMatch(nodeText(detail),/stale-message/);
const expired=renderConversationEnhanced(detail,{id:"expired",thread_type:"group",thread_id:"g-expired"},0,undefined,60);
await Promise.resolve();
expireSession();releaseExpired();await expired;
assert.doesNotMatch(nodeText(detail),/expired-message/);
'''
    )


def test_group_member_request_ignores_late_refresh_and_expired_session() -> None:
    assert_admin_javascript(
        r'''
let releaseFirst,releaseSecond,releaseExpired;
const response=data=>({ok:true,status:200,json:async()=>data});
let groupRequests=0;
globalThis.fetch=async path=>{
  if(path==="/admin/api/access")return response({allowed_users:[],admin_users:[],allowed_groups:[],fingerprint:"fp"});
  if(path==="/admin/api/friends")return response({items:[]});
  if(path==="/admin/api/groups")return response({items:[{id:"g-a",name:"A"},{id:"g-expired",name:"Expired"}]});
  if(path==="/admin/api/groups/g-a/members")return await new Promise(resolve=>{
    groupRequests+=1;
    if(groupRequests===1)releaseFirst=()=>resolve(response({items:[{id:"old-member",name:"Stale member"}]}));
    else releaseSecond=()=>resolve(response({items:[{id:"new-member",name:"Current member"}]}));
  });
  if(path==="/admin/api/groups/g-expired/members")return await new Promise(resolve=>{releaseExpired=()=>resolve(response({items:[{id:"expired-member",name:"Expired member"}]}));});
  throw new Error(`unexpected fetch ${path}`);
};
await renderAccessEnhanced();
const buttons=findNodes(testNodes["#app"],node=>node.tagName==="BUTTON"&&node.textContent==="Xem thành viên");
const first=buttons[0].click();await Promise.resolve();
const second=buttons[0].click();await Promise.resolve();
releaseSecond();await second;
assert.match(nodeText(testNodes["#app"]),/Current member/);
releaseFirst();await first;
assert.doesNotMatch(nodeText(testNodes["#app"]),/Stale member/);
const expired=buttons[1].click();await Promise.resolve();
expireSession();releaseExpired();await expired;
assert.doesNotMatch(nodeText(testNodes["#app"]),/Expired member/);
'''
    )


def test_stale_qr_request_cannot_replace_current_image_url() -> None:
    assert_admin_javascript(
        r'''
let releaseQr;
const revoked=[];
URL.createObjectURL=()=>"blob:stale";
URL.revokeObjectURL=value=>revoked.push(value);
globalThis.fetch=async()=>await new Promise(resolve=>{releaseQr=()=>resolve({
  ok:true,status:200,blob:async()=>({}),
});});
const image=document.createElement("img");
state.view="system";state.renderVersion=10;state.qrUrl="blob:current";
const pending=loadQrWithRetry(image,[0],10);
state.renderVersion=11;
releaseQr();
assert.equal(await pending,false);
assert.equal(image.src,undefined);
assert.equal(state.qrUrl,"blob:current");
assert.deepEqual(revoked,["blob:stale"]);
'''
    )


@pytest.mark.asyncio
async def test_admin_web_overview_includes_latest_message_and_recent_activity(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="latest",
        provider_message_id="overview-latest",
        sent_at="2026-08-10T10:00:00Z",
    )
    store.log_tool_activity(
        requester_id="web-admin",
        thread_type="system",
        thread_id="admin-web",
        tool_name="admin_web.test",
        status="success",
        occurred_at="2026-08-10T10:01:00Z",
    )
    client, cookie, _csrf = await authenticated_web_client(
        tmp_path,
        admin=AdminService(store=store),
        store=store,
        bridge=FakeBridge(),
    )
    try:
        response = await client.get(
            "/admin/api/overview",
            headers={"Cookie": cookie},
        )
        body = await response.json()
        assert body["latest_message_at"] == "2026-08-10T10:00:00Z"
        assert any(
            item["tool_name"] == "admin_web.test"
            for item in body["recent_activity"]
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_access_transaction_applies_once_and_rolls_back(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "gateway": {
                    "platforms": {"zalo": {"extra": config().to_mapping()}}
                }
            },
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
        config_file=config_file,
        store=HistoryStore(tmp_path / "h.sqlite"),
        runtime_config_provider=runtime_provider,
        runtime_config_applier=runtime_applier,
    )
    snapshot = admin.get_access_config(requester=requester("admin", admin=True))

    result = await admin.apply_access_config(
        allowed_users=["admin", "u-1", "u-2"],
        admin_users=["admin"],
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
        config_file=config_file,
        store=HistoryStore(tmp_path / "failure.sqlite"),
        runtime_config_provider=lambda: runtime[-1],
        runtime_config_applier=fail_then_restore,
    )
    with pytest.raises(RuntimeError, match="runtime apply failed"):
        await failing.apply_access_config(
            allowed_users=["admin", "u-1"],
            admin_users=["admin"],
            allowed_groups=["g-1"],
            expected_fingerprint=before.fingerprint,
            requester=requester("admin", admin=True),
        )
    assert config_file.read_access_config().fingerprint == before.fingerprint
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_admin_access_transaction_preserves_all_runtime_overrides(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "gateway": {
                    "platforms": {"zalo": {"extra": config().to_mapping()}}
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    runtime_before = CompanyConfig.from_mapping(
        {
            **config().to_mapping(),
            "bridge_url": "http://127.0.0.1:9876",
            "bridge_token": "r" * 32,
            "history_context_messages": 73,
            "media_max_bytes": 654321,
        }
    )
    applied: list[CompanyConfig] = []
    admin = AdminService(
        config_file=CompanyConfigFile(path),
        store=HistoryStore(tmp_path / "h.sqlite"),
        runtime_config_provider=lambda: runtime_before,
        runtime_config_applier=applied.append,
    )
    snapshot = admin.get_access_config(requester=requester("admin", admin=True))

    await admin.apply_access_config(
        allowed_users=["admin", "u-2"],
        admin_users=["admin", "u-2"],
        allowed_groups=["g-2"],
        expected_fingerprint=snapshot["fingerprint"],
        requester=requester("admin", admin=True),
    )

    assert applied == [
        CompanyConfig.from_mapping(
            {
                **runtime_before.to_mapping(include_secret=True),
                "allowed_users": ["admin", "u-2"],
                "admin_users": ["admin", "u-2"],
                "allowed_groups": ["g-2"],
            }
        )
    ]


@pytest.mark.asyncio
async def test_admin_web_access_apply_maps_conflict_and_audits(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "gateway": {
                    "platforms": {"zalo": {"extra": config().to_mapping()}}
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    store = HistoryStore(tmp_path / "h.sqlite")
    runtime = [config()]
    admin = AdminService(
        config_file=CompanyConfigFile(path),
        store=store,
        status_provider=lambda: {
            "success": True,
            "connected": True,
            "bot": {"id": "bot", "name": "Trợ lý"},
        },
        runtime_config_provider=lambda: runtime[-1],
        runtime_config_applier=runtime.append,
    )
    client, cookie, csrf = await authenticated_web_client(
        tmp_path,
        admin=admin,
        store=store,
        bridge=FakeBridge(),
    )
    try:
        access = await client.get(
            "/admin/api/access",
            headers={"Cookie": cookie},
        )
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
        applied_body = await applied.json()
        assert runtime[-1].allowed_groups == frozenset({"g-1", "g-2"})
        invalid = await client.post(
            "/admin/api/access/apply",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={
                "allowed_users": [],
                "admin_users": ["admin"],
                "allowed_groups": ["g-1"],
                "fingerprint": applied_body["fingerprint"],
            },
        )
        assert invalid.status == 400
        assert await invalid.json() == {
            "code": "invalid_config",
            "message": "Danh sách thành viên được phép không được để trống",
            "retryable": False,
        }
        invalid_subset = await client.post(
            "/admin/api/access/apply",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={
                "allowed_users": ["admin"],
                "admin_users": ["outside"],
                "allowed_groups": ["g-1"],
                "fingerprint": applied_body["fingerprint"],
            },
        )
        assert invalid_subset.status == 400
        assert (await invalid_subset.json())["message"] == (
            "Mọi quản trị viên phải đồng thời là thành viên được phép"
        )
        conflict = await client.post(
            "/admin/api/access/apply",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={**snapshot, "allowed_groups": ["g-1"]},
        )
        assert conflict.status == 409
        audit = store.connection.execute(
            "SELECT requester_id, thread_type, thread_id, tool_name "
            "FROM tool_activity "
            "WHERE tool_name='admin_web.apply_access_config' "
            "ORDER BY id LIMIT 1"
        ).fetchone()
        assert tuple(audit) == (
            "web-admin",
            "system",
            "admin-web",
            "admin_web.apply_access_config",
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_history_export_delete_and_attachment_scope(
    tmp_path: Path,
) -> None:
    media_root = tmp_path / "media"
    store = HistoryStore(tmp_path / "h.sqlite", media_root=media_root)
    media = media_root / "group" / "g-1" / "file.txt"
    media.parent.mkdir(parents=True)
    media.write_text("safe", encoding="utf-8")
    stored = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="báo giá",
        provider_message_id="m-1",
        attachments=[
            {
                "kind": "file",
                "filename": "file.txt",
                "local_path": str(media),
                "download_status": "downloaded",
            }
        ],
    )
    admin = AdminService(store=store, export_root=tmp_path / "exports")
    client, cookie, csrf = await authenticated_web_client(
        tmp_path,
        admin=admin,
        store=store,
        bridge=FakeBridge(),
    )
    try:
        conversations = await client.get(
            "/admin/api/conversations",
            headers={"Cookie": cookie},
        )
        conversation = (await conversations.json())["items"][0]
        messages = await client.get(
            f"/admin/api/conversations/{conversation['id']}",
            headers={"Cookie": cookie},
        )
        assert (await messages.json())["items"][0]["text"] == "báo giá"
        attachment = await client.get(
            f"/admin/api/attachments/{stored.attachment_ids[0]}",
            headers={"Cookie": cookie},
        )
        assert attachment.status == 200
        assert await attachment.text() == "safe"
        exported = await client.post(
            "/admin/api/history/export",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={"thread_type": "group", "thread_id": "g-1"},
        )
        assert exported.status == 200
        assert "báo giá" in await exported.text()
        deleted = await client.post(
            "/admin/api/history/delete",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={
                "thread_type": "group",
                "thread_id": "g-1",
                "confirm": True,
            },
        )
        assert deleted.status == 200
        audit_rows = {
            tuple(row)
            for row in store.connection.execute(
                "SELECT requester_id, thread_type, thread_id, tool_name "
                "FROM tool_activity ORDER BY id"
            )
        }
        assert {
            (
                "web-admin",
                "system",
                "admin-web",
                "admin_web.attachment_download",
            ),
            ("web-admin", "system", "admin-web", "admin_web.history_export"),
            ("web-admin", "system", "admin-web", "admin_web.history_delete"),
        } <= audit_rows
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_history_export_and_delete_honor_sender_and_query_filters(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="alpha",
        provider_message_id="filter-1",
    )
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-2",
        text="beta",
        provider_message_id="filter-2",
    )
    admin = AdminService(store=store, export_root=tmp_path / "exports")
    client, cookie, csrf = await authenticated_web_client(
        tmp_path,
        admin=admin,
        store=store,
        bridge=FakeBridge(),
    )
    try:
        exported = await client.post(
            "/admin/api/history/export",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={"thread_type": "group", "thread_id": "g-1", "sender_id": "u-1"},
        )
        assert exported.status == 200
        exported_text = await exported.text()
        assert '"text":"alpha"' in exported_text
        assert '"text":"beta"' not in exported_text

        deleted = await client.post(
            "/admin/api/history/delete",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={
                "thread_type": "group",
                "thread_id": "g-1",
                "query": "beta",
                "confirm": True,
            },
        )
        assert deleted.status == 200
        assert (await deleted.json())["messages"] == 1
        remaining = store.connection.execute(
            "SELECT sender_id, text FROM messages ORDER BY id"
        ).fetchall()
        assert [tuple(row) for row in remaining] == [("u-1", "alpha")]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_attachment_is_always_downloaded_as_untrusted_binary(
    tmp_path: Path,
) -> None:
    media_root = tmp_path / "media"
    store = HistoryStore(tmp_path / "h.sqlite", media_root=media_root)
    media = media_root / "group" / "g-1" / "payload.html"
    media.parent.mkdir(parents=True)
    media.write_text("<script>window.attack=true</script>", encoding="utf-8")
    stored = store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="attachment",
        provider_message_id="attachment-html",
        attachments=[
            {
                "kind": "file",
                "filename": "payload.html",
                "local_path": str(media),
                "download_status": "downloaded",
            }
        ],
    )
    client, cookie, _csrf = await authenticated_web_client(
        tmp_path,
        admin=AdminService(store=store),
        store=store,
        bridge=FakeBridge(),
    )
    try:
        response = await client.get(
            f"/admin/api/attachments/{stored.attachment_ids[0]}",
            headers={"Cookie": cookie},
        )

        assert response.status == 200
        assert response.headers["Content-Type"] == "application/octet-stream"
        assert response.headers["Content-Disposition"].startswith("attachment")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert await response.text() == "<script>window.attack=true</script>"
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first_path", "duplicate_path", "expected_action"),
    [
        ("/admin/api/system/qr", "/admin/api/system/reconnect", "login_qr"),
        ("/admin/api/system/reconnect", "/admin/api/system/qr", "reconnect"),
    ],
)
async def test_admin_web_qr_and_reconnect_share_one_inflight_relogin(
    tmp_path: Path,
    first_path: str,
    duplicate_path: str,
    expected_action: str,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    calls: list[str] = []

    def callback(action: str):
        async def run(_args=None):
            calls.append(action)
            started.set()
            try:
                await release.wait()
            finally:
                finished.set()
            return {"success": True}

        return run

    store = HistoryStore(tmp_path / "h.sqlite")
    client, cookie, csrf = await authenticated_web_client(
        tmp_path,
        admin=AdminService(
            store=store,
            lifecycle={
                "login_qr": callback("login_qr"),
                "reconnect": callback("reconnect"),
            },
        ),
        store=store,
        bridge=FakeBridge(),
    )
    try:
        first = await client.post(
            first_path,
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={},
        )
        assert first.status == 202
        await asyncio.wait_for(started.wait(), timeout=1)

        duplicate = await client.post(
            duplicate_path,
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={},
        )

        assert duplicate.status == 202
        assert calls == [expected_action]
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=1)
    finally:
        release.set()
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_system_activity_restart_is_accepted_once(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    calls: list[tuple[str, str]] = []
    completed = asyncio.Event()

    async def restart(args=None):
        calls.append(("restart", str((args or {}).get("target") or "")))
        completed.set()
        return {"success": True}

    admin = AdminService(
        store=store,
        status_provider=lambda: {
            "success": True,
            "connected": True,
            "provider": "unknown",
            "model": "unknown",
        },
        lifecycle={
            "restart": restart,
            "login_qr": lambda _args=None: {"success": True},
        },
        log_provider=lambda lines: {
            "success": True,
            "lines": [f"last-{lines}"],
        },
    )
    client, cookie, csrf = await authenticated_web_client(
        tmp_path,
        admin=admin,
        store=store,
        bridge=FakeBridge(),
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
        await asyncio.wait_for(completed.wait(), timeout=1)
        await asyncio.sleep(0.1)
        duplicate = await client.post(
            "/admin/api/system/restart",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={"target": "bridge"},
        )
        assert duplicate.status == 202
        await asyncio.sleep(0.15)
        assert calls == [("restart", "bridge")]

        await asyncio.sleep(0.3)
        accepted_after_cooldown = await client.post(
            "/admin/api/system/restart",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={"target": "bridge"},
        )
        assert accepted_after_cooldown.status == 202
        await asyncio.sleep(0.1)
        assert calls == [
            ("restart", "bridge"),
            ("restart", "bridge"),
        ]
        activity = await client.get(
            "/admin/api/activity",
            headers={"Cookie": cookie},
        )
        assert any(
            item["tool_name"] == "admin_web.restart"
            for item in (await activity.json())["items"]
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_system_resolves_bot_profile_when_status_name_is_missing(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    bridge = FakeBridge()
    admin = AdminService(
        store=store,
        status_provider=lambda: {
            "success": True,
            "connected": True,
            "bot": {"id": "bot", "name": ""},
            "provider": "provider-a",
            "model": "model-a",
        },
    )
    client, cookie, _csrf = await authenticated_web_client(
        tmp_path,
        admin=admin,
        store=store,
        bridge=bridge,
    )
    try:
        response = await client.get(
            "/admin/api/system",
            headers={"Cookie": cookie},
        )
        assert response.status == 200
        body = await response.json()
        assert body["bot"] == {"id": "bot", "name": "Trợ lý"}
        assert "/chat-info" in [call[1] for call in bridge.calls]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_unhandled_errors_use_redacted_json_contract(
    tmp_path: Path,
    caplog,
) -> None:
    async def broken_status():
        raise RuntimeError("Authorization: Bearer secret-value")

    store = HistoryStore(tmp_path / "h.sqlite")
    client, cookie, _csrf = await authenticated_web_client(
        tmp_path,
        admin=AdminService(store=store, status_provider=broken_status),
        store=store,
        bridge=FakeBridge(),
    )
    caplog.set_level("ERROR")
    try:
        response = await client.get(
            "/admin/api/overview",
            headers={"Cookie": cookie},
        )
        body_text = await response.text()
        assert response.status == 500
        assert response.content_type == "application/json"
        assert json.loads(body_text) == {
            "code": "internal_error",
            "message": "Không thể xử lý yêu cầu",
            "retryable": False,
        }
        assert "secret-value" not in body_text
        assert "secret-value" not in caplog.text
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_http_errors_use_vietnamese_json_contract(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    client, cookie, csrf = await authenticated_web_client(
        tmp_path,
        admin=AdminService(store=store),
        store=store,
        bridge=FakeBridge(),
    )
    try:
        missing = await client.get(
            "/admin/api/not-found",
            headers={"Cookie": cookie},
        )
        assert missing.status == 404
        assert missing.content_type == "application/json"
        assert await missing.json() == {
            "code": "not_found",
            "message": "Không tìm thấy tài nguyên",
            "retryable": False,
        }

        wrong_method = await client.post(
            "/admin/api/overview",
            headers={"Cookie": cookie, "X-CSRF-Token": csrf},
            json={},
        )
        assert wrong_method.status == 405
        assert wrong_method.content_type == "application/json"
        assert await wrong_method.json() == {
            "code": "method_not_allowed",
            "message": "Phương thức không được hỗ trợ",
            "retryable": False,
        }
        assert wrong_method.headers["Allow"] == "GET,HEAD"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_query_errors_are_stable_vietnamese_messages(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    client, cookie, _csrf = await authenticated_web_client(
        tmp_path,
        admin=AdminService(store=store),
        store=store,
        bridge=FakeBridge(),
    )
    try:
        cases = [
            (
                "/admin/api/conversations?limit=abc",
                "invalid_page",
                "Tham số phân trang không hợp lệ",
            ),
            (
                "/admin/api/activity?limit=abc",
                "invalid_page",
                "Bộ lọc hoặc phân trang hoạt động không hợp lệ",
            ),
            (
                "/admin/api/system/logs?lines=abc",
                "invalid_lines",
                "Số dòng log không hợp lệ",
            ),
        ]
        for path, code, message in cases:
            response = await client.get(path, headers={"Cookie": cookie})
            assert response.status == 400
            assert response.content_type == "application/json"
            body = await response.json()
            assert body == {
                "code": code,
                "message": message,
                "retryable": False,
            }
            assert "must be an integer" not in json.dumps(body)
    finally:
        await client.close()


def test_admin_history_export_rejects_destination_outside_export_root(
    tmp_path: Path,
) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="safe",
        provider_message_id="export-scope",
    )
    admin = AdminService(store=store, export_root=tmp_path / "exports")
    outside = tmp_path / "outside.jsonl"

    with pytest.raises(CompanyConfigError, match="export root"):
        admin.history_export(
            outside,
            requester=requester("admin", admin=True),
        )

    assert not outside.exists()


@pytest.mark.asyncio
async def test_admin_web_prefers_dedicated_group_members_and_normalizes_profiles(
    tmp_path: Path,
) -> None:
    class RealShapeBridge:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def request(self, method, path, payload=None, params=None):
            self.calls.append(path)
            if path == "/contacts":
                return {
                    "success": True,
                    "result": {
                        "friends": [{"id": "u-1", "name": "Lan"}],
                        "groups": [{"id": "g-1", "name": "Group AI"}],
                    },
                }
            if path == "/groups":
                return {
                    "success": True,
                    "result": {"version": "1", "gridVerMap": {"g-1": "7"}},
                }
            if path == "/friends":
                return {
                    "success": True,
                    "result": [{"userId": "u-1", "displayName": "Lan"}],
                }
            if path == "/group-members":
                return {
                    "success": True,
                    "result": {
                        "members": ["u-1", {"id": "u-2", "name": "Minh"}],
                        "profiles": {
                            "u-1": {
                                "id": "u-1",
                                "displayName": "Lan",
                                "zaloName": "Lan Zalo",
                                "avatar": "https://example.invalid/lan.png",
                                "accountStatus": 0,
                                "type": 0,
                                "lastUpdateTime": 0,
                                "globalId": "global-u-1",
                            }
                        },
                    },
                }
            return {"success": True}

    bridge = RealShapeBridge()
    store = HistoryStore(tmp_path / "h.sqlite")
    client, cookie, _csrf = await authenticated_web_client(
        tmp_path,
        admin=AdminService(store=store),
        store=store,
        bridge=bridge,
    )
    try:
        groups = await (
            await client.get("/admin/api/groups", headers={"Cookie": cookie})
        ).json()
        members = await (
            await client.get(
                "/admin/api/groups/g-1/members",
                headers={"Cookie": cookie},
            )
        ).json()
        assert groups["items"] == [{"id": "g-1", "name": "Group AI"}]
        assert members["items"] == [
            {"id": "u-1", "name": "Lan"},
            {"id": "u-2", "name": "Minh"},
        ]
        assert "/group-members" in bridge.calls
        assert "/chat-info" not in bridge.calls
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_group_members_falls_back_to_legacy_chat_info(
    tmp_path: Path,
) -> None:
    class LegacyBridge:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def request(self, method, path, payload=None, params=None):
            self.calls.append(path)
            if path == "/group-members":
                return {
                    "error": "Cannot GET /group-members",
                    "outcome": "failed",
                }
            if path == "/chat-info":
                return {
                    "success": True,
                    "result": {
                        "gridInfoMap": {
                            "g-1": {
                                "groupId": "g-1",
                                "currentMems": [],
                                "memberIds": [],
                                "memVerList": ["u-legacy_0"],
                            }
                        }
                    },
                }
            return {"success": True}

    bridge = LegacyBridge()
    store = HistoryStore(tmp_path / "h.sqlite")
    client, cookie, _csrf = await authenticated_web_client(
        tmp_path,
        admin=AdminService(store=store),
        store=store,
        bridge=bridge,
    )
    try:
        members = await (
            await client.get(
                "/admin/api/groups/g-1/members",
                headers={"Cookie": cookie},
            )
        ).json()
        assert members["items"] == [
            {"id": "u-legacy", "name": "u-legacy"},
        ]
        assert bridge.calls == ["/group-members", "/chat-info"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_admin_web_keeps_last_contact_snapshot_when_bridge_goes_down(
    tmp_path: Path,
) -> None:
    bridge = FakeBridge()
    store = HistoryStore(tmp_path / "h.sqlite")
    client, cookie, _csrf = await authenticated_web_client(
        tmp_path,
        admin=AdminService(store=store),
        store=store,
        bridge=bridge,
    )
    try:
        first = await client.get(
            "/admin/api/friends",
            headers={"Cookie": cookie},
        )
        assert (await first.json())["items"][0]["id"] == "u-1"
        bridge.available = False
        stale = await client.get(
            "/admin/api/friends",
            headers={"Cookie": cookie},
        )
        body = await stale.json()
        assert stale.status == 200
        assert body["stale"] is True
        assert body["items"][0]["id"] == "u-1"
        assert body["error"] == "bridge unavailable"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_member_can_list_describe_and_call_zalo_without_requester_argument(tmp_path: Path):
    bridge = FakeBridge()
    tooling = ZaloTooling(bridge=bridge, store=HistoryStore(tmp_path / "h.sqlite"), config=config())

    with bind_requester(requester("u-1")):
        listed = json.loads(await tooling.zalo({"action": "list", "query": "poll", "requester_id": "admin"}))
        described = json.loads(await tooling.zalo({"action": "describe", "method": "createPoll"}))
        called = json.loads(
            await tooling.zalo(
                {
                    "action": "call",
                    "method": "createPoll",
                    "params": {"groupId": "g-1", "question": "Trua?", "options": ["A", "B"]},
                }
            )
        )

    assert listed["methods"][0]["name"] == "createPoll"
    assert described["method"]["name"] == "createPoll"
    assert called["result"]["pollId"] == "p-1"
    assert "hide-me" not in json.dumps(called)
    assert bridge.calls[-1] == (
        "POST",
        "/api/createPoll",
        {"params": {"groupId": "g-1", "question": "Trua?", "options": ["A", "B"]}},
    )


@pytest.mark.asyncio
async def test_history_member_scope_is_dm_self_or_allowed_group(tmp_path: Path):
    store = HistoryStore(tmp_path / "h.sqlite")
    store.store_message(thread_type="dm", thread_id="u-1", sender_id="u-1", text="alpha", provider_message_id="1")
    store.store_message(thread_type="dm", thread_id="u-2", sender_id="u-2", text="alpha", provider_message_id="2")
    store.store_message(thread_type="group", thread_id="g-1", sender_id="u-2", text="alpha", provider_message_id="3")
    tooling = ZaloTooling(bridge=FakeBridge(), store=store, config=config())

    with bind_requester(requester("u-1")):
        result = json.loads(await tooling.zalo_history({"action": "search", "query": "alpha"}))

    assert {(row["thread_type"], row["thread_id"]) for row in result["items"]} == {
        ("dm", "u-1"),
        ("group", "g-1"),
    }


@pytest.mark.asyncio
async def test_history_recent_normalizes_thread_type_before_scope_check(
    tmp_path: Path,
):
    store = HistoryStore(tmp_path / "h.sqlite")
    store.store_message(
        thread_type="dm",
        thread_id="u-2",
        sender_id="u-2",
        text="private-u-2",
        provider_message_id="private-2",
    )
    tooling = ZaloTooling(bridge=FakeBridge(), store=store, config=config())

    with bind_requester(requester("u-1")):
        result = json.loads(
            await tooling.zalo_history(
                {"action": "recent", "thread_type": "DM", "thread_id": "u-2"}
            )
        )

    assert result.get("error")
    assert "private-u-2" not in json.dumps(result)


@pytest.mark.asyncio
async def test_non_admin_admin_action_is_blocked_and_admin_memory_mutates(tmp_path: Path):
    store = HistoryStore(tmp_path / "h.sqlite")
    memory = tmp_path / "MEMORY.md"
    memory.write_text("old\n", encoding="utf-8")
    tooling = ZaloTooling(bridge=FakeBridge(), store=store, config=config(), memory_path=memory)

    with bind_requester(requester("u-1")):
        denied = json.loads(await tooling.zalo_admin({"action": "memory_add", "text": "secret"}))
    assert denied["error"]
    assert memory.read_text(encoding="utf-8") == "old\n"

    with bind_requester(requester("admin", admin=True)):
        added = json.loads(await tooling.zalo_admin({"action": "memory_add", "text": "new fact"}))
        removed = json.loads(await tooling.zalo_admin({"action": "memory_delete", "text": "new fact"}))
    assert added["success"] is True
    assert removed["success"] is True
    assert "new fact" not in memory.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_admin_memory_uses_hermes_entry_delimiter(tmp_path: Path):
    store = HistoryStore(tmp_path / "h.sqlite")
    memory = tmp_path / "memories" / "MEMORY.md"
    tooling = ZaloTooling(
        bridge=FakeBridge(),
        store=store,
        config=config(),
        memory_path=memory,
    )

    with bind_requester(requester("admin", admin=True)):
        await tooling.zalo_admin({"action": "memory_add", "text": "first fact"})
        await tooling.zalo_admin({"action": "memory_add", "text": "second fact"})

    assert memory.read_text(encoding="utf-8") == "first fact\n§\nsecond fact"


def test_memory_guard_blocks_non_admin_file_and_code_paths(tmp_path: Path):
    memory_path = tmp_path / "memories" / "MEMORY.md"
    user_path = memory_path.parent / "USER.md"
    tooling = ZaloTooling(
        bridge=FakeBridge(),
        store=HistoryStore(tmp_path / "h.sqlite"),
        config=config(),
        memory_path=memory_path,
    )
    with bind_requester(requester("u-1")):
        assert tooling.guard_tool_call("memory", {"action": "add", "content": "x"})["action"] == "block"
        assert tooling.guard_tool_call("memory", {"action": "replace", "old": "a", "new": "b"})["action"] == "block"
        assert tooling.guard_tool_call("memory", {"action": "read"}) is None
        assert tooling.guard_tool_call("read_file", {"path": str(memory_path)}) is None
        assert tooling.guard_tool_call("write_file", {"path": str(memory_path)})["action"] == "block"
        assert tooling.guard_tool_call("WRITE_FILE", {"path": str(memory_path)})["action"] == "block"
        assert tooling.guard_tool_call("write_file", {"path": str(user_path)})["action"] == "block"
        assert tooling.guard_tool_call(
            "patch",
            {"patch": f"*** Update File: {user_path}\n@@\n-old\n+new"},
        )["action"] == "block"
        assert tooling.guard_tool_call("terminal", {"command": f"Get-Content '{user_path}'"})["action"] == "block"
        assert tooling.guard_tool_call("execute_code", {"code": f"open(r'{user_path}').read()"})["action"] == "block"
    with bind_requester(requester("admin", admin=True)):
        assert tooling.guard_tool_call("write_file", {"path": str(user_path)}) is None


def _control_plane_tooling(tmp_path: Path, monkeypatch):
    hermes_home = tmp_path / "hermes-home"
    data_root = tmp_path / "zalo-data"
    store = HistoryStore(
        tmp_path / "runtime" / "history.sqlite3",
        media_root=tmp_path / "runtime" / "media",
    )
    admin = AdminService(
        config_file=CompanyConfigFile(hermes_home / "config.yaml"),
        store=store,
        memory_path=hermes_home / "memories" / "MEMORY.md",
        export_root=hermes_home / "exports",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("ZALO_DATA_DIR", str(data_root))
    return ZaloTooling(
        bridge=FakeBridge(),
        store=store,
        config=config(),
        admin=admin,
    )


def test_non_admin_guard_blocks_runtime_control_plane_paths_and_operations(
    tmp_path: Path,
    monkeypatch,
):
    tooling = _control_plane_tooling(tmp_path, monkeypatch)
    db_path = tooling.store.db_path
    config_path = tooling.admin.config_file.path
    media_root = tooling.store.media_root
    export_root = tooling.admin.export_root
    hermes_env = Path(os.environ["HERMES_HOME"]) / ".env"
    data_root = Path(os.environ["ZALO_DATA_DIR"])
    blocked_calls = [
        ("memory", {"action": "delete", "content": "x"}),
        ("read_file", {"path": str(config_path)}),
        ("read_file", {"path": str(db_path)}),
        ("read_file", {"path": f"{db_path}-wal"}),
        ("write_file", {"path": f"{db_path}-shm", "content": "x"}),
        ("write_file", {"path": str(media_root / "message.bin"), "content": "x"}),
        (
            "patch",
            {
                "patch": (
                    "*** Begin Patch\n"
                    f"*** Update File: {export_root / 'history.jsonl'}\n"
                    "@@\n-old\n+new\n"
                    "*** End Patch"
                )
            },
        ),
        ("terminal", {"command": f"Get-Content '{hermes_env}'"}),
        (
            "execute_code",
            {"code": f"open(r'{Path.home() / '.hermes-zalo' / 'company.env'}').read()"},
        ),
        ("terminal", {"command": "Get-Content ~/.hermes-zalo/company.env"}),
        ("python", {"code": "open('/etc/hermes-zalo-company.env').read()"}),
        ("terminal", {"command": f"Get-ChildItem '{data_root / 'credentials'}'"}),
        ("terminal", {"command": "systemctl restart hermes-gateway"}),
        ("terminal", {"command": "systemctl kill hermes-gateway.service"}),
        (
            "terminal",
            {"command": "sudo systemctl stop hermes-zalo-company-bridge.service"},
        ),
        ("terminal", {"command": "hermes gateway start"}),
        ("history_export", {"destination": "history.jsonl"}),
        ("zalo_admin", {"action": "delete_history"}),
        (
            "terminal",
            {"command": "curl -X POST http://127.0.0.1/admin/api/history/export"},
        ),
        ("terminal", {"command": "Write-Output $env:OPENAI_API_KEY"}),
        ("terminal", {"command": "Get-ChildItem Env:"}),
        ("terminal", {"command": "gci Env:"}),
        ("terminal", {"command": "dir Env:"}),
        ("terminal", {"command": "printenv"}),
        ("terminal", {"command": "env"}),
        (
            "terminal",
            {
                "command": "Get-Content config.yaml",
                "workdir": os.environ["HERMES_HOME"],
            },
        ),
        (
            "execute_code",
            {
                "code": "open('config.yaml').read()",
                "cwd": os.environ["HERMES_HOME"],
            },
        ),
    ]

    with bind_requester(requester("u-1")):
        for tool_name, args in blocked_calls:
            decision = tooling.guard_tool_call(tool_name, args)
            assert decision and decision["action"] == "block", (tool_name, args)
            assert "quản trị viên" in decision["message"]


def test_non_admin_guard_parses_unified_diff_file_markers(
    tmp_path: Path,
    monkeypatch,
):
    tooling = _control_plane_tooling(tmp_path, monkeypatch)
    protected_path = tooling.admin.memory_path.parent / "USER.md"
    protected_patch = (
        "--- /dev/null\n"
        f"+++ {protected_path}\n"
        "@@ -0,0 +1 @@\n"
        "+private memory\n"
    )
    ordinary_patch = (
        "--- a/src/example.py\n"
        "+++ b/src/example.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    with bind_requester(requester("u-1")):
        decision = tooling.guard_tool_call("apply_patch", {"patch": protected_patch})
        assert decision and decision["action"] == "block"
        assert tooling.guard_tool_call(
            "apply_patch",
            {"patch": ordinary_patch},
        ) is None


def test_non_admin_guard_blocks_relative_shared_memory_mutation_aliases(
    tmp_path: Path,
    monkeypatch,
):
    tooling = _control_plane_tooling(tmp_path, monkeypatch)
    workspace = tmp_path / "unrelated-workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    reviewer_patch = (
        "--- /dev/null\n"
        "+++ memories/USER.md\n"
        "@@ -0,0 +1 @@\n"
        "+private memory\n"
    )
    blocked_calls = [
        ("apply_patch", {"patch": reviewer_patch}),
        ("write_file", {"path": "MEMORY.md", "content": "private"}),
        ("edit_file", {"path": "USER.md", "old": "old", "new": "private"}),
        (
            "execute_code",
            {"code": "from pathlib import Path\nPath('USER.md').write_text('private')"},
        ),
    ]

    with bind_requester(requester("u-1")):
        for tool_name, args in blocked_calls:
            decision = tooling.guard_tool_call(tool_name, args)
            assert decision and decision["action"] == "block", (tool_name, args)

        assert tooling.guard_tool_call(
            "write_file",
            {"path": "notes/USER.md", "content": "ordinary workspace note"},
        ) is None


def test_non_admin_guard_blocks_environment_enumeration_variants(
    tmp_path: Path,
    monkeypatch,
):
    tooling = _control_plane_tooling(tmp_path, monkeypatch)
    blocked_calls = [
        ("terminal", {"command": "Get-ChildItem Env:*"}),
        ("terminal", {"command": "ls Env:"}),
        ("terminal", {"command": "[Environment]::GetEnvironmentVariables()"}),
        ("terminal", {"command": "printenv -0"}),
        ("terminal", {"command": "env -0"}),
        ("terminal", {"command": "env --null"}),
        ("execute_code", {"code": "import os; print(os.environ)"}),
        ("python", {"code": "import os\nprint(os.environ.items())"}),
    ]

    with bind_requester(requester("u-1")):
        for tool_name, args in blocked_calls:
            decision = tooling.guard_tool_call(tool_name, args)
            assert decision and decision["action"] == "block", (tool_name, args)


def test_non_admin_guard_allows_normal_local_environment_variable(
    tmp_path: Path,
    monkeypatch,
):
    tooling = _control_plane_tooling(tmp_path, monkeypatch)

    with bind_requester(requester("u-1")):
        assert tooling.guard_tool_call(
            "execute_code",
            {
                "code": (
                    "environment = {'mode': 'development'}\n"
                    "print(environment.items())"
                )
            },
        ) is None


def test_non_admin_guard_protects_runtime_workdirs_but_allows_home_workspace(
    tmp_path: Path,
    monkeypatch,
):
    tooling = _control_plane_tooling(tmp_path, monkeypatch)
    hermes_home = Path(os.environ["HERMES_HOME"])
    data_root = Path(os.environ["ZALO_DATA_DIR"])
    blocked_workdirs = [
        hermes_home,
        tooling.admin.memory_path.parent,
        tooling.admin.memory_path.parent / "nested",
        tooling.store.media_root,
        tooling.store.media_root / "nested",
        tooling.admin.export_root,
        tooling.admin.export_root / "nested",
        data_root,
        data_root / "credentials",
    ]

    with bind_requester(requester("u-1")):
        for workdir in blocked_workdirs:
            decision = tooling.guard_tool_call(
                "terminal",
                {"command": "Get-Content notes.txt", "workdir": str(workdir)},
            )
            assert decision and decision["action"] == "block", workdir

        assert tooling.guard_tool_call(
            "terminal",
            {
                "command": "Get-Content notes.txt",
                "workdir": str(hermes_home / "workspace" / "project"),
            },
        ) is None


def test_non_admin_guard_allows_normal_workspace_work_and_safe_service_status(
    tmp_path: Path,
    monkeypatch,
):
    tooling = _control_plane_tooling(tmp_path, monkeypatch)
    safe_path = tmp_path / "workspace" / "config.yaml"
    history_export_note = tmp_path / "workspace" / "notes" / "history-export.md"
    protected_text = str(tooling.admin.config_file.path)
    allowed_calls = [
        ("memory", {"action": "read"}),
        ("read_file", {"path": str(tooling.admin.memory_path)}),
        ("read_file", {"path": str(safe_path)}),
        ("read_file", {"path": str(history_export_note)}),
        ("write_file", {"path": str(safe_path), "content": protected_text}),
        (
            "patch",
            {
                "patch": (
                    "*** Begin Patch\n"
                    f"*** Update File: {safe_path}\n"
                    "@@\n"
                    f"-{protected_text}\n"
                    "+ordinary: true\n"
                    "*** End Patch"
                )
            },
        ),
        ("terminal", {"command": "systemctl status nginx"}),
        ("terminal", {"command": "systemctl status hermes-gateway.service"}),
        ("terminal", {"command": "systemctl show hermes-gateway.service"}),
        ("terminal", {"command": "systemctl is-active hermes-gateway.service"}),
        ("terminal", {"command": "Get-Content ./notes/history-export.md"}),
        ("terminal", {"command": "git status --short"}),
        (
            "terminal",
            {"command": "Get-Content config.yaml", "workdir": str(safe_path.parent)},
        ),
        ("execute_code", {"code": "print(sum([1, 2, 3]))"}),
        (
            "execute_code",
            {"code": "print('workspace')", "cwd": str(safe_path.parent)},
        ),
    ]

    with bind_requester(requester("u-1")):
        for tool_name, args in allowed_calls:
            assert tooling.guard_tool_call(tool_name, args) is None, (tool_name, args)


def test_non_admin_guard_allows_workspace_below_database_parent(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    admin = AdminService(
        config_file=CompanyConfigFile(tmp_path / "runtime" / "config.yaml"),
        store=store,
        memory_path=tmp_path / "runtime" / "memories" / "MEMORY.md",
    )
    tooling = ZaloTooling(
        bridge=FakeBridge(),
        store=store,
        config=config(),
        admin=admin,
    )

    with bind_requester(requester("u-1")):
        assert tooling.guard_tool_call(
            "terminal",
            {
                "command": "Get-Content notes.txt",
                "workdir": str(tmp_path / "workspace"),
            },
        ) is None


def test_admin_guard_always_passes_control_plane_calls(tmp_path: Path, monkeypatch):
    tooling = _control_plane_tooling(tmp_path, monkeypatch)
    calls = [
        ("memory", {"action": "delete"}),
        ("read_file", {"path": str(tooling.admin.config_file.path)}),
        (
            "write_file",
            {"path": str(tooling.admin.memory_path.parent / "USER.md")},
        ),
        ("terminal", {"command": "systemctl restart hermes-gateway"}),
        ("terminal", {"command": "systemctl kill hermes-gateway.service"}),
        ("history_delete", {}),
        ("terminal", {"command": "Write-Output $env:OPENAI_API_KEY"}),
        ("terminal", {"command": "Get-ChildItem Env:"}),
        (
            "terminal",
            {
                "command": "Get-Content config.yaml",
                "workdir": os.environ["HERMES_HOME"],
            },
        ),
    ]

    with bind_requester(requester("admin", admin=True)):
        for tool_name, args in calls:
            assert tooling.guard_tool_call(tool_name, args) is None


def test_pre_tool_hook_audits_blocked_control_plane_read(tmp_path: Path, monkeypatch):
    tooling = _control_plane_tooling(tmp_path, monkeypatch)

    with bind_requester(requester("u-1")):
        decision = tooling.on_pre_tool_call(
            tool_name="read_file",
            args={"path": str(Path(os.environ["HERMES_HOME"]) / ".env")},
        )

    assert decision and decision["action"] == "block"
    row = tooling.store.connection.execute(
        "SELECT tool_name, status FROM tool_activity ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert (row["tool_name"], row["status"]) == ("read_file", "blocked")


class FakeContext:
    def __init__(self) -> None:
        self.tools = []
        self.hooks = []

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))


def test_register_tooling_registers_three_tools_and_guards(tmp_path: Path):
    ctx = FakeContext()
    tooling = ZaloTooling(bridge=FakeBridge(), store=HistoryStore(tmp_path / "h.sqlite"), config=config())
    register_tooling(ctx, tooling)
    assert {entry["name"] for entry in ctx.tools} == {"zalo", "zalo_history", "zalo_admin"}
    assert {name for name, _ in ctx.hooks} == {"pre_tool_call", "post_tool_call", "pre_gateway_dispatch"}


def test_pre_tool_hook_does_not_block_non_zalo_turn_without_requester(tmp_path: Path):
    tooling = ZaloTooling(bridge=FakeBridge(), store=HistoryStore(tmp_path / "h.sqlite"), config=config())
    assert tooling.on_pre_tool_call(tool_name="read_file", args={"path": "README.md"}) is None


@pytest.mark.asyncio
async def test_follow_up_admin_boundary_and_allowlist_are_fail_closed(tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "h.sqlite")
    runtime_config = config()
    sent: list[tuple[str, str]] = []

    async def send_dm(target_id: str, text: str):
        sent.append((target_id, text))
        return {"success": True, "message_id": f"provider-{len(sent)}"}

    follow_ups = FollowUpService(
        store=store,
        allowed_users=lambda: set(runtime_config.allowed_users),
        send_dm=send_dm,
    )
    admin = AdminService(store=store, follow_up_service=follow_ups)
    tooling = ZaloTooling(
        bridge=FakeBridge(),
        store=store,
        config=runtime_config,
        admin=admin,
    )
    payload = {
        "action": "follow_up_create",
        "title": "Họp",
        "question": "Có họp không?",
        "targets": [{"zalo_id": "u-1", "name": "Lan"}],
        "due_at": "2099-08-15T10:00:00Z",
    }

    with bind_requester(requester("u-1", admin=False)):
        denied = json.loads(await tooling.zalo_admin(payload))
    assert "error" in denied
    assert sent == []

    with bind_requester(requester("admin", admin=True)):
        rejected = json.loads(
            await tooling.zalo_admin(
                {**payload, "targets": [{"zalo_id": "outside"}]}
            )
        )
    assert "allowlist" in rejected["error"]
    assert sent == []

    with bind_requester(requester("admin", admin=True)):
        created = json.loads(await tooling.zalo_admin(payload))
    assert created["success"] is True
    assert sent == [("u-1", "Có họp không?")]

    with bind_requester(requester("admin", admin=True)):
        status = json.loads(
            await tooling.zalo_admin(
                {"action": "follow_up_status", "follow_up_id": created["follow_up_id"]}
            )
        )
    assert status["targets"][0]["target_id"] == "u-1"


def test_pre_tool_hook_logs_blocked_memory_mutation(tmp_path: Path):
    store = HistoryStore(tmp_path / "h.sqlite")
    tooling = ZaloTooling(bridge=FakeBridge(), store=store, config=config())

    with bind_requester(requester("u-1")):
        decision = tooling.on_pre_tool_call(
            tool_name="memory",
            args={"action": "replace", "old": "a", "new": "b"},
        )

    assert decision and decision["action"] == "block"
    row = store.connection.execute(
        "SELECT tool_name, status FROM tool_activity ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert (row["tool_name"], row["status"]) == ("memory", "blocked")


def test_post_tool_hook_uses_actual_hermes_result_contract(tmp_path: Path):
    store = HistoryStore(tmp_path / "h.sqlite")
    tooling = ZaloTooling(bridge=FakeBridge(), store=store, config=config())

    with bind_requester(requester("u-1")):
        tooling.on_post_tool_call(
            tool_name="terminal",
            args={"command": "false"},
            result=json.dumps(
                {
                    "error": "Authorization: Basic dXNlcjpwYXNz",
                    "outcome": "failed",
                }
            ),
            task_id="zalo:dm:u-1",
            duration_ms=5,
        )

    row = store.connection.execute(
        "SELECT status, error_text FROM tool_activity ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["status"] == "failed"
    assert "dXNlcjpwYXNz" not in (row["error_text"] or "")
    assert "REDACTED" in (row["error_text"] or "")


@pytest.mark.asyncio
async def test_admin_logs_are_redacted_before_returning_to_chat(tmp_path: Path):
    log_path = tmp_path / "bridge.log"
    log_path.write_text('failure {"token":"abc123"} Authorization: Bearer secret-value\n', encoding="utf-8")
    store = HistoryStore(tmp_path / "h.sqlite")
    admin = AdminService(store=store, log_path=log_path)
    tooling = ZaloTooling(bridge=FakeBridge(), store=store, config=config(), admin=admin)
    with bind_requester(requester("admin", admin=True)):
        result = json.loads(await tooling.zalo_admin({"action": "show_logs"}))
    rendered = json.dumps(result)
    assert "abc123" not in rendered
    assert "secret-value" not in rendered
    assert "REDACTED" in rendered


@pytest.mark.asyncio
async def test_admin_allowlist_mutation_refreshes_in_memory_config(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {"gateway": {"platforms": {"zalo": {"extra": config().to_mapping()}}}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    store = HistoryStore(tmp_path / "h.sqlite")
    admin = AdminService(store=store, config_file=CompanyConfigFile(config_path))
    tooling = ZaloTooling(bridge=FakeBridge(), store=store, config=config(), admin=admin)
    with bind_requester(requester("admin", admin=True)):
        result = json.loads(await tooling.zalo_admin({"action": "add_user", "zalo_id": "u-3"}))
    assert result["success"] is True
    assert "u-3" in tooling.config.allowed_users


@pytest.mark.asyncio
async def test_admin_surface_executes_memory_history_and_lifecycle_immediately(
    tmp_path: Path,
):
    store = HistoryStore(tmp_path / "h.sqlite")
    store.store_message(
        thread_type="group",
        thread_id="g-1",
        sender_id="u-1",
        text="export-me",
        provider_message_id="admin-history-1",
    )
    memory = tmp_path / "MEMORY.md"
    memory.write_text("old fact\n", encoding="utf-8")
    lifecycle_calls: list[str] = []

    def lifecycle(action: str):
        def run(_args=None):
            lifecycle_calls.append(action)
            return {"success": True, "action": action}

        return run

    admin = AdminService(
        store=store,
        memory_path=memory,
        status_provider=lambda: {"success": True, "connected": True},
        lifecycle={
            action: lifecycle(action)
            for action in ("login_qr", "start", "stop", "restart")
        },
        log_provider=lambda lines: {"success": True, "lines": [f"last-{lines}"]},
    )
    tooling = ZaloTooling(
        bridge=FakeBridge(),
        store=store,
        config=config(),
        admin=admin,
    )
    export_path = tmp_path / "history.jsonl"

    with bind_requester(requester("admin", admin=True)):
        status = json.loads(await tooling.zalo_admin({"action": "status"}))
        updated = json.loads(
            await tooling.zalo_admin(
                {"action": "memory_update", "old": "old fact", "new": "new fact"}
            )
        )
        exported = json.loads(
            await tooling.zalo_admin(
                {
                    "action": "history_export",
                    "destination": str(export_path),
                    "thread_type": "group",
                    "thread_id": "g-1",
                }
            )
        )
        lifecycle_results = [
            json.loads(await tooling.zalo_admin({"action": action}))
            for action in ("login_qr", "start", "stop", "restart")
        ]
        logs = json.loads(
            await tooling.zalo_admin({"action": "show_logs", "lines": 25})
        )
        deleted = json.loads(
            await tooling.zalo_admin(
                {
                    "action": "history_delete",
                    "thread_type": "group",
                    "thread_id": "g-1",
                }
            )
        )

    assert status["connected"] is True
    assert updated["success"] is True
    assert memory.read_text(encoding="utf-8") == "new fact"
    assert exported["messages"] == 1 and export_path.exists()
    assert all(result["success"] for result in lifecycle_results)
    assert lifecycle_calls == ["login_qr", "start", "stop", "restart"]
    assert logs["lines"] == ["last-25"]
    assert deleted["messages"] == 1
