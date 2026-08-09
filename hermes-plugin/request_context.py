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
    session_key: str = ""

    def __post_init__(self) -> None:
        if not self.requester_id:
            raise ValueError("requester_id is required")
        if self.thread_type not in {"dm", "group", "system"}:
            raise ValueError("thread_type must be dm, group, or system")
        if not self.thread_id:
            raise ValueError("thread_id is required")


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
    token: Token[Requester | None] = _REQUESTER.set(requester)
    try:
        yield requester
    finally:
        _REQUESTER.reset(token)
