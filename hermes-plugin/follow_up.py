"""Durable follow-up workflow for the company Zalo assistant.

This module contains only business state transitions.  Network delivery is
injected by the adapter so the workflow remains testable and does not depend
on the Node bridge implementation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

try:
    from .history_store import HistoryStore
except ImportError:  # Hermes may load plugin modules as top-level modules.
    from history_store import HistoryStore


def _utc_now_datetime() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("due_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def classify_response(text: str) -> str:
    normalized = str(text or "").strip().casefold()
    if normalized.startswith("có"):
        return "yes"
    if normalized.startswith("không") or normalized.startswith("ko"):
        return "no"
    return "other"


def _send_result_fields(result: Any) -> tuple[bool, str | None, Mapping[str, Any]]:
    if isinstance(result, Mapping):
        raw = result
        success = bool(result.get("success")) and not result.get("error")
        message_id = result.get("message_id") or result.get("messageId")
    else:
        raw_value = getattr(result, "raw_response", None)
        raw = raw_value if isinstance(raw_value, Mapping) else {}
        success = bool(getattr(result, "success", False)) and not getattr(result, "error", None)
        message_id = getattr(result, "message_id", None)
    return success, (str(message_id) if message_id not in (None, "") else None), raw


class FollowUpService:
    """Stateful follow-up operations backed by HistoryStore."""

    def __init__(
        self,
        *,
        store: HistoryStore,
        allowed_users: Callable[[], set[str]],
        send_dm: Callable[[str, str], Awaitable[Any]],
        now: Callable[[], datetime] = _utc_now_datetime,
    ) -> None:
        self.store = store
        self.allowed_users = allowed_users
        self.send_dm = send_dm
        self.now = now
        self._tick_lock = asyncio.Lock()

    def _now(self) -> datetime:
        value = self.now()
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = _parse_utc(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _targets(targets: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)):
            raise ValueError("targets must be a list")
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for target in targets:
            if not isinstance(target, Mapping):
                raise ValueError("each target must be an object")
            target_id = str(target.get("zalo_id") or target.get("target_id") or "").strip()
            if not target_id:
                raise ValueError("target zalo_id is required")
            if target_id in seen:
                raise ValueError("target zalo_id must be unique")
            seen.add(target_id)
            normalized.append(
                {
                    "target_id": target_id,
                    "target_name": str(target.get("name") or target.get("target_name") or "").strip(),
                }
            )
        if not normalized:
            raise ValueError("at least one target is required")
        return normalized

    async def create(
        self,
        *,
        owner_id: str,
        title: str,
        question: str,
        targets: Sequence[Mapping[str, Any]],
        due_at: str,
    ) -> dict[str, Any]:
        owner = str(owner_id or "").strip()
        normalized_title = str(title or "").strip()
        normalized_question = str(question or "").strip()
        if not owner or not normalized_title or not normalized_question:
            raise ValueError("owner_id, title, and question are required")
        now = self._now()
        due = _parse_utc(due_at)
        if due <= now:
            raise ValueError("due_at must be in the future")
        normalized_targets = self._targets(targets)
        allowed = {str(value) for value in (self.allowed_users() or set())}
        outside = [item["target_id"] for item in normalized_targets if item["target_id"] not in allowed]
        if outside:
            raise ValueError("target is outside the allowlist")

        follow_up_id = self.store.create_follow_up(
            owner_id=owner,
            title=normalized_title,
            question_text=normalized_question,
            due_at=_iso(due),
            targets=normalized_targets,
            created_at=_iso(now),
        )
        outcomes: list[dict[str, Any]] = []
        for target in normalized_targets:
            target_id = target["target_id"]
            claimed = self.store.claim_initial_target(follow_up_id, target_id)
            if claimed is None:
                outcomes.append({"target_id": target_id, "state": "initial_unknown"})
                continue
            state = "initial_unknown"
            provider_id: str | None = None
            try:
                result = await self.send_dm(target_id, normalized_question)
                success, provider_id, raw = _send_result_fields(result)
                if success:
                    state = "awaiting_response"
                elif str(raw.get("outcome") or "").casefold() == "unknown":
                    state = "initial_unknown"
                else:
                    state = "initial_failed"
            except asyncio.CancelledError:
                raise
            except Exception:
                state = "initial_unknown"
            completed = self.store.complete_initial_target(
                follow_up_id,
                target_id,
                state=state,
                provider_message_id=provider_id,
                sent_at=_iso(self._now()),
            )
            outcomes.append(
                {
                    "target_id": target_id,
                    "state": str((completed or {}).get("state") or state),
                    "provider_message_id": (completed or {}).get("initial_provider_message_id"),
                }
            )
        return {"success": True, "follow_up_id": follow_up_id, "targets": outcomes}

    def record_inbound_response(
        self,
        *,
        stored_message_id: int,
        sender_id: str,
        thread_type: str,
        thread_id: str,
        sent_at: str,
        text: str,
    ) -> list[dict[str, Any]]:
        if str(thread_type).lower() != "dm" or str(thread_id) != str(sender_id):
            return []
        return self.store.record_follow_up_response(
            stored_message_id=int(stored_message_id),
            target_id=str(sender_id),
            sent_at=str(sent_at),
            response_kind=classify_response(text),
        )

    @staticmethod
    def _target_label(state: str, response_kind: str | None) -> str:
        if state == "responded":
            return {
                "yes": "Có",
                "no": "Không",
                "other": "Đã phản hồi khác",
            }.get(str(response_kind or ""), "Đã phản hồi khác")
        if state in {"initial_failed", "reminder_failed"}:
            return "gửi lỗi"
        if state in {"initial_unknown", "reminder_unknown"}:
            return "không rõ kết quả"
        return "Chưa phản hồi"

    def _render_report(
        self,
        follow_up: Mapping[str, Any],
        targets: Sequence[Mapping[str, Any]],
    ) -> str:
        lines = [f"Báo cáo: {follow_up.get('title') or 'Theo dõi phản hồi'}"]
        for target in targets:
            name = str(target.get("target_name") or target.get("target_id") or "(không tên)")
            label = self._target_label(
                str(target.get("state") or ""),
                target.get("response_kind"),
            )
            lines.append(f"- {name}: {label}")
        lines.append("Đang chờ chỉ đạo của admin.")
        return "\n".join(lines)

    async def _send_target_reminder(self, target: Mapping[str, Any], title: str) -> str:
        state = "reminder_unknown"
        provider_id: str | None = None
        text = f"Nhắc bạn phản hồi yêu cầu: {title}. Vui lòng trả lời khi có thể."
        try:
            result = await self.send_dm(str(target["target_id"]), text)
            success, provider_id, raw = _send_result_fields(result)
            if success:
                state = "reminded"
            elif str(raw.get("outcome") or "").casefold() != "unknown":
                state = "reminder_failed"
        except asyncio.CancelledError:
            raise
        except Exception:
            state = "reminder_unknown"
        self.store.complete_reminder_target(
            int(target["id"]),
            state=state,
            provider_message_id=provider_id,
            sent_at=_iso(self._now()),
        )
        return state

    async def tick(self) -> dict[str, int]:
        async with self._tick_lock:
            self.store.recover_follow_up_claims()
            now = _iso(self._now())
            reminder_claims = self.store.claim_due_reminder_targets(now=now)
            reminder_count = 0
            for target in reminder_claims:
                await self._send_target_reminder(
                    target,
                    str(target.get("title") or "yêu cầu cần phản hồi"),
                )
                reminder_count += 1

            report_claims = self.store.claim_due_reports(now=now)
            report_count = 0
            for follow_up in report_claims:
                targets = self.store.follow_up_targets(int(follow_up["id"]))
                state = "unknown"
                try:
                    result = await self.send_dm(
                        str(follow_up["owner_id"]),
                        self._render_report(follow_up, targets),
                    )
                    success, _provider_id, _raw = _send_result_fields(result)
                    if success:
                        state = "sent"
                except asyncio.CancelledError:
                    raise
                except Exception:
                    state = "unknown"
                self.store.complete_follow_up_report(
                    int(follow_up["id"]),
                    report_state=state,
                    sent_at=_iso(self._now()),
                )
                report_count += 1
            return {"reminders": reminder_count, "reports": report_count}

    async def status(self, *, follow_up_id: int | None = None) -> dict[str, Any]:
        rows = self.store.list_follow_ups(follow_up_id)
        if follow_up_id is not None and not rows:
            raise ValueError("follow-up was not found")
        items = []
        for row in rows:
            item = dict(row)
            item["targets"] = self.store.follow_up_targets(int(row["id"]))
            items.append(item)
        if follow_up_id is not None:
            return {"success": True, **items[0]}
        return {"success": True, "items": items}

    async def extend(
        self,
        *,
        actor_id: str,
        follow_up_id: int,
        due_at: str,
    ) -> dict[str, Any]:
        del actor_id
        due = _parse_utc(due_at)
        if due <= self._now():
            raise ValueError("due_at must be in the future")
        updated = self.store.extend_follow_up(
            follow_up_id=int(follow_up_id),
            due_at=_iso(due),
        )
        if updated is None:
            raise ValueError("follow-up was not found or is closed")
        return await self.status(follow_up_id=int(follow_up_id))

    async def remind(
        self,
        *,
        actor_id: str,
        follow_up_id: int,
        target_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        del actor_id
        follow_ups = self.store.list_follow_ups(int(follow_up_id))
        if not follow_ups:
            raise ValueError("follow-up was not found")
        if str(follow_ups[0].get("state") or "") == "closed":
            raise ValueError("follow-up is closed")
        claims = self.store.claim_manual_reminder_targets(
            follow_up_id=int(follow_up_id),
            target_ids=target_ids,
            claimed_at=_iso(self._now()),
        )
        for target in claims:
            await self._send_target_reminder(
                target,
                str(target.get("title") or "yêu cầu cần phản hồi"),
            )
        return {"success": True, "follow_up_id": int(follow_up_id), "reminded": len(claims)}

    def close(self, *, actor_id: str, follow_up_id: int) -> dict[str, Any]:
        del actor_id
        updated = self.store.close_follow_up(follow_up_id=int(follow_up_id))
        if updated is None:
            raise ValueError("follow-up was not found or already closed")
        return {"success": True, "follow_up_id": int(follow_up_id), "state": "closed"}
