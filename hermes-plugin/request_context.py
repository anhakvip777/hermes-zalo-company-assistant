from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator


class MissingRequesterContext(RuntimeError):
    """Raised when a privileged tool is called outside a bound Zalo turn."""


@dataclass(frozen=True, slots=True)
class Requester:
    requester_id: str
    thread_type: str
    thread_id: str
    is_admin: bool
    session_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.requester_id, str) or not self.requester_id.strip():
            raise ValueError("requester_id is required")
        if not isinstance(self.thread_type, str) or self.thread_type not in {
            "user",
            "dm",
            "group",
            "system",
        }:
            raise ValueError("thread_type must be user, dm, group, or system")
        if not isinstance(self.thread_id, str) or not self.thread_id.strip():
            raise ValueError("thread_id is required")
        if not isinstance(self.is_admin, bool):
            raise TypeError("is_admin must be bool")
        if not isinstance(self.session_key, str) or not self.session_key.strip():
            raise ValueError("session_key is required")


_REQUESTER: ContextVar[Requester | None] = ContextVar(
    "hermes_zalo_requester",
    default=None,
)


def current_requester() -> Requester:
    requester = _REQUESTER.get()
    if requester is None:
        raise MissingRequesterContext(
            "No authenticated Zalo requester is bound to this tool call"
        )
    return requester


@contextmanager
def bind_requester(requester: Requester) -> Iterator[Requester]:
    if not isinstance(requester, Requester):
        raise TypeError("bind_requester expects a Requester")
    token: Token[Requester | None] = _REQUESTER.set(requester)
    try:
        yield requester
    finally:
        _REQUESTER.reset(token)
