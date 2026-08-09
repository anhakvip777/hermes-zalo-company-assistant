from __future__ import annotations

import asyncio

import pytest

from request_context import (
    MissingRequesterContext,
    Requester,
    bind_requester,
    current_requester,
)


def requester(user_id: str) -> Requester:
    return Requester(
        requester_id=user_id,
        thread_type="dm",
        thread_id=user_id,
        is_admin=user_id == "admin",
        session_key=f"agent:main:zalo:dm:{user_id}",
    )


def test_current_requester_fails_closed_without_bound_turn() -> None:
    with pytest.raises(MissingRequesterContext):
        current_requester()


def test_bind_requester_restores_nested_context() -> None:
    outer = requester("u-1")
    inner = requester("admin")
    with bind_requester(outer):
        assert current_requester() == outer
        with bind_requester(inner):
            assert current_requester() == inner
        assert current_requester() == outer
    with pytest.raises(MissingRequesterContext):
        current_requester()


@pytest.mark.asyncio
async def test_context_is_isolated_between_concurrent_turns() -> None:
    ready = asyncio.Event()

    async def read_bound(value: Requester) -> str:
        with bind_requester(value):
            await ready.wait()
            await asyncio.sleep(0)
            return current_requester().requester_id

    one = asyncio.create_task(read_bound(requester("u-1")))
    two = asyncio.create_task(read_bound(requester("u-2")))
    ready.set()

    assert await asyncio.gather(one, two) == ["u-1", "u-2"]
