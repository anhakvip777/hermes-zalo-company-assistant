from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FakeCompanyBridge:
    """In-process bridge double used by Python integration tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.methods = {
            "sendMessage": {
                "name": "sendMessage",
                "parameters": ["message", "threadId", "type"],
            },
            "createPoll": {
                "name": "createPoll",
                "parameters": ["options", "groupId"],
            },
        }
        self.next_outcome: dict[str, Any] | None = None
        self.profile = {"id": "bot-id", "name": "Trợ lý công ty"}
        self.friends = [
            {"id": "u-1", "name": "Lan"},
            {"id": "admin", "name": "Việt Anh"},
        ]
        self.groups = [
            {"id": "g-1", "name": "Group AI", "memberCount": 2}
        ]
        self.members = {"g-1": self.friends}
        self.logged_in = True
        self.available = True
        self.qr_png = b"\x89PNG\r\n\x1a\n" + b"fake-qr"

    async def request(
        self,
        http_method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "http_method": http_method,
                "path": path,
                "payload": dict(payload or {}),
                "params": dict(params or {}),
            }
        )
        if not self.available:
            return {"error": "bridge unavailable", "outcome": "failed"}
        if self.next_outcome is not None:
            result, self.next_outcome = self.next_outcome, None
            return result
        if path == "/api/methods":
            query = str((params or {}).get("query") or "").lower()
            methods = [value for value in self.methods.values() if not query or query in value["name"].lower()]
            return {"version": "2.1.2", "methods": methods}
        if path.startswith("/api/methods/"):
            method = path.rsplit("/", 1)[-1]
            return {"version": "2.1.2", "method": self.methods[method]}
        if path.startswith("/api/"):
            method = path.rsplit("/", 1)[-1]
            if method not in self.methods:
                return {"error": f"unknown zca-js API method: {method}", "outcome": "failed"}
            return {"success": True, "result": {"providerId": "provider-1", "token": "never-leak"}}
        if path == "/health":
            return {
                "ok": True,
                "loggedIn": self.logged_in,
                "ownId": self.profile["id"],
                "qr": "authenticated" if self.logged_in else "pending",
            }
        if path == "/policy":
            return {
                "mode": "all_operational_methods",
                "allowedActionCount": len(self.methods),
            }
        if path in {"/friends", "/contacts"}:
            return {"success": True, "result": self.friends}
        if path == "/groups":
            return {"success": True, "result": self.groups}
        if path == "/chat-info":
            thread_id = str((params or {}).get("threadId") or "")
            if str((params or {}).get("threadType")) == "group":
                return {
                    "success": True,
                    "result": {
                        "id": thread_id,
                        "members": self.members.get(thread_id, []),
                    },
                }
            return {"success": True, "result": self.profile}
        if path == "/qr":
            return {
                "status": "authenticated" if self.logged_in else "pending"
            }
        if path == "/relogin":
            self.logged_in = False
            return {"success": True, "status": "pending"}
        return {"success": True}

    async def request_bytes(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> tuple[bytes, str]:
        self.calls.append(
            {
                "http_method": "GET",
                "path": path,
                "payload": {},
                "params": dict(params or {}),
            }
        )
        if not self.available or path != "/qr.png":
            raise RuntimeError("QR image unavailable")
        return self.qr_png, "image/png"
